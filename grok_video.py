"""
grok_video.py — Grok Aurora video generation engine
=====================================================
Uses Playwright to control Chrome with saved Grok account profiles.
Supports multiple accounts with automatic rotation when quota is hit.

How it works:
  1. Launch Chrome with saved profile (user already logged in to grok.com)
  2. Navigate to grok.com/imagine
  3. Inject JS to call Grok REST API from within the authenticated page
  4. Stream progress until video URL is returned
  5. Download MP4 and return path

Account rotation:
  - Each account has its own Chrome user-data-dir
  - When one hits quota (429), automatically switch to next
  - Profiles stored in: ./grok_profiles/account_0/, account_1/, ...
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent
PROFILES_DIR  = BASE_DIR / "grok_profiles"
DOWNLOADS_DIR = BASE_DIR / "grok_downloads"
PROFILES_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ── Grok API constants (extracted from src_veo_grok/grok/) ────────────────────
GROK_BASE             = "https://grok.com"
ENDPOINT_CREATE_POST  = f"{GROK_BASE}/rest/media/post/create"
ENDPOINT_CONVO_NEW    = f"{GROK_BASE}/rest/app-chat/conversations/new"
ENDPOINT_UPSCALE      = f"{GROK_BASE}/rest/media/video/upscale"

DEFAULT_CFG = {
    "aspectRatio": "16:9",
    "videoLength": 6,
    "resolutionName": "480p",
}


# ── Profile manager ───────────────────────────────────────────────────────────
class AccountManager:
    """Manages multiple Grok Chrome profiles and tracks quota status."""

    def __init__(self):
        self._profiles: list[dict] = self._load_profiles()
        self._current_idx: int = self._load_current_idx()

    def _profiles_file(self) -> Path:
        return PROFILES_DIR / "profiles.json"

    def _load_profiles(self) -> list[dict]:
        f = self._profiles_file()
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _load_current_idx(self) -> int:
        f = PROFILES_DIR / "current.json"
        if f.exists():
            try:
                return int(json.loads(f.read_text()).get("idx", 0))
            except Exception:
                pass
        return 0

    def save(self):
        self._profiles_file().write_text(
            json.dumps(self._profiles, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        (PROFILES_DIR / "current.json").write_text(
            json.dumps({"idx": self._current_idx}), encoding="utf-8"
        )

    def add_profile(self, name: str = "") -> dict:
        """Create a new profile slot."""
        idx = len(self._profiles)
        profile = {
            "id": idx,
            "name": name or f"account_{idx}",
            "dir": str(PROFILES_DIR / f"account_{idx}"),
            "status": "active",      # active | quota_hit | needs_login
            "quota_reset_at": 0,
            "videos_today": 0,
            "last_used": 0,
        }
        self._profiles.append(profile)
        Path(profile["dir"]).mkdir(parents=True, exist_ok=True)
        self.save()
        return profile

    def list_profiles(self) -> list[dict]:
        return self._profiles

    def get_active_profile(self) -> Optional[dict]:
        """Return next available profile, rotating past quota-hit ones."""
        now = time.time()
        count = len(self._profiles)
        if not count:
            return None

        for _ in range(count):
            p = self._profiles[self._current_idx % count]
            # Reset quota if 24h passed
            if p["status"] == "quota_hit" and now > p.get("quota_reset_at", 0):
                p["status"] = "active"
                p["videos_today"] = 0
                self.save()

            if p["status"] == "active":
                return p

            # Move to next
            self._current_idx = (self._current_idx + 1) % count

        return None

    def mark_quota_hit(self, profile_id: int):
        """Mark profile as quota hit, rotate to next."""
        for p in self._profiles:
            if p["id"] == profile_id:
                p["status"] = "quota_hit"
                p["quota_reset_at"] = time.time() + 86400  # 24h
                self._current_idx = (profile_id + 1) % len(self._profiles)
                self.save()
                print(f"[grok] ⚠️ Account {p['name']} quota hit → rotating to next")
                break

    def mark_video_done(self, profile_id: int):
        for p in self._profiles:
            if p["id"] == profile_id:
                p["videos_today"] = p.get("videos_today", 0) + 1
                p["last_used"] = time.time()
                self.save()
                break

    def mark_needs_login(self, profile_id: int):
        for p in self._profiles:
            if p["id"] == profile_id:
                p["status"] = "needs_login"
                self.save()
                break


# Global account manager
_account_mgr = AccountManager()


# ── Grok JS injection (from grok_api_text_to_video.py) ───────────────────────
GROK_JS = r"""
(async ({ prompt, cfg, timeoutSeconds }) => {
  function parseJsonObjectsFromBuffer(buffer) {
    const out = [];
    let depth = 0, inString = false, escape = false, start = -1;
    for (let i = 0; i < buffer.length; i++) {
      const ch = buffer[i];
      if (start === -1) { if (ch === '{') { start = i; depth = 1; } continue; }
      if (inString) {
        if (escape) escape = false;
        else if (ch && ch.charCodeAt(0) === 92) escape = true;
        else if (ch === '"') inString = false;
        continue;
      }
      if (ch === '"') { inString = true; continue; }
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          const slice = buffer.slice(start, i + 1);
          try { out.push(JSON.parse(slice)); } catch(e) {}
          start = -1;
        }
      }
    }
    return { objects: out, tail: start !== -1 ? buffer.slice(start) : '' };
  }

  function pickProgressEvent(objects) {
    let last = null;
    for (const obj of objects) {
      const svr = obj && obj.result && obj.result.response &&
                  obj.result.response.streamingVideoGenerationResponse;
      if (svr && typeof svr.progress === 'number') {
        last = { progress: svr.progress, videoUrl: svr.videoUrl || null,
                 parentPostId: svr.parentPostId || null };
      }
    }
    return last;
  }

  // 1. Create post
  const createRes = await fetch('https://grok.com/rest/media/post/create', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ mediaType: 'MEDIA_POST_TYPE_VIDEO', prompt }),
  });
  const createData = await createRes.json().catch(() => null);
  const parentPostId = createData && createData.post && createData.post.id;

  if (!parentPostId) {
    return { ok: false, error: 'create_post_failed', createStatus: createRes.status,
             createData: createData };
  }

  // 2. Start conversation (streaming)
  const requestId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  const convoPayload = {
    temporary: true, modelName: 'grok-3', message: prompt,
    toolOverrides: { videoGen: true }, enableSideBySide: true,
    responseMetadata: {
      experiments: [],
      modelConfigOverride: {
        modelMap: { videoGenModelConfig: Object.assign({ parentPostId }, cfg) },
      },
    },
  };

  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), Math.max(1, timeoutSeconds) * 1000);

  let lastEvent = null;
  let convoStatus = 0;
  try {
    const res = await fetch('https://grok.com/rest/app-chat/conversations/new', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-xai-request-id': requestId },
      credentials: 'include',
      body: JSON.stringify(convoPayload),
      signal: ctrl.signal,
    });
    convoStatus = res.status;

    if (res.body) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseJsonObjectsFromBuffer(buffer);
        buffer = parsed.tail;
        const ev = pickProgressEvent(parsed.objects);
        if (ev) {
          lastEvent = ev;
          if (ev.progress >= 100 && ev.videoUrl) break;
        }
      }
    } else {
      const text = await res.text();
      const parsed = parseJsonObjectsFromBuffer(text);
      lastEvent = pickProgressEvent(parsed.objects);
    }
    clearTimeout(t);
  } catch(e) {
    clearTimeout(t);
    return { ok: false, error: String(e), convoStatus, parentPostId };
  }

  if (!lastEvent || !lastEvent.videoUrl) {
    return { ok: false, error: 'no_video_url', convoStatus, parentPostId, lastEvent };
  }

  // 3. Upscale (optional, skip for free accounts to save quota)
  let finalUrl = lastEvent.videoUrl;
  let upscaleStatus = 0;
  try {
    const upRes = await fetch('https://grok.com/rest/media/video/upscale', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ videoId: parentPostId }),
    });
    upscaleStatus = upRes.status;
    if (upRes.status === 200) {
      const upData = await upRes.json().catch(() => null);
      if (upData && upData.hdMediaUrl) finalUrl = upData.hdMediaUrl;
    }
  } catch(e) {}

  return {
    ok: true, videoUrl: finalUrl, parentPostId,
    progress: lastEvent.progress, convoStatus, upscaleStatus,
  };
})
"""


# ── Core generation function ──────────────────────────────────────────────────
async def generate_video_grok(
    prompt: str,
    profile: dict,
    cfg: dict = None,
    timeout_seconds: int = 300,
    log_cb=None,
) -> dict:
    """
    Generate one video using Grok. Returns:
      { ok, video_path, video_url, error, quota_hit }
    """
    from playwright.async_api import async_playwright

    def log(msg):
        print(f"[grok:{profile['name']}] {msg}", flush=True)
        if callable(log_cb):
            log_cb(msg)

    profile_dir = Path(profile["dir"])
    profile_dir.mkdir(parents=True, exist_ok=True)

    log(f"🎬 Generating: {prompt[:60]}...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--mute-audio",
                "--window-size=1280,720",
            ],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        try:
            # Navigate to Grok
            log("🌐 Navigating to grok.com/imagine...")
            await page.goto(f"{GROK_BASE}/imagine", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Check if logged in
            current_url = page.url
            if "login" in current_url or "signin" in current_url or "accounts.x.com" in current_url:
                log("❌ Not logged in — need to login first!")
                return {"ok": False, "error": "needs_login", "profile_id": profile["id"]}

            # Call Grok API via JS injection
            log("🚀 Calling Grok API...")
            payload = {
                "prompt": prompt,
                "cfg": cfg or DEFAULT_CFG,
                "timeoutSeconds": timeout_seconds,
            }

            result = await page.evaluate(GROK_JS, payload)

            if not isinstance(result, dict):
                return {"ok": False, "error": "invalid_result", "raw": result}

            # Check quota hit (429 or specific error)
            create_status = result.get("createStatus", 0)
            convo_status = result.get("convoStatus", 0)
            if create_status == 429 or convo_status == 429:
                log("⚠️ Quota hit (429)")
                return {"ok": False, "error": "quota_hit", "quota_hit": True}

            if not result.get("ok"):
                error = result.get("error", "unknown")
                log(f"❌ Generation failed: {error}")
                return {"ok": False, "error": error, "details": result}

            video_url = result.get("videoUrl", "")
            log(f"✅ Video URL: {video_url[:80]}...")

            # Download video
            output_path = DOWNLOADS_DIR / f"{uuid.uuid4().hex}.mp4"
            downloaded = await _download_video(page, video_url, output_path)

            if downloaded:
                log(f"📥 Downloaded: {output_path.name} ({output_path.stat().st_size // 1024}KB)")
                return {
                    "ok": True,
                    "video_path": str(output_path),
                    "video_url": video_url,
                    "profile_id": profile["id"],
                }
            else:
                return {"ok": False, "error": "download_failed", "video_url": video_url}

        except Exception as e:
            log(f"❌ Error: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            await browser.close()


async def _download_video(page, url: str, out_path: Path, timeout_ms: int = 60000) -> bool:
    """Download video via Playwright context request (uses browser cookies)."""
    try:
        resp = await page.context.request.get(url, timeout=timeout_ms)
        body = await resp.body()
        if resp.status == 200 and len(body) > 10000:
            out_path.write_bytes(body)
            return True
        print(f"[grok] Download failed: status={resp.status} size={len(body)}")
        return False
    except Exception as e:
        print(f"[grok] Download error: {e}")
        return False


# ── Multi-account pipeline ────────────────────────────────────────────────────
async def generate_video_with_rotation(
    prompt: str,
    cfg: dict = None,
    timeout_seconds: int = 300,
    log_cb=None,
    max_retries: int = None,
) -> dict:
    """
    Try generating with current account, rotate if quota hit.
    Retries all available accounts before giving up.
    """
    profiles = _account_mgr.list_profiles()
    if not profiles:
        return {"ok": False, "error": "no_profiles — add accounts first via /api/grok/add-account"}

    max_retries = max_retries or len(profiles)

    for attempt in range(max_retries):
        profile = _account_mgr.get_active_profile()
        if not profile:
            return {"ok": False, "error": "all_accounts_quota_hit"}

        result = await generate_video_grok(prompt, profile, cfg, timeout_seconds, log_cb)

        if result.get("ok"):
            _account_mgr.mark_video_done(profile["id"])
            return result

        if result.get("quota_hit") or result.get("error") == "quota_hit":
            _account_mgr.mark_quota_hit(profile["id"])
            continue  # Try next account

        if result.get("error") == "needs_login":
            _account_mgr.mark_needs_login(profile["id"])
            continue  # Try next account

        # Other error — don't rotate, just return
        return result

    return {"ok": False, "error": "all_retries_exhausted"}


# ── Login helper ──────────────────────────────────────────────────────────────
async def open_login_browser(profile_id: int):
    """
    Open a visible Chrome window for user to login to Grok.
    Call this once per account to save the login session.
    """
    from playwright.async_api import async_playwright

    profiles = _account_mgr.list_profiles()
    profile = next((p for p in profiles if p["id"] == profile_id), None)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    profile_dir = Path(profile["dir"])
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"[grok] Opening Chrome for login — profile: {profile['name']}")
    print(f"[grok] Please login to grok.com in the browser window that opens...")
    print(f"[grok] After login, press Enter in this terminal to close and save session.")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--no-first-run", "--window-size=1280,900"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(f"{GROK_BASE}/imagine")

        # Wait for user to login
        print("[grok] Waiting for user to login... (press Ctrl+C when done)")
        try:
            await asyncio.sleep(120)  # 2 minutes for user to login
        except asyncio.CancelledError:
            pass
        finally:
            # Update status
            for p in _account_mgr._profiles:
                if p["id"] == profile_id:
                    p["status"] = "active"
                    _account_mgr.save()
            await browser.close()
            print(f"[grok] ✅ Session saved for profile {profile['name']}")


# ── Sync wrappers for Flask ───────────────────────────────────────────────────
def sync_generate(prompt: str, cfg: dict = None, timeout: int = 300, log_cb=None) -> dict:
    """Synchronous wrapper for use in Flask routes."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            generate_video_with_rotation(prompt, cfg, timeout, log_cb)
        )
    finally:
        loop.close()


def sync_open_login(profile_id: int):
    """Synchronous wrapper for login flow."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(open_login_browser(profile_id))
    finally:
        loop.close()


# ── Account management helpers ────────────────────────────────────────────────
def get_account_manager() -> AccountManager:
    return _account_mgr


if __name__ == "__main__":
    # Quick test: list profiles
    mgr = get_account_manager()
    profiles = mgr.list_profiles()
    print(f"Profiles: {len(profiles)}")
    for p in profiles:
        print(f"  [{p['id']}] {p['name']} — {p['status']} — {p['videos_today']} videos today")
