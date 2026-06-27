# Kế Hoạch Triển Khai: Whiteboard Animation Video Pipeline

Hoàn toàn **CÓ THỂ** thực hiện được pipeline này. Đây là một luồng (flow) rất kinh điển và hiệu quả để tạo ra dạng video "Whiteboard Animation" (hoạt hình vẽ tay) hoặc "Stick Figure" tự động.

Dưới đây là phân tích chi tiết về tính khả thi và cách mình (Antigravity) có thể triển khai từng bước trong hệ thống của bạn:

## Phân Tích Các Bước (Pipeline)

### 1. Audio (MP3/WAV) ➜ Whisper ➜ Transcript + Timestamps
- **Tính khả thi:** 100%
- **Công nghệ:** `openai-whisper` (chạy local) hoặc gọi API (Groq Whisper / OpenAI).
- **Cách làm:** Đưa file audio đầu vào qua Whisper với tham số `word_timestamps=True` (hoặc `segment-level timestamps`). Whisper sẽ trả ra JSON chứa text và thời gian (start/end) chính xác từng từ/câu.

### 2. Scene split theo lời thoại
- **Tính khả thi:** 100%
- **Công nghệ:** Python script.
- **Cách làm:** Dựa vào `timestamps` từ Whisper và ngắt câu logic (dấu chấm, phẩy), mình có thể gom các đoạn thoại thành từng "Cảnh" (Scene) riêng biệt. Ví dụ: Cứ mỗi đoạn 3-5 giây (hoặc 1 câu trọn vẹn) sẽ cắt thành 1 Scene.

### 3. SVG Generation (Stick figure + draw-on stroke animation)
- **Tính khả thi:** 100%
- **Công nghệ:** LLM (Gemini/Groq) kết hợp thư viện thao tác SVG (Python `svgwrite` hoặc template tĩnh).
- **Cách làm:** 
  - Đưa nội dung từng Scene vào AI (LLM) để AI quyết định hình ảnh biểu tượng cần vẽ (VD: "bóng đèn", "người que đang chạy", "biểu đồ tăng trưởng").
  - LLM sinh ra mã SVG path tương ứng (hoặc query từ một kho icon SVG định dạng nét vẽ - stroke).
  - Để tạo hiệu ứng "Draw-on" (hiệu ứng tay vẽ/đường nét chạy), mình sẽ tiêm (inject) CSS/JS vào file SVG: dùng kỹ thuật `stroke-dasharray` và `stroke-dashoffset` chạy animation theo đúng độ dài (duration) của Scene đó.

### 4. Playwright render ➜ PNG frames (30fps)
- **Tính khả thi:** 100%
- **Công nghệ:** `playwright` (Python/Nodejs).
- **Cách làm:** 
  - Mở một file HTML ảo chứa đoạn SVG đã được gắn animation.
  - Sử dụng tính năng chạy timeline của browser, Playwright sẽ chụp ảnh màn hình (screenshot) liên tục với tốc độ 30 hình/giây (30fps).
  - Output sẽ là hàng ngàn ảnh `.png` lưu trong thư mục tạm. (Hoặc có thể tối ưu hơn: quay luôn luồng video từ headless browser nếu không muốn lưu từng frame, nhưng chụp PNG cho độ chuẩn xác frame-by-frame cao nhất).

### 5. FFmpeg ghép frames + audio ➜ Video MP4
- **Tính khả thi:** 100%
- **Công nghệ:** `ffmpeg`.
- **Cách làm:**
  - FFmpeg nhận đầu vào là dãy ảnh `%04d.png` ở tốc độ 30fps (`-framerate 30 -i frame_%04d.png`).
  - Gắn file audio gốc vào (`-i audio.mp3`).
  - Encode ra `libx264` thành video MP4 hoàn chỉnh.

---

## Đánh Giá Tối Ưu & Khuyến Nghị

Pipeline này cực kỳ khả thi bằng Python. Tuy nhiên, nếu bắt tay vào code, mình có một số đề xuất tối ưu để app chạy mượt hơn trên máy của bạn:

1. **Khâu Playwright ➜ PNG (Bước 4):**
   - Chụp 30fps bằng Playwright cho 1 video 60 giây tức là phải chụp ~1800 tấm ảnh PNG. Quá trình này có thể hơi chậm và tốn I/O ổ cứng.
   - **Cách giải quyết thay thế:** Dùng thư viện `remotion` (React) để render video tĩnh thẳng từ HTML/SVG, hoặc dùng FFmpeg + ffmpeg-python kết hợp với Cairo/Manim (thư viện chuyên vẽ animation toán học/hình học của 3Blue1Brown bằng Python) để sinh ra video trực tiếp thay vì chụp từng frame qua Playwright.
   - Nếu vẫn muốn dùng trình duyệt, có thể dùng extension quay màn hình tự động bên trong Puppeteer/Playwright để xuất thẳng `.webm` rồi dùng FFmpeg ép lại mp4.

2. **Khâu sinh SVG (Bước 3):**
   - AI LLM thỉnh thoảng sinh mã SVG path bị méo hoặc không ra hình rõ ràng.
   - Để an toàn: Xây dựng một thư viện (library) chứa vài trăm file SVG (dạng nét vẽ) chuẩn. Dùng AI để "Search" và bốc file SVG phù hợp ghép vào, thay vì ép AI vẽ SVG từ con số 0.

**Kết luận:** Nếu bạn muốn tích hợp luồng này vào tool hiện tại hoặc làm một tab tool mới cho "Whiteboard Video", mình hoàn toàn có thể thiết kế và code luồng này cho bạn!
