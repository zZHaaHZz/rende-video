# Spec: Tự động đăng video ngắn đa kênh lên Facebook, TikTok và YouTube Shorts

**Author:** Codex (soạn theo yêu cầu của chủ dự án)  
**Date:** 2026-08-01  
**Status:** Approved — người dùng duyệt triển khai ngày 2026-08-01  
**Reviewers:** Chủ dự án  
**Related documents:** `README.md`, `docs/product-plan.md`, `Auto-Create-Video/README.vi.md`  
**Target application:** Streamlit app tại `tool.py`  

> Quy ước: trong tài liệu này, “TB” được hiểu là **TikTok**. Nếu TB là nền
> tảng khác, spec MUST được cập nhật và duyệt lại trước khi triển khai.

## Context

AI Video Creator hiện tạo và xuất video MP4 cùng metadata nhưng người
dùng vẫn phải mở từng mạng xã hội, tải video lên, sao chép caption và theo dõi
kết quả thủ công. Công việc lặp lại này làm đứt quãng pipeline “một nút bấm” mà
sản phẩm đang hướng tới.

Module mới cho phép kết nối nhiều Facebook Fanpage, nhiều tài khoản TikTok và
nhiều kênh YouTube, chọn một video ngắn đã render, chỉnh metadata theo từng đích,
đăng ngay hoặc đặt lịch, rồi theo dõi trạng thái ngay trong ứng dụng. Module phải
dùng đầu ra hiện có tại `~/Desktop/AI_Videos/`, không thay đổi logic tạo/render
video và không xử lý thumbnail.

Đây là tích hợp với dịch vụ bên ngoài có OAuth, quyền xuất bản, giới hạn API và
quy trình xét duyệt ứng dụng. TikTok Direct Post yêu cầu quyền `video.publish`,
phải lấy thông tin creator mới nhất trước khi hiển thị lựa chọn đăng và client
chưa audit chỉ có thể đăng ở chế độ riêng tư. Facebook cần Meta App cùng quyền
quản lý/đăng nội dung Page tương ứng được Meta phê duyệt. YouTube dùng OAuth 2.0
và `videos.insert`; project API chưa được xác minh có thể bị giới hạn video ở chế
độ private. YouTube tự phân loại video vuông/dọc dài tối đa 3 phút là Shorts theo
quy tắc hiện hành, module không có endpoint “Shorts” riêng.

## 2. Mục tiêu và phạm vi phát hành

### 2.1 Mục tiêu MVP

- Kết nối một hoặc nhiều Facebook Fanpage, tài khoản TikTok và kênh YouTube được
  ủy quyền.
- Đăng ngay một video MP4 lên một hoặc nhiều tài khoản đã chọn.
- Đặt lịch đăng theo múi giờ `Asia/Ho_Chi_Minh`.
- Theo dõi lịch sử, trạng thái, URL/ID bài đăng và lỗi có thể xử lý.
- Thử lại an toàn khi lỗi tạm thời mà không tạo bài trùng.

### 2.2 Giả định cần duyệt

- A-1: “TB” là TikTok.
- A-2: MVP chạy trên máy cá nhân; lịch chỉ được thực thi khi tiến trình worker
  đang chạy. App MUST hiển thị cảnh báo rõ nếu worker dừng.
- A-3: MVP chỉ đăng video MP4; chưa đăng ảnh/carousel/text-only.
- A-4: Facebook đích là **Page**, không đăng lên profile cá nhân hoặc Group.
- A-5: TikTok dùng Direct Post. Khi app chưa qua audit, UI MUST giới hạn theo
  quyền riêng tư do TikTok trả về, thường là `SELF_ONLY`.
- A-6: Người dùng tự tạo Meta App/TikTok Developer App và chịu trách nhiệm hoàn
  tất review/audit; module chỉ cung cấp màn hình cấu hình và tích hợp.
- A-7: Người dùng tự tạo Google Cloud project, bật YouTube Data API v3, cấu hình
  OAuth consent và chịu trách nhiệm hoàn tất verification/audit nếu Google yêu cầu.
- A-8: Mỗi lần OAuth YouTube kết nối đúng một kênh đích. Nhiều kênh được kết nối
  thành nhiều `ConnectedAccount`; không giả định một token có thể đăng tùy ý lên
  mọi kênh, trừ tài khoản YouTube Content Partner được cấp quyền riêng.
- A-9: Module tối ưu cho video ngắn dọc/vuông tối đa 3 phút. Video không đủ điều
  kiện Shorts MUST bị chặn ở MVP thay vì upload thành video dài ngoài ý muốn.
- A-10: Thumbnail không được chọn, tạo hoặc upload trong module xuất bản.

## 3. Luồng người dùng

1. Trong **⚙️ Settings → Kết nối kênh**, người dùng kết nối từng Facebook
   Fanpage, tài khoản TikTok hoặc kênh YouTube bằng OAuth.
2. Sau khi pipeline render thành công, màn hình kết quả MUST cho phát, tạm dừng,
   tua và xem toàn bộ video vừa tạo để người dùng kiểm tra hình, tiếng, phụ đề và
   lỗi dựng trước khi xuất bản.
3. Nếu phát hiện lỗi, người dùng quay lại chỉnh sửa/render lại; phiên bản chưa
   duyệt MUST không được upload. Nếu video ổn, người dùng bấm **📣 Đăng video**.
4. Hệ thống hiển thị danh sách checkbox theo nhóm **Facebook Fanpage**,
   **YouTube Shorts** và **TikTok**, mỗi dòng có avatar, tên và Page/channel ID.
5. Người dùng tick một hoặc nhiều Fanpage/kênh/tài khoản muốn đăng video vừa tạo,
   rồi nhập/chỉnh caption hoặc metadata riêng cho từng đích nếu cần.
6. Với TikTok, hệ thống tải thông tin creator mới nhất và hiển thị đúng các lựa
   chọn privacy/comment/duet/stitch mà tài khoản cho phép.
7. Với YouTube, người dùng nhập title, description, tags, category, privacy và
   lựa chọn thông báo subscriber; UI hiển thị channel ID/tên kênh rõ ràng.
8. Người dùng chọn **Đăng ngay** hoặc **Đặt lịch**; khi đặt lịch, họ chọn ngày,
   giờ và múi giờ, sau đó xem lại bản tóm tắt và xác nhận.
9. Worker upload video, theo dõi trạng thái từ nền tảng và cập nhật lịch sử.
10. Khi thành công, UI hiển thị platform post ID và URL nếu API cung cấp; khi lỗi,
   UI hiển thị mã lỗi nội bộ, hướng xử lý và nút thử lại nếu an toàn.

Người dùng vẫn MAY mở tab **📣 Xuất bản** để chọn lại video cũ hoặc quản lý lịch
đăng; luồng chính của video mới MUST bắt đầu ngay từ kết quả render.

## Functional Requirements

### 4.1 Tài khoản và quyền truy cập

- FR-1: Hệ thống MUST hỗ trợ OAuth cho Facebook/Meta, TikTok và Google/YouTube.
- FR-2: Hệ thống MUST chỉ hiển thị Facebook Page mà tài khoản đã ủy quyền và
  có khả năng xuất bản video.
- FR-3: Hệ thống MUST lưu access token/refresh token ở dạng mã hóa và MUST
  NOT ghi token, app secret hoặc authorization code vào log.
- FR-4: Người dùng MUST có thể ngắt kết nối tài khoản; sau khi ngắt, mọi job
  chưa chạy của tài khoản đó MUST chuyển sang `blocked`.
- FR-5: Hệ thống MUST phát hiện token hết hạn/thu hồi và yêu cầu kết nối lại,
  không tự động yêu cầu quyền rộng hơn.
- FR-29: Hệ thống MUST cho phép kết nối và nhận diện nhiều kênh YouTube độc lập
  bằng channel ID, tên kênh và avatar nếu API cung cấp.
- FR-34: Hệ thống MUST chỉ cho kết nối Facebook Page; profile cá nhân và Group
  MUST NOT xuất hiện như một publish target.

### 4.2 Soạn và xác nhận bài đăng

- FR-6: Hệ thống MUST cho phép chọn một file `.mp4` tồn tại từ đầu ra dự án
  hoặc từ đường dẫn cục bộ do người dùng chọn.
- FR-7: Hệ thống MUST kiểm tra file đọc được, MIME/codec được hỗ trợ, kích
  thước và thời lượng trước khi tạo job.
- FR-8: Hệ thống MUST cho phép nhập caption riêng cho từng nền tảng và SHOULD
  điền trước từ metadata/caption đã xuất bởi pipeline nếu có.
- FR-9: Hệ thống MUST hiển thị bản tóm tắt gồm video, tài khoản đích, caption,
  quyền riêng tư và thời điểm trước khi người dùng xác nhận.
- FR-10: Hệ thống MUST NOT gửi video tới nền tảng trước thao tác xác nhận rõ
  ràng của người dùng cho lần đăng hoặc lịch đăng đó.
- FR-11: Với TikTok, hệ thống MUST gọi Creator Info khi mở form xuất bản và
  MUST chỉ cho chọn các giá trị privacy/interaction vừa được API trả về.
- FR-12: Với TikTok, UI MUST hiển thị các khai báo nội dung thương mại cần
  thiết và MUST chuyển đúng lựa chọn của người dùng sang API.
- FR-30: Với YouTube, hệ thống MUST thu thập title, description, tags, category,
  privacy (`private`, `unlisted`, `public`), `notifySubscribers`, made-for-kids và
  synthetic-media disclosure theo khả năng API hiện hành.
- FR-31: YouTube adapter MUST upload resumable qua YouTube Data API `videos.insert`
  với `https://www.googleapis.com/auth/youtube.upload`; OAuth MUST yêu cầu thêm
  `https://www.googleapis.com/auth/youtube.readonly` chỉ để đọc tên và channel ID
  cho màn hình chọn đúng kênh.
- FR-32: Trước khi tạo YouTube job, hệ thống MUST kiểm tra video có tỷ lệ vuông
  hoặc dọc và thời lượng không quá 180 giây; nếu không đạt MUST trả
  `NOT_YOUTUBE_SHORT` và không upload.
- FR-33: Module MUST NOT yêu cầu, tạo, chọn hoặc upload thumbnail cho Facebook,
  TikTok hay YouTube.
- FR-35: Khi render hoàn tất, hệ thống MUST chuyển trực tiếp đường dẫn tuyệt đối,
  SHA-256 và metadata của video vừa tạo sang bước **Chọn nơi đăng**.
- FR-36: Bước **Chọn nơi đăng** MUST hiển thị các publish target đã kết nối theo
  nhóm nền tảng và cho phép chọn đồng thời nhiều Fanpage/kênh/tài khoản.
- FR-37: Hệ thống MUST NOT tự chọn sẵn hoặc tự đăng lên bất kỳ target nào nếu
  người dùng chưa tick target và xác nhận.
- FR-38: Màn hình sau render MUST có video player hỗ trợ play, pause, seek và xem
  toàn màn hình để người dùng duyệt đúng file MP4 sẽ được đăng.
- FR-39: Hệ thống MUST NOT coi render thành công là phê duyệt xuất bản; chỉ thao
  tác **Đăng video** của người dùng mới mở bước chọn target/lịch.
- FR-40: Nếu video được render lại sau khi đã mở form xuất bản, hệ thống MUST cập
  nhật fingerprint sang bản mới và MUST yêu cầu xác nhận lại trước khi tạo job.

### 4.3 Đăng ngay và đặt lịch

- FR-13: Người dùng MUST có thể đăng ngay lên một hoặc nhiều đích đã chọn.
- FR-14: Người dùng MUST có thể đặt lịch ở thời điểm tương lai, mặc định theo
  `Asia/Ho_Chi_Minh`; hệ thống MUST lưu cả UTC và timezone gốc.
- FR-15: Một yêu cầu nhiều đích MUST tạo một job con độc lập cho mỗi đích để
  lỗi ở một nền tảng/kênh không làm mất kết quả ở các đích còn lại.
- FR-16: Worker MUST claim job nguyên tử để hai worker không xử lý cùng job.
- FR-17: Hệ thống MUST dùng idempotency key nội bộ cho từng job và MUST NOT
  tự retry bước có khả năng đã tạo post nếu chưa xác định được kết quả.
- FR-18: Người dùng MUST có thể hủy job ở trạng thái `scheduled`; hủy sau khi
  upload bắt đầu MUST bị từ chối với thông báo rõ ràng.
- FR-19: Người dùng MAY tạo bản sao một job đã lỗi để chỉnh và đăng lại.

### 4.4 Trạng thái và lịch sử

- FR-20: Job MUST dùng một trong các trạng thái: `scheduled`, `queued`,
  `validating`, `uploading`, `processing`, `published`, `failed`, `blocked`,
  `cancelled`, `unknown`.
- FR-21: UI MUST hiển thị trạng thái, nền tảng, tài khoản, thời gian dự kiến,
  số lần thử, lỗi gần nhất, platform post ID và URL khi có.
- FR-22: Hệ thống MUST poll trạng thái xử lý bất đồng bộ theo quy định của
  từng nền tảng cho tới trạng thái kết thúc hoặc hết thời gian chờ.
- FR-23: Hệ thống MUST ghi audit event cho tạo lịch, xác nhận, bắt đầu upload,
  retry, thành công, thất bại, hủy và ngắt kết nối tài khoản.
- FR-24: Người dùng MUST có thể lọc lịch sử theo nền tảng, tài khoản, trạng
  thái và khoảng ngày.

### 4.5 Retry và vận hành

- FR-25: Lỗi timeout, HTTP 429 và 5xx trước khi nền tảng xác nhận tạo post
  SHOULD được retry tối đa 3 lần với exponential backoff và jitter.
- FR-26: Lỗi validation, thiếu quyền, token bị thu hồi và nội dung bị từ chối
  MUST NOT tự retry.
- FR-27: Khi không phân biệt được request đã thành công hay chưa, job MUST
  chuyển `unknown` và yêu cầu đối soát/trạng thái API trước khi đăng lại.
- FR-28: Worker MUST cập nhật heartbeat; UI MUST cảnh báo nếu không có
  heartbeat trong 90 giây.

## Non-Functional Requirements

### 5.1 Bảo mật

- **NFR-S1:** Token và client secret MUST được mã hóa at rest bằng khóa nằm ngoài
  file dữ liệu; plaintext credential MUST NOT tồn tại trong SQLite/JSON/log.
- **NFR-S2:** OAuth callback MUST kiểm tra `state`, redirect URI cố định và thời
  hạn authorization attempt không quá 10 phút.
- **NFR-S3:** Log MUST che token, secret, authorization header và query parameter
  nhạy cảm; test tự động MUST kiểm chứng việc che dữ liệu.
- **NFR-S4:** Module MUST yêu cầu quyền tối thiểu cần thiết cho đăng Page/TikTok/
  YouTube; YouTube chỉ yêu cầu `youtube.upload` và `youtube.readonly`.
- **NFR-S5:** Việc thêm module vào `~/.avc_config.json` MUST NOT làm lộ credential
  hiện có hơn mức hiện trạng; credential social mới MUST dùng kho mã hóa riêng.

### 5.2 Độ tin cậy và hiệu năng

- **NFR-R1:** Job và audit event MUST tồn tại sau khi app/worker restart.
- **NFR-R2:** Không được tạo hai upload cho cùng một job khi chạy thử nghiệm đồng
  thời với 2 worker trong 100 lần claim.
- **NFR-R3:** Danh sách 500 job gần nhất MUST tải trong 2 giây trên máy phát triển.
- **NFR-R4:** Worker MUST bắt đầu xử lý job đến hạn trong vòng 60 giây khi worker
  khỏe và không bị rate limit.
- **NFR-R5:** Mọi timestamp lưu trữ MUST là UTC ISO-8601; UI MUST hiển thị theo
  timezone người dùng đã chọn.

### 5.3 Khả dụng

- **NFR-U1:** Form MUST không cho xác nhận nếu thiếu video, tài khoản đích,
  metadata bắt buộc hoặc lựa chọn TikTok theo Creator Info.
- **NFR-U2:** Mỗi lỗi người dùng nhìn thấy MUST có mã ổn định và hướng xử lý,
  không hiển thị raw stack trace hoặc raw provider response.

## Acceptance Criteria

### AC-1: Kết nối Facebook Page (FR-1, FR-2, FR-3, NFR-S2)

**Given** người dùng bắt đầu kết nối Facebook với OAuth state hợp lệ  
**When** Meta callback trả authorization code và danh sách Page được phép  
**Then** hệ thống lưu từng Page dưới dạng tài khoản xuất bản  
**And** token được mã hóa và không xuất hiện trong log.

### AC-2: Kết nối TikTok (FR-1, FR-3, FR-5)

**Given** TikTok Developer App đã được cấu hình đúng  
**When** người dùng cấp quyền cần thiết và callback thành công  
**Then** tài khoản TikTok xuất hiện ở trạng thái `connected`  
**And** ngày hết hạn token được lưu để chủ động yêu cầu kết nối lại.

### AC-3: Chặn file không hợp lệ (FR-6, FR-7, NFR-U1)

**Given** người dùng chọn file không tồn tại hoặc không phải MP4 hợp lệ  
**When** họ mở bước xác nhận  
**Then** hệ thống không tạo job  
**And** hiển thị mã `MEDIA_INVALID` cùng lý do.

### AC-4: Xác nhận trước khi đăng (FR-9, FR-10)

**Given** form có video và tài khoản hợp lệ  
**When** người dùng chưa bấm xác nhận  
**Then** không có request upload nào được gửi tới Facebook, TikTok hoặc YouTube.

### AC-5: Đăng Facebook thành công (FR-13, FR-20, FR-21)

**Given** Page còn quyền đăng và video hợp lệ  
**When** người dùng xác nhận đăng ngay và provider báo hoàn tất  
**Then** job chuyển `published`  
**And** lưu Page post/video ID và URL nếu provider trả về.

### AC-6: TikTok dùng lựa chọn hiện hành (FR-11, FR-12)

**Given** Creator Info chỉ trả privacy `SELF_ONLY` và cấm duet  
**When** người dùng soạn bài TikTok  
**Then** UI chỉ cho chọn `SELF_ONLY` và không cho bật duet  
**And** request khởi tạo bài đăng khớp đúng các lựa chọn đó.

### AC-7: Đặt lịch đúng timezone (FR-14, NFR-R4, NFR-R5)

**Given** người dùng chọn 09:00 ngày kế tiếp tại `Asia/Ho_Chi_Minh`  
**When** họ xác nhận đặt lịch  
**Then** hệ thống lưu đúng thời điểm UTC tương ứng và timezone gốc  
**And** worker khỏe bắt đầu job không muộn hơn 60 giây sau thời điểm đó.

### AC-8: Một nền tảng lỗi không ảnh hưởng nền tảng khác (FR-15)

**Given** một yêu cầu nhắm Facebook, TikTok và hai kênh YouTube  
**When** Facebook cùng một kênh YouTube thành công còn các đích khác lỗi quyền  
**Then** job Facebook là `published`  
**And** job YouTube thành công giữ `published`  
**And** từng job lỗi độc lập là `failed` hoặc `blocked` với `PERMISSION_REQUIRED`.

### AC-9: Retry lỗi tạm thời (FR-25, FR-26)

**Given** provider trả 503 hai lần rồi thành công trước khi tạo post  
**When** worker xử lý job  
**Then** worker thử tối đa ba lần với backoff  
**And** chỉ một platform post được tạo.

### AC-10: Trạng thái không xác định (FR-17, FR-27)

**Given** kết nối rớt sau khi upload hoàn tất nhưng trước response xác nhận  
**When** không thể đối soát platform post ID  
**Then** job chuyển `unknown`  
**And** hệ thống không tự upload lại video.

### AC-11: Hủy lịch (FR-18)

**Given** job đang `scheduled`  
**When** người dùng bấm hủy và xác nhận  
**Then** job chuyển `cancelled` và worker không claim job đó.

### AC-12: Worker dừng (FR-28)

**Given** không có heartbeat worker trong 90 giây  
**When** người dùng mở tab Xuất bản  
**Then** UI hiển thị cảnh báo lịch tự động đang không hoạt động.

### AC-13: Ngắt kết nối (FR-4)

**Given** tài khoản có ít nhất một job chưa chạy  
**When** người dùng xác nhận ngắt kết nối  
**Then** credential bị vô hiệu hóa/xóa an toàn  
**And** các job chưa chạy chuyển `blocked`.

### AC-14: Lịch sử và audit (FR-21, FR-23, FR-24, NFR-R1)

**Given** đã có các job ở nhiều trạng thái  
**When** app restart và người dùng lọc theo nền tảng/trạng thái  
**Then** danh sách đúng vẫn được hiển thị  
**And** mỗi job giữ đầy đủ audit event trước restart.

### AC-15: Điền caption từ metadata (FR-8)

**Given** video đã chọn có metadata/caption được pipeline xuất cùng thư mục  
**When** người dùng mở form tạo bài  
**Then** caption tương ứng được điền trước  
**And** người dùng vẫn có thể chỉnh nội dung trước khi xác nhận.

### AC-16: Claim job nguyên tử (FR-16, NFR-R2)

**Given** một job `queued` và hai worker cùng yêu cầu claim  
**When** hai transaction chạy đồng thời  
**Then** đúng một worker nhận quyền xử lý job  
**And** worker còn lại không gọi provider API.

### AC-17: Theo dõi provider processing (FR-22)

**Given** provider đã nhận upload và trả trạng thái đang xử lý  
**When** worker poll trạng thái theo adapter  
**Then** job giữ `processing` cho tới trạng thái kết thúc hoặc timeout  
**And** platform post ID nhận được được lưu ngay.

### AC-18: Tạo bản sao job lỗi (FR-19)

**Given** một job đang `failed`  
**When** người dùng chọn tạo bản sao và xác nhận sau khi chỉnh caption/lịch  
**Then** một job mới với ID và idempotency key mới được tạo  
**And** job lỗi ban đầu không bị thay đổi.

### AC-19: Kết nối nhiều kênh YouTube (FR-1, FR-3, FR-5, FR-29)

**Given** người dùng sở hữu hoặc quản lý nhiều kênh YouTube  
**When** họ hoàn tất OAuth riêng cho từng kênh  
**Then** mỗi kênh được lưu thành một `ConnectedAccount` có channel ID duy nhất  
**And** UI luôn hiển thị tên cùng channel ID trước khi chọn đích.

### AC-20: Upload YouTube Shorts thành công (FR-30, FR-31)

**Given** video dọc 9:16 dài 60 giây, metadata hợp lệ và kênh đã kết nối  
**When** worker xử lý YouTube job  
**Then** adapter dùng resumable `videos.insert` với scope `youtube.upload`  
**And** job lưu video ID, URL và chuyển `published` sau khi xử lý thành công.

### AC-21: Chặn video không phải Shorts (FR-7, FR-32)

**Given** video ngang hoặc dài hơn 180 giây  
**When** người dùng chọn một kênh YouTube làm đích  
**Then** hệ thống trả `NOT_YOUTUBE_SHORT` và không tạo YouTube job  
**And** không gửi byte nào tới YouTube.

### AC-22: Không xử lý thumbnail (FR-33)

**Given** video hoặc thư mục đầu ra có hay không có file thumbnail  
**When** người dùng tạo bài cho bất kỳ nền tảng nào  
**Then** UI không hiển thị trường thumbnail  
**And** không adapter nào gọi API tạo/chọn/upload thumbnail.

### AC-23: Chọn nơi đăng sau khi duyệt video (FR-35, FR-36, FR-37)

**Given** pipeline vừa render thành công `video.mp4`  
**When** người dùng xem xong và bấm **Đăng video**  
**Then** video vừa tạo được gắn sẵn vào bước **Chọn nơi đăng**  
**And** các target đã kết nối được chia nhóm Facebook Fanpage, YouTube Shorts và
TikTok với tên cùng Page/channel/account ID  
**And** không target nào được chọn sẵn  
**And** không request upload nào được gửi trước khi người dùng tick ít nhất một
target và xác nhận.

### AC-24: Facebook chỉ hiển thị Fanpage (FR-2, FR-34)

**Given** tài khoản Meta OAuth có quyền với Fanpage và có profile/Group liên quan  
**When** hệ thống tải danh sách publish target Facebook  
**Then** chỉ Fanpage đủ quyền xuất bản xuất hiện trong danh sách  
**And** profile cá nhân cùng Group không được lưu thành `ConnectedAccount`.

### AC-25: Duyệt video trước khi đăng (FR-10, FR-38, FR-39)

**Given** pipeline vừa render thành công một video  
**When** màn hình kết quả xuất hiện  
**Then** người dùng có thể play, pause, tua và xem toàn màn hình đúng file đó  
**And** hệ thống chưa tạo publish job hoặc gửi request upload  
**And** bước chọn target chỉ mở sau khi người dùng bấm **Đăng video**.

### AC-26: Render lại trước khi xác nhận (FR-35, FR-40)

**Given** người dùng đã mở form xuất bản nhưng phát hiện lỗi và render lại video  
**When** bản render mới hoàn tất  
**Then** form dùng đường dẫn và SHA-256 của bản mới  
**And** mọi xác nhận trước đó bị vô hiệu  
**And** không job nào dùng fingerprint của bản video lỗi.

### AC-27: Chọn đăng ngay hoặc đặt lịch sau khi duyệt (FR-9, FR-13, FR-14)

**Given** video đã được người dùng duyệt và ít nhất một target được chọn  
**When** người dùng chọn **Đặt lịch**, nhập ngày/giờ/timezone tương lai và xác nhận  
**Then** job được lưu `scheduled` theo đúng UTC cùng timezone gốc  
**And** không upload trước thời điểm đã chọn.

### AC-28: Đăng ngay sau khi duyệt (FR-9, FR-13)

**Given** video đã được người dùng duyệt và ít nhất một target được chọn  
**When** người dùng chọn **Đăng ngay** và xác nhận  
**Then** job được đưa vào `queued` ngay lập tức.

## Edge Cases

- EC-1: OAuth callback sai/mất `state` → từ chối, `OAUTH_STATE_INVALID`, không
  lưu credential.
- EC-2: Người dùng từ chối OAuth → giữ trạng thái chưa kết nối, không coi là
  lỗi hệ thống.
- EC-3: Token hết hạn/thu hồi → job `blocked`, `TOKEN_EXPIRED`, yêu cầu kết nối lại.
- EC-4: Page bị gỡ quyền sau khi lên lịch → job `blocked`, không retry tự động.
- EC-5: TikTok client chưa audit → chỉ dùng privacy API cho phép; không cố
  cưỡng ép đăng public.
- EC-6: Creator Info timeout/429/5xx → không cho xác nhận TikTok; retry tải
  thông tin theo backoff.
- EC-7: Video bị xóa/đổi nội dung sau khi lên lịch → kiểm tra lại fingerprint
  trước upload; nếu lệch chuyển `failed` với `MEDIA_CHANGED`.
- EC-8: File quá lớn, sai codec/tỷ lệ/thời lượng → chặn trước upload bằng
  giới hạn hiện hành do provider trả về hoặc cấu hình adapter.
- EC-9: Mất mạng trước khi provider nhận upload → retry theo FR-25.
- EC-10: Mất mạng sau khi provider có thể đã nhận upload → `unknown`, đối
  soát trước mọi thao tác thủ công.
- EC-11: Rate limit → tôn trọng `Retry-After` nếu có; không retry vượt FR-25.
- EC-12: Provider 5xx kéo dài → `failed` sau lần thử cuối, giữ job và audit.
- EC-13: Hai worker claim cùng lúc → chỉ một claim thành công.
- EC-14: App/worker dừng giữa upload → khi khởi động lại phải đối soát trạng
  thái; không mặc định upload lại.
- EC-15: Ổ đĩa đầy hoặc SQLite bị khóa → không tạo job nửa vời; hiển thị
  `STORAGE_UNAVAILABLE`.
- EC-16: Caption vượt giới hạn provider → lỗi validation trước upload, chỉ rõ
  nền tảng và giới hạn hiện hành.
- EC-17: Lịch ở quá khứ → từ chối `SCHEDULE_IN_PAST`.
- EC-18: Job bị hủy đúng lúc worker claim → transaction quyết định duy nhất;
  hoặc hủy thành công trước claim, hoặc báo đã bắt đầu và không hủy.
- EC-19: Google OAuth trả tài khoản không có kênh YouTube → không tạo account,
  hiển thị `YOUTUBE_CHANNEL_NOT_FOUND`.
- EC-20: Hai lần OAuth trả cùng channel ID → cập nhật credential account hiện có,
  không tạo kênh trùng.
- EC-21: YouTube API project chưa verified và ép privacy private → lưu đúng privacy
  thực tế, cảnh báo `PROVIDER_PRIVACY_RESTRICTED`, không báo public thành công.
- EC-22: Resumable upload YouTube bị ngắt → tiếp tục từ upload session hợp lệ;
  nếu session hết hạn thì đối soát trước khi khởi tạo lại.
- EC-23: Video YouTube Short dài hơn 60 giây có Content ID claim → lưu trạng thái/
  restriction provider trả về và cảnh báo có thể bị chặn toàn cầu; không tự xóa.

## API Contracts

Ứng dụng hiện là Streamlit monolith, vì vậy MVP không mở API quản lý job công
khai. Các interface dưới đây là hợp đồng giữa UI, scheduler và provider adapter.
OAuth là ngoại lệ và cung cấp hai route tối thiểu:

- `GET /oauth/{platform}/start` tạo authorization attempt có `state`, sau đó
  redirect tới provider; `{platform}` chỉ nhận `facebook`, `tiktok` hoặc `youtube`.
- `GET /oauth/{platform}/callback?code=...&state=...` kiểm tra state, đổi code lấy
  token rồi redirect về tab Xuất bản. Thành công trả redirect 302; input/provider
  lỗi cũng redirect 302 nhưng kèm mã tham chiếu an toàn trong session, không đặt
  token hoặc raw provider error vào URL.

```typescript
type Platform = "facebook_page" | "tiktok" | "youtube_short";
type JobStatus =
  | "scheduled" | "queued" | "validating" | "uploading" | "processing"
  | "published" | "failed" | "blocked" | "cancelled" | "unknown";

interface CreatePublishRequest {
  mediaPath: string;
  targets: Array<{
    accountId: string;
    platform: Platform;
    caption: string;
    options: FacebookOptions | TikTokOptions | YouTubeShortOptions;
  }>;
  publishAt: string;       // ISO-8601 có offset; đăng ngay nếu <= now
  timezone: string;        // IANA timezone, mặc định Asia/Ho_Chi_Minh
  confirmed: true;
}

interface FacebookOptions {
  mode: "video" | "reel";
  title?: string;
}

interface TikTokOptions {
  privacyLevel: string;    // MUST thuộc Creator Info response mới nhất
  disableComment: boolean;
  disableDuet: boolean;
  disableStitch: boolean;
  commercialContent: {
    promoteOwnBrand: boolean;
    promoteThirdParty: boolean;
  };
  videoCoverTimestampMs?: number;
}

interface YouTubeShortOptions {
  title: string;                 // required, giới hạn theo API hiện hành
  description: string;
  tags: string[];
  categoryId: string;
  privacyStatus: "private" | "unlisted" | "public";
  notifySubscribers: boolean;
  selfDeclaredMadeForKids: boolean;
  containsSyntheticMedia: boolean;
  defaultLanguage?: string;
}

interface PublishJobView {
  id: string;
  batchId: string;
  platform: Platform;
  accountId: string;
  status: JobStatus;
  scheduledAtUtc: string;
  attemptCount: number;
  providerPostId?: string;
  providerPostUrl?: string;
  error?: ApiError;
}

interface ApiError {
  code: string;            // mã nội bộ ổn định
  message: string;         // thông báo an toàn cho người dùng
  retryable: boolean;
  details?: Record<string, string>; // MUST NOT chứa secret/raw token
}

interface SocialProviderAdapter {
  validateMedia(path: string): Promise<MediaValidation>;
  refreshAccount(accountId: string): Promise<ConnectedAccount>;
  publish(job: PublishJob): Promise<PublishReceipt>;
  getStatus(receipt: PublishReceipt): Promise<ProviderStatus>;
  revoke(accountId: string): Promise<void>;
}
```

### 8.1 Kết quả tạo job

- Thành công: trả một `batchId` và một `PublishJobView` cho mỗi target.
- Validation error: `MEDIA_INVALID`, `CAPTION_INVALID`, `TARGET_INVALID`,
  `SCHEDULE_IN_PAST` hoặc `CONSENT_REQUIRED`; không tạo job con nào.
- Storage error: `STORAGE_UNAVAILABLE`; không để batch/job không đầy đủ.

### 8.2 Provider contracts

- Facebook adapter MUST tách bước upload/publish/status theo API version cấu
  hình; MUST lưu provider video/post ID ngay khi nhận được.
- TikTok adapter MUST gọi Creator Info trước Direct Post, khởi tạo video post,
  upload theo URL do TikTok cấp và poll publish status.
- YouTube adapter MUST xác minh channel ID sau OAuth, upload resumable bằng
  `POST https://www.googleapis.com/upload/youtube/v3/videos` (`videos.insert`) và
  theo dõi `processingDetails`/`status`; adapter MUST NOT gọi thumbnail endpoint.
- Mọi adapter MUST map raw provider error sang `ApiError` và chỉ lưu raw payload
  đã redaction trong debug log.

## Data Models

MVP dùng SQLite riêng tại vùng dữ liệu ứng dụng để có transaction và claim job
nguyên tử. Không nhét lịch sử/job vào `~/.avc_config.json`.

### ConnectedAccount

| Field | Type | Constraints |
|---|---|---|
| id | UUID/text | PK, immutable |
| platform | enum | `facebook_page`, `tiktok`, `youtube_short`; not null |
| provider_account_id | text | not null; unique cùng platform |
| display_name | text | not null |
| status | enum | `connected`, `expired`, `revoked`, `error` |
| scopes | JSON text | not null |
| encrypted_credential | blob | not null; authenticated encryption |
| credential_expires_at | timestamp | UTC, nullable |
| created_at | timestamp | UTC, immutable |
| updated_at | timestamp | UTC |

Index: unique `(platform, provider_account_id)`; index `(status)`.

### PublishBatch

| Field | Type | Constraints |
|---|---|---|
| id | UUID/text | PK |
| media_path | text | absolute path, not null |
| media_sha256 | char(64) | not null |
| created_at | timestamp | UTC, immutable |
| confirmed_at | timestamp | UTC, not null |

### PublishJob

| Field | Type | Constraints |
|---|---|---|
| id | UUID/text | PK |
| batch_id | UUID/text | FK PublishBatch, not null |
| account_id | UUID/text | FK ConnectedAccount, not null |
| platform | enum | not null |
| caption | text | not null, provider validation applies |
| options | JSON text | not null, schema-versioned |
| status | enum | not null, default `scheduled` |
| scheduled_at_utc | timestamp | UTC, not null |
| source_timezone | text | IANA name, not null |
| attempt_count | integer | >= 0, default 0 |
| next_attempt_at | timestamp | UTC, nullable |
| claimed_by | text | nullable |
| claim_expires_at | timestamp | UTC, nullable |
| idempotency_key | text | unique, not null |
| provider_publish_id | text | nullable |
| provider_post_id | text | nullable |
| provider_post_url | text | nullable |
| last_error_code | text | nullable |
| last_error_message | text | redacted, nullable |
| created_at | timestamp | UTC, immutable |
| updated_at | timestamp | UTC |

Indexes: `(status, scheduled_at_utc)`, `(account_id, created_at)`, unique
`(idempotency_key)`.

### AuditEvent

| Field | Type | Constraints |
|---|---|---|
| id | UUID/text | PK |
| job_id | UUID/text | FK PublishJob, nullable cho account event |
| account_id | UUID/text | FK ConnectedAccount, nullable |
| event_type | text | not null |
| safe_payload | JSON text | redacted, MUST NOT chứa credentials |
| created_at | timestamp | UTC, immutable |

Index: `(job_id, created_at)`.

### WorkerHeartbeat

| Field | Type | Constraints |
|---|---|---|
| worker_id | text | PK |
| version | text | not null |
| last_seen_at | timestamp | UTC, not null |

## 10. UI Specification

Thêm bước hành động vào màn hình kết quả render và tab cấp cao **📣 Xuất bản**
bên cạnh Pipeline/Veo3/Creative Studio/Settings.

- **Kết quả render:** player của đúng MP4 vừa tạo với play/pause/seek/fullscreen;
  nút **Sửa & render lại** và nút **📣 Đăng video**. Chưa có upload ở màn hình này.
  Nút Đăng video mở form với video hiện tại đã gắn sẵn, không mở file picker.
- **Chọn nơi đăng:** danh sách checkbox 3 nhóm; Facebook chỉ gồm Fanpage, YouTube
  gồm từng channel, TikTok gồm từng account. Mỗi target hiển thị avatar, tên và ID;
  mặc định không tick target nào.

- **Kết nối:** danh sách Fanpage/tài khoản TikTok/kênh YouTube, channel/account
  ID, trạng thái token, kết nối lại và ngắt kết nối.
- **Tạo bài trong tab Xuất bản:** dùng cho video cũ; chọn video gần đây hoặc
  đường dẫn, preview, caption/metadata theo nền tảng, chọn đồng thời nhiều target,
  đăng ngay/đặt lịch và xác nhận. Không có trường thumbnail.
- **Thời điểm đăng:** radio **Đăng ngay** hoặc **Đặt lịch**. Đặt lịch hiển thị
  ngày, giờ và timezone; trước nút xác nhận phải hiển thị thời điểm đầy đủ theo
  timezone người dùng và UTC tương ứng.
- **Lịch đăng:** job tương lai, countdown, sửa khi còn `scheduled`, hủy.
- **Lịch sử:** bộ lọc, trạng thái, lỗi, số lần thử, post ID/URL, audit timeline.
- **Worker badge:** `Đang chạy`, `Mất kết nối` hoặc `Chưa cấu hình` dựa heartbeat.

Trong tab **⚙️ Settings**, thêm mục **Kết nối kênh** cùng cấu hình Meta App,
TikTok Developer App, Google OAuth/YouTube Data API và callback. Facebook chỉ
hiển thị nút **Kết nối Fanpage**; YouTube hiển thị **Kết nối thêm kênh YouTube**
để lặp lại cho nhiều channel. Secret input MUST bị che và không render lại plaintext.

## 11. Rollout Plan

1. **Phase 1 — Local sandbox:** data model, provider adapters mock, đăng Facebook
   test Page, TikTok `SELF_ONLY` và YouTube private, không đặt lịch production.
2. **Phase 2 — Scheduling:** worker riêng, retry/idempotency, heartbeat, lịch sử.
3. **Phase 3 — Production approval:** hoàn tất Meta App Review, TikTok audit và
   Google OAuth/API verification cần thiết; kiểm thử public bằng account được duyệt.
4. **Phase 4 — Hardening:** kiểm thử restart, concurrency, rate limit, credential
   rotation và backup/restore database không chứa plaintext secret.

Rollback: tắt feature flag `SOCIAL_PUBLISHING_ENABLED`; worker ngừng claim job
mới nhưng không xóa database/credential. Các job đang upload phải được đối soát
trước khi rollback hoàn tất.

## Out of Scope

- OS-1: Đăng Facebook profile cá nhân/Group — API và quyền khác Page.
- OS-2: Instagram, Threads, Zalo — cần adapter và spec riêng.
- OS-3: Đăng ảnh, carousel, story, live stream hoặc text-only — MVP tập trung MP4.
- OS-4: Tự sinh caption/hashtag bằng AI — MVP chỉ tái sử dụng metadata hiện
  có và cho người dùng chỉnh.
- OS-5: Tự động trả lời bình luận/inbox hoặc thu thập analytics — ngoài mục
  tiêu xuất bản.
- OS-6: Chạy lịch 24/7 trên cloud — MVP là local worker; cloud deployment cần
  thiết kế vận hành, secret manager và chi phí riêng.
- OS-7: Bỏ qua review/audit, cưỡng ép TikTok public hoặc dùng browser automation
  để né API chính thức — vi phạm chính sách và không được triển khai.
- OS-8: Tạo, chọn hoặc upload thumbnail — người dùng tập trung video ngắn và đã
  xác nhận không cần tính năng này.
- OS-9: Upload video dài YouTube — MVP chỉ nhận video đủ điều kiện Shorts.

## 13. Open Decisions — cần người dùng duyệt

- **D-1:** Xác nhận TB = TikTok.
- **D-2:** Chọn Facebook output mặc định: `Reel` (khuyến nghị cho video 9:16) hay
  video Page thông thường.
- **D-3:** Chấp nhận điều kiện MVP local: app/worker phải chạy để lịch hoạt động,
  hay đổi phạm vi sang worker cloud 24/7.
- **D-4:** OAuth production cần callback HTTPS công khai; chọn domain triển khai
  hoặc chỉ chạy sandbox/manual setup trong Phase 1.
- **D-5:** Xác nhận cho phép tạo kho credential mã hóa và SQLite mới trong vùng
  dữ liệu ứng dụng khi bước triển khai bắt đầu.
- **D-6:** Với YouTube, mặc định privacy là `private` (khuyến nghị khi test),
  `unlisted` hay `public` sau khi project đã được xác minh.
- **D-7:** Khi chọn nhiều kênh YouTube, dùng cùng title/description mặc định rồi
  cho phép override từng kênh (khuyến nghị), hay bắt buộc nhập riêng từ đầu.

## 14. Definition of Done

- Spec chuyển sang `Approved` sau khi D-1 đến D-5 được chốt.
- Mỗi AC-1 đến AC-28 có test tự động; mọi test provider dùng mock, ngoài bộ test
  sandbox được đánh dấu integration.
- Mỗi EC-1 đến EC-23 có test hoặc test mapping tương ứng.
- Typecheck/test hiện có của repo vẫn pass.
- Không secret nào xuất hiện trong Git, log, snapshot test hoặc SQLite plaintext.
- Facebook test Page, TikTok sandbox/`SELF_ONLY` và ít nhất hai kênh YouTube test
  upload private thành công bằng một video đầu ra thực tế của project.
- Tài liệu setup mô tả Meta App, TikTok App, Google Cloud/YouTube Data API,
  callback, scopes, worker và cách xử lý token hết hạn.

## 15. Tài liệu API tham chiếu

- TikTok Content Posting API — Get Started:
  https://developers.tiktok.com/doc/content-posting-api-get-started/
- TikTok Direct Post API:
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- TikTok Creator Info:
  https://developers.tiktok.com/doc/content-posting-api-reference-query-creator-info
- TikTok Content Sharing Guidelines:
  https://developers.tiktok.com/doc/content-sharing-guidelines/
- Meta Graph API documentation (Page video/Reels publishing và quyền phải được
  xác minh lại theo Graph API version tại thời điểm triển khai):
  https://developers.facebook.com/docs/graph-api/
- YouTube Data API `videos.insert`:
  https://developers.google.com/youtube/v3/docs/videos/insert
- YouTube OAuth 2.0:
  https://developers.google.com/youtube/v3/guides/authentication
- YouTube Shorts tối đa 3 phút và điều kiện phân loại:
  https://support.google.com/youtube/answer/15424877
