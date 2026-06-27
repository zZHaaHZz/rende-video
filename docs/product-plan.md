# 🎬 AI Video Creator — Phương Án Sản Phẩm Cuối
**Hội thoại PO × BA | Version 1.0 | 18/06/2026**

---

## 🗣️ PO × BA — Phân Tích Yêu Cầu

> **PO:** Yêu cầu từ stakeholder rất rõ: người dùng chỉ cần **một nút bấm**, hệ thống tự chạy toàn bộ pipeline từ keyword → YouTube-ready. Không phải làm thủ công từng bước.

> **BA:** Đúng. Tôi đã audit codebase hiện tại. App đang có **4 bước thủ công rời rạc** (Topics → Script → Build → Export). Người dùng phải tự nhấn từng step. Chúng ta cần **Auto-Pipeline Mode** chạy liên tục không cần can thiệp.

> **PO:** Quan trọng nhất: video phải **không vi phạm bản quyền**. Đây là deal-breaker cho YouTube.

> **BA:** Tôi đã xác định nguồn footage hiện tại là **Pexels API** — đây là nguồn **CC0 / royalty-free hoàn toàn hợp lệ cho YouTube commercial use**. Không cần thay đổi nguồn video. Nhạc nền thì cần thêm nguồn mới.

> **PO:** Thumbnail AI-generated cũng phải đẹp hơn. Hiện tại chỉ là Canvas text đơn giản.

> **BA:** Đồng ý. Và tiêu đề YouTube cần AI optimize theo SEO, không chỉ lấy từ script.

---

## 📊 Gap Analysis — Hiện Tại vs Yêu Cầu

| # | Tính Năng Yêu Cầu | Trạng Thái Hiện Tại | Gap |
|---|---|---|---|
| 1 | Tìm keyword/chủ đề tự động | ✅ Có (TopicsPage — AI gợi ý 6 chủ đề) | Thiếu trending score |
| 2 | Viết kịch bản theo cảnh | ✅ Có (ScriptPage — AI + JSON schema) | ✅ Đủ dùng |
| 3 | Tách kịch bản theo giây từng đoạn | ✅ Có (`durationSec` per scene) | Thiếu timeline visualization |
| 4 | Video theo từng đoạn kịch bản | ✅ Có (Pexels footage per scene) | ✅ Đủ |
| 5 | Voice đọc kịch bản (TTS) | ✅ Có (Groq Orpheus TTS + Web Speech fallback) | Thiếu giọng Việt AI chất lượng cao |
| 6 | Ghép voice vào video từng đoạn | ✅ Có (Canvas + AudioContext render) | ✅ Hoạt động |
| 7 | Thumbnail thu hút | ⚠️ Có nhưng yếu (Canvas text đơn giản) | Cần AI-generated thumbnail |
| 8 | Tiêu đề SEO tối ưu | ⚠️ Có (lấy từ script) | Cần AI YouTube SEO title optimizer |
| 9 | Download video về | ✅ Có (WebM → MP4 via FFmpeg.wasm) | ✅ Hoạt động |
| 10 | **Auto-pipeline (1 click)** | ❌ **Không có** — thủ công 4 bước | **Gap lớn nhất — cần build mới** |
| 11 | Không vi phạm bản quyền | ✅ Pexels CC0 footage | Thiếu nhạc nền CC0 |
| 12 | Nhạc nền | ❌ Không có | Cần thêm Pixabay Music API |

---

## 🎯 Phương Án Cuối — Đã Chốt

### Kiến Trúc Pipeline Tự Động (9 bước)

```
[AUTO-PIPELINE MODE — 1 click]
      │
      ▼
STEP 1: KEYWORD RESEARCH (AI)
  Input:  Niche category / custom keyword
  Output: 6 trending topics + SEO score
  Tech:   Groq AI (llama-3.3-70b) + YouTube trend prompt
      │
      ▼ Auto-pick topic #1 (hoặc user chọn trước)
STEP 2: SCRIPT GENERATION (AI)
  Input:  Topic + duration + style + language
  Output: JSON scenes [{label, narration, durationSec, searchKeyword}]
  Tech:   Groq AI — structured JSON output
      │
      ▼
STEP 3: FOOTAGE FETCH (CC0 — Không vi phạm bản quyền)
  Input:  searchKeyword từng scene
  Output: Video URL (Pexels CC0 License)
  Tech:   Pexels API — Free for commercial use ✅
      │
      ▼
STEP 4: TTS VOICE GENERATION
  Input:  narration text từng scene
  Output: AudioBuffer per scene
  Primary:  Groq Orpheus TTS (playai-tts — English)
  Fallback: Web Speech API (đa ngôn ngữ)
  NEW:      FPT.AI TTS (Tiếng Việt chất lượng cao)
      │
      ▼
STEP 5: BACKGROUND MUSIC (CC0) ← MỚI
  Input:  Video style/mood
  Output: Audio track (CC0 license)
  Tech:   Pixabay Music API / Freesound.org
  Mix:    BGM volume 15-20%, duck khi có voice
      │
      ▼
STEP 6: VIDEO RENDER (Canvas + MediaRecorder)
  Input:  footage + audioBuffer + BGM + scenes
  Output: Blob (WebM → MP4 via FFmpeg.wasm)
  Note:   Thêm subtitle animation, BGM mix
      │
      ▼
STEP 7: THUMBNAIL AI GENERATION ← NÂNG CẤP
  Input:  YouTube title + scene 1 thumbnail frame
  Output: 1280×720 JPG thumbnail đẹp
  Tech:   Canvas enhanced (gradient + typography + frame)
      │
      ▼
STEP 8: YOUTUBE SEO OPTIMIZE ← NÂNG CẤP
  Input:  topic + script content
  Output: { title ≤60 chars, description w/ chapters, 30 tags }
  Tech:   Groq AI với YouTube SEO system prompt
      │
      ▼
STEP 9: EXPORT PACKAGE
  Output:
  ├── ai_video.mp4 (full video có voice + BGM)
  ├── thumbnail.jpg (1280×720)
  ├── youtube_metadata.txt (title + desc + tags)
  └── script.docx (optional)
```

---

## 🔐 Bản Quyền — Giải Pháp Chi Tiết

| Asset | Nguồn | License | Status YouTube |
|-------|-------|---------|----------------|
| **Video footage** | Pexels.com | CC0 + Pexels License | ✅ Commercial OK |
| **AI Voice (TTS)** | Groq / Web Speech / FPT.AI | Tự tạo | ✅ Owned |
| **Nhạc nền** | Pixabay Music | Pixabay License (Free commercial) | ✅ Commercial OK |
| **Thumbnail** | Canvas self-generated | Tự tạo | ✅ Owned |
| **Script content** | AI-generated (user owns) | Owned by user | ✅ OK |

> **⚠️ Note:** Pexels khuyến khích attribution trong description (optional). Pixabay Music không yêu cầu attribution. Tất cả nguồn trên đều **YouTube Content ID safe**.

---

## 🏗️ Kiến Trúc UI Mới

### Pages Structure (Refactor)

```
App
├── Page 1: Topics           (KEEP — thêm auto-select + SEO score)
├── Page 2: Script           (KEEP — thêm duration timeline bar)
├── Page 3: Auto-Pipeline    ← MAJOR NEW
│   ├── Auto Mode (1-click full pipeline)
│   └── Manual Mode (current behavior — giữ lại)
├── Page 4: Export           (UPGRADE — thumbnail preview, metadata)
└── Page 5: Settings         ← NEW
    ├── API Keys (Groq, Pexels, FPT.AI, Pixabay)
    └── Preferences (language, style defaults, duration)
```

### Auto-Pipeline UI Layout

```
┌──────────────────────────────────────────────────────┐
│  🚀 Auto Tạo Video                    [Cài đặt ⚙️]  │
├──────────────────────────────────────────────────────┤
│  Niche: [Technology ▼]  Duration: [3 phút ▼]        │
│  Language: [Tiếng Việt ▼]  Style: [Educational ▼]   │
│                                                      │
│  [🚀 BẮT ĐẦU TẠO VIDEO]  ← Nút duy nhất cần bấm   │
├──────────────────────────────────────────────────────┤
│  Pipeline Progress: ████████░░ 7/9 bước              │
│                                                      │
│  ✅ 1. Tìm chủ đề trending      (2s)                │
│  ✅ 2. Viết kịch bản 8 cảnh     (12s)               │
│  ✅ 3. Fetch footage Pexels      (18s)               │
│  ✅ 4. Tạo giọng đọc TTS        (45s)               │
│  ✅ 5. Thêm nhạc nền CC0        (8s)                │
│  ✅ 6. Render video              (120s)              │
│  ✅ 7. Tạo thumbnail             (3s)               │
│  🔄 8. Tối ưu SEO metadata...                       │
│  ⏳ 9. Đóng gói export                              │
└──────────────────────────────────────────────────────┘
```

---

## 📋 User Stories (PO Priority Order)

### Sprint 1 — Auto-Pipeline Core

**US-001** | 8 pts | **Auto Run Full Pipeline**
```
As a content creator,
I want to click "Auto Tạo Video" and have the system automatically
run all 9 steps without my intervention,
So that I can generate a complete YouTube-ready video in < 5 minutes.

Acceptance Criteria:
- Given I've selected niche + configured API keys,
  When I click "🚀 Auto Tạo Video",
  Then pipeline runs steps 1–9 sequentially with real-time progress.
- Given any step fails,
  When error occurs,
  Then pipeline pauses, shows error message, offers Retry / Skip.
- Given pipeline completes successfully,
  When all 9 steps finish,
  Then Export screen shows all downloadable files.
- Given pipeline is running,
  When I see the log,
  Then each step shows: icon + name + status + elapsed time.
```

**US-002** | 5 pts | **Real-time Pipeline Log UI**
```
As a content creator,
I want to see real-time step-by-step progress with elapsed time,
So that I know the system is working and can estimate completion.

AC:
- Each step shows: icon + name + status (pending/running/done/error)
- Time elapsed per step displayed in seconds
- Overall progress bar: X/9 steps complete + percentage
- Log auto-scrolls to latest entry
- Estimated time remaining shown
```

**US-003** | 5 pts | **Background Music CC0 (Pixabay)**
```
As a content creator,
I want the system to automatically add CC0 background music,
So that my YouTube videos won't get copyright strikes.

AC:
- System fetches music from Pixabay Music API matching video style/mood
- BGM is mixed at 15-20% volume with voice (ducking when voice plays)
- User can disable BGM in settings or skip this step
- Music credit is included in export metadata for optional attribution
- Graceful fallback: if Pixabay unavailable, skip BGM silently
```

**US-004** | 5 pts | **Enhanced AI Thumbnail**
```
As a content creator,
I want an eye-catching thumbnail generated automatically,
So that my video gets higher click-through rate on YouTube.

AC:
- Thumbnail uses actual Pexels footage frame as background
- Text layout: title prominent (large bold), contrast gradient overlay
- Design elements: colored accent bar, channel brand area
- Output: 1280×720 JPG at ≥95% quality
- Button to regenerate with different layout style
- Thumbnail previewed before download
```

**US-005** | 3 pts | **SEO-Optimized YouTube Metadata**
```
As a content creator,
I want AI to generate SEO-optimized title, description with chapters, and 30 tags,
So that my video ranks higher in YouTube search.

AC:
- Title: ≤60 chars, includes primary keyword, emotional hook word
- Description: first 150 chars keyword-rich, includes timestamps/chapters,
  3-5 hashtags, ends with CTA + subscribe prompt
- Tags: 30 relevant tags (mix broad + specific + long-tail)
- All fields copyable with 1-click copy button
- Chapter timestamps auto-calculated from scene durationSec
```

### Sprint 2 — Quality & Polish

**US-006** | 3 pts | **High-Quality Vietnamese TTS (FPT.AI)**
```
As a Vietnamese content creator,
I want high-quality Vietnamese AI voice,
So that my videos sound professional to Vietnamese viewers.

AC:
- Integrates FPT.AI TTS API (fptTts.js already exists)
- Voice selection: male/female options
- Auto-fallback to Web Speech if FPT.AI quota exceeded
- Voice test button in settings
```

**US-007** | 3 pts | **Centralized Settings Page**
```
As a user,
I need a dedicated settings page to manage all API keys and preferences,
So that I don't have to re-enter configuration every session.

AC:
- Settings page: Groq key, Pexels key, FPT.AI key, Pixabay key
- Keys persisted in localStorage
- Show/hide key toggle per field
- Validation check per key (green ✅ / red ❌ indicator)
- Default preferences: language, duration, style
```

---

## 🗓️ Sprint Plan

### Sprint 1 (7–10 ngày) — Core Auto-Pipeline
| Story | Points | Priority |
|-------|--------|----------|
| US-001: Auto Pipeline Engine | 8 | Critical |
| US-002: Pipeline Log UI | 5 | Critical |
| US-003: BGM CC0 (Pixabay) | 5 | High |
| US-004: Enhanced Thumbnail | 5 | High |
| US-005: YouTube SEO metadata | 3 | High |
| **Total** | **26 pts** | |

### Sprint 2 (5–7 ngày) — Quality + Polish
| Story | Points | Priority |
|-------|--------|----------|
| US-006: FPT.AI Vietnamese TTS | 3 | Medium |
| US-007: Settings Page | 3 | Medium |
| Subtitle animation improvement | 3 | Low |
| Mobile responsive | 2 | Low |
| **Total** | **11 pts** | |

---

## 🔧 Tech Stack — Đã Chốt

| Component | Technology | Status |
|-----------|-----------|--------|
| Framework | React + Vite | ✅ Có sẵn |
| AI (Script + SEO) | Groq API (llama-3.3-70b-versatile) | ✅ Có sẵn |
| TTS English | Groq Orpheus (playai-tts) | ✅ Có sẵn |
| TTS Vietnamese | FPT.AI TTS | ✅ fptTts.js có sẵn |
| TTS Fallback | Web Speech API | ✅ Có sẵn |
| Footage (CC0) | Pexels API | ✅ Có sẵn |
| BGM (CC0) | Pixabay Music API | **Cần thêm** |
| Thumbnail | Canvas API nâng cấp | Cần cải thiện |
| Video Render | Canvas + MediaRecorder | ✅ Có sẵn |
| Video Export | FFmpeg.wasm (WebM→MP4) | ✅ Có sẵn |
| Storage | localStorage | ✅ Có sẵn |

---

## ⚡ Quick Wins (Có thể làm ngay)

1. **Auto-select best topic** — sau khi generate topics, tự chọn topic đầu tiên
2. **YouTube SEO prompt upgrade** — thêm `chapters timestamps` + `30 tags` vào ScriptPage prompt
3. **Thumbnail layout nâng cấp** — gradient + emoji + title với shadow đẹp hơn
4. **Chain các step lại** — sau khi script xong → tự fetch footage → tự build video

---

## ✅ Definition of Done

Video output được coi là **YouTube-ready** khi:
- [x] File MP4 (hoặc WebM) download được
- [x] Có voice đọc lời thoại theo từng cảnh
- [x] Footage từ nguồn Pexels CC0 — không vi phạm bản quyền
- [x] Thumbnail 1280×720 download được
- [x] Tiêu đề ≤ 60 ký tự, có primary keyword
- [x] Description có chapter timestamps + hashtags
- [x] 30 tags copy được
- [ ] (Sprint 2) Nhạc nền CC0 được mix vào video
- [ ] (Sprint 2) Giọng Việt FPT.AI chất lượng cao

---

*📄 Saved to: `/docs/product-plan.md`*
*🔄 Cập nhật sau mỗi sprint retrospective.*
