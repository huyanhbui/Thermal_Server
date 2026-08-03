# 06 — Bảo mật và quyền riêng tư

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Sửa lỗi: [S2](01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào), [D15](01-danh-gia-thiet-ke-hien-tai.md#d15--tự-tải-binary--chạy-quyền-administrator--tệp-chưa-ký-số), [D17](01-danh-gia-thiet-ke-hien-tai.md#d17--prompt-chat-rời-máy-host-sang-máy-đồng-nghiệp)
> Quyết định: [ADR-002](adr/ADR-002-xac-thuc-token.md) · Hợp đồng: [03](03-hop-dong-api.md)

## Mục lục

- [Mô hình mối đe dọa](#1-mô-hình-mối-đe-dọa)
- [Xác thực và phân quyền](#2-xác-thực-và-phân-quyền)
- [Phơi nhiễm qua tunnel](#3-phơi-nhiễm-qua-tunnel)
- [Quyền riêng tư của prompt](#4-quyền-riêng-tư-của-prompt)
- [Chuỗi cung ứng](#5-chuỗi-cung-ứng)
- [Quyền Administrator](#6-quyền-administrator)
- [Nhật ký kiểm toán](#7-nhật-ký-kiểm-toán)
- [Danh sách kiểm tra trước khi ship](#8-danh-sách-kiểm-tra-trước-khi-ship)

---

## 1. Mô hình mối đe dọa

### Tài sản cần bảo vệ

| # | Tài sản | Vì sao quan trọng |
|---|---|---|
| 1 | **Nội dung prompt và câu trả lời** | Người dùng gõ gì thì hệ thống biết nấy. Có thể chứa thông tin công việc |
| 2 | Tính toàn vẹn của telemetry | Nền tảng của mọi quyết định điều phối và mọi con số ESG |
| 3 | Chu kỳ CPU của các máy phụ | Đây là tài nguyên bị "cho mượn" — kẻ tấn công có thể chiếm dụng |
| 4 | Tính toàn vẹn của báo cáo ESG | Báo cáo có thể được nộp cho bên thứ ba |
| 5 | Mật khẩu phòng | Cửa vào tất cả những thứ trên |

### Kẻ tấn công

| Loại | Năng lực | Mức quan tâm |
|---|---|---|
| **Bot quét Internet** | Tìm thấy URL tunnel bằng quét diện rộng, thử endpoint mặc định | **Cao** — chắc chắn xảy ra khi bật tunnel |
| **Người trong mạng LAN** | Có quyền truy cập mạng, biết cổng 8000 | Trung bình |
| **Worker hợp lệ nhưng tò mò** | Có token hợp lệ; muốn xem prompt của người khác | Trung bình |
| **Cựu thành viên phòng** | Đã bị kick nhưng còn giữ token | Trung bình |
| Kẻ tấn công có chủ đích | Nhắm riêng vào tổ chức này | Thấp ở giai đoạn này |

**Thay đổi lớn nhất so với PoC:** PoC chỉ chạy LAN, sau tường lửa, không có gì đáng lấy ngoài số nhiệt độ. Hệ mới **chủ động đưa API ra Internet công cộng** và **thêm một tài sản có giá trị thật (nội dung chat)**. Mô hình mối đe dọa đổi hoàn toàn, không phải đổi một phần.

### Phân tích STRIDE gọn

| Loại | Rủi ro cụ thể | Xử lý |
|---|---|---|
| **Giả mạo danh tính** | `POST /ingest` với tên node bất kỳ ([`server.py:154`](../server/server.py)) | Danh tính từ token (§2) |
| **Sửa đổi dữ liệu** | Bơm telemetry giả để lệch quyết định điều phối và số ESG | Token + giới hạn tần suất |
| **Chối bỏ** | Không có vết ai làm gì | Nhật ký kiểm toán (§7) |
| **Lộ thông tin** | `/api/state` và `/ws` mở cho mọi người; prompt hiện trong log | Phân quyền + không ghi log prompt (§4) |
| **Từ chối dịch vụ** | Node ma hút hết job; dò mật khẩu; spam chat | Giới hạn tần suất + hạn giữ chỗ |
| **Nâng quyền** | Worker gọi `/api/settings` đổi ngưỡng cả cụm | Tách quyền worker / quản trị (§2) |

---

## 2. Xác thực và phân quyền

### Vấn đề hiện tại

**Không endpoint nào kiểm tra bất cứ điều gì.** Bảng đầy đủ ở [01 §S2](01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào).

Đường tấn công cụ thể nhất, không cần kỹ năng gì đặc biệt:

```bash
# Bơm một node ma luôn mát, chạy mỗi 2 giây
while true; do
  curl -X POST https://<tunnel>/ingest \
    -d '{"node":"Node-Ma","cpu_temp":25,"cpu_util":1,"power_w":10}'
  sleep 2
done
```

Node này luôn mát nhất, không bao giờ bị gắn cờ, và dưới scheduler chấm điểm mới nó **luôn thắng điểm** ([04 §4](04-dac-ta-scheduler.md#4-giai-đoạn-2--chấm-điểm)). Nó nhận hết chat job của cả cụm và không bao giờ trả kết quả. Hệ thống ngừng hoạt động. Ba dòng shell.

### Luồng token

```
Worker                                       Host
  │  POST /join {room_code, password, ...}    │
  ├──────────────────────────────────────────►│ 1. kiểm tra giới hạn tần suất theo IP
  │                                            │ 2. so hash mật khẩu (thời gian hằng)
  │                                            │ 3. kiểm tra sức chứa
  │                                            │ 4. sinh token 256 bit từ CSPRNG
  │                                            │ 5. lưu {token_hash -> node, quyền, hạn}
  │                                            │ 6. ghi room_audit
  │◄───────────────────────────────────────────┤ 201 {token, room_config}
  │                                            │
  │  Mọi request sau: Authorization: Bearer …  │
  ├──────────────────────────────────────────►│ tra token -> node + quyền
  │                                            │ DANH TÍNH LẤY TỪ ĐÂY, KHÔNG TỪ THÂN
```

### Sáu quy tắc

| # | Quy tắc | Vì sao |
|---|---|---|
| 1 | **Danh tính node suy ra từ token, không bao giờ từ query hay body** | Nếu không, worker hợp lệ vẫn mạo danh worker khác bằng cách đổi tham số |
| 2 | Token = 32 byte từ `secrets.token_bytes`, mã base64url | Đủ entropy để không dò được |
| 3 | **Lưu hash của token, không lưu token** | Rò rỉ cơ sở dữ liệu không đồng nghĩa rò rỉ quyền truy cập |
| 4 | Token **có trạng thái và thu hồi được** | Tính năng "kick worker" không có ý nghĩa nếu không thu hồi được token. Đây là lý do **không dùng JWT không trạng thái** |
| 5 | Hạn mặc định 24 giờ, tự gia hạn khi còn hoạt động | |
| 6 | Hai mức quyền: `worker` và `admin` | Worker không được đổi ngưỡng cả cụm |

Ma trận quyền đầy đủ: [03 §2](03-hop-dong-api.md#2-ma-trận-xác-thực).

### Mật khẩu phòng

```python
# Argon2id — ưu tiên
argon2.PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# PBKDF2 — nếu muốn tránh thêm phụ thuộc (nằm sẵn trong thư viện chuẩn)
hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, 600_000)
```

- Muối ngẫu nhiên riêng cho mỗi phòng
- So sánh bằng `hmac.compare_digest` — tránh rò rỉ qua thời gian phản hồi
- **Không bao giờ ghi mật khẩu vào log**, kể cả ở mức DEBUG, kể cả một phần
- Yêu cầu tối thiểu 8 ký tự khi tạo phòng; hiện thanh đo độ mạnh trên giao diện

### Giới hạn tần suất

| Endpoint | Giới hạn | Vượt thì |
|---|---|---|
| `POST /join` | 5 lần/phút/IP | 429 + backoff lũy thừa (2s, 4s, 8s… trần 5 phút) |
| `POST /ingest` | 2 lần/giây/token | 429 |
| `POST /chat` | 10 lần/phút/token | 429 |
| Các endpoint khác | 60 lần/phút/token | 429 |

**Giới hạn `/join` là bắt buộc, không phải tùy chọn.** Không có nó, một mật khẩu 8 ký tự bị dò qua tunnel trong vài giờ. Có nó, thời gian dò kéo dài tới mức không thực tế.

`AUTH_FAILED` trả **cùng một thông điệp** cho sai mã phòng và sai mật khẩu — không tiết lộ mã phòng nào tồn tại.

---

## 3. Phơi nhiễm qua tunnel

### Điều cần nói thẳng

Bật tunnel = **đưa toàn bộ API ra Internet công cộng**. Cloudflare quick tunnel không thêm bất kỳ lớp xác thực nào.

**URL tunnel không phải bí mật.** Chúng xuất hiện trong log DNS, trong Certificate Transparency, và bị quét chủ động bởi bot. Coi URL là công khai ngay từ giây đầu tiên nó tồn tại.

### Bốn biện pháp

| # | Biện pháp | Chi tiết |
|---|---|---|
| 1 | **LAN là mặc định, tunnel là opt-in** | Người dùng phải bấm bật, và thấy cảnh báo rõ ràng khi bật |
| 2 | **Không bật tunnel khi chưa đặt mật khẩu** | Chặn ở tầng mã, không phải bằng lời khuyên trong tài liệu |
| 3 | **Chỉ số 401 hiển thị trên dashboard** | Người dùng thấy được mình đang bị dò |
| 4 | **Tự tắt tunnel sau N giờ không hoạt động** | Giảm bề mặt tấn công; mặc định 8 giờ |

Cảnh báo hiển thị khi bật tunnel:

```
⚠️  Bật tunnel sẽ đưa phòng này ra Internet công cộng.
    Bất kỳ ai có đường link đều có thể thử mật khẩu.
    • Dùng mật khẩu mạnh (≥12 ký tự)
    • Tắt tunnel khi không dùng
    • Trong cùng mạng LAN thì KHÔNG cần tunnel
```

### Cấu hình chỉ chạy LAN

Cho môi trường doanh nghiệp nghiêm ngặt:

```json
{ "tunnel_enabled": false, "bind_address": "192.168.1.50", "allow_tunnel": false }
```

`allow_tunnel: false` **vô hiệu hóa tính năng ở tầng mã**, không chỉ tắt mặc định. Bộ phận IT cần khẳng định được điều này khi phê duyệt phần mềm.

---

## 4. Quyền riêng tư của prompt

Đây là vấn đề quản trị dữ liệu nghiêm túc nhất của thiết kế, và bản thiết kế gốc chưa đề cập tới.

### Prompt đi qua đâu

```
Người dùng gõ trên dashboard
   │  HTTPS (nếu qua tunnel) hoặc HTTP (nếu LAN)
   ▼
Host — prompt nằm trong RAM, trong hàng đợi job
   │  HTTP thuần trên LAN  ← KHÔNG MÃ HÓA
   ▼
Worker (máy tính của một đồng nghiệp)
   │  prompt nằm trong RAM tiến trình worker
   │  prompt truyền sang runtime LLM qua 127.0.0.1
   ▼
Runtime LLM — prompt nằm trong RAM, có thể trong log của chính runtime
```

Ba sự thật phải nói với người dùng, không được để họ tự phát hiện:

1. **Nội dung chat được xử lý trên máy tính của đồng nghiệp khác.**
2. **Chặng host → worker trên LAN không được mã hóa** trừ khi bổ sung TLS.
3. **Runtime LLM có thể tự ghi log prompt** theo mặc định của nó.

### Bảy quy tắc

| # | Quy tắc | Hiện thực |
|---|---|---|
| 1 | **Worker không ghi log nội dung prompt** | Chỉ ghi `job_id`, số token, thời lượng, năng lượng |
| 2 | **Tắt log của runtime LLM** | `llama-server --log-disable` hoặc tương đương |
| 3 | Host chỉ giữ prompt trong RAM cho tới khi trả kết quả | Không ghi vào `telemetry.db` |
| 4 | Lịch sử chat lưu tùy chọn, mặc định **tắt** | Người dùng chủ động bật |
| 5 | Chỉ token `admin` xem được nội dung chat | Worker chỉ thấy prompt của job mình đang chạy |
| 6 | Xóa prompt khỏi bộ nhớ job ngay sau khi trả kết quả | |
| 7 | **Nói rõ trên giao diện** trước khi người dùng gõ | Xem dưới |

Thông báo hiển thị lần đầu mở ô chat:

```
ⓘ  Câu hỏi của bạn sẽ được xử lý trên một máy tính khác trong phòng
    (hiện có: Node-A, Node-B, Node-C).
    Nội dung không được ghi lại theo mặc định.
    Đừng gửi thông tin nhạy cảm hoặc bí mật kinh doanh.
```

### TLS cho chặng LAN

Ngoài phạm vi mốc đầu, nhưng phải ghi vào lộ trình. Phương án: host tự sinh chứng chỉ CA, cấp chứng chỉ cho từng worker lúc `/join`. Đến khi làm được, **tài liệu phải nói thẳng rằng chặng này là plaintext** thay vì im lặng.

---

## 5. Chuỗi cung ứng

Sửa [D15](01-danh-gia-thiet-ke-hien-tai.md#d15--tự-tải-binary--chạy-quyền-administrator--tệp-chưa-ký-số).

### Vấn đề

Từ góc nhìn của EDR doanh nghiệp, worker sẽ trông như thế này:

- Tệp thực thi **chưa ký số**
- Chạy quyền **Administrator**
- Nạp **driver mức nhân** (LibreHardwareMonitor)
- **Tải thêm tệp thực thi** từ Internet
- **Thực thi** những tệp vừa tải
- Mở **cổng lắng nghe** trên localhost

Đó là mô tả chính xác của một trình tải mã độc. Nó sẽ bị cách ly. Đây là kết quả mặc định, không phải rủi ro lý thuyết.

### Sáu biện pháp

| # | Biện pháp | Bắt buộc |
|---|---|---|
| 1 | **Ghim phiên bản + SHA256** cho mọi tệp tải về | ✅ |
| 2 | **Kiểm tra hash TRƯỚC khi chạy**, từ chối nếu lệch | ✅ |
| 3 | Chỉ HTTPS, chỉ từ danh sách miền đã ghim | ✅ |
| 4 | **Tài liệu whitelist cho IT** | ✅ |
| 5 | Gói sẵn mô hình trong bộ cài thay vì tải lúc chạy | Nên |
| 6 | Ký số tệp thực thi của chính mình | Khi triển khai diện rộng |

Biện pháp 2 đáng nhấn mạnh: hash phải được kiểm **trước khi tệp được thực thi lần đầu**, không phải sau. Kiểm sau khi chạy là không kiểm.

### Cấu hình ghim

```json
{
  "runtime": {
    "url": "https://github.com/…/llama-<phiên bản đã ghim>-win-x64.zip",
    "sha256": "<hash thật, tự tính khi chốt phiên bản>",
    "version": "<ghim cụ thể, KHÔNG dùng latest>"
  },
  "model": {
    "id": "qwen2.5-0.5b-instruct-q4_k_m",
    "url": "https://huggingface.co/…/….gguf",
    "sha256": "<hash thật>",
    "license": "Apache-2.0",
    "size_mb": 398
  },
  "allowed_domains": ["github.com", "objects.githubusercontent.com",
                      "huggingface.co", "cdn-lfs.huggingface.co"]
}
```

**Không bao giờ sao chép hash từ tài liệu.** Tự tải, tự tính, tự ghi:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server.exe
```

### Tài liệu whitelist cho IT

Phải có trước khi triển khai lên máy người khác. Tài liệu này quyết định dự án được duyệt hay không, nhiều hơn bất kỳ tính năng nào.

Nội dung tối thiểu:

| Mục | Nội dung |
|---|---|
| Tệp thực thi | Đường dẫn đầy đủ + SHA256 của từng tệp |
| Quyền cần | Administrator, và **lý do cụ thể** (driver đọc cảm biến — không phải "để cho chắc") |
| Cổng | Vào: 8000 chỉ trên host. Ra: 443 tới danh sách miền đã ghim |
| Kết nối mạng | Worker chỉ outbound; không có cổng lắng nghe ra ngoài |
| Dữ liệu thu thập | Nhiệt độ, mức sử dụng, công suất. **Không đọc tệp, không đọc dữ liệu người dùng** |
| Dữ liệu truyền đi | Telemetry và nội dung chat, chỉ trong nội bộ cụm |
| Gỡ cài | Cách gỡ sạch |

Điểm mạnh cần nhấn: [`SensorReader.cs`](../agent/SensorReader.cs) là **toàn bộ** mặt tiếp xúc với máy, dài 67 dòng, và bình luận ở đầu tệp đã nói rõ *"HARDWARE SENSORS ONLY — it never reads files or user data"*. Đây là thứ có thể đưa cho IT đọc trực tiếp.

---

## 6. Quyền Administrator

Agent cần Administrator vì LibreHardwareMonitor nạp driver mức nhân để đọc nhiệt độ CPU ([`SensorReader.cs:16`](../agent/SensorReader.cs), [`app.manifest`](../agent/app.manifest)).

### Giảm nhẹ

1. **Tách tiến trình theo quyền.** Chỉ phần đọc cảm biến cần Administrator. Phần chạy LLM, phần nói chuyện mạng thì không.

```
NodeAgent.exe            (quyền người dùng thường)
   ├─ vòng job, HTTP, runtime LLM
   └─ SensorService.exe  (Administrator) — CHỈ đọc cảm biến, trả qua IPC cục bộ
```

Giảm đáng kể bề mặt tấn công: nếu phần xử lý mạng bị khai thác, kẻ tấn công không có quyền quản trị.

2. **Chế độ không cần quyền quản trị.** Cho phép chạy mà không đọc được nhiệt độ:

| | Có Administrator | Không có |
|---|---|---|
| Nhiệt độ CPU | ✅ | ❌ |
| Mức sử dụng CPU | ✅ | ✅ |
| Chạy suy luận LLM | ✅ | ✅ |
| Tham gia điều phối | Đầy đủ | Chỉ theo mức sử dụng |

Máy không có quyền quản trị vẫn đóng góp được sức tính toán, chỉ là không tham gia phần thông minh về nhiệt. Tốt hơn nhiều so với không cài được. Node ở chế độ này được đánh dấu rõ trên dashboard và **không được tính vào ESG Tầng 1**.

---

## 7. Nhật ký kiểm toán

```sql
CREATE TABLE room_audit (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  actor TEXT,          -- tên node hoặc 'admin' hoặc 'anonymous'
  action TEXT,         -- join | join_failed | leave | kick | settings_changed
                       -- | tunnel_enabled | tunnel_disabled | token_revoked
  source_ip TEXT,
  detail TEXT          -- JSON, KHÔNG BAO GIỜ chứa mật khẩu hay nội dung prompt
);
```

### Ghi gì

| Sự kiện | Ghi |
|---|---|
| Vào phòng thành công | node, IP, năng lực máy |
| **Vào phòng thất bại** | IP, lý do (sai mã / sai mật khẩu / phòng đầy) |
| Đuổi worker | ai đuổi, ai bị đuổi |
| Đổi ngưỡng | giá trị cũ, giá trị mới, ai đổi |
| Bật/tắt tunnel | ai, URL |
| Vượt giới hạn tần suất | IP, endpoint, số lần |

### Không ghi gì

- Mật khẩu, kể cả một phần, kể cả đã băm
- Token, kể cả một phần
- Nội dung prompt hoặc câu trả lời
- Bất kỳ thứ gì từ tệp của người dùng

### Cảnh báo tự động

| Điều kiện | Hành động |
|---|---|
| >10 lần `join_failed` từ một IP trong 5 phút | Cảnh báo trên dashboard + chặn IP 15 phút |
| `join_failed` từ >5 IP khác nhau trong 1 giờ | Cảnh báo: có thể đang bị quét |
| Node gửi telemetry mà không nằm trong danh sách phòng | Cảnh báo: có thể có token rò rỉ |

---

## 8. Danh sách kiểm tra trước khi ship

Bản đầy đủ dùng khi review: [`.agent/checklists/security.md`](../.agent/checklists/security.md).

### Chặn ship nếu chưa xong

- [ ] Mọi endpoint trừ `/join` đều yêu cầu token
- [ ] Danh tính node lấy từ token, **không** từ query hay body
- [ ] Mật khẩu băm bằng Argon2id hoặc PBKDF2 ≥600k vòng
- [ ] So sánh mật khẩu bằng hàm thời gian hằng
- [ ] Giới hạn tần suất `/join` hoạt động và đã có test
- [ ] Token thu hồi được; "kick worker" thực sự chặn được truy cập
- [ ] Tách quyền `worker` / `admin`
- [ ] **Không** bật được tunnel khi chưa đặt mật khẩu
- [ ] Mọi tệp tải về đều kiểm SHA256 **trước khi chạy**
- [ ] Worker không ghi log nội dung prompt
- [ ] Log của runtime LLM đã tắt
- [ ] Nhật ký kiểm toán ghi cả lần vào phòng thất bại
- [ ] Không có mật khẩu/token nào xuất hiện trong bất kỳ nhật ký nào
- [ ] Tài liệu whitelist cho IT đã viết xong

### Nên có

- [ ] Đã tách `SensorService.exe` theo quyền
- [ ] Chế độ chạy không cần quyền quản trị
- [ ] Tunnel tự tắt sau thời gian không hoạt động
- [ ] Chỉ số 401 hiển thị trên dashboard
- [ ] Thông báo quyền riêng tư hiện lần đầu mở ô chat

### Ghi nhận là nợ kỹ thuật (không chặn ship)

- [ ] TLS cho chặng host → worker trên LAN
- [ ] Ký số tệp thực thi
- [ ] Nhật ký kiểm toán ký chống sửa
