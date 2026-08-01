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
| 🎨 **Creative Studio** | Làm phim ngắn, quảng cáo, UGC, mood film... → prompt Veo 3 → upload clip → tự dựng |

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
├── creative_studio.py         # Module sáng tạo nội dung độc lập + dựng clip Veo 3
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

### Creative Studio (mảng nội dung sáng tạo)

Creative Studio là workflow độc lập, không dùng project hay state của
Main/Shorts/Veo3 Studio. Giao diện được chia thành wizard 4 bước:

1. **Ý tưởng:** chọn dạng nội dung, hướng kể chuyện, loại hình video (người
   thật, hoạt hình 2D/3D, anime, claymation...), phong cách, mood và nhịp dựng.
2. **Storyboard:** AI tạo creative direction, Character Bible và prompt từng
   cảnh. Có thể thêm ảnh tham chiếu, chỉnh duration, khóa khung hình đầu/cuối,
   hướng chuyển động và đổi thứ tự cảnh.
3. **Sản xuất:** chọn Gemini Web để upload MP4 thủ công hoặc Veo API để tự tạo
   tất cả cảnh còn thiếu. Mỗi cảnh có sound plan riêng và có thể upload
   Foley/SFX, chỉnh âm lượng cùng thời điểm bắt đầu.
4. **Xuất bản:** thêm nhạc, giữ audio gốc, tự động audio-ducking và ghép MP4
   bằng timeline `xfade/acrossfade` (cut, dissolve, whip, flash, fade, match).
   Khi hình cần loop để đủ duration, audio gốc chỉ phát một lần rồi pad silence,
   tránh tiếng click hoặc ambience bị lặp máy móc.

Project được lưu riêng tại `~/.avc_creative_project.json`; clip tại
`~/.avc_creative_assets/`; video final tại `~/Desktop/AI_Videos/Creative_Studio/`.

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
