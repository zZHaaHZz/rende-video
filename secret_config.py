"""Store application secrets in a gitignored project .env file."""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any


ENV_FILE = Path(__file__).resolve().with_name(".env")
SECRET_ENV_MAP = {
    "gemini": "GEMINI_API_KEYS",
    "groq": "GROQ_API_KEYS",
    "pexels": "PEXELS_API_KEYS",
    "pixabay": "PIXABAY_API_KEY",
    "openai": "OPENAI_API_KEY",
    "useapi_token": "USEAPI_TOKEN",
    "useapi_email": "USEAPI_EMAIL",
}
LIST_SECRET_FIELDS = {"gemini", "groq", "pexels"}
SOCIAL_APP_ENV = "SOCIAL_APP_CREDENTIALS"
SOCIAL_ACCOUNT_ENV = "SOCIAL_ACCOUNT_CREDENTIALS"
_ENV_LOCK = threading.RLock()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


def _parse_env(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def load_secrets(path: Path = ENV_FILE) -> dict[str, Any]:
    file_values = _parse_env(path)
    result: dict[str, Any] = {}
    for field, env_name in SECRET_ENV_MAP.items():
        raw = os.environ.get(env_name, file_values.get(env_name, ""))
        if field in LIST_SECRET_FIELDS:
            try:
                parsed = json.loads(raw) if raw else []
                result[field] = [str(item) for item in parsed] if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                result[field] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            try:
                parsed = json.loads(raw) if raw else ""
                result[field] = parsed if isinstance(parsed, str) else ""
            except json.JSONDecodeError:
                result[field] = raw
    return result


def save_secrets(values: dict[str, Any], path: Path = ENV_FILE) -> None:
    """Update managed variables while preserving unrelated .env entries."""
    with _ENV_LOCK:
        managed_names = set(SECRET_ENV_MAP.values())
        preserved = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                name = line.split("=", 1)[0].strip() if "=" in line else ""
                if name not in managed_names:
                    preserved.append(line)

        generated = ["# API credentials managed by the app Settings tab."]
        for field, env_name in SECRET_ENV_MAP.items():
            value = values.get(field, [] if field in LIST_SECRET_FIELDS else "")
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            generated.append(f"{env_name}='{encoded}'")
        content = "\n".join(preserved + ([""] if preserved else []) + generated) + "\n"
        _atomic_write(path, content)


def load_social_secrets(path: Path = ENV_FILE) -> tuple[dict[str, Any], dict[str, Any]]:
    values = _parse_env(path)

    def object_value(name: str) -> dict[str, Any]:
        raw = os.environ.get(name, values.get(name, ""))
        try:
            parsed = json.loads(raw) if raw else {}
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    return object_value(SOCIAL_APP_ENV), object_value(SOCIAL_ACCOUNT_ENV)


def save_social_secrets(apps: dict[str, Any], accounts: dict[str, Any],
                        path: Path = ENV_FILE) -> None:
    """Persist OAuth app credentials and account tokens in .env."""
    managed_names = {SOCIAL_APP_ENV, SOCIAL_ACCOUNT_ENV}
    with _ENV_LOCK:
        preserved = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                name = line.split("=", 1)[0].strip() if "=" in line else ""
                if name not in managed_names:
                    preserved.append(line)
        generated = [
            "# Social OAuth credentials managed by the app Settings tab.",
            f"{SOCIAL_APP_ENV}='{json.dumps(apps, ensure_ascii=False, separators=(',', ':'))}'",
            f"{SOCIAL_ACCOUNT_ENV}='{json.dumps(accounts, ensure_ascii=False, separators=(',', ':'))}'",
        ]
        content = "\n".join(preserved + ([""] if preserved else []) + generated) + "\n"
        _atomic_write(path, content)


def extract_legacy_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Remove old plaintext secret fields from a JSON config and return them."""
    return {field: config.pop(field) for field in SECRET_ENV_MAP if field in config}
