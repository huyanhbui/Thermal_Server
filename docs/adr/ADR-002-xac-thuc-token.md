# ADR-002 — Xác thực bằng token có trạng thái; danh tính node suy ra từ token

**Trạng thái:** Đã chốt
**Ngày:** 2026-07-31
**Liên quan:** [`01 §S2`](../01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào), [`06`](../06-bao-mat-va-quyen-rieng-tu.md), [`03`](../03-hop-dong-api.md)

## Bối cảnh

PoC **không có xác thực trên bất kỳ endpoint nào**. Ở phạm vi LAN sau tường lửa, với tài sản duy nhất là số nhiệt độ, điều này chấp nhận được.

Thiết kế mới đổi hai thứ cùng lúc:

1. **Chủ động đưa API ra Internet công cộng** qua tunnel. Cloudflare quick tunnel không thêm lớp xác thực nào, và URL tunnel không phải bí mật — chúng xuất hiện trong log DNS, Certificate Transparency, và bị bot quét chủ động.
2. **Thêm một tài sản có giá trị thật:** nội dung chat của người dùng.

Đường tấn công cụ thể nhất, không cần kỹ năng gì đặc biệt:

```bash
while true; do
  curl -X POST https://<tunnel>/ingest \
    -d '{"node":"Node-Ma","cpu_temp":25,"cpu_util":1,"power_w":10}'
  sleep 2
done
```

Node ma này luôn mát nhất, không bao giờ bị gắn cờ, và dưới scheduler chấm điểm mới nó **luôn thắng điểm**. Nó nhận hết chat job của cả cụm và không bao giờ trả kết quả. Hệ thống ngừng hoạt động. Ba dòng shell.

Thêm nữa: `GET /jobs/next?node=X` ([`server.py:162`](../../server/server.py)) lấy danh tính node **từ query string** — nên ngay cả khi có mật khẩu phòng, một worker hợp lệ vẫn mạo danh worker khác được bằng cách đổi tham số.

## Quyết định

**Token có trạng thái, danh tính suy ra từ token.**

```
POST /join {room_code, password, node_name, capabilities}
   → 201 {token, room_config}

Mọi request sau:  Authorization: Bearer <token>
```

Sáu quy tắc:

1. **Danh tính node suy ra từ token, không bao giờ từ query hay body.** Thân yêu cầu mâu thuẫn với token → `403 IDENTITY_MISMATCH` + ghi kiểm toán.
2. Token = 32 byte từ CSPRNG, mã base64url.
3. **Lưu hash của token, không lưu token.**
4. **Token có trạng thái và thu hồi được.**
5. Hạn mặc định 24 giờ, tự gia hạn khi còn hoạt động.
6. Hai mức quyền: `worker` và `admin`.

Mật khẩu phòng băm bằng Argon2id (hoặc PBKDF2-HMAC-SHA256 600.000 vòng), so sánh bằng hàm thời gian hằng. Giới hạn tần suất `/join`: 5 lần/phút/IP + backoff lũy thừa.

**Không được bật tunnel khi chưa đặt mật khẩu** — chặn ở tầng mã, không phải bằng lời khuyên trong tài liệu.

## Phương án đã cân nhắc

### A. JWT không trạng thái

Ký token, không lưu gì phía server, xác thực bằng chữ ký.

**Loại vì một lý do quyết định: không thu hồi được.**

Thiết kế yêu cầu "Host có thể kick worker". Với JWT không trạng thái, kick chỉ là thay đổi giao diện — worker bị kick vẫn gọi API bình thường cho tới khi token hết hạn. Để thu hồi thật thì phải có danh sách chặn phía server, mà như vậy là đã có trạng thái rồi, chỉ là phức tạp hơn.

Ở quy mô 10 node, tra một từ điển trong bộ nhớ là chuyện không đáng bàn. Lợi thế "không trạng thái" của JWT chỉ có nghĩa khi cần mở rộng nhiều máy chủ — điều không nằm trong phạm vi.

### B. Mật khẩu phòng gửi kèm mỗi request

Đơn giản nhất, không cần quản lý token.

**Loại:** mật khẩu xuất hiện trong mọi request → tăng bề mặt rò rỉ (log truy cập, log proxy, lịch sử shell). Không thu hồi riêng từng worker được. Không phân quyền được. Không có cách nào hết hạn.

### C. Chứng chỉ client (mTLS)

Bảo mật mạnh nhất.

**Loại ở giai đoạn này:** cần hạ tầng khóa công khai, cần phân phối chứng chỉ, cần xử lý gia hạn. Với mô hình mối đe dọa hiện tại, chi phí lớn hơn lợi ích rất nhiều. Ghi lại như hướng đi khả dĩ nếu sau này cần TLS hai chiều cho chặng LAN.

### D. Khóa API cố định, cấu hình sẵn trên từng máy

**Loại:** vẫn phải phân phối bí mật thủ công tới 9 máy, mà không có ưu điểm nào so với token. Đổi khóa phải làm thủ công trên từng máy.

## Hệ quả

### Tích cực

- Chặn được toàn bộ bốn đường tấn công đã liệt kê ở [01 §S2](../01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào)
- Kick worker **thực sự có hiệu lực**
- Phân quyền: worker không đổi được ngưỡng của cả cụm
- Danh tính đáng tin → nhật ký kiểm toán có giá trị
- Vào phòng thất bại được ghi lại → phát hiện được việc bị dò mật khẩu

### Tiêu cực

- **Thêm trạng thái phía host.** Kho token phải tồn tại qua khởi động lại, nếu không mọi worker bị đăng xuất mỗi lần host restart. Thêm một bảng, thêm một đường có thể hỏng.
- **Vòng vào phòng phức tạp hơn.** Worker phải xử lý token hết hạn, token bị thu hồi, và tự vào lại phòng. Khoảng 1 ngày công thêm ở phía agent.
- **Mật khẩu là điểm hỏng do con người.** Người dùng sẽ đặt mật khẩu yếu, hoặc gửi mật khẩu cùng link mời trong một tin nhắn. Giảm nhẹ bằng yêu cầu độ dài tối thiểu và thanh đo độ mạnh, nhưng không loại bỏ được.
- Giới hạn tần suất có thể chặn nhầm khi 10 worker cùng vào phòng từ cùng một IP NAT. Giới hạn 5 lần/phút/IP phải tính tới trường hợp này — **cần test ca C7**.

### Trung tính

- Argon2id thêm một phụ thuộc. PBKDF2 nằm sẵn trong thư viện chuẩn và đủ tốt ở 600.000 vòng — chọn cái nào cũng được, miễn ghi rõ.
- Token trong query string của WebSocket (`/ws?token=…`) sẽ vào log truy cập. Chấp nhận được vì token thu hồi được và có hạn; giải pháp sạch hơn là subprotocol header, để lại cho sau.

## Kiểm chứng

| Cách kiểm | Kỳ vọng |
|---|---|
| Ca S1–S15 ([11 §6](../11-chien-luoc-kiem-thu.md#6-kiểm-thử-bảo-mật)) | Toàn bộ xanh, **không có ngoại lệ** |
| Ca S2, S3 | Không mạo danh được node khác |
| Ca S6 | Token của worker đã kick bị từ chối |
| Ca S12 | Quét toàn bộ log: **không có mật khẩu hay token nào** |
| Ca C7 | 10 node vào phòng đồng thời không bị chặn nhầm |
| Ca S9 | Không bật được tunnel khi chưa có mật khẩu |

**Cổng chặn:** M1 chưa xong thì **không được bật tunnel** trong bất kỳ hoàn cảnh nào, kể cả để demo.
