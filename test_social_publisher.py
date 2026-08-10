import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from social_publisher import (
    OAuthManager,
    ProviderPublisher,
    PublishError,
    PublishWorker,
    SocialStore,
    sha256_file,
    validate_media,
)


class FakeResponse:
    def __init__(self, data=None, status=200, headers=None):
        self._data = data or {}
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
    def json(self):
        return self._data


class FakeYouTubeOAuthSession:
    def post(self, url, **kwargs):
        return FakeResponse({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    def get(self, url, **kwargs):
        return FakeResponse({"items": [{"id": "UC-one", "snippet": {"title": "Kênh Một"}},
                                       {"id": "UC-two", "snippet": {"title": "Kênh Hai"}}]})


class FakeYouTubePublishSession:
    def __init__(self):
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse({}, headers={"Location": "https://upload.example/session"})
    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return FakeResponse({"id": "video-123"})
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse({"items": [{"processingDetails": {"processingStatus": "succeeded"}}]})


def fake_probe(_path):
    return {"codec": "h264", "width": 1080, "height": 1920,
            "duration": 60.0, "format": "mov,mp4"}


class SocialPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SocialStore(root / "social.db", root / "key", root / ".env")
        self.video = root / "video.mp4"
        self.video.write_bytes(b"not-real-but-probe-is-injected")
        self.facebook_id = self.store.upsert_account(
            "facebook_page", "page-1", "Trang 1", {"access_token": "secret-token"},
            ["pages_manage_posts"])
        self.youtube_id = self.store.upsert_account(
            "youtube_short", "channel-1", "Kenh 1", {"access_token": "youtube-token"},
            OAuthManager.YOUTUBE_SCOPES)

    def tearDown(self):
        self.tmp.cleanup()

    def test_credentials_are_stored_in_env_not_database(self):
        raw = self.store.db_path.read_bytes()
        self.assertNotIn(b"secret-token", raw)
        self.assertIn("secret-token", self.store.env_path.read_text())
        account = self.store.get_account(self.facebook_id, include_credential=True)
        self.assertEqual(account["credential"]["access_token"], "secret-token")

    def test_oauth_state_is_single_use_and_expires(self):
        state = self.store.create_oauth_attempt("youtube", "http://localhost/callback")
        self.assertEqual(self.store.consume_oauth_attempt(state, "youtube"), "http://localhost/callback")
        with self.assertRaises(PublishError) as caught:
            self.store.consume_oauth_attempt(state, "youtube")
        self.assertEqual(caught.exception.code, "OAUTH_STATE_INVALID")

    def test_youtube_authorization_uses_only_approved_scopes(self):
        self.store.set_app_credentials("youtube", {"client_id": "id", "client_secret": "secret",
                                                       "redirect_uri": "http://localhost/?social_provider=youtube"})
        url = OAuthManager(self.store).authorization_url("youtube")
        self.assertIn("youtube.upload", url)
        self.assertIn("youtube.readonly", url)
        self.assertNotIn("youtube.force-ssl", url)

    def test_media_rejects_landscape_and_over_180_seconds_for_shorts(self):
        def landscape(_):
            return {"codec": "h264", "width": 1920, "height": 1080, "duration": 30, "format": "mp4"}
        with self.assertRaises(PublishError) as caught:
            validate_media(self.video, "youtube_short", landscape)
        self.assertEqual(caught.exception.code, "NOT_YOUTUBE_SHORT")
        def too_long(_):
            return {"codec": "h264", "width": 1080, "height": 1920, "duration": 181, "format": "mp4"}
        with self.assertRaises(PublishError):
            validate_media(self.video, "youtube_short", too_long)

    def test_confirmation_and_target_are_required(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page",
                   "caption": "Caption", "options": {}}]
        with self.assertRaises(PublishError) as caught:
            self.store.create_batch(str(self.video), target, datetime.now(timezone.utc), "UTC", False, fake_probe)
        self.assertEqual(caught.exception.code, "CONSENT_REQUIRED")
        with self.assertRaises(PublishError) as caught:
            self.store.create_batch(str(self.video), [], datetime.now(timezone.utc), "UTC", True, fake_probe)
        self.assertEqual(caught.exception.code, "TARGET_INVALID")

    def test_multi_target_batch_creates_independent_jobs(self):
        targets = [
            {"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}},
            {"account_id": self.youtube_id, "platform": "youtube_short", "caption": "YT",
             "options": {"title": "YT", "privacyStatus": "private"}},
        ]
        result = self.store.create_batch(str(self.video), targets, datetime.now(timezone.utc), "UTC", True, fake_probe)
        self.assertEqual(len(result["job_ids"]), 2)
        self.assertEqual({j["platform"] for j in self.store.list_jobs()}, {"facebook_page", "youtube_short"})

    def test_schedule_in_past_is_rejected_and_future_is_scheduled(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}}]
        with self.assertRaises(PublishError) as caught:
            self.store.create_batch(str(self.video), target, datetime.now(timezone.utc) - timedelta(minutes=1),
                                    "UTC", True, fake_probe)
        self.assertEqual(caught.exception.code, "SCHEDULE_IN_PAST")
        self.store.create_batch(str(self.video), target, datetime.now(timezone.utc) + timedelta(hours=1),
                                "UTC", True, fake_probe)
        self.assertEqual(self.store.list_jobs()[0]["status"], "scheduled")

    def test_atomic_claim_allows_only_one_worker(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}}]
        self.store.create_batch(str(self.video), target, datetime.now(timezone.utc), "UTC", True, fake_probe)
        barrier = threading.Barrier(3)
        results = []
        def claim(worker):
            barrier.wait()
            results.append(self.store.claim_due_job(worker))
        threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_disconnect_blocks_scheduled_jobs_and_removes_secret(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}}]
        self.store.create_batch(str(self.video), target, datetime.now(timezone.utc) + timedelta(hours=1),
                                "UTC", True, fake_probe)
        self.store.disconnect_account(self.facebook_id)
        self.assertEqual(self.store.list_jobs()[0]["status"], "blocked")
        self.assertEqual(self.store.get_account(self.facebook_id, True)["credential"], {})

    def test_cancel_only_scheduled_job(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}}]
        result = self.store.create_batch(str(self.video), target, datetime.now(timezone.utc) + timedelta(hours=1),
                                         "UTC", True, fake_probe)
        self.assertTrue(self.store.cancel_job(result["job_ids"][0]))
        self.assertFalse(self.store.cancel_job(result["job_ids"][0]))

    def test_duplicate_channel_updates_instead_of_creating_duplicate(self):
        second = self.store.upsert_account("youtube_short", "channel-1", "Tên mới",
                                           {"access_token": "new"}, OAuthManager.YOUTUBE_SCOPES)
        self.assertEqual(second, self.youtube_id)
        channels = [a for a in self.store.list_accounts(False) if a["platform"] == "youtube_short"]
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["display_name"], "Tên mới")

    def test_audit_payload_redacts_secret_keys(self):
        self.store.audit("test", payload={"token": "bad", "safe": "ok", "client_secret": "bad2"})
        with self.store.connect() as db:
            payload = db.execute("SELECT safe_payload FROM audit_events WHERE event_type='test'").fetchone()[0]
        self.assertIn("ok", payload)
        self.assertNotIn("bad", payload)

    def test_youtube_oauth_connects_each_returned_channel(self):
        self.store.set_app_credentials("youtube", {"client_id": "id", "client_secret": "secret",
            "redirect_uri": "http://localhost/?social_provider=youtube"})
        state = self.store.create_oauth_attempt("youtube", "http://localhost/?social_provider=youtube")
        ids = OAuthManager(self.store, FakeYouTubeOAuthSession()).complete("youtube", "code", state)
        self.assertEqual(len(ids), 2)
        channel_ids = {a["provider_account_id"] for a in self.store.list_accounts()}
        self.assertTrue({"UC-one", "UC-two"}.issubset(channel_ids))

    def test_youtube_publisher_is_resumable_polls_processing_and_never_uploads_thumbnail(self):
        session = FakeYouTubePublishSession()
        publisher = ProviderPublisher(self.store, session)
        job = {"account_id": self.youtube_id, "platform": "youtube_short", "media_path": str(self.video),
               "caption": "Title", "options": '{"title":"Title","privacyStatus":"private"}'}
        receipt = publisher.publish(job)
        self.assertEqual(receipt["post_id"], "video-123")
        urls = " ".join(call[1] for call in session.calls)
        self.assertIn("uploadType", str(session.calls[0][2]["params"]))
        self.assertIn("processingDetails", str(session.calls[-1][2]["params"]))
        self.assertNotIn("thumbnail", urls.lower())

    def test_worker_marks_success_and_provider_exception_unknown_without_duplicate_retry(self):
        target = [{"account_id": self.facebook_id, "platform": "facebook_page", "caption": "FB", "options": {}}]
        self.store.create_batch(str(self.video), target, datetime.now(timezone.utc), "UTC", True, fake_probe)
        successful = mock.Mock()
        successful.publish.return_value = {"post_id": "p1", "post_url": "https://example/p1"}
        with mock.patch("social_publisher.validate_media", return_value={"sha256": sha256_file(self.video)}):
            self.assertTrue(PublishWorker(self.store, successful, "w-success").process_once())
        self.assertEqual(self.store.list_jobs()[0]["status"], "published")

        self.store.create_batch(str(self.video), target, datetime.now(timezone.utc), "UTC", True, fake_probe)
        uncertain = mock.Mock()
        uncertain.publish.side_effect = OSError("connection dropped after upload")
        with mock.patch("social_publisher.validate_media", return_value={"sha256": sha256_file(self.video)}):
            PublishWorker(self.store, uncertain, "w-unknown").process_once()
        self.assertEqual(self.store.list_jobs()[0]["status"], "unknown")
        self.assertEqual(uncertain.publish.call_count, 1)

    def test_worker_heartbeat_becomes_healthy(self):
        self.assertFalse(self.store.worker_is_healthy())
        self.store.heartbeat("worker-test")
        self.assertTrue(self.store.worker_is_healthy())


if __name__ == "__main__":
    unittest.main()
