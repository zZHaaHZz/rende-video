# 🎬 AI Video Creator

Công cụ tạo video AI tự động — từ keyword → video hoàn chỉnh với voice, phụ đề, và thumbnail, tất cả chạy bằng **một giao diện Streamlit**.

---

## ✨ Tính Năng Chính

| Tính năng | Mô tả |
|---|---|
| 🤖 **Kịch bản AI** | Generate script theo cảnh với Gemini / Groq (llama-3.3-70b) |
| 🎙️ **TTS đa giọng** | CapCut TTS (ưu tiên) → Edge TTS → Groq TTS |
| 🎞️ **Footage CC0** | Tự động fetch video từ Pexels & Pixabay (royalty-free) |
| 📝 **Phụ đề tự động** | SRT/ASS với word-timing, UPPERCASE TikTok style |
| 🖼️ **Thumbnail AI** | DALL-E 3 (ưu tiên) → Gemini Imagen 3 |
| 🎬 **Render video** | FFmpeg ghép cảnh + voice + phụ đề → MP4 |
| 📺 **Long-form & Shorts** | Hỗ trợ video dài (main) và video ngắn (Shorts) song song |
| 🔀 **Chống trùng footage** | Global deduplication + shuffle Pexels/Pixabay kết quả |

---

## 🚀 Cài Đặt & Chạy

### 1. Clone project

```bash
git clone <repo-url>
cd ai-video-creator
```

### 2. Tạo môi trường Python

```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
# hoặc: venv\Scripts\activate   # Windows
```

### 3. Cài dependencies

```bash
pip install streamlit requests edge-tts
```

> **CapCut TTS** (optional, chất lượng cao hơn): module `capcut_tts.py` đã có sẵn trong repo — không cần cài thêm package.

### 4. Cài FFmpeg

FFmpeg là **bắt buộc** để render video và ghép phụ đề.

```bash
# macOS (Homebrew)
brew install ffmpeg

# Nếu cần libass để burn phụ đề (khuyến nghị)
brew install ffmpeg-full
```

> Script sẽ tự ưu tiên `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` nếu có.

### 5. Chạy ứng dụng

```bash
streamlit run tool.py
```

Mở trình duyệt tại `http://localhost:8501`.

---

## 🔑 Cấu Hình API Keys

Sau khi chạy app, vào tab **⚙️ Settings** để nhập API keys. Tất cả được lưu tự động vào `~/.avc_config.json`.

| API | Cần thiết | Mục đích | Lấy ở đâu |
|---|---|---|---|
| **Gemini** | Khuyến nghị | Generate kịch bản + Thumbnail Imagen | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| **Groq** | Khuyến nghị | Generate kịch bản (fallback) + Groq TTS | [console.groq.com](https://console.groq.com/keys) |
| **Pexels** | Khuyến nghị | Fetch footage video CC0 | [pexels.com/api](https://www.pexels.com/api/) |
| **Pixabay** | Optional | Footage bổ sung từ Pixabay | [pixabay.com/api/docs](https://pixabay.com/api/docs/) |
| **OpenAI** | Optional | Thumbnail DALL-E 3 (chất lượng cao hơn) | [platform.openai.com](https://platform.openai.com/api-keys) |

> **Lưu ý:** Có thể thêm nhiều Gemini key và Groq key — app sẽ tự round-robin và fallback khi quota hết.

---

## 📁 Cấu Trúc Project

```
ai-video-creator/
├── tool.py                    # 🎯 App chính (Streamlit)
├── capcut_tts.py              # Module CapCut TTS
├── grok_video.py              # Module Grok video generation
├── test_srt.py                # Test script cho SRT
│
├── capcut-tts-api/            # CapCut TTS API client (CLI)
│   ├── capcut_common_task_client.py
│   └── Voice.json             # Danh sách giọng CapCut
│
├── docs/                      # Tài liệu nội bộ
│   ├── product-plan.md        # Kế hoạch sản phẩm & user stories
│   └── whiteboard_animation_pipeline.md
│
└── .gitignore                 # Bỏ qua media, cache, env
```

### Files & Folders được tạo lúc runtime (không commit)

| Path | Mô tả |
|---|---|
| `~/.avc_config.json` | API keys + lịch sử footage đã dùng |
| `~/.avc_project.json` | Trạng thái project Main |
| `~/.avc_project_shorts.json` | Trạng thái project Shorts |
| `~/.avc_audio/` | Cache file audio TTS |
| `/tmp/avc/` | File tạm trong quá trình render |
| `~/Desktop/AI_Videos/` | Output video & thumbnail mặc định |

---

## 🎯 Workflow Sử Dụng

```
1. Settings  →  Nhập API keys
2. Topics    →  Chọn chủ đề / nhập keyword
3. Script    →  AI viết kịch bản theo cảnh
4. Edit      →  Chỉnh sửa từng cảnh (text, keyword, duration)
5. Build     →  Fetch footage + render video
6. Export    →  Tải MP4 + thumbnail + metadata
```

### Chế Độ Main vs Shorts

- **Main**: Video dài (mặc định, lưu vào `.avc_project.json`)
- **Shorts**: Video ngắn 60s (lưu vào `.avc_project_shorts.json`)
- Chuyển chế độ bằng nút toggle trong sidebar

---

## 🎙️ Voices Hỗ Trợ

### CapCut TTS (chất lượng cao nhất)
Xem danh sách đầy đủ trong `capcut-tts-api/Voice.json`. Một số giọng phổ biến:
- 🇻🇳 **Cô Gái Hoạt Ngôn** (BV074) — Tiếng Việt nữ
- 🇻🇳 **Nam Giọng Thuyết Minh** — Tiếng Việt nam
- 🇺🇸 **American Male** — English nam
- 🇰🇷 **Korean Male/Female** — Tiếng Hàn

### Edge TTS (fallback)
`vi-VN-NamMinhNeural`, `vi-VN-HoaiMyNeural`, `en-US-GuyNeural`, `en-US-JennyNeural`, `ko-KR-InJoonNeural`

---

## 🛠️ Troubleshooting

### FFmpeg không tìm thấy
```bash
which ffmpeg          # Kiểm tra FFmpeg có trong PATH chưa
brew reinstall ffmpeg # macOS: cài lại
```

### Phụ đề không hiện trên video
FFmpeg cần có **libass** để burn phụ đề. Cài `ffmpeg-full`:
```bash
brew install ffmpeg-full
```

### Quota Gemini / Groq hết
- Thêm nhiều API key trong Settings — app sẽ tự fallback
- Gemini free tier: 15 RPM / 1M TPD
- Groq free tier: ~6K TPM (llama) / 15K TPM (gemma2)

### Footage bị trùng lặp
Lịch sử footage được lưu trong `~/.avc_config.json` (key `used_videos`, tối đa 1000 entries). Xoá key này nếu muốn reset:
```bash
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.avc_config.json'
cfg = json.loads(p.read_text())
cfg['used_videos'] = []
p.write_text(json.dumps(cfg, indent=2))
print('Done — reset used_videos')
"
```

---

## 📦 Dependencies

```
streamlit
requests
edge-tts
```

> `ffmpeg` cần cài system-level (không qua pip).

Cài một lần:
```bash
pip install streamlit requests edge-tts
```

---

## 📝 License

Project này dành cho mục đích cá nhân / nội bộ.  
Footage từ **Pexels** (CC0) và **Pixabay** (Pixabay License) — an toàn cho YouTube commercial use.

---

*📄 Tài liệu sản phẩm chi tiết: [`docs/product-plan.md`](docs/product-plan.md)*
