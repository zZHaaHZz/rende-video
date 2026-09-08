# AI Video Creator

Ứng dụng Streamlit tạo video từ chủ đề hoặc kịch bản: viết nội dung bằng AI, tạo giọng đọc, tìm footage, dựng phụ đề, render MP4 và xuất bản lên mạng xã hội.

## Tính năng

- Pipeline video dài và Shorts: kịch bản → cảnh → voice → footage → phụ đề → MP4.
- Gemini, Groq và OpenAI cho kịch bản, hình ảnh và thumbnail.
- CapCut TTS (20+ giọng Việt/Anh/Hàn), Edge TTS và Groq TTS.
- Footage từ Pexels, Pixabay và Coverr; xen kẽ video + ảnh tự động.
- Veo 3 Studio và Creative Studio cho video AI theo từng cảnh.
- Đăng ngay hoặc đặt lịch lên Facebook Fanpage, YouTube Shorts và TikTok.
- Lưu nhiều API key để tự động fallback khi hết quota.
- Cache TTS theo hash (giọng + tốc độ + text) — chỉ re-generate khi thay đổi.

## Yêu cầu

- Python 3.9 trở lên.
- FFmpeg (standard build) — **dùng `brew install ffmpeg`, không dùng `ffmpeg-full`**.
- Node.js chỉ cần khi sử dụng project độc lập `Auto-Create-Video/`.

## Cài đặt

```bash
git clone <repo-url>
cd ai-video-creator

python3 -m venv venv
source venv/bin/activate
pip install streamlit requests cryptography edge-tts google-genai playwright watchdog
```

Cài FFmpeg trên macOS:

```bash
brew install ffmpeg
```

> ⚠️ **Không dùng `ffmpeg-full`** — bản này hay bị broken do dependency `libx265` không tương thích sau khi upgrade Homebrew. App tự động chọn bản hoạt động được.

## Chạy ứng dụng

```bash
python3 -m streamlit run tool.py
```

Sau đó mở [http://localhost:8501](http://localhost:8501).

> 💡 Cài `watchdog` để Streamlit tự reload khi sửa code: `pip install watchdog`

Các tab chính:

1. **Pipeline:** tạo video dài hoặc Shorts.
2. **Veo3 Studio:** tạo clip bằng Veo 3.
3. **Creative Studio:** xây storyboard và dựng phim theo cảnh.
4. **Xuất bản:** duyệt, đăng ngay hoặc đặt lịch.
5. **Settings:** quản lý API key và kết nối tài khoản mạng xã hội.

## Cấu hình API key

Cách khuyến nghị là chạy app và nhập key trong tab **Settings**. App đọc và ghi file `.env` tại thư mục gốc của project.

Có thể tạo thủ công từ file mẫu:

```bash
cp .env.example .env
```

Các biến được hỗ trợ:

| Biến | Định dạng | Công dụng |
|---|---|---|
| `GEMINI_API_KEYS` | JSON array | Gemini, Imagen và Veo API |
| `GROQ_API_KEYS` | JSON array | LLM và Groq TTS |
| `PEXELS_API_KEYS` | JSON array | Video và ảnh Pexels |
| `PIXABAY_API_KEY` | JSON string | Video, ảnh và nhạc Pixabay |
| `OPENAI_API_KEY` | JSON string | OpenAI và DALL-E |
| `USEAPI_TOKEN` | JSON string | Google Flow qua UseAPI |
| `USEAPI_EMAIL` | JSON string | Tài khoản Google Flow tùy chọn |
| `SOCIAL_APP_CREDENTIALS` | JSON object | Client ID/Secret Facebook, YouTube và TikTok |
| `SOCIAL_ACCOUNT_CREDENTIALS` | JSON object | Access/refresh token của các kênh đã kết nối |

Ví dụ cú pháp nằm trong [`.env.example`](.env.example). `.env` đã được Git bỏ qua và app đặt quyền file thành `600` trên hệ thống POSIX.

Không commit hoặc gửi file `.env` cho người khác.

## Kết nối mạng xã hội

Trong **Settings**, nhập Client ID/Key, Client Secret và Redirect URI cho nền tảng cần dùng, sau đó bấm nút kết nối OAuth.

Credential mạng xã hội cũng nằm trong `.env`. App tự cập nhật biến `SOCIAL_ACCOUNT_CREDENTIALS` khi OAuth cấp hoặc refresh token. Dữ liệu mới trong `~/.avc_social/social.db` chỉ giữ metadata tài khoản, lịch đăng và audit; bản mã hóa legacy được giữ làm backup cho tới khi người dùng chủ động xóa.

Xem hướng dẫn chi tiết tại [`docs/social-publishing-setup.md`](docs/social-publishing-setup.md).

## Dữ liệu cục bộ

| Đường dẫn | Nội dung |
|---|---|
| `.env` | API key của app |
| `~/.avc_config.json` | Thiết lập không nhạy cảm và lịch sử footage |
| `~/.avc_project.json` | Trạng thái pipeline video dài |
| `~/.avc_project_shorts.json` | Trạng thái pipeline Shorts |
| `~/.avc_creative_project.json` | Trạng thái Creative Studio |
| `~/.avc_audio/` | Cache TTS (hash theo giọng + tốc độ + text) |
| `~/.avc_social/social.db` | Metadata tài khoản, lịch đăng và audit; không chứa credential thật |
| `~/Desktop/AI_Videos/` | Video xuất ra mặc định |

## Cấu trúc project

```text
ai-video-creator/
├── tool.py                 # Ứng dụng Streamlit chính
├── secret_config.py        # Đọc, ghi và migrate API key sang .env
├── creative_studio.py      # Storyboard và dựng video sáng tạo
├── social_publisher.py     # OAuth, database, worker và provider publishing
├── social_publisher_ui.py  # Giao diện kết nối và xuất bản
├── veo3_video.py           # Tích hợp Veo 3 API
├── capcut_tts.py           # Adapter CapCut TTS (20+ giọng, retry, cache)
├── vietnamese_tts.py       # Chuẩn hóa nội dung tiếng Việt cho TTS
├── video_config.py         # Kiểm tra cấu hình script import
├── capcut-tts-api/         # Client CapCut TTS (submit/poll/download)
├── Auto-Create-Video/      # Pipeline TypeScript độc lập
└── docs/                   # Spec và tài liệu thiết kế
```

## Kiểm thử

Chạy bộ unit test chính:

```bash
python3 -m unittest -q \
  test_secret_config.py \
  test_video_config.py \
  test_vietnamese_tts.py \
  test_creative_studio.py \
  test_social_publisher.py
```

Kiểm tra pipeline TypeScript độc lập:

```bash
cd Auto-Create-Video
npm test
npm run typecheck
```

## Xử lý lỗi thường gặp

- **TTS cảnh 1 fail, cảnh còn lại có cache:** hash thay đổi do đổi giọng/tốc độ — bấm **Render lại**, cảnh có cache không bị tạo lại.
- **FFmpeg không tìm thấy hoặc crash (libx265/libx264):** gỡ `ffmpeg-full` rồi cài lại `ffmpeg` standard: `brew uninstall ffmpeg-full && brew install ffmpeg`.
- **Phụ đề không xuất hiện:** FFmpeg standard đã có `libass`; nếu vẫn lỗi chạy `ffmpeg -filters | grep ass`.
- **API hết quota:** thêm key dự phòng trong Settings.
- **Key không được nhận sau khi cập nhật:** khởi động lại tiến trình Streamlit (`Ctrl+C` → `python3 -m streamlit run tool.py`).
- **OAuth hết hạn:** vào Settings và kết nối lại tài khoản tương ứng.
- **Streamlit không tự reload sau khi sửa code:** cài `pip install watchdog` để bật file watcher nhanh.

## Bảo mật

- Không ghi API key hoặc credential vào log.
- `.env` chỉ lưu cục bộ và không được Git theo dõi.
- Credential mạng xã hội nằm dạng plaintext trong `.env`; file được đặt quyền `600` nhưng vẫn phải được bảo vệ như mật khẩu.

## Giấy phép

Project dành cho mục đích cá nhân hoặc nội bộ. Khi xuất bản thương mại, hãy kiểm tra điều khoản hiện hành của từng nhà cung cấp AI, TTS và footage.
