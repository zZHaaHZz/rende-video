"""Durable multi-channel publishing for AI Video Creator.

The module is UI-independent so scheduling, OAuth and provider behavior can be
tested without importing Streamlit. Secrets are encrypted with Fernet and jobs
are stored in SQLite using atomic claims.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from secret_config import ENV_FILE, load_social_secrets, save_social_secrets


PLATFORMS = ("facebook_page", "tiktok", "youtube_short")
TERMINAL_STATUSES = ("published", "failed", "blocked", "cancelled", "unknown")
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class PublishError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise PublishError("TIMEZONE_REQUIRED", "Thời gian phải có múi giờ.")
    return value.astimezone(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path) -> Dict[str, Any]:
    ffprobe = os.environ.get("FFPROBE_BIN", "ffprobe")
    command = [ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_name,width,height:format=duration,format_name",
               "-of", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError("MEDIA_PROBE_FAILED", f"Không đọc được thông tin video: {exc}") from exc
    if result.returncode != 0:
        raise PublishError("MEDIA_INVALID", "File video không hợp lệ hoặc bị hỏng.")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        return {
            "codec": stream.get("codec_name", ""),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "duration": float(payload["format"].get("duration", 0)),
            "format": payload["format"].get("format_name", ""),
        }
    except (KeyError, ValueError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise PublishError("MEDIA_INVALID", "Không tìm thấy video stream hợp lệ.") from exc


def validate_media(path: str | Path, platform: Optional[str] = None,
                   probe: Callable[[Path], Dict[str, Any]] = probe_video) -> Dict[str, Any]:
    media = Path(path).expanduser().resolve()
    if not media.is_file() or media.suffix.lower() != ".mp4" or media.stat().st_size == 0:
        raise PublishError("MEDIA_INVALID", "Cần chọn một file MP4 tồn tại và không rỗng.")
    info = probe(media)
    if info.get("codec") not in {"h264", "hevc", "av1"}:
        raise PublishError("MEDIA_CODEC_UNSUPPORTED", "Video phải dùng H.264, HEVC hoặc AV1.")
    if platform == "youtube_short":
        if float(info.get("duration", 0)) <= 0 or float(info["duration"]) > 180:
            raise PublishError("NOT_YOUTUBE_SHORT", "YouTube Shorts phải dài tối đa 180 giây.")
        if int(info.get("height", 0)) < int(info.get("width", 0)):
            raise PublishError("NOT_YOUTUBE_SHORT", "YouTube Shorts phải là video dọc hoặc vuông.")
    return {**info, "path": str(media), "sha256": sha256_file(media), "size": media.stat().st_size}


class CredentialVault:
    def __init__(self, key_path: Path):
        self.key_path = key_path
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        self._fernet = Fernet(key_path.read_bytes().strip())

    def encrypt(self, value: Dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def decrypt(self, value: bytes) -> Dict[str, Any]:
        try:
            return json.loads(self._fernet.decrypt(value).decode())
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise PublishError("CREDENTIAL_DECRYPT_FAILED", "Không giải mã được thông tin kết nối.") from exc


class SocialStore:
    def __init__(self, db_path: Optional[Path] = None, key_path: Optional[Path] = None,
                 env_path: Optional[Path] = None):
        base = Path(os.environ.get("AVC_SOCIAL_DIR", str(Path.home() / ".avc_social"))).expanduser()
        self.db_path = Path(db_path or base / "social.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path = Path(key_path or base / "credential.key")
        self.env_path = Path(env_path or ENV_FILE)
        self._init_schema()
        self._migrate_credentials_to_env()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS connected_accounts(
              id TEXT PRIMARY KEY, platform TEXT NOT NULL, provider_account_id TEXT NOT NULL,
              display_name TEXT NOT NULL, avatar_url TEXT, status TEXT NOT NULL DEFAULT 'connected',
              scopes TEXT NOT NULL, encrypted_credential BLOB NOT NULL,
              credential_expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(platform, provider_account_id));
            CREATE INDEX IF NOT EXISTS idx_accounts_status ON connected_accounts(status);
            CREATE TABLE IF NOT EXISTS app_credentials(
              platform TEXT PRIMARY KEY, encrypted_value BLOB NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS oauth_attempts(
              state TEXT PRIMARY KEY, platform TEXT NOT NULL, redirect_uri TEXT NOT NULL,
              expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publish_batches(
              id TEXT PRIMARY KEY, media_path TEXT NOT NULL, media_sha256 TEXT NOT NULL,
              created_at TEXT NOT NULL, confirmed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publish_jobs(
              id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES publish_batches(id),
              account_id TEXT NOT NULL REFERENCES connected_accounts(id), platform TEXT NOT NULL,
              caption TEXT NOT NULL, options TEXT NOT NULL, status TEXT NOT NULL,
              scheduled_at_utc TEXT NOT NULL, source_timezone TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
              claimed_by TEXT, claim_expires_at TEXT, idempotency_key TEXT NOT NULL UNIQUE,
              provider_publish_id TEXT, provider_post_id TEXT, provider_post_url TEXT,
              last_error_code TEXT, last_error_message TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_jobs_due ON publish_jobs(status, scheduled_at_utc);
            CREATE INDEX IF NOT EXISTS idx_jobs_account ON publish_jobs(account_id, created_at);
            CREATE TABLE IF NOT EXISTS audit_events(
              id TEXT PRIMARY KEY, job_id TEXT, account_id TEXT, event_type TEXT NOT NULL,
              safe_payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_audit_job ON audit_events(job_id, created_at);
            CREATE TABLE IF NOT EXISTS worker_heartbeats(
              worker_id TEXT PRIMARY KEY, version TEXT NOT NULL, last_seen_at TEXT NOT NULL);
            """)

    def _migrate_credentials_to_env(self) -> None:
        """Copy legacy encrypted credentials to .env without deleting the backup."""
        if not self.key_path.exists():
            return
        vault = CredentialVault(self.key_path)
        apps, accounts = load_social_secrets(self.env_path)
        with self.connect() as db:
            app_rows = db.execute("SELECT platform,encrypted_value FROM app_credentials").fetchall()
            account_rows = db.execute(
                "SELECT id,encrypted_credential FROM connected_accounts"
            ).fetchall()
        try:
            for row in app_rows:
                value = vault.decrypt(row["encrypted_value"])
                if value and not apps.get(row["platform"]):
                    apps[row["platform"]] = value
            for row in account_rows:
                if bytes(row["encrypted_credential"]) == b"{}":
                    continue
                value = vault.decrypt(row["encrypted_credential"])
                if value and not accounts.get(row["id"]):
                    accounts[row["id"]] = value
        except PublishError:
            return
        save_social_secrets(apps, accounts, self.env_path)

    def set_app_credentials(self, platform: str, value: Dict[str, Any]) -> None:
        if platform not in {"facebook", "tiktok", "youtube"}:
            raise PublishError("PLATFORM_INVALID", "Nền tảng không hợp lệ.")
        apps, accounts = load_social_secrets(self.env_path)
        apps[platform] = value
        save_social_secrets(apps, accounts, self.env_path)

    def get_app_credentials(self, platform: str) -> Dict[str, Any]:
        apps, _ = load_social_secrets(self.env_path)
        value = apps.get(platform, {})
        return value if isinstance(value, dict) else {}

    def create_oauth_attempt(self, platform: str, redirect_uri: str) -> str:
        state = secrets.token_urlsafe(32)
        now = utc_now()
        with self.connect() as db:
            db.execute("DELETE FROM oauth_attempts WHERE expires_at < ?", (iso_utc(now),))
            db.execute("INSERT INTO oauth_attempts VALUES(?,?,?,?,?)",
                       (state, platform, redirect_uri, iso_utc(now + timedelta(minutes=10)), iso_utc(now)))
        return state

    def consume_oauth_attempt(self, state: str, platform: str) -> str:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM oauth_attempts WHERE state=? AND platform=?", (state, platform)).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= utc_now():
                db.rollback()
                raise PublishError("OAUTH_STATE_INVALID", "Phiên kết nối không hợp lệ hoặc đã hết hạn.")
            db.execute("DELETE FROM oauth_attempts WHERE state=?", (state,))
            db.commit()
        return row["redirect_uri"]

    def upsert_account(self, platform: str, provider_account_id: str, display_name: str,
                       credential: Dict[str, Any], scopes: Iterable[str], avatar_url: str = "",
                       expires_at: Optional[str] = None) -> str:
        if platform not in PLATFORMS:
            raise PublishError("PLATFORM_INVALID", "Nền tảng không hợp lệ.")
        now, account_id = iso_utc(utc_now()), str(uuid.uuid4())
        with self.connect() as db:
            existing = db.execute("SELECT id FROM connected_accounts WHERE platform=? AND provider_account_id=?",
                                  (platform, provider_account_id)).fetchone()
            if existing:
                account_id = existing["id"]
            db.execute("""INSERT INTO connected_accounts
              (id,platform,provider_account_id,display_name,avatar_url,status,scopes,encrypted_credential,
               credential_expires_at,created_at,updated_at) VALUES(?,?,?,?,?,'connected',?,?,?,?,?)
              ON CONFLICT(platform,provider_account_id) DO UPDATE SET display_name=excluded.display_name,
              avatar_url=excluded.avatar_url,status='connected',scopes=excluded.scopes,
              encrypted_credential=excluded.encrypted_credential,credential_expires_at=excluded.credential_expires_at,
              updated_at=excluded.updated_at""",
              (account_id, platform, provider_account_id, display_name, avatar_url,
               json.dumps(sorted(set(scopes))), b"{}", expires_at, now, now))
        apps, accounts = load_social_secrets(self.env_path)
        accounts[account_id] = credential
        save_social_secrets(apps, accounts, self.env_path)
        self.audit("account_connected", account_id=account_id, payload={"platform": platform})
        return account_id

    def list_accounts(self, connected_only: bool = True) -> List[Dict[str, Any]]:
        query = "SELECT id,platform,provider_account_id,display_name,avatar_url,status,scopes,credential_expires_at,created_at,updated_at FROM connected_accounts"
        args: tuple = ()
        if connected_only:
            query += " WHERE status='connected'"
        query += " ORDER BY platform,display_name"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, args).fetchall()]

    def get_account(self, account_id: str, include_credential: bool = False) -> Dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM connected_accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise PublishError("TARGET_INVALID", "Không tìm thấy kênh đã kết nối.")
        result = dict(row)
        if include_credential:
            _, accounts = load_social_secrets(self.env_path)
            value = accounts.get(account_id, {})
            result["credential"] = value if isinstance(value, dict) else {}
        result.pop("encrypted_credential", None)
        return result

    def disconnect_account(self, account_id: str) -> None:
        now = iso_utc(utc_now())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE connected_accounts SET status='revoked',encrypted_credential=?,updated_at=? WHERE id=?",
                       (b"{}", now, account_id))
            db.execute("UPDATE publish_jobs SET status='blocked',last_error_code='ACCOUNT_DISCONNECTED',updated_at=? "
                       "WHERE account_id=? AND status IN ('scheduled','queued')", (now, account_id))
            db.commit()
        apps, accounts = load_social_secrets(self.env_path)
        accounts.pop(account_id, None)
        save_social_secrets(apps, accounts, self.env_path)
        self.audit("account_disconnected", account_id=account_id)

    def create_batch(self, media_path: str, targets: List[Dict[str, Any]], publish_at: datetime,
                     source_timezone: str, confirmed: bool,
                     probe: Callable[[Path], Dict[str, Any]] = probe_video) -> Dict[str, Any]:
        if not confirmed:
            raise PublishError("CONSENT_REQUIRED", "Bạn cần xác nhận trước khi đăng.")
        if not targets:
            raise PublishError("TARGET_INVALID", "Hãy chọn ít nhất một kênh.")
        if publish_at.tzinfo is None:
            raise PublishError("TIMEZONE_REQUIRED", "Thời gian đăng phải có múi giờ.")
        now = utc_now()
        if publish_at.astimezone(timezone.utc) < now - timedelta(seconds=5):
            raise PublishError("SCHEDULE_IN_PAST", "Không thể đặt lịch trong quá khứ.")
        validated: Dict[str, Dict[str, Any]] = {}
        for target in targets:
            account = self.get_account(target["account_id"])
            if account["status"] != "connected" or account["platform"] != target["platform"]:
                raise PublishError("TARGET_INVALID", "Kênh đích không còn kết nối.")
            caption = str(target.get("caption", ""))
            if not caption.strip():
                raise PublishError("CAPTION_INVALID", "Caption/tiêu đề không được để trống.")
            validated[target["platform"]] = validate_media(media_path, target["platform"], probe)
        media = next(iter(validated.values()))
        batch_id, now_text = str(uuid.uuid4()), iso_utc(now)
        jobs: List[str] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO publish_batches VALUES(?,?,?,?,?)",
                       (batch_id, media["path"], media["sha256"], now_text, now_text))
            for target in targets:
                job_id = str(uuid.uuid4())
                jobs.append(job_id)
                status = "queued" if publish_at.astimezone(timezone.utc) <= now + timedelta(seconds=5) else "scheduled"
                db.execute("""INSERT INTO publish_jobs
                  (id,batch_id,account_id,platform,caption,options,status,scheduled_at_utc,source_timezone,
                   idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (job_id, batch_id, target["account_id"], target["platform"], target["caption"],
                   json.dumps(target.get("options", {}), ensure_ascii=False), status,
                   iso_utc(publish_at), source_timezone, str(uuid.uuid4()), now_text, now_text))
            db.commit()
        for job_id in jobs:
            self.audit("job_confirmed", job_id=job_id, payload={"batch_id": batch_id})
        return {"batch_id": batch_id, "job_ids": jobs, "media_sha256": media["sha256"]}

    def claim_due_job(self, worker_id: str, lease_seconds: int = 300) -> Optional[Dict[str, Any]]:
        now, lease = utc_now(), utc_now() + timedelta(seconds=lease_seconds)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT j.*,b.media_path,b.media_sha256 FROM publish_jobs j
              JOIN publish_batches b ON b.id=j.batch_id
              WHERE j.status IN ('queued','scheduled') AND j.scheduled_at_utc<=?
              AND (j.next_attempt_at IS NULL OR j.next_attempt_at<=?)
              AND (j.claim_expires_at IS NULL OR j.claim_expires_at<=?)
              ORDER BY j.scheduled_at_utc LIMIT 1""", (iso_utc(now), iso_utc(now), iso_utc(now))).fetchone()
            if not row:
                db.commit()
                return None
            changed = db.execute("UPDATE publish_jobs SET status='validating',claimed_by=?,claim_expires_at=?,updated_at=? "
                                 "WHERE id=? AND status IN ('queued','scheduled')",
                                 (worker_id, iso_utc(lease), iso_utc(now), row["id"])).rowcount
            db.commit()
        return dict(row) if changed == 1 else None

    def update_job(self, job_id: str, status: str, **fields: Any) -> None:
        allowed = {"provider_publish_id", "provider_post_id", "provider_post_url", "last_error_code",
                   "last_error_message", "attempt_count", "next_attempt_at", "claimed_by", "claim_expires_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        updates.update({"status": status, "updated_at": iso_utc(utc_now())})
        sql = "UPDATE publish_jobs SET " + ",".join(f"{k}=?" for k in updates) + " WHERE id=?"
        with self.connect() as db:
            db.execute(sql, (*updates.values(), job_id))
        self.audit(f"job_{status}", job_id=job_id, payload={"error": updates.get("last_error_code")})

    def cancel_job(self, job_id: str) -> bool:
        with self.connect() as db:
            changed = db.execute("UPDATE publish_jobs SET status='cancelled',updated_at=? WHERE id=? AND status='scheduled'",
                                 (iso_utc(utc_now()), job_id)).rowcount
        if changed:
            self.audit("job_cancelled", job_id=job_id)
        return changed == 1

    def list_jobs(self, limit: int = 500, platform: str = "", status: str = "") -> List[Dict[str, Any]]:
        clauses, args = [], []
        if platform:
            clauses.append("j.platform=?"); args.append(platform)
        if status:
            clauses.append("j.status=?"); args.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = """SELECT j.*,a.display_name,a.provider_account_id,b.media_path FROM publish_jobs j
          JOIN connected_accounts a ON a.id=j.account_id JOIN publish_batches b ON b.id=j.batch_id""" + where + \
          " ORDER BY j.created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(sql, args).fetchall()]
        for row in rows:
            row["options"] = json.loads(row["options"] or "{}")
        return rows

    def audit(self, event_type: str, job_id: str = "", account_id: str = "",
              payload: Optional[Dict[str, Any]] = None) -> None:
        safe = {k: v for k, v in (payload or {}).items()
                if not any(secret in k.lower() for secret in ("token", "secret", "authorization", "code"))}
        with self.connect() as db:
            db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                       (str(uuid.uuid4()), job_id or None, account_id or None, event_type,
                        json.dumps(safe, ensure_ascii=False), iso_utc(utc_now())))

    def heartbeat(self, worker_id: str, version: str = "1") -> None:
        with self.connect() as db:
            db.execute("INSERT INTO worker_heartbeats VALUES(?,?,?) ON CONFLICT(worker_id) DO UPDATE SET version=excluded.version,last_seen_at=excluded.last_seen_at",
                       (worker_id, version, iso_utc(utc_now())))

    def worker_is_healthy(self, max_age_seconds: int = 90) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT MAX(last_seen_at) AS seen FROM worker_heartbeats").fetchone()
        return bool(row and row["seen"] and datetime.fromisoformat(row["seen"]) >= utc_now() - timedelta(seconds=max_age_seconds))


def _json_response(response: requests.Response, code: str) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        provider_error = data.get("error")
        nested_message = provider_error.get("message") if isinstance(provider_error, dict) else ""
        message = data.get("error_description") or nested_message or data.get("message")
        raise PublishError(code, str(message or f"Provider HTTP {response.status_code}"),
                           retryable=response.status_code in RETRYABLE_HTTP)
    return data


class OAuthManager:
    YOUTUBE_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",
                      "https://www.googleapis.com/auth/youtube.readonly")

    def __init__(self, store: SocialStore, session: Any = requests):
        self.store, self.http = store, session

    def authorization_url(self, platform: str) -> str:
        cfg = self.store.get_app_credentials(platform)
        redirect_uri = cfg.get("redirect_uri", "")
        if not cfg.get("client_id") or not cfg.get("client_secret") or not redirect_uri:
            raise PublishError("OAUTH_CONFIG_MISSING", "Hãy lưu Client ID, Client Secret và Redirect URI trước.")
        state = self.store.create_oauth_attempt(platform, redirect_uri)
        if platform == "youtube":
            return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                "client_id": cfg["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                "scope": " ".join(self.YOUTUBE_SCOPES), "access_type": "offline",
                "prompt": "consent select_account", "state": state})
        if platform == "facebook":
            version = cfg.get("graph_version", "v24.0")
            return f"https://www.facebook.com/{version}/dialog/oauth?" + urlencode({
                "client_id": cfg["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                "scope": "pages_show_list,pages_read_engagement,pages_manage_posts", "state": state})
        if platform == "tiktok":
            return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
                "client_key": cfg["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                "scope": "user.info.basic,video.publish", "state": state})
        raise PublishError("PLATFORM_INVALID", "Nền tảng OAuth không hợp lệ.")

    def complete(self, platform: str, code: str, state: str) -> List[str]:
        redirect_uri = self.store.consume_oauth_attempt(state, platform)
        cfg = self.store.get_app_credentials(platform)
        if platform == "youtube":
            token = _json_response(self.http.post("https://oauth2.googleapis.com/token", data={
                "client_id": cfg["client_id"], "client_secret": cfg["client_secret"], "code": code,
                "grant_type": "authorization_code", "redirect_uri": redirect_uri}, timeout=30), "OAUTH_TOKEN_FAILED")
            channels = _json_response(self.http.get("https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {token['access_token']}"}, timeout=30), "YOUTUBE_CHANNEL_FAILED").get("items", [])
            if not channels:
                raise PublishError("YOUTUBE_CHANNEL_NOT_FOUND", "Tài khoản Google không có kênh YouTube.")
            ids = []
            for channel in channels:
                snippet = channel.get("snippet", {})
                credential = {**token, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}
                expires = iso_utc(utc_now() + timedelta(seconds=int(token.get("expires_in", 3600))))
                thumbs = snippet.get("thumbnails", {})
                avatar = (thumbs.get("default") or {}).get("url", "")
                ids.append(self.store.upsert_account("youtube_short", channel["id"], snippet.get("title", channel["id"]),
                    credential, self.YOUTUBE_SCOPES, avatar, expires))
            return ids
        if platform == "facebook":
            version = cfg.get("graph_version", "v24.0")
            token = _json_response(self.http.get(f"https://graph.facebook.com/{version}/oauth/access_token", params={
                "client_id": cfg["client_id"], "client_secret": cfg["client_secret"], "code": code,
                "redirect_uri": redirect_uri}, timeout=30), "OAUTH_TOKEN_FAILED")
            pages = _json_response(self.http.get(f"https://graph.facebook.com/{version}/me/accounts",
                params={"fields": "id,name,access_token,picture", "access_token": token["access_token"]}, timeout=30), "FACEBOOK_PAGES_FAILED").get("data", [])
            return [self.store.upsert_account("facebook_page", p["id"], p["name"],
                    {"access_token": p["access_token"], "graph_version": version},
                    ("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
                    ((p.get("picture") or {}).get("data") or {}).get("url", "")) for p in pages if p.get("access_token")]
        if platform == "tiktok":
            token = _json_response(self.http.post("https://open.tiktokapis.com/v2/oauth/token/", data={
                "client_key": cfg["client_id"], "client_secret": cfg["client_secret"], "code": code,
                "grant_type": "authorization_code", "redirect_uri": redirect_uri}, timeout=30), "OAUTH_TOKEN_FAILED")
            profile = _json_response(self.http.get("https://open.tiktokapis.com/v2/user/info/",
                params={"fields": "open_id,display_name,avatar_url"},
                headers={"Authorization": f"Bearer {token['access_token']}"}, timeout=30), "TIKTOK_PROFILE_FAILED").get("data", {}).get("user", {})
            open_id = profile.get("open_id") or token.get("open_id")
            if not open_id:
                raise PublishError("TIKTOK_ACCOUNT_NOT_FOUND", "Không đọc được tài khoản TikTok.")
            expires = iso_utc(utc_now() + timedelta(seconds=int(token.get("expires_in", 86400))))
            return [self.store.upsert_account("tiktok", open_id, profile.get("display_name", open_id), token,
                    ("user.info.basic", "video.publish"), profile.get("avatar_url", ""), expires)]
        raise PublishError("PLATFORM_INVALID", "Nền tảng OAuth không hợp lệ.")


class ProviderPublisher:
    def __init__(self, store: SocialStore, session: Any = requests):
        self.store, self.http = store, session

    def publish(self, job: Dict[str, Any]) -> Dict[str, str]:
        account = self.store.get_account(job["account_id"], include_credential=True)
        options = json.loads(job.get("options") or "{}")
        if job["platform"] == "facebook_page":
            return self._facebook(account, job, options)
        if job["platform"] == "youtube_short":
            return self._youtube(account, job, options)
        if job["platform"] == "tiktok":
            return self._tiktok(account, job, options)
        raise PublishError("PLATFORM_INVALID", "Nền tảng không được hỗ trợ.")

    def _facebook(self, account: Dict[str, Any], job: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, str]:
        cred, page_id = account["credential"], account["provider_account_id"]
        version = cred.get("graph_version", "v24.0")
        with open(job["media_path"], "rb") as media:
            response = self.http.post(f"https://graph-video.facebook.com/{version}/{page_id}/videos",
                data={"description": job["caption"], "access_token": cred["access_token"]},
                files={"source": (Path(job["media_path"]).name, media, "video/mp4")}, timeout=600)
        data = _json_response(response, "FACEBOOK_UPLOAD_FAILED")
        video_id = str(data.get("id", ""))
        return {"post_id": video_id, "post_url": f"https://www.facebook.com/{video_id}" if video_id else ""}

    def _refresh_youtube(self, account: Dict[str, Any]) -> Dict[str, Any]:
        cred = account["credential"]
        expires = account.get("credential_expires_at")
        if not expires or datetime.fromisoformat(expires) > utc_now() + timedelta(minutes=2):
            return cred
        if not cred.get("refresh_token"):
            raise PublishError("TOKEN_EXPIRED", "Kênh YouTube cần kết nối lại.")
        data = _json_response(self.http.post("https://oauth2.googleapis.com/token", data={
            "client_id": cred["client_id"], "client_secret": cred["client_secret"],
            "refresh_token": cred["refresh_token"], "grant_type": "refresh_token"}, timeout=30), "TOKEN_REFRESH_FAILED")
        updated = {**cred, **data}
        self.store.upsert_account("youtube_short", account["provider_account_id"], account["display_name"], updated,
            OAuthManager.YOUTUBE_SCOPES, account.get("avatar_url", ""),
            iso_utc(utc_now() + timedelta(seconds=int(data.get("expires_in", 3600)))))
        return updated

    def _youtube(self, account: Dict[str, Any], job: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, str]:
        cred = self._refresh_youtube(account)
        body = {"snippet": {"title": options.get("title") or job["caption"],
                            "description": options.get("description", job["caption"]),
                            "tags": options.get("tags", []), "categoryId": options.get("categoryId", "22")},
                "status": {"privacyStatus": options.get("privacyStatus", "private"),
                           "selfDeclaredMadeForKids": bool(options.get("selfDeclaredMadeForKids", False)),
                           "containsSyntheticMedia": bool(options.get("containsSyntheticMedia", True))}}
        init = self.http.post("https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status",
                    "notifySubscribers": str(bool(options.get("notifySubscribers", False))).lower()},
            headers={"Authorization": f"Bearer {cred['access_token']}", "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(Path(job["media_path"]).stat().st_size)},
            data=json.dumps(body), timeout=30)
        if not init.ok:
            _json_response(init, "YOUTUBE_UPLOAD_INIT_FAILED")
        upload_url = init.headers.get("Location")
        if not upload_url:
            raise PublishError("YOUTUBE_UPLOAD_INIT_FAILED", "YouTube không trả upload session.")
        with open(job["media_path"], "rb") as media:
            result = self.http.put(upload_url, headers={"Content-Type": "video/mp4"}, data=media, timeout=900)
        data = _json_response(result, "YOUTUBE_UPLOAD_FAILED")
        video_id = str(data.get("id", ""))
        if not video_id:
            raise PublishError("YOUTUBE_UPLOAD_FAILED", "YouTube không trả video ID.")
        for _ in range(30):
            status = _json_response(self.http.get("https://www.googleapis.com/youtube/v3/videos",
                params={"part": "status,processingDetails", "id": video_id},
                headers={"Authorization": f"Bearer {cred['access_token']}"}, timeout=30),
                "YOUTUBE_STATUS_FAILED")
            items = status.get("items", [])
            processing = (items[0].get("processingDetails", {}) if items else {}).get("processingStatus", "")
            if processing == "succeeded" or (items and not processing):
                return {"post_id": video_id, "post_url": f"https://youtu.be/{video_id}"}
            if processing in {"failed", "terminated"}:
                raise PublishError("YOUTUBE_PROCESSING_FAILED", "YouTube không xử lý được video.")
            time.sleep(2)
        raise PublishError("YOUTUBE_PROCESSING_TIMEOUT", "YouTube vẫn đang xử lý; hãy kiểm tra lại lịch sử.")

    def _tiktok(self, account: Dict[str, Any], job: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, str]:
        token, path = account["credential"]["access_token"], Path(job["media_path"])
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        creator = _json_response(self.http.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
                                                headers=headers, json={}, timeout=30), "TIKTOK_CREATOR_INFO_FAILED")
        allowed = creator.get("data", {}).get("privacy_level_options", [])
        privacy = options.get("privacyLevel", "SELF_ONLY")
        if allowed and privacy not in allowed:
            raise PublishError("PRIVACY_OPTION_INVALID", "Quyền riêng tư TikTok không còn hợp lệ.")
        size = path.stat().st_size
        init = _json_response(self.http.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=headers, json={
            "post_info": {"title": job["caption"], "privacy_level": privacy,
                          "disable_comment": bool(options.get("disableComment", False)),
                          "disable_duet": bool(options.get("disableDuet", False)),
                          "disable_stitch": bool(options.get("disableStitch", False))},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size, "total_chunk_count": 1}}, timeout=30), "TIKTOK_UPLOAD_INIT_FAILED")
        upload_url, publish_id = init.get("data", {}).get("upload_url"), init.get("data", {}).get("publish_id", "")
        if not upload_url:
            raise PublishError("TIKTOK_UPLOAD_INIT_FAILED", "TikTok không trả upload URL.")
        with path.open("rb") as media:
            response = self.http.put(upload_url, headers={"Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{size-1}/{size}"}, data=media, timeout=900)
        if not response.ok:
            raise PublishError("TIKTOK_UPLOAD_FAILED", f"TikTok upload HTTP {response.status_code}",
                               retryable=response.status_code in RETRYABLE_HTTP)
        # Direct Post is asynchronous. Poll the publish ticket instead of
        # claiming success merely because the bytes reached TikTok.
        status_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        for _ in range(30):
            status_data = _json_response(self.http.post(
                "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                headers=status_headers, json={"publish_id": publish_id}, timeout=30),
                "TIKTOK_STATUS_FAILED")
            state = status_data.get("data", {}).get("status", "")
            if state == "PUBLISH_COMPLETE":
                post_ids = status_data.get("data", {}).get("publicaly_available_post_id", [])
                post_id = str(post_ids[0]) if post_ids else ""
                return {"publish_id": publish_id, "post_id": post_id,
                        "post_url": f"https://www.tiktok.com/@{account['provider_account_id']}/video/{post_id}" if post_id else ""}
            if state == "FAILED":
                raise PublishError("TIKTOK_PROCESSING_FAILED",
                                   str(status_data.get("data", {}).get("fail_reason", "TikTok từ chối video.")))
            time.sleep(2)
        raise PublishError("TIKTOK_PROCESSING_TIMEOUT", "TikTok vẫn đang xử lý; hãy kiểm tra lại lịch sử.")


class PublishWorker:
    def __init__(self, store: SocialStore, publisher: Optional[ProviderPublisher] = None,
                 worker_id: Optional[str] = None, poll_seconds: int = 10):
        self.store = store
        self.publisher = publisher or ProviderPublisher(store)
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def process_once(self) -> bool:
        self.store.heartbeat(self.worker_id)
        job = self.store.claim_due_job(self.worker_id)
        if not job:
            return False
        try:
            current = validate_media(job["media_path"], job["platform"])
            if current["sha256"] != job["media_sha256"]:
                raise PublishError("MEDIA_CHANGED", "Video đã thay đổi sau khi lên lịch.")
            self.store.update_job(job["id"], "uploading", attempt_count=int(job["attempt_count"]) + 1)
            receipt = self.publisher.publish(job)
            self.store.update_job(job["id"], "published", provider_publish_id=receipt.get("publish_id"),
                                  provider_post_id=receipt.get("post_id"), provider_post_url=receipt.get("post_url"),
                                  claimed_by=None, claim_expires_at=None)
        except PublishError as exc:
            attempts = int(job["attempt_count"]) + 1
            if exc.retryable and attempts < 3:
                delay = 2 ** attempts * 15
                self.store.update_job(job["id"], "queued", attempt_count=attempts,
                    next_attempt_at=iso_utc(utc_now() + timedelta(seconds=delay)),
                    last_error_code=exc.code, last_error_message=exc.message,
                    claimed_by=None, claim_expires_at=None)
            else:
                status = "blocked" if exc.code in {"TOKEN_EXPIRED", "PERMISSION_REQUIRED", "ACCOUNT_DISCONNECTED"} else "failed"
                self.store.update_job(job["id"], status, attempt_count=attempts,
                    last_error_code=exc.code, last_error_message=exc.message,
                    claimed_by=None, claim_expires_at=None)
        except Exception:
            self.store.update_job(job["id"], "unknown", last_error_code="PROVIDER_RESULT_UNKNOWN",
                                  last_error_message="Không xác định provider đã nhận video hay chưa.",
                                  claimed_by=None, claim_expires_at=None)
        return True

    def start(self) -> "PublishWorker":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.worker_id, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.process_once()
            except Exception:
                worked = False
            self._stop.wait(0.2 if worked else self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()
