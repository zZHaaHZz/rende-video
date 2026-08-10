import unittest
import tempfile
from pathlib import Path

from secret_config import (
    extract_legacy_secrets,
    load_secrets,
    load_social_secrets,
    save_secrets,
    save_social_secrets,
)


class SecretConfigTests(unittest.TestCase):
    def test_round_trip_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            values = {
                "gemini": ["gem-1", "gem-2"], "groq": ["groq-1"], "pexels": [],
                "pixabay": "pix", "openai": "openai", "useapi_token": "token",
                "useapi_email": "me@example.com",
            }
            save_secrets(values, env_file)
            self.assertEqual(load_secrets(env_file), values)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)


    def test_save_preserves_unmanaged_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("UNRELATED=value\n")
            save_secrets({}, env_file)
            self.assertIn("UNRELATED=value", env_file.read_text())


    def test_extract_removes_secrets_from_json_config(self):
        config = {"gemini": ["secret"], "tts_rate": "1.3"}
        self.assertEqual(extract_legacy_secrets(config), {"gemini": ["secret"]})
        self.assertEqual(config, {"tts_rate": "1.3"})

    def test_social_secrets_round_trip_without_removing_api_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            save_secrets({"gemini": ["gem"]}, env_file)
            apps = {"facebook": {"client_secret": "app-secret"}}
            accounts = {"account-1": {"access_token": "token"}}
            save_social_secrets(apps, accounts, env_file)
            self.assertEqual(load_social_secrets(env_file), (apps, accounts))
            self.assertEqual(load_secrets(env_file)["gemini"], ["gem"])
