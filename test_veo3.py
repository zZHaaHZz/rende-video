import json
from pathlib import Path
import sys
import os

# Import veo3_video module
try:
    import veo3_video
except ImportError:
    print("❌ Không tìm thấy module veo3_video.py trong thư mục hiện tại.")
    sys.exit(1)

def main():
    config_path = Path.home() / ".avc_config.json"
    if not config_path.exists():
        print(f"❌ Không tìm thấy file cấu hình tại {config_path}")
        print("Vui lòng mở web UI Streamlit và thêm ít nhất một Gemini key trước.")
        sys.exit(1)

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Không thể đọc file cấu hình: {e}")
        sys.exit(1)

    keys = cfg.get("gemini", [])
    if not keys:
        print("❌ Chưa có Gemini API key nào trong danh sách 'gemini' của file cấu hình.")
        sys.exit(1)

    print("🔑 Danh sách Gemini key hiện có:")
    for idx, key in enumerate(keys):
        masked_key = f"{key[:12]}...{key[-8:]}" if len(key) > 20 else key
        print(f"  [{idx + 1}] {masked_key}")

    try:
        sel = input(f"👉 Chọn số thứ tự key để test (1-{len(keys)}) hoặc nhập API key mới: ").strip()
        if not sel:
            print("Đã hủy.")
            return

        if sel.isdigit() and 1 <= int(sel) <= len(keys):
            chosen_key = keys[int(sel) - 1]
        else:
            chosen_key = sel  # Người dùng nhập key mới trực tiếp
    except KeyboardInterrupt:
        print("\nĐã hủy.")
        return

    print("\n🎬 Bắt đầu test tạo video ngắn bằng Veo3...")
    prompt = "a beautiful red rose blooming, cinematic, time-lapse, high quality"
    print(f"📝 Prompt test: '{prompt}'")
    print("⏳ Quá trình này có thể mất từ 1 - 2 phút (chạy ngầm). Vui lòng đợi...")

    def log_callback(msg):
        print(f"   [Veo3 Progress] {msg}")

    # Chạy thử
    res_path = veo3_video.generate_video_veo3_best(
        keyword=prompt,
        gemini_api_key=chosen_key,
        orientation="landscape",
        scene_text="rose blooming",
        timeout_seconds=200,
        resolution="720p",
        log_cb=log_callback
    )

    if res_path and Path(res_path).exists():
        print("\n✅ THÀNH CÔNG!")
        print(f"📹 Đường dẫn video kết quả: {res_path}")
        print(f"📦 File size: {Path(res_path).stat().st_size / 1024 / 1024:.2f} MB")
    else:
        print("\n❌ THẤT BẠI!")
        print("Vui lòng kiểm tra log lỗi bên trên (quota limit, permission, hoặc key chưa được allowlist Veo3).")

if __name__ == "__main__":
    main()
