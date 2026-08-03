# 12 — Lộ trình và milestone

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)

Lộ trình theo **thứ tự phụ thuộc kỹ thuật**, không gắn ngày tháng. Ước lượng công tính theo một người làm toàn thời gian; nhân đôi nếu làm bán thời gian hoặc chưa quen codebase.

## Mục lục

- [Nguyên tắc sắp xếp](#1-nguyên-tắc-sắp-xếp)
- [Bảng tổng quan](#2-bảng-tổng-quan)
- [M0 — Nền móng](#m0--nền-móng)
- [M1 — Phòng và xác thực](#m1--phòng-và-xác-thực)
- [M2 — Scheduler thật](#m2--scheduler-thật)
- [M3 — LLM và chat](#m3--llm-và-chat)
- [M4 — ESG ba tầng](#m4--esg-ba-tầng)
- [M5 — Thời tiết, tunnel, đóng gói](#m5--thời-tiết-tunnel-đóng-gói)
- [M6 — Hoàn thiện](#m6--hoàn-thiện)
- [Tạm cho demo với vĩnh viễn](#3-tạm-cho-demo-với-vĩnh-viễn)
- [Rủi ro lộ trình](#4-rủi-ro-lộ-trình)

---

## 1. Nguyên tắc sắp xếp

| # | Nguyên tắc | Hệ quả |
|---|---|---|
| 1 | **Xác thực trước, tính năng sau** | Thêm xác thực vào một hệ thống đã chạy khó hơn nhiều so với xây từ đầu. M1 đứng trước mọi thứ |
| 2 | **Scheduler trước LLM** | Điều phối phải đúng trước khi có tải thật để điều phối. Kiểm bằng node giả rẻ hơn kiểm bằng suy luận thật |
| 3 | **Đo trước khi tuyên bố** | ESG (M4) đứng sau LLM (M3), vì J/token cần token thật |
| 4 | **Mỗi mốc kết thúc bằng thứ chạy được** | Không có mốc nào chỉ là hạ tầng thuần túy |
| 5 | **Quyết định tạm phải được đánh dấu là tạm** | Xem §3 |

---

## 2. Bảng tổng quan

| Mốc | Nội dung | Công | Kết quả demo được |
|---|---|---|---|
| **M0** | Nền móng: cache dự báo, băng trễ, dọn nợ | 3–5 ngày | Dashboard hết hiển thị số mâu thuẫn |
| **M1** | Phòng, mật khẩu, token, phân quyền | 5–8 ngày | Vào phòng có xác thực; nhiều node |
| **M2** | Scheduler chấm điểm + giữ chỗ | 5–8 ngày | Job đi đúng máy tốt nhất, có lý do ghi log |
| **M3** | Runtime LLM, chat, luồng job | 8–12 ngày | **Chat thật chạy phân tán** |
| **M4** | ESG ba tầng, nhật ký sự kiện, A/B | 6–10 ngày | Báo cáo chống chất vấn được |
| **M5** | Thời tiết, tunnel, bộ cài | 5–8 ngày | Cài trên máy sạch, chạy khác mạng |
| **M6** | Giao diện, tài liệu, hoàn thiện | 5–8 ngày | Sản phẩm dùng được |
| | **Tổng** | **37–59 ngày** | |

Khoảng 8–12 tuần cho một người. **Quyết định runtime LLM đã chốt** ([ADR-005](adr/ADR-005-llm-runtime.md)) — M3 được phép bắt đầu; còn rủi ro IT whitelist (chưa hỏi).

---

## M0 — Nền móng

**Mục tiêu:** dọn những vấn đề khiến mọi thứ sau này khó hơn, và làm cho dashboard ngừng nói dối.

### Việc

| # | Việc | Sửa lỗi | Công |
|---|---|---|---|
| 1 | `ForecastCache` — dự báo tính một lần, đọc nhiều nơi | [M6](01-danh-gia-thiet-ke-hien-tai.md#m6--dự-báo-được-tính-hai-lần-ở-hai-nơi-và-có-thể-lệch-nhau) | 1 ngày |
| 2 | Băng trễ + thời gian lưu trú tối thiểu | [M7](01-danh-gia-thiet-ke-hien-tai.md#m7--không-có-trễ-trong-quyết-định-gắn-cờ--node-dao-động-quanh-ngưỡng) | 0,5 ngày |
| 3 | Bộ sinh tải demo về cờ opt-in | [M9](01-danh-gia-thiet-ke-hien-tai.md#m9--bộ-sinh-tải-demo-luôn-bật) | 0,5 ngày |
| 4 | Máy trạng thái node tường minh | [M13](01-danh-gia-thiet-ke-hien-tai.md#m13--trạng-thái-khởi-động-nguội-chưa-được-định-nghĩa) | 1 ngày |
| 5 | `build_dataset` O(n²) → O(n) | [M10](01-danh-gia-thiet-ke-hien-tai.md#m10--build_dataset-có-độ-phức-tạp-on) | 0,5 ngày |
| 6 | Bảng `esg_events` + `room_audit` | [S5](01-danh-gia-thiet-ke-hien-tai.md#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram) | 1 ngày |
| 7 | `PRAGMA journal_mode=WAL` | [02 §8](02-kien-truc-he-thong.md#8-lưu-trữ) | 5 phút |

### Xong khi

- [ ] Con số trên dashboard **chính là** con số đã dùng để quyết định gắn cờ
- [ ] Node dao động quanh ngưỡng không nhấp nháy trạng thái
- [ ] `python server.py` mặc định **không** bơm burn job
- [ ] Bảng sự kiện tồn tại và được ghi (dù chưa dùng để báo cáo)
- [ ] 32 test cũ vẫn xanh
- [ ] Có test cho băng trễ (ca H1–H5 ở [04 §9](04-dac-ta-scheduler.md#9-bảng-ca-kiểm-thử))

---

## M1 — Phòng và xác thực

**Mục tiêu:** không endpoint nào chạy mà không có token. Đây là mốc **chặn tunnel** — không được bật tunnel trước khi mốc này xong.

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | `room.py`: tạo phòng, băm mật khẩu, cấp/thu hồi token | 2 ngày |
| 2 | Middleware xác thực cho mọi endpoint | 1 ngày |
| 3 | **Danh tính node lấy từ token** trên toàn bộ đường code | 1 ngày |
| 4 | Giới hạn tần suất + backoff lũy thừa | 1 ngày |
| 5 | Phân quyền `worker` / `admin` | 0,5 ngày |
| 6 | `/join`, `/leave`, `/nodes/ready`, `/kick` | 1 ngày |
| 7 | Trang đăng nhập trên dashboard | 1 ngày |
| 8 | Ghi nhật ký kiểm toán | 0,5 ngày |

### Xong khi

- [ ] Toàn bộ 15 ca bảo mật S1–S15 ([11 §6](11-chien-luoc-kiem-thu.md#6-kiểm-thử-bảo-mật)) xanh
- [ ] Không tìm thấy mật khẩu hay token trong bất kỳ tệp log nào
- [ ] Kick worker thực sự chặn được truy cập
- [ ] 10 node giả vào phòng đồng thời không tranh chấp
- [ ] Node thứ 11 nhận `409 ROOM_FULL`

---

## M2 — Scheduler thật

**Mục tiêu:** công thức chấm điểm thực sự quyết định job đi đâu. Đây là mốc biến sản phẩm từ "dashboard nhiệt độ" thành "hệ điều phối".

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | `scheduler.py`: lọc → chấm điểm → giữ chỗ | 2 ngày |
| 2 | Vòng thu hồi giữ chỗ quá hạn | 0,5 ngày |
| 3 | Theo dõi `inflight` | 0,5 ngày |
| 4 | Bỏ `_throttled` và `_poll_count` ([M14](01-danh-gia-thiet-ke-hien-tai.md#m14--hai-chính-sách-điều-phối-chồng-lên-nhau)) | 0,5 ngày |
| 5 | Long-poll cho `/jobs/next` | 1 ngày |
| 6 | `idle_baseline` theo node + ngưỡng hiệu lực | 1 ngày |
| 7 | Chế độ `round_robin` cho A/B | 0,5 ngày |
| 8 | **Bộ giả lập 10 node** ([11 §4](11-chien-luoc-kiem-thu.md#4-bộ-giả-lập-10-node)) | 2 ngày |
| 9 | Ghi log quyết định có lý do đọc được | 0,5 ngày |

Việc 8 tốn 2 ngày nhưng trả lại nhiều lần trong M3–M6. Đừng cắt nó.

### Xong khi

- [ ] Toàn bộ ca F1–F7, S1–S10, R1–R6 ([04 §9](04-dac-ta-scheduler.md#9-bảng-ca-kiểm-thử)) xanh
- [ ] Ca S9: **thêm node nóng không làm đổi điểm của node cũ**
- [ ] Ca C1–C10 ([11 §4](11-chien-luoc-kiem-thu.md#ca-tích-hợp)) xanh
- [ ] Log giải thích được mọi quyết định gán mà không cần gắn debugger
- [ ] Node treo không làm kẹt job vĩnh viễn

---

## M3 — LLM và chat

**Mục tiêu:** chat thật chạy phân tán. Từ đây tải sinh nhiệt là công việc có ích, không phải vòng lặp đốt CPU giả.

> ✅ **[ADR-005](adr/ADR-005-llm-runtime.md) đã chốt** (llama.cpp b10216 + Qwen2.5-0.5B Q4_K_M). Việc 1–2 trong bảng dưới coi như xong phần quyết định; G4 = hiện thực `ILlmRunner`.

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | Benchmark runtime trên ≥2 máy thật ([09 §5](09-so-sanh-llm-runtime.md#5-đo-trước-khi-chốt)) | 2 ngày |
| 2 | Chốt ADR-005, ghim phiên bản + SHA256 thật | 0,5 ngày |
| 3 | `ILlmRunner` + hiện thực đầu tiên | 2 ngày |
| 4 | `Downloader.cs` có kiểm hash | 1 ngày |
| 5 | Hàng đợi chat + `/chat`, `/chat/{id}`, `/jobs/result` | 2 ngày |
| 6 | Ô chat trên dashboard + nhãn "chạy trên Node-X" | 1,5 ngày |
| 7 | Host tự suy luận (phương án P2) | 1 ngày |
| 8 | Đo `energy_j`, `tokens_out` phía worker | 1 ngày |
| 9 | Dự báo ΔT + model theo node ([05](05-du-bao-nhiet.md)) | 2 ngày |

### Xong khi

- [ ] Chat từ dashboard trả về câu trả lời, hiển thị máy đã chạy
- [ ] Node bị gắn cờ không nhận job chat mới
- [ ] Worker chết giữa chừng → **người dùng vẫn nhận được trả lời** (ca X2)
- [ ] Kết quả job mang `tokens_out` và `energy_j`
- [ ] Hash lệch thì từ chối chạy (ca S10)
- [ ] Leave-one-node-out MAE được báo cáo, không giấu
- [ ] **Ca M10** ([11 §8](11-chien-luoc-kiem-thu.md#8-kiểm-thử-thủ-công)): người dùng máy phụ không thấy máy chậm rõ rệt

---

## M4 — ESG ba tầng

**Mục tiêu:** con số ESG chống chất vấn được. Đây là mốc quyết định giá trị thương mại của sản phẩm.

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | Tái cấu trúc `esg.py` sang ba tầng | 2 ngày |
| 2 | Báo cáo tính từ nhật ký sự kiện (hàm thuần) | 1,5 ngày |
| 3 | Tầng 1: J/token, throttle tránh được | 1 ngày |
| 4 | Chế độ `--ab-benchmark` + bộ prompt cố định | 1,5 ngày |
| 5 | Tầng 2: dòng rò, quạt, hệ số làm mát | 1,5 ngày |
| 6 | Tầng 3: ngoại suy + nhãn dự phóng | 1 ngày |
| 7 | Sàn ngưỡng chống thao túng | 0,5 ngày |
| 8 | Panel ESG ba khối trên dashboard | 1,5 ngày |
| 9 | Xuất CSV nhật ký sự kiện | 0,5 ngày |
| 10 | Tích hợp `power_model.json` làm đường dự phòng | 1 ngày |

### Xong khi

- [ ] Toàn bộ ca E1–E14 ([11 §7](11-chien-luoc-kiem-thu.md#7-kiểm-thử-esg)) xanh
- [ ] **Ca E13: gắn cờ mọi node cả ngày không làm J/token đẹp lên**
- [ ] Ca X5: host khởi động lại, ESG tính lại được
- [ ] Ba tầng là ba đối tượng JSON riêng
- [ ] Đã chạy A/B thật ít nhất một lần, có số
- [ ] Trả lời được cả 6 câu phản biện ở [07 §10](07-esg-3-tang.md#10-câu-hỏi-phản-biện-và-câu-trả-lời) bằng dữ liệu

---

## M5 — Thời tiết, tunnel, đóng gói

**Mục tiêu:** cài được lên máy sạch, chạy được khác mạng.

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | `weather.py` + cache + đường dự phòng | 1 ngày |
| 2 | Panel thời tiết, phân biệt rõ nhiệt môi trường / nhiệt CPU | 0,5 ngày |
| 3 | Hệ số làm mát theo site vào ESG Tầng 2 | 0,5 ngày |
| 4 | Trợ lý tunnel + tự nối lại + cảnh báo | 1,5 ngày |
| 5 | Chặn bật tunnel khi chưa có mật khẩu | 0,5 ngày |
| 6 | Bộ cài host và worker | 2 ngày |
| 7 | Trình hướng dẫn lần đầu, có bước kiểm tra | 1,5 ngày |
| 8 | Tài liệu whitelist cho IT | 0,5 ngày |

### Xong khi

- [ ] Cài trên máy sạch không cần thao tác thủ công (ca M7)
- [ ] Host + worker qua tunnel hoạt động (ca M2)
- [ ] Tunnel đứt: worker LAN không ảnh hưởng (ca X6)
- [ ] Không bật được tunnel khi chưa đặt mật khẩu (ca S9)
- [ ] Gỡ cài sạch, hỏi trước khi xóa dữ liệu ESG (ca M8)
- [ ] Tài liệu IT đã gửi và nhận phản hồi

---

## M6 — Hoàn thiện

### Việc

| # | Việc | Công |
|---|---|---|
| 1 | Lưới 10 node, màu theo nhiệt | 1,5 ngày |
| 2 | Hiệu ứng luồng việc Đỏ→Xanh | 1 ngày |
| 3 | Hiển thị lý do gắn cờ trên thẻ node | 0,5 ngày |
| 4 | Xuất báo cáo có định dạng | 1 ngày |
| 5 | Cập nhật `README.md`, `HOW_IT_WORKS.md` | 1 ngày |
| 6 | Chạy toàn bộ kiểm thử thủ công M1–M10 | 1 ngày |
| 7 | Diễn tập demo ≥2 lần | 0,5 ngày |
| 8 | Chạy `ship-gate` | 0,5 ngày |

### Xong khi

- [ ] Chạy 4 giờ liên tục không rò bộ nhớ (ca M9)
- [ ] Kịch bản demo 10 phút chạy trơn hai lần liên tiếp
- [ ] Toàn bộ [`.agent/checklists/ship-gate.md`](../.agent/checklists/ship-gate.md) đã tick
- [ ] Có bản ghi màn hình dự phòng

---

## 3. Tạm cho demo với vĩnh viễn

Ghi rõ để sau này không ai nhầm một quyết định tạm thời thành một quyết định kiến trúc.

### Vĩnh viễn — đừng đổi mà không viết ADR mới

| Quyết định | Ở đâu |
|---|---|
| Worker chỉ outbound | [02 §1](02-kien-truc-he-thong.md#1-nguyên-tắc-kiến-trúc) |
| Danh tính node từ token | [ADR-002](adr/ADR-002-xac-thuc-token.md) |
| Giữ chỗ qua `target` + hạn giữ chỗ | [ADR-001](adr/ADR-001-reservation-thay-vi-push.md) |
| ESG ba tầng, không cộng gộp | [ADR-003](adr/ADR-003-esg-ba-tang.md) |
| Dự báo ΔT | [ADR-004](adr/ADR-004-du-bao-delta-t.md) |
| Nhật ký sự kiện là nguồn gốc số liệu | [07 §6](07-esg-3-tang.md#6-nhật-ký-sự-kiện--nguồn-gốc-của-mọi-con-số) |
| Không có Room Directory | [10 §3](10-phong-tunnel-trien-khai.md#3-vì-sao-cắt-room-directory) |
| Chuẩn hóa điểm theo khoảng tuyệt đối | [04 §4.2](04-dac-ta-scheduler.md#42-headroom--khoảng-an-toàn-nhiệt-còn-lại) |

### Tạm — dự kiến sẽ đổi

| Quyết định tạm | Vì sao tạm | Đổi thành gì |
|---|---|---|
| Long-poll cho job | Đủ dùng ở 10 node | WebSocket bền khi cần độ trễ thấp hơn |
| Một model gộp cho mọi node | ΔT có thể đã đủ | Model theo node nếu leave-one-node-out cho thấy cần |
| `max_concurrent = 1` | An toàn khi chưa có số đo | Tăng theo kết quả benchmark M3 |
| SQLite | Thừa sức cho 10 node | Chỉ đổi khi vượt xa quy mô này |
| HTTP thuần host→worker trên LAN | Chấp nhận được trong LAN tin cậy | TLS với CA tự sinh |
| Hệ số ESG Tầng 2 mặc định | Chưa hiệu chuẩn | Thay bằng số đo thật khi có |
| Thời tiết chỉ ở Tầng 2 | Cụm một site | Bật `w_weather` khi thực sự đa site |
| Tệp thực thi chưa ký số | Chi phí | Ký số khi triển khai diện rộng |

**Quy tắc:** mọi quyết định tạm phải có comment trong code trỏ tới dòng tương ứng của bảng này. Sáu tháng sau, không ai nhớ cái nào là tạm.

---

## 4. Rủi ro lộ trình

| Rủi ro | Khả năng | Ảnh hưởng | Giảm nhẹ |
|---|---|---|---|
| **IT chặn runtime LLM** | Trung bình | Chặn M3 | **Hỏi IT trước M3**, không phải trong M3. Chuẩn bị sẵn phương án ONNX |
| Mô hình 0,5B trả lời tiếng Việt kém | Trung bình | Đổi mô hình → đổi ngân sách RAM và thông lượng | Kiểm chất lượng tiếng Việt ngay ở bước benchmark M3 |
| Máy không đọc được công suất | **Cao** | ESG Tầng 1 rỗng | Chạy `power_probe.ps1` **ngay bây giờ**, không đợi M4 |
| A/B cho kết quả âm | Trung bình | Câu chuyện thương mại yếu đi | Đã có kịch bản trả lời ([07 §3.2](07-esg-3-tang.md#32-so-sánh-ab--con-số-bán-hàng)). Trung thực vẫn thắng |
| Đồng nghiệp gỡ phần mềm vì máy chậm | Trung bình | Không có worker để điều phối | Ca M10 là cổng chặn ở M3, không phải việc để sau |
| Không đủ máy thật để thử | Trung bình | Chỉ kiểm được bằng giả lập | Bộ giả lập 10 node ở M2 chính là để phòng việc này |
| Phạm vi phình ra | **Cao** | Trượt lịch | Bảng "vĩnh viễn / tạm" ở §3 là ranh giới. Mọi thứ ngoài đó là mốc M7 |

**Việc nên làm ngay hôm nay, trước cả M0:**

```bash
powershell -ExecutionPolicy Bypass -File scripts\measure_power\power_probe.ps1
```

Chạy trên mọi máy dự kiến tham gia. Kết quả quyết định ESG Tầng 1 có tồn tại hay không — và biết sớm thì còn kịp mua đồng hồ điện.
