"""Streamlit views for the social publishing module."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from social_publisher import OAuthManager, PublishError, SocialStore, validate_media


PLATFORM_LABELS = {
    "facebook_page": "Facebook Fanpage",
    "youtube_short": "YouTube Shorts",
    "tiktok": "TikTok",
}
STATUS_LABELS = {
    "scheduled": "🕒 Đã lên lịch", "queued": "⏳ Chờ đăng", "validating": "🔎 Đang kiểm tra",
    "uploading": "⬆️ Đang tải", "processing": "⚙️ Đang xử lý", "published": "✅ Đã đăng",
    "failed": "❌ Thất bại", "blocked": "🔒 Cần kết nối lại", "cancelled": "🚫 Đã hủy",
    "unknown": "⚠️ Cần đối soát",
}


def _show_error(st: Any, error: Exception) -> None:
    if isinstance(error, PublishError):
        st.error(f"{error.code}: {error.message}")
    else:
        st.error("UNEXPECTED_ERROR: Có lỗi không mong đợi. Chi tiết đã được giữ khỏi giao diện.")


def handle_oauth_callback(st: Any, store: SocialStore) -> None:
    params = st.query_params
    code, state = params.get("code"), params.get("state")
    platform = params.get("social_provider")
    if params.get("error"):
        st.warning("Bạn đã hủy hoặc từ chối kết nối kênh.")
        return
    if not (code and state and platform in {"facebook", "youtube", "tiktok"}):
        return
    marker = f"oauth_done_{state}"
    if st.session_state.get(marker):
        return
    try:
        account_ids = OAuthManager(store).complete(platform, code, state)
        st.session_state[marker] = True
        st.success(f"✅ Đã kết nối {len(account_ids)} kênh/tài khoản.")
        for key in ("code", "state", "scope", "authuser", "prompt", "social_provider"):
            if key in st.query_params:
                del st.query_params[key]
    except Exception as exc:
        _show_error(st, exc)


def render_connection_settings(st: Any, store: SocialStore) -> None:
    st.divider()
    st.header("📣 Kết nối kênh xuất bản")
    st.caption("OAuth app key và token được lưu cục bộ trong file .env; không ghi vào database hoặc log.")
    handle_oauth_callback(st, store)

    definitions = [
        ("facebook", "Facebook Fanpage", "Kết nối Fanpage"),
        ("youtube", "YouTube", "Kết nối thêm kênh YouTube"),
        ("tiktok", "TikTok", "Kết nối TikTok"),
    ]
    for platform, title, connect_label in definitions:
        existing = store.get_app_credentials(platform)
        with st.expander(f"🔌 {title}", expanded=False):
            client_label = "Client Key" if platform == "tiktok" else "Client ID"
            client_id = st.text_input(client_label, value=existing.get("client_id", ""),
                                      key=f"social_{platform}_client_id")
            client_secret = st.text_input("Client Secret", value="", type="password",
                                          placeholder="Để trống nếu không thay đổi",
                                          key=f"social_{platform}_client_secret")
            redirect = st.text_input("OAuth Redirect URI", value=existing.get("redirect_uri", ""),
                                     placeholder=f"http://localhost:8501/?social_provider={platform}",
                                     key=f"social_{platform}_redirect")
            graph_version = ""
            if platform == "facebook":
                graph_version = st.text_input("Meta Graph API version", value=existing.get("graph_version", "v24.0"),
                                              key="social_meta_graph_version")
            if platform == "youtube":
                st.caption("Quyền dùng: youtube.upload để đăng và youtube.readonly để hiện đúng Channel ID.")
            cols = st.columns(2)
            if cols[0].button("💾 Lưu cấu hình", key=f"save_social_{platform}", width="stretch"):
                secret = client_secret or existing.get("client_secret", "")
                if not client_id.strip() or not secret or not redirect.strip():
                    st.error("Cần nhập đủ Client ID/Key, Client Secret và Redirect URI.")
                else:
                    value = {"client_id": client_id.strip(), "client_secret": secret,
                             "redirect_uri": redirect.strip()}
                    if graph_version:
                        value["graph_version"] = graph_version.strip()
                    store.set_app_credentials(platform, value)
                    st.success("Đã lưu cấu hình mã hóa.")
                    existing = value
            if existing.get("client_id") and existing.get("client_secret") and existing.get("redirect_uri"):
                try:
                    url = OAuthManager(store).authorization_url(platform)
                    cols[1].link_button(f"🔐 {connect_label}", url, width="stretch")
                except Exception as exc:
                    _show_error(st, exc)

    accounts = store.list_accounts(connected_only=False)
    if accounts:
        st.subheader("Kênh đã kết nối")
        for account in accounts:
            cols = st.columns([1, 4, 2, 1])
            if account.get("avatar_url"):
                cols[0].image(account["avatar_url"], width=42)
            cols[1].markdown(f"**{account['display_name']}**  \n`{account['provider_account_id']}`")
            cols[2].write(f"{PLATFORM_LABELS.get(account['platform'], account['platform'])} · {account['status']}")
            if account["status"] == "connected" and cols[3].button("Ngắt", key=f"disconnect_{account['id']}"):
                store.disconnect_account(account["id"])
                st.rerun()
    else:
        st.info("Chưa có Fanpage, kênh YouTube hoặc TikTok nào được kết nối.")


def _default_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    value = metadata if isinstance(metadata, dict) else {}
    return {"title": str(value.get("title", "")), "description": str(value.get("description", "")),
            "tags": value.get("tags", []) if isinstance(value.get("tags", []), list) else []}


def render_publish_composer(st: Any, store: SocialStore, media_path: str,
                            metadata: Optional[Dict[str, Any]] = None, key_prefix: str = "publish") -> None:
    path = Path(media_path).expanduser()
    if not path.is_file():
        st.error("MEDIA_INVALID: Không tìm thấy video để đăng.")
        return
    accounts = store.list_accounts()
    if not accounts:
        st.warning("Hãy kết nối ít nhất một Fanpage/kênh trong Settings trước.")
        return
    meta = _default_metadata(metadata)
    st.markdown("### 1. Chọn nơi đăng")
    selected = []
    for platform in ("facebook_page", "youtube_short", "tiktok"):
        platform_accounts = [a for a in accounts if a["platform"] == platform]
        if not platform_accounts:
            continue
        st.markdown(f"**{PLATFORM_LABELS[platform]}**")
        for account in platform_accounts:
            label = f"{account['display_name']} · {account['provider_account_id']}"
            if st.checkbox(label, value=False, key=f"{key_prefix}_target_{account['id']}"):
                selected.append(account)
    if not selected:
        st.info("Chưa chọn kênh nào. Video sẽ không được đăng.")
        return

    st.markdown("### 2. Nội dung từng kênh")
    targets = []
    for account in selected:
        platform = account["platform"]
        with st.expander(f"{PLATFORM_LABELS[platform]} · {account['display_name']}", expanded=True):
            if platform == "youtube_short":
                title = st.text_input("Tiêu đề", value=meta["title"][:100], key=f"{key_prefix}_title_{account['id']}")
                description = st.text_area("Mô tả", value=meta["description"], key=f"{key_prefix}_desc_{account['id']}")
                tags = st.text_input("Tags (phân cách dấu phẩy)", value=", ".join(map(str, meta["tags"])),
                                     key=f"{key_prefix}_tags_{account['id']}")
                privacy = st.selectbox("Quyền riêng tư", ["private", "unlisted", "public"],
                                       key=f"{key_prefix}_privacy_{account['id']}")
                made_for_kids = st.checkbox("Nội dung dành cho trẻ em", value=False,
                                            key=f"{key_prefix}_kids_{account['id']}")
                notify = st.checkbox("Thông báo người đăng ký", value=False,
                                     key=f"{key_prefix}_notify_{account['id']}")
                options = {"title": title, "description": description,
                           "tags": [t.strip() for t in tags.split(",") if t.strip()], "categoryId": "22",
                           "privacyStatus": privacy, "notifySubscribers": notify,
                           "selfDeclaredMadeForKids": made_for_kids, "containsSyntheticMedia": True}
                caption = title
            elif platform == "tiktok":
                caption = st.text_area("Caption", value=(meta["title"] + "\n\n" + " ".join("#" + str(t).replace(" ", "") for t in meta["tags"][:7])).strip(),
                                       key=f"{key_prefix}_caption_{account['id']}")
                privacy = st.selectbox("Quyền riêng tư", ["SELF_ONLY", "PUBLIC_TO_EVERYONE",
                    "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"], key=f"{key_prefix}_tt_privacy_{account['id']}")
                options = {"privacyLevel": privacy,
                           "disableComment": st.checkbox("Tắt bình luận", key=f"{key_prefix}_tt_comment_{account['id']}"),
                           "disableDuet": st.checkbox("Tắt Duet", key=f"{key_prefix}_tt_duet_{account['id']}"),
                           "disableStitch": st.checkbox("Tắt Stitch", key=f"{key_prefix}_tt_stitch_{account['id']}")}
            else:
                caption = st.text_area("Caption", value=(meta["title"] + "\n\n" + meta["description"]).strip(),
                                       key=f"{key_prefix}_caption_{account['id']}")
                options = {"mode": "reel"}
            targets.append({"account_id": account["id"], "platform": platform,
                            "caption": caption, "options": options})

    st.markdown("### 3. Thời điểm đăng")
    mode = st.radio("", ["Đăng ngay", "Đặt lịch"], horizontal=True, key=f"{key_prefix}_schedule_mode")
    tz_name = st.selectbox("Múi giờ", ["Asia/Ho_Chi_Minh", "UTC"], key=f"{key_prefix}_timezone")
    tz = ZoneInfo(tz_name)
    if mode == "Đặt lịch":
        cols = st.columns(2)
        chosen_date = cols[0].date_input("Ngày đăng", value=(datetime.now(tz) + timedelta(days=1)).date(),
                                         key=f"{key_prefix}_date")
        chosen_time = cols[1].time_input("Giờ đăng", value=datetime.now(tz).replace(second=0, microsecond=0).time(),
                                         key=f"{key_prefix}_time")
        publish_at = datetime.combine(chosen_date, chosen_time, tzinfo=tz)
        st.caption(f"Lịch: {publish_at.isoformat()} · UTC: {publish_at.astimezone(ZoneInfo('UTC')).isoformat()}")
    else:
        publish_at = datetime.now(tz)

    st.markdown("### 4. Xác nhận")
    st.write(f"Video: `{path.name}` · {len(targets)} kênh · **{mode}**")
    if st.button("✅ Xác nhận đăng", type="primary", width="stretch", key=f"{key_prefix}_confirm"):
        try:
            result = store.create_batch(str(path), targets, publish_at, tz_name, confirmed=True)
            st.success(f"Đã tạo {len(result['job_ids'])} tác vụ xuất bản.")
            st.session_state[f"{key_prefix}_submitted"] = True
        except Exception as exc:
            _show_error(st, exc)


def render_post_render_publish(st: Any, store: SocialStore, media_path: str,
                               metadata: Optional[Dict[str, Any]] = None, key_prefix: str = "rendered") -> None:
    path = Path(media_path)
    st.markdown("### 👀 Duyệt video trước khi đăng")
    st.caption("Hãy xem, tua và kiểm tra hình/tiếng/phụ đề. Render thành công không tự động đăng.")
    st.video(str(path))
    fingerprint = f"{path.resolve()}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
    state_key = f"{key_prefix}_open_{hash(fingerprint)}"
    if st.button("📣 Đăng video", type="primary", width="stretch", key=f"{state_key}_button"):
        st.session_state[state_key] = True
    if st.session_state.get(state_key):
        render_publish_composer(st, store, str(path), metadata, key_prefix=state_key)


def render_publish_tab(st: Any, store: SocialStore) -> None:
    st.header("📣 Xuất bản")
    healthy = store.worker_is_healthy()
    (st.success if healthy else st.warning)("🟢 Worker đang chạy" if healthy else "🟠 Worker chưa có heartbeat trong 90 giây")
    compose, history = st.tabs(["Tạo bài từ video cũ", "Lịch & lịch sử"])
    with compose:
        base = Path.home() / "Desktop" / "AI_Videos"
        videos = sorted(base.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:100] if base.exists() else []
        labels = {f"{p.name} · {p.stat().st_size / 1024 / 1024:.1f} MB": p for p in videos}
        selected = st.selectbox("Chọn video", [""] + list(labels), key="social_old_video")
        manual = st.text_input("Hoặc đường dẫn MP4", key="social_manual_video")
        candidate = manual.strip() or (str(labels[selected]) if selected else "")
        if candidate:
            st.video(candidate)
            if st.button("Chọn nơi đăng", key="social_old_open"):
                st.session_state["social_old_composer"] = True
            if st.session_state.get("social_old_composer"):
                render_publish_composer(st, store, candidate, {}, key_prefix="old_video")
    with history:
        filters = st.columns(2)
        platform = filters[0].selectbox("Nền tảng", [""] + list(PLATFORM_LABELS),
                                        format_func=lambda x: "Tất cả" if not x else PLATFORM_LABELS[x])
        status = filters[1].selectbox("Trạng thái", [""] + list(STATUS_LABELS),
                                     format_func=lambda x: "Tất cả" if not x else STATUS_LABELS[x])
        jobs = store.list_jobs(platform=platform, status=status)
        if not jobs:
            st.info("Chưa có tác vụ xuất bản.")
        for job in jobs:
            with st.expander(f"{STATUS_LABELS.get(job['status'], job['status'])} · {job['display_name']} · {Path(job['media_path']).name}"):
                st.write(f"Nền tảng: {PLATFORM_LABELS.get(job['platform'])}")
                st.write(f"Lịch UTC: `{job['scheduled_at_utc']}` · thử: {job['attempt_count']}")
                if job.get("provider_post_url"):
                    st.link_button("Mở bài đăng", job["provider_post_url"])
                if job.get("last_error_code"):
                    st.error(f"{job['last_error_code']}: {job.get('last_error_message', '')}")
                if job["status"] == "scheduled" and st.button("Hủy lịch", key=f"cancel_{job['id']}"):
                    if store.cancel_job(job["id"]):
                        st.rerun()
