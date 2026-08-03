# 00 — Tổng quan kỹ thuật (tài liệu chủ)

> **Nền tảng Điều phối Nhiệt + LLM Phân tán (Chủ–Phụ)**
> Tài liệu này là điểm vào duy nhất. Đọc riêng nó phải hiểu được toàn cảnh; mọi chi tiết nằm ở các tài liệu vệ tinh được liên kết bên dưới.

| | |
|---|---|
| **Trạng thái** | Bản đặc tả — chưa hiện thực |
| **Cơ sở** | `Thermal-PoC` (2 node, burn job, đang chạy được) |
| **Mục tiêu** | Bán sản phẩm: chưa ra thị trường nhưng **dùng thật được** trong nội bộ |
| **Nền tảng** | Windows 10/11 |
| **Quy mô** | Tới 10 máy |

---

## Mục lục toàn bộ tài liệu

| # | Tài liệu | Trả lời câu hỏi |
|---|---|---|
| **00** | **Tổng quan kỹ thuật** *(bạn đang ở đây)* | Hệ thống này là gì, gồm những gì, đọc gì tiếp |
| 01 | [Đánh giá thiết kế hiện tại](01-danh-gia-thiet-ke-hien-tai.md) | Thiết kế ban đầu sai ở đâu, đúng ở đâu, tại sao |
| 02 | [Kiến trúc hệ thống](02-kien-truc-he-thong.md) | Có những tiến trình nào, dữ liệu chảy thế nào |
| 03 | [Hợp đồng API](03-hop-dong-api.md) | Endpoint nào, tham số gì, lỗi ra sao |
| 04 | [Đặc tả Scheduler](04-dac-ta-scheduler.md) | Job được gán cho máy nào, theo công thức nào |
| 05 | [Dự báo nhiệt](05-du-bao-nhiet.md) | Mô hình học gì, huấn luyện ra sao, sai số bao nhiêu |
| 06 | [Bảo mật và quyền riêng tư](06-bao-mat-va-quyen-rieng-tu.md) | Ai vào được, dữ liệu đi đâu, rủi ro gì |
| 07 | [ESG 3 tầng](07-esg-3-tang.md) | Con số tiết kiệm tính thế nào, bảo vệ được đến đâu |
| 08 | [Đo công suất](08-do-cong-suat.md) | Lấy số watt từ đâu, làm gì khi máy không báo |
| 09 | [So sánh LLM runtime](09-so-sanh-llm-runtime.md) | Chạy mô hình bằng gì, chọn mô hình nào |
| 10 | [Phòng, tunnel, triển khai](10-phong-tunnel-trien-khai.md) | Vào phòng kiểu gì, cài đặt ra sao |
| 11 | [Chiến lược kiểm thử](11-chien-luoc-kiem-thu.md) | Test cái gì, giả lập 10 node bằng cách nào |
| 12 | [Lộ trình và milestone](12-lo-trinh-va-milestone.md) | Làm theo thứ tự nào, xong là thế nào |
| 13 | [Vận hành và sự cố](13-van-hanh-va-su-co.md) | Hỏng thì xem ở đâu, sửa thế nào |
| — | [ADR](adr/) | Các quyết định kiến trúc đã khóa và lý do |
| — | [`AGENTS.md`](../AGENTS.md) | Quy tắc cho AI coding agent làm việc trên repo này |

**Đường đọc gợi ý:**

- *Quản lý / thẩm định:* 00 → 01 (phần "Kết luận ngắn") → 07 → 12
- *Dev bắt tay code:* 00 → 02 → 03 → 04 → 12
- *Người triển khai / IT:* 00 → 10 → 06 → 13
- *Người làm phần ESG:* 07 → 08 → chạy script `scripts/measure_power/`

---

## 1. Hệ thống này làm gì

Một ứng dụng Windows duy nhất, hai chế độ: **mở phòng (Host)** hoặc **vào phòng (Worker)**.

Khi chạy, nó đồng thời:

1. **Thu thập** nhiệt độ CPU/GPU, mức sử dụng và công suất thật từ cảm biến phần cứng
2. **Dự báo** máy nào sắp vượt ngưỡng nhiệt trong 3 phút tới
3. **Chia tải chat LLM** (mô hình ~0,5B tham số, chạy trên CPU) giữa tối đa 10 máy
4. **Chọn máy** theo mức an toàn nhiệt còn lại, mức rảnh, mức tiêu thụ điện và năng lực phần cứng
5. **Báo cáo** năng lượng, chi phí và CO₂ theo ba tầng độ tin cậy khác nhau

Điểm khác biệt so với PoC hiện tại: **tải là công việc thật (suy luận LLM), không phải vòng lặp đốt CPU giả**. Nhờ vậy mọi con số ESG có một mẫu số có nghĩa — số token sinh ra.

### Không làm ở giai đoạn này

- Cắt lớp mô hình chạy xuyên máy (tensor/pipeline parallelism)
- Bắt buộc Docker với người dùng cuối
- SaaS đa khách hàng đầy đủ
- Sàn giao dịch carbon thật
- Hỗ trợ đa hệ điều hành

---

## 2. Kiến trúc một trang

```
┌──────────────────── MÁY CHỦ — Host ────────────────────────────────┐
│                                                                     │
│  Room Service        xác thực mã phòng + mật khẩu, cấp token        │
│  Telemetry Store     SQLite: telemetry + nhật ký sự kiện ESG        │
│  Forecast Loop       dự báo ΔT mỗi 5s → ghi vào cache               │
│  Scheduler           chấm điểm node → giữ chỗ job cho node thắng    │
│  Chat Queue          hàng đợi yêu cầu chat + theo dõi inflight      │
│  LLM Runtime         host cũng có thể tự suy luận (phương án P2)    │
│  ESG Engine          3 tầng: ĐO / SUY RA / NGOẠI SUY                │
│  Dashboard + WS      lưới node, luồng việc, ESG, thời tiết, chat    │
│  Tunnel Helper       tùy chọn — chỉ khi worker ở mạng khác          │
└───────────────────────────┬─────────────────────────────────────────┘
                            │  HTTPS — kết nối luôn do worker khởi tạo
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Worker 1            Worker 2       …    Worker N  (tổng ≤ 10 kể cả host)
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │ Sensor   │        │ Sensor   │        │ Sensor   │  đọc cảm biến, 2s/lần
   │ Job loop │        │ Job loop │        │ Job loop │  lấy job, suy luận, trả kết quả
   │ LLM      │        │ LLM      │        │ LLM      │  llama-server / ONNX (xem 09)
   └──────────┘        └──────────┘        └──────────┘
```

**Bất biến số một:** worker **không bao giờ** lắng nghe cổng. Mọi kết nối do worker khởi tạo ra ngoài. Chỉ máy Host cần mở tường lửa. Tính chất này được kế thừa nguyên vẹn từ PoC và **mọi thay đổi sau này phải bảo toàn nó** — xem [01 §G1](01-danh-gia-thiet-ke-hien-tai.md#g1--worker-chỉ-outbound).

Chi tiết đầy đủ: [`02-kien-truc-he-thong.md`](02-kien-truc-he-thong.md).

---

## 3. Bảng quyết định đã khóa

| Hạng mục | Quyết định | Ghi ở đâu |
|---|---|---|
| Hệ điều hành | Windows, không nhấn đa nền tảng | — |
| Ứng dụng | Một bộ cài, hai chế độ Host/Worker | [02](02-kien-truc-he-thong.md) |
| Vai trò Host | Điều phối **và** có thể tự suy luận | [02](02-kien-truc-he-thong.md) |
| Quy mô | Tối đa 10 node | [04](04-dac-ta-scheduler.md) |
| Sensor + LLM | Luôn đi cùng nhau trên mỗi node | [02](02-kien-truc-he-thong.md) |
| **Gán job** | **Host chấm điểm → giữ chỗ qua trường `target`, không phải ai-đến-trước** | [ADR-001](adr/ADR-001-reservation-thay-vi-push.md) |
| **Xác thực** | **Mã phòng + mật khẩu → token; danh tính node lấy từ token** | [ADR-002](adr/ADR-002-xac-thuc-token.md) |
| **ESG** | **3 tầng ĐO / SUY RA / NGOẠI SUY, không cộng gộp** | [ADR-003](adr/ADR-003-esg-ba-tang.md) |
| **Dự báo** | **Học ΔT (mức tăng nhiệt), không học nhiệt tuyệt đối** | [ADR-004](adr/ADR-004-du-bao-delta-t.md) |
| **LLM runtime** | **✅ Đã chốt** — llama.cpp b10216 + Qwen2.5-0.5B Q4_K_M | [ADR-005](adr/ADR-005-llm-runtime.md), [09](09-so-sanh-llm-runtime.md) |
| Mạng | LAN là đường chính; tunnel là tùy chọn | [10](10-phong-tunnel-trien-khai.md) |
| Room directory | **Cắt khỏi phạm vi** — link mời là đủ | [10](10-phong-tunnel-trien-khai.md) |
| Thời tiết | Ngữ cảnh + hệ số ESG, **không** vào công thức chấm điểm | [04](04-dac-ta-scheduler.md), [07](07-esg-3-tang.md) |
| Đơn vị tiền | VNĐ là chính, USD phụ | [07](07-esg-3-tang.md) |

Bốn dòng in đậm là **thay đổi so với bản thiết kế ban đầu**. Lý do đầy đủ ở [`01-danh-gia-thiet-ke-hien-tai.md`](01-danh-gia-thiet-ke-hien-tai.md).

---

## 4. Bốn thay đổi lớn so với thiết kế ban đầu

### 4.1. Scheduler phải giữ chỗ, không thể chỉ lọc

Bản thiết kế đưa ra công thức chấm điểm nhưng cơ chế hiện tại là **worker tự đến lấy việc, ai đến trước lấy trước**. Không có bước "chọn". Nếu code thẳng theo thiết kế, hàm `score()` sẽ chạy, có test xanh, và **không ảnh hưởng gì tới việc job đi đâu**.

Sửa: host chấm điểm rồi **giữ chỗ job cho node thắng** qua trường `target` đã có sẵn trong code, kèm hạn giữ chỗ để job không kẹt khi node chết. Vẫn giữ nguyên tính chất outbound-only.

→ [01 §S1](01-danh-gia-thiet-ke-hien-tai.md#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại) · [04](04-dac-ta-scheduler.md) · [ADR-001](adr/ADR-001-reservation-thay-vi-push.md)

### 4.2. Xác thực là điều kiện tiên quyết của tunnel

Hiện tại **không endpoint nào kiểm tra gì cả**. Bật tunnel = đưa toàn bộ API ra Internet công cộng. Ba dòng `curl` đủ để bơm một node ma luôn mát, hút hết job của cả cụm và không bao giờ trả kết quả.

Sửa: `POST /join` đổi mã phòng + mật khẩu lấy token; danh tính node lấy **từ token**, không bao giờ từ query string; giới hạn tần suất thử mật khẩu; tách quyền worker và quản trị.

→ [01 §S2](01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào) · [06](06-bao-mat-va-quyen-rieng-tu.md) · [ADR-002](adr/ADR-002-xac-thuc-token.md)

### 4.3. ESG chuyển sang 3 tầng

Công thức cũ đếm *thời gian né* rồi gọi là *năng lượng tiết kiệm*. Nó bị thao túng được: hạ ngưỡng xuống 40°C thì mọi node luôn bị gắn cờ, con số "tiết kiệm" tăng tuyến tính, trong khi hệ thống **không dispatch được job nào**.

Sửa: tách bạch ba tầng, hiển thị riêng, không bao giờ cộng gộp.

| Tầng | Nội dung | Độ tin cậy |
|---|---|---|
| **1 · ĐO THẬT** | J/token thực đo, A/B với round-robin, thời gian throttle tránh được | Bảo vệ được 100% |
| **2 · SUY RA** | Điện rò theo nhiệt, điện quạt, hệ số làm mát theo site | Có giả định, ghi rõ ngay cạnh số |
| **3 · NGOẠI SUY** | Chiếu lên N node × T thời gian, định giá carbon | Dán nhãn "dự phóng" |

→ [01 §S3](01-danh-gia-thiet-ke-hien-tai.md#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được) · [07](07-esg-3-tang.md) · [ADR-003](adr/ADR-003-esg-ba-tang.md)

### 4.4. Dự báo học ΔT thay vì nhiệt tuyệt đối

Một `model.pkl` chung cho 10 máy dị chủng là sai mô hình: laptop mỏng chạy 95°C là bình thường, desktop chạy 78°C là bất thường. Model học trên hỗn hợp sẽ sai **có hệ thống** cho cả hai.

Sửa: nhãn là *mức tăng nhiệt trong 3 phút tới*, không phải nhiệt độ tuyệt đối. Cộng ngưỡng tương đối theo baseline đo được của từng máy — cũng chính là cơ chế chống thao túng chỉ số ở §4.3.

→ [01 §S4](01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình) · [05](05-du-bao-nhiet.md) · [ADR-004](adr/ADR-004-du-bao-delta-t.md)

---

## 5. Vòng lặp bốn giai đoạn, ánh xạ sang code

Giữ nguyên khung bốn giai đoạn của đề án gốc, gắn thêm phần LLM:

| Giai đoạn | Việc | File hiện có | Thay đổi |
|---|---|---|---|
| **1 · Triển khai** | Cài app, host mở phòng, worker vào phòng | [`Program.cs`](../agent/Program.cs) | Thêm luồng `/join`, tải runtime LLM |
| **2 · Thu thập** | Nhiệt CPU/GPU, mức dùng, công suất, gắn `site_id` | [`SensorReader.cs`](../agent/SensorReader.cs), [`store.py`](../server/store.py) | Thêm `site_id`, `inflight`, nhật ký sự kiện |
| **3 · Phân tích** | Dự báo ΔT trong 3 phút; thời tiết làm ngữ cảnh | [`features.py`](../server/features.py), [`forecaster.py`](../server/forecaster.py) | Đổi nhãn sang ΔT; cache kết quả |
| **4 · Điều phối** | Chấm điểm → giữ chỗ → suy luận → ghi nhận ESG | [`balancer.py`](../server/balancer.py), [`esg.py`](../server/esg.py) | Chấm điểm + giữ chỗ; ESG từ nhật ký sự kiện |

---

## 6. Bản đồ mã nguồn: từ PoC sang hệ đích

| File hiện có | Số phận | Ghi chú |
|---|---|---|
| [`server/store.py`](../server/store.py) | **Giữ, mở rộng** | Thêm bảng `esg_events`, cột `site_id` |
| [`server/features.py`](../server/features.py) | **Giữ, mở rộng** | Thêm đặc trưng; đổi nhãn sang ΔT |
| [`server/forecaster.py`](../server/forecaster.py) | **Giữ, mở rộng** | Model theo node + model gộp dự phòng |
| [`server/balancer.py`](../server/balancer.py) | **Tái cấu trúc** | Thành `ChatJobQueue` + giữ chỗ; **bỏ** `_throttled` |
| [`server/esg.py`](../server/esg.py) | **Tái cấu trúc** | 3 tầng; tính từ nhật ký sự kiện thay vì biến tích lũy |
| [`server/settings.py`](../server/settings.py) | **Giữ, mở rộng** | Thành cấu hình phòng (model, ngưỡng, trọng số, site) |
| [`server/server.py`](../server/server.py) | **Tái cấu trúc** | Tách route ra module; thêm xác thực; cache dự báo |
| [`server/calibrate.py`](../server/calibrate.py) | **Giữ** | Thêm pha đo công suất cho [08](08-do-cong-suat.md) |
| [`server/train_model.py`](../server/train_model.py) | **Sửa** | O(n²) → O(n); nhãn ΔT; model theo node |
| [`server/static/dashboard.html`](../server/static/dashboard.html) | **Viết lại giao diện** | Lưới 10 node, ô chat, ESG 3 tầng, thời tiết |
| [`agent/SensorReader.cs`](../agent/SensorReader.cs) | **Giữ nguyên** | Không đụng — đang hoạt động tốt |
| [`agent/JobRunner.cs`](../agent/JobRunner.cs) | **Giữ** | Thành chế độ demo tùy chọn |
| [`agent/Program.cs`](../agent/Program.cs) | **Mở rộng** | `/join`, token, vòng suy luận LLM |
| **Module mới** | `room.py`, `scheduler.py`, `llm.py`, `weather.py`, `power.py` | |

---

## 7. Công cụ đo công suất

Bốn script độc lập tại `scripts/measure_power/`, không phụ thuộc phần còn lại của hệ thống — dùng được ngay hôm nay để trả lời câu hỏi *"máy của tôi có đọc được công suất không?"*:

| Script | Việc |
|---|---|
| `power_probe.ps1` | Dò xem máy này lấy được số watt từ nguồn nào |
| `power_baseline.py` | Chạy tải bậc thang, ghi `(util, temp, power)` ra CSV |
| `power_model_fit.py` | Khớp đường cong công suất, xuất `power_model.json` dự phòng |
| `energy_per_token.py` | Tính J/token — hiện thực Tầng 1 của ESG |

Hướng dẫn: [`08-do-cong-suat.md`](08-do-cong-suat.md).

---

## 8. Trạng thái quyết định còn treo

| Quyết định | Ai quyết | Tài liệu hỗ trợ | Chặn việc gì |
|---|---|---|---|
| ~~LLM runtime + mô hình~~ | ✅ Đã chốt ([ADR-005](adr/ADR-005-llm-runtime.md)) | [09](09-so-sanh-llm-runtime.md) | — (M3 được mở) |
| Máy có đọc được `power_w` không | Kết quả đo | [08](08-do-cong-suat.md) + chạy `power_probe.ps1` | Tầng 1 của ESG |
| Named tunnel hay LAN-only | Chủ dự án + IT | [10](10-phong-tunnel-trien-khai.md) | Mốc M5 |
| Whitelist `llama-server.exe` / ký số | IT + ngân sách | [10 §7b](10-phong-tunnel-trien-khai.md), [ADR-005](adr/ADR-005-llm-runtime.md) | Triển khai 9 máy phụ |

---

## 9. Nguyên tắc bất di bất dịch

Năm điều dưới đây được ghi thành luật trong [`.agent/context/invariants.md`](../.agent/context/invariants.md) và [`AGENTS.md`](../AGENTS.md). Phá bất kỳ điều nào là lỗi thiết kế, không phải lựa chọn phong cách.

1. **Worker chỉ outbound.** Không lắng nghe cổng. Không cần rule tường lửa ở máy phụ.
2. **Danh tính node lấy từ token**, không bao giờ từ query string hay body.
3. **Ba tầng ESG không được cộng gộp** thành một con số.
4. **Mọi quyết định hệ trọng phải có một dòng nhật ký** giải thích được bằng tiếng người — gắn cờ, gỡ cờ, gán job, giữ chỗ hết hạn, đổi ngưỡng.
5. **Con số hiển thị phải là con số đã dùng để ra quyết định.** Không tính lại ở nơi khác rồi hiển thị bản khác.
