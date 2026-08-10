# Thiết lập đăng video đa kênh

Module hỗ trợ Facebook Fanpage, TikTok và nhiều kênh YouTube Shorts. Sau khi
render, xem lại video rồi bấm **Đăng video** để chọn kênh và đăng ngay/đặt lịch.

## Khởi động

```bash
pip install streamlit requests cryptography edge-tts
streamlit run tool.py
```

Dữ liệu runtime nằm ở hai nơi: `.env` lưu Client ID/Secret cùng access/refresh
token; `~/.avc_social/social.db` chỉ lưu metadata account, lịch đăng và audit.
`.env` có quyền `600` trên macOS/Linux và đã được Git bỏ qua, nhưng vẫn là
plaintext nên phải được bảo vệ như mật khẩu. Khi nâng cấp, app copy credential
legacy sang `.env` nhưng giữ database/key mã hóa làm backup cho tới khi người
dùng chủ động xác nhận xóa.

## Redirect URI local

Nếu app chạy tại `http://localhost:8501`, cấu hình:

- Facebook: `http://localhost:8501/?social_provider=facebook`
- YouTube: `http://localhost:8501/?social_provider=youtube`
- TikTok: `http://localhost:8501/?social_provider=tiktok`

Provider có thể yêu cầu HTTPS/domain được xác minh ở production. URI trong
Developer Console và URI nhập trong Settings phải giống hệt nhau.

## Facebook Fanpage

1. Tạo Meta App, thêm Facebook Login và redirect URI.
2. Xin `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
3. Trong **Settings → Kết nối kênh → Facebook Fanpage**, nhập App ID/Secret,
   redirect URI và Graph API version rồi lưu.
4. Bấm **Kết nối Fanpage**. Module chỉ lưu Page, không lưu profile hoặc Group.

Production có thể cần Meta App Review.

## YouTube Shorts — nhiều kênh

1. Tạo Google Cloud project, bật YouTube Data API v3 và tạo OAuth Web Client.
2. Thêm redirect URI và hai scope `youtube.upload`, `youtube.readonly`.
3. Nhập Client ID/Secret/Redirect URI trong Settings rồi lưu.
4. Bấm **Kết nối thêm kênh YouTube**. Lặp lại cho các kênh khác.

`youtube.readonly` chỉ đọc tên/channel ID; `youtube.upload` dùng để upload.
Project chưa verification có thể bị giới hạn video ở privacy `private`. Video
ngang hoặc dài hơn 180 giây bị chặn trước upload.

## TikTok

1. Tạo TikTok Developer App, bật Login Kit và Content Posting API.
2. Cấu hình redirect URI và xin `user.info.basic`, `video.publish`.
3. Nhập Client Key/Secret/Redirect URI trong Settings rồi kết nối.

Client chưa audit thường chỉ được Direct Post ở `SELF_ONLY`. Module kiểm tra
Creator Info lúc đăng và từ chối privacy option không còn hợp lệ.

## Đăng video

1. Render và xem lại hình, tiếng, phụ đề.
2. Có lỗi thì sửa/render lại; xác nhận cũ không áp dụng cho file mới.
3. Bấm **Đăng video**, tick Fanpage/kênh/account và chỉnh metadata từng đích.
4. Chọn **Đăng ngay** hoặc **Đặt lịch**, kiểm tra tóm tắt rồi xác nhận.

App/worker phải chạy để thực thi lịch. Tab **Xuất bản** cảnh báo khi không có
heartbeat trong 90 giây. Mỗi kênh là một job độc lập.

## Mã lỗi thường gặp

- `TOKEN_EXPIRED`: kết nối lại account.
- `NOT_YOUTUBE_SHORT`: dùng video dọc/vuông tối đa 180 giây.
- `MEDIA_CHANGED`: file đổi sau khi lên lịch; tạo job mới.
- `PROVIDER_RESULT_UNKNOWN`: kiểm tra nền tảng trước khi đăng lại để tránh trùng.
