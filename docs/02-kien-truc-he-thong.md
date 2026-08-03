# 02 — Kiến trúc hệ thống

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Đọc trước: [`01-danh-gia-thiet-ke-hien-tai.md`](01-danh-gia-thiet-ke-hien-tai.md)
> Đọc tiếp: [`03-hop-dong-api.md`](03-hop-dong-api.md), [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md)

## Mục lục

- [Nguyên tắc kiến trúc](#1-nguyên-tắc-kiến-trúc)
- [Bản đồ tiến trình](#2-bản-đồ-tiến-trình)
- [Module trên Host](#3-module-trên-host)
- [Module trên Worker](#4-module-trên-worker)
- [Luồng dữ liệu](#5-luồng-dữ-liệu)
- [Máy trạng thái của node](#6-máy-trạng-thái-của-node)
- [Cache dự báo](#7-cache-dự-báo--nguồn-sự-thật-duy-nhất)
- [Lưu trữ](#8-lưu-trữ)
- [Chế độ chạy](#9-chế-độ-chạy)
- [Xử lý lỗi](#10-xử-lý-lỗi)
- [Ngân sách hiệu năng](#11-ngân-sách-hiệu-năng-ở-10-node)

---

## 1. Nguyên tắc kiến trúc

| # | Nguyên tắc | Hệ quả thực tế |
|---|---|---|
| 1 | **Worker chỉ outbound** | Không cần mở tường lửa ở máy phụ; laptop di chuyển giữa các mạng vẫn chạy |
| 2 | **Host là nguồn sự thật duy nhất** | Mọi quyền, cấu hình, danh sách worker, số liệu ESG nằm ở host. Không có dịch vụ đám mây bắt buộc |
| 3 | **Một con số, một nơi tính** | Dự báo tính đúng một lần ở vòng forecast, ghi vào cache; mọi nơi khác đọc cache |
| 4 | **Nhật ký sự kiện là nguồn gốc, không phải biến tích lũy** | Báo cáo ESG là hàm thuần tính từ sự kiện → tái lập được, kiểm toán được |
| 5 | **Suy giảm có kiểm soát** | Mất tunnel → LAN vẫn chạy. Mất worker → job chuyển máy. Chưa có model → dùng dự phòng tuyến tính có badge rõ |
| 6 | **Mọi quyết định để lại dấu vết** | Gắn cờ, gỡ cờ, gán job, giữ chỗ hết hạn, đổi ngưỡng — đều có một dòng log đọc được |

---

## 2. Bản đồ tiến trình

### Trên máy Host

```
Host.exe  (khởi động, giao diện tạo phòng)
   │
   ├─► engine (Python, FastAPI, cổng 8000, chỉ bind 127.0.0.1 + LAN IP)
   │      ├─ Room Service         xác thực, cấp/thu hồi token
   │      ├─ Ingest API           nhận telemetry
   │      ├─ Forecast Loop        5s/lần  → ghi ForecastCache
   │      ├─ Scheduler Loop       1s/lần  → chấm điểm, giữ chỗ job
   │      ├─ Reaper Loop          1s/lần  → thu hồi giữ chỗ quá hạn
   │      ├─ Weather Poll         15min/lần (tùy chọn)
   │      ├─ ESG Engine           tính từ nhật ký sự kiện
   │      └─ Dashboard + WebSocket
   │
   ├─► worker nội bộ (tùy chọn) — host cũng là một node
   │      ├─ Sensor loop
   │      └─ LLM runtime
   │
   └─► cloudflared.exe (tùy chọn) — chỉ khi có worker ở mạng khác
```

**Vì sao giữ engine bằng Python.** Toàn bộ phần dự báo (scikit-learn, numpy) và sáu module đã kiểm thử đang là Python. Viết lại sang C# để "đồng nhất ngôn ngữ" là bỏ đi 32 test đang xanh và vài tuần công, đổi lấy một lợi ích thẩm mỹ. Host là **một máy duy nhất do người triển khai kiểm soát** — cài Python ở đó là chuyện chấp nhận được (hoặc đóng gói bằng PyInstaller). Ràng buộc "không cần cài gì" chỉ áp dụng cho **worker**, nơi có tới 9 máy của người khác.

### Trên máy Worker

```
Worker.exe  (một tệp tự chứa, .NET 8 self-contained)
   │
   ├─ Join flow          nhập link mời + mật khẩu → nhận token
   ├─ Downloader         tải runtime + model nếu thiếu (kiểm tra SHA256)
   ├─ Sensor loop        2s/lần → POST /ingest
   ├─ Job loop           long-poll GET /jobs/next → suy luận → POST /jobs/result
   └─ LLM runtime        tiến trình con (xem 09-so-sanh-llm-runtime.md)
```

Worker **không cần Python**. Đây là ràng buộc cứng: mỗi phụ thuộc thêm vào worker phải nhân với 9 máy và 9 lần thuyết phục đồng nghiệp.

---

## 3. Module trên Host

| Module | File | Trạng thái | Trách nhiệm |
|---|---|---|---|
| `store.py` | [hiện có](../server/store.py) | Mở rộng | Telemetry + `esg_events` + `site_id` |
| `features.py` | [hiện có](../server/features.py) | Mở rộng | Vector đặc trưng từ cửa sổ mẫu |
| `forecaster.py` | [hiện có](../server/forecaster.py) | Mở rộng | Dự báo ΔT; model theo node + model gộp dự phòng |
| `esg.py` | [hiện có](../server/esg.py) | Tái cấu trúc | 3 tầng, tính từ nhật ký sự kiện |
| `settings.py` | [hiện có](../server/settings.py) | Mở rộng | Cấu hình phòng: model, ngưỡng, trọng số, site |
| `balancer.py` | [hiện có](../server/balancer.py) | Tái cấu trúc | Hàng đợi + giữ chỗ; **bỏ** `_throttled` |
| `server.py` | [hiện có](../server/server.py) | Tái cấu trúc | Tạo app, vòng lặp nền; route tách ra module riêng |
| `room.py` | **mới** | | Mã phòng, băm mật khẩu, cấp/thu hồi token, giới hạn tần suất |
| `scheduler.py` | **mới** | | Chấm điểm node, chọn người thắng ([04](04-dac-ta-scheduler.md)) |
| `forecast_cache.py` | **mới** | | Nguồn sự thật duy nhất cho dự báo và trạng thái node |
| `llm.py` | **mới** | | Suy luận cục bộ trên host (phương án P2) |
| `weather.py` | **mới** | | Gọi API thời tiết theo site, có cache và đường dự phòng |
| `power.py` | **mới** | | Ước lượng công suất khi cảm biến trả null ([08](08-do-cong-suat.md)) |

### Ranh giới module

```
                    ┌─────────────┐
   /ingest ────────►│   store     │◄──── esg (đọc nhật ký sự kiện)
                    └──────┬──────┘
                           │ recent()
                    ┌──────▼──────┐
                    │  features   │
                    └──────┬──────┘
                    ┌──────▼──────┐
                    │ forecaster  │
                    └──────┬──────┘
                    ┌──────▼──────────────┐
                    │  forecast_cache     │◄─── weather, power
                    │  (nguồn sự thật)    │
                    └──────┬──────────────┘
                ┌──────────┼──────────┐
                ▼          ▼          ▼
          ┌──────────┐ ┌────────┐ ┌───────────┐
          │scheduler │ │  esg   │ │ dashboard │
          └────┬─────┘ └────────┘ └───────────┘
               │ chọn node
          ┌────▼─────┐
          │ balancer │──► /jobs/next (giữ chỗ theo target)
          └──────────┘
```

Quy tắc phụ thuộc: **mũi tên chỉ đi xuống**. `scheduler` không được gọi ngược lên `store`; nó chỉ đọc `forecast_cache`. Nhờ vậy test scheduler chỉ cần dựng một cache giả, không cần cả cơ sở dữ liệu.

---

## 4. Module trên Worker

| Thành phần | File | Trạng thái | Trách nhiệm |
|---|---|---|---|
| `SensorReader.cs` | [hiện có](../agent/SensorReader.cs) | **Không đụng** | Đọc cảm biến qua LibreHardwareMonitor |
| `JobRunner.cs` | [hiện có](../agent/JobRunner.cs) | Giữ | Burn job — chỉ dùng ở chế độ demo |
| `AgentConfig.cs` | [hiện có](../agent/AgentConfig.cs) | Mở rộng | Thêm token, URL phòng, đường dẫn model |
| `Program.cs` | [hiện có](../agent/Program.cs) | Mở rộng | Thêm luồng join, long-poll, vòng suy luận |
| `RoomClient.cs` | **mới** | | `/join`, quản lý token, tự nối lại khi mất |
| `LlmRunner.cs` | **mới** | | Khởi động và giám sát tiến trình runtime LLM |
| `Downloader.cs` | **mới** | | Tải có kiểm tra SHA256, hiện tiến độ |

`SensorReader.cs` **giữ nguyên không sửa một dòng**. Nó đang hoạt động đúng, có chế độ tự kiểm tra (`--test-sensors`), và là mặt tiếp xúc duy nhất với phần cứng — càng ít đụng vào càng tốt.

---

## 5. Luồng dữ liệu

### 5.1. Vào phòng

```
Worker                                  Host
  │  POST /join {room_code, password,     │
  │              node_name, capabilities} │
  ├──────────────────────────────────────►│ kiểm tra giới hạn tần suất
  │                                       │ so khớp hash mật khẩu
  │                                       │ kiểm tra sức chứa (≤10)
  │◄──────────────────────────────────────┤ 201 {token, room_config}
  │                                       │   room_config: model_id, model_sha256,
  │                                       │   runtime_url, threshold, site_id
  │                                       │
  │  tải runtime + model nếu thiếu        │
  │  kiểm tra SHA256                      │
  │  khởi động runtime LLM                │
  │                                       │
  │  POST /nodes/ready                    │
  ├──────────────────────────────────────►│ node chuyển sang WARMING_UP
```

### 5.2. Telemetry — 2 giây một lần

```
Worker: đọc cảm biến ──► POST /ingest (Bearer token)
                              │
Host:   danh tính node LẤY TỪ TOKEN, bỏ qua mọi giá trị node trong body
                              │
                         store.insert(...)
```

### 5.3. Dự báo — 5 giây một lần

```
Host forecast loop:
  với mỗi node đang hoạt động:
      samples   = store.recent(node, 180s)
      feats     = features.build_features(samples)
      delta_t   = forecaster.predict_delta(feats)        # xem 05
      pred_max  = nhiệt_hiện_tại + delta_t
      áp dụng băng trễ  → flagged / cleared / giữ nguyên
      ghi ForecastCache[node] = {pred_max, flagged, state, reason, ts}
      nếu trạng thái đổi → ghi esg_events + một dòng log
```

### 5.4. Chat — từ lúc gõ tới lúc có câu trả lời

```
Người dùng ──► POST /chat {prompt}
                    │
Host: tạo job {id, prompt, created_at}, đưa vào hàng đợi
                    │
Scheduler loop (1s):
    ứng viên = node ở trạng thái READY, không bị gắn cờ,
               inflight < max_concurrent, đã tải xong model
    nếu rỗng → nếu host tự chạy được thì host suy luận (P2)
             → nếu không, job chờ tiếp
    ngược lại → điểm = score(node)  cho từng ứng viên   [xem 04]
                người_thắng = argmax
                job.target = người_thắng
                job.reserved_until = now + RESERVATION_TIMEOUT_S
                inflight[người_thắng] += 1
                log: "[SCHED] job abc123 -> Node-B (điểm 0.82: headroom 0.9,
                      rảnh 0.7, điện 0.8, inflight 0/1)"
                    │
Worker long-poll GET /jobs/next
    ├─ có job target=mình → nhận, suy luận
    └─ hết thời gian chờ  → 204, poll lại

Worker ──► POST /jobs/result {job_id, text, tokens_in, tokens_out,
                              duration_ms, energy_j}
                    │
Host: inflight[node] -= 1
      ghi esg_events(job_completed, detail={tokens, joules, ...})
      đẩy kết quả lên WebSocket
                    │
Người dùng thấy câu trả lời + nhãn "chạy trên Node-B"
```

### 5.5. Giữ chỗ quá hạn

```
Reaper loop (1s):
  với mỗi job có reserved_until < now:
      log: "[SCHED] job abc123 giữ chỗ hết hạn ở Node-B → trả về hàng đợi"
      inflight[Node-B] -= 1
      job.target = None
      đánh dấu Node-B là nghi ngờ (trừ điểm tạm thời)
      job quay lại hàng đợi để chấm điểm lại
```

Không có bước này, một node treo sẽ nuốt job vĩnh viễn. Đây là hệ quả trực tiếp của việc chuyển từ "ai đến trước" sang "giữ chỗ" — xem [ADR-001](adr/ADR-001-reservation-thay-vi-push.md).

---

## 6. Máy trạng thái của node

```
              ┌──────────┐
              │ JOINING  │  đã xác thực, đang tải model
              └────┬─────┘
                   │ model sẵn sàng, có mẫu telemetry đầu tiên
              ┌────▼─────────┐
              │ WARMING_UP   │  <5 mẫu hoặc <30s lịch sử
              │              │  nhận job được, nhưng điểm bị phạt
              └────┬─────────┘
                   │ đủ lịch sử để dự báo
              ┌────▼─────┐         dự báo ≥ ngưỡng
              │  READY   │──────────────────────┐
              │          │◄─────────────────────┤
              └────┬─────┘   dự báo ≤ ngưỡng−3  │
                   │          và đã đủ thời gian │
                   │              lưu trú    ┌───▼────────┐
                   │                         │ AT_RISK    │
                   │                         │ không nhận │
                   │                         │ job mới    │
                   │                         └───┬────────┘
                   │ không có mẫu >10s           │ không có mẫu >10s
              ┌────▼──────┐                      │
              │  STALE    │◄─────────────────────┘
              └────┬──────┘   (gỡ cờ kẹt — xem 01 §G2)
                   │ không có mẫu >900s
              ┌────▼──────┐
              │ INACTIVE  │  biến mất hoàn toàn khỏi hệ thống
              └───────────┘
```

**So với PoC:** `active_nodes` ([`server.py:57`](../server/server.py)) và logic gỡ cờ kẹt ([`server.py:81-90`](../server/server.py)) đã hiện thực đúng hai chuyển trạng thái `STALE` và `INACTIVE`. Tài liệu này chỉ đặt tên tường minh cho chúng và bổ sung `JOINING` / `WARMING_UP`.

**Chỉ trạng thái `READY` và `WARMING_UP` mới được chấm điểm.** Mọi trạng thái khác bị loại khỏi tập ứng viên trước khi tính điểm — không dùng thủ thuật "điểm âm vô cùng", vì nó khiến log khó đọc và test khó viết.

| Hằng số | Giá trị | Nguồn |
|---|---|---|
| `STALE_AFTER_S` | 10 | [`server.py:32`](../server/server.py) — giữ nguyên |
| `ACTIVE_WINDOW_S` | 900 | [`server.py:33`](../server/server.py) — giữ nguyên |
| `MIN_SAMPLES` | 5 | [`features.py:7`](../server/features.py) — giữ nguyên |
| `MIN_SPAN_S` | 30 | [`features.py:8`](../server/features.py) — giữ nguyên |
| `HYSTERESIS_C` | 3,0 | **mới** — [04](04-dac-ta-scheduler.md) |
| `MIN_DWELL_S` | 30 | **mới** — [04](04-dac-ta-scheduler.md) |
| `RESERVATION_TIMEOUT_S` | 20 | **mới** — [04](04-dac-ta-scheduler.md) |

---

## 7. Cache dự báo — nguồn sự thật duy nhất

Sửa lỗi [M6](01-danh-gia-thiet-ke-hien-tai.md#m6--dự-báo-được-tính-hai-lần-ở-hai-nơi-và-có-thể-lệch-nhau).

```python
@dataclass
class NodeForecast:
    node: str
    state: str                  # READY | AT_RISK | WARMING_UP | STALE
    predicted_max_c: float | None
    delta_t_c: float | None
    current_temp_c: float | None
    headroom: float | None      # 0..1 — xem 04
    cpu_util: float | None
    power_w: float | None
    power_source: str           # 'sensor' | 'model' | 'none' — xem 08
    inflight: int
    flagged_since: float | None
    computed_at: float
    reason: str                 # chuỗi đọc được, hiện lên dashboard
```

**Ai ghi:** chỉ vòng forecast (5s/lần) và scheduler (cập nhật `inflight`).
**Ai đọc:** scheduler, dashboard/WebSocket, `/api/state`, ESG.

Ba lợi ích, đều là sửa lỗi thật:

1. Con số trên dashboard **chính là** con số đã dùng để ra quyết định — không còn cảnh badge `AT RISK` nằm cạnh dự báo 73,8°C với ngưỡng 75°C.
2. Ở 10 node, giảm từ ~50 lần dự báo/10 giây xuống còn 20 — bỏ được toàn bộ phần tính lại chỉ để vẽ giao diện.
3. Trường `reason` mang lời giải thích tới tận màn hình: *"dự báo 78,2°C ≥ ngưỡng 75°C"* thay vì để người xem tự đoán.

---

## 8. Lưu trữ

Một tệp SQLite duy nhất, `telemetry.db`, ba bảng.

```sql
-- Giữ nguyên từ PoC, thêm site_id
CREATE TABLE telemetry (
  node TEXT NOT NULL, ts REAL NOT NULL,
  cpu_temp REAL, gpu_temp REAL, cpu_util REAL, power_w REAL,
  site_id TEXT
);
CREATE INDEX idx_node_ts ON telemetry(node, ts);

-- Mới: nguồn gốc của mọi con số ESG  (sửa lỗi S5)
CREATE TABLE esg_events (
  id INTEGER PRIMARY KEY,
  node TEXT NOT NULL,
  event TEXT NOT NULL,        -- flagged | cleared | threshold_changed | job_completed
  ts REAL NOT NULL,
  threshold_at_time REAL,
  predicted_max REAL,
  detail TEXT                 -- JSON: tokens_out, energy_j, duration_ms, scheduler_mode
);
CREATE INDEX idx_esg_ts ON esg_events(ts);

-- Mới: đường kiểm toán cho phòng
CREATE TABLE room_audit (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  actor TEXT,                 -- node hoặc 'admin'
  action TEXT,                -- join | join_failed | kick | settings_changed
  detail TEXT
);
```

**Giữ lại dữ liệu.** `telemetry` tăng khoảng 5 dòng/giây ở 10 node ≈ 430 nghìn dòng/ngày ≈ 30 MB/ngày. Cần một tác vụ dọn: giữ nguyên độ phân giải đầy đủ trong 7 ngày, sau đó gộp xuống trung bình mỗi phút. **`esg_events` không bao giờ xóa** — đó là sổ cái.

**Hiệu năng ghi.** [`store.py:26`](../server/store.py) gọi `commit()` sau mỗi lần chèn. Ở 5 dòng/giây thì không sao, nhưng nên bật `PRAGMA journal_mode=WAL` để đọc không chặn ghi khi dashboard đang truy vấn.

---

## 9. Chế độ chạy

| Chế độ | Lệnh | Việc |
|---|---|---|
| Bình thường | `Host.exe` | Phòng + chat + dự báo + ESG |
| Hiệu chuẩn | `Host.exe --calibrate` | Chu kỳ tải để thu dữ liệu huấn luyện ([05](05-du-bao-nhiet.md)) |
| Đo công suất | `Host.exe --power-baseline` | Tải bậc thang để lập đường cong công suất ([08](08-do-cong-suat.md)) |
| So sánh A/B | `Host.exe --ab-benchmark` | Chạy bộ prompt cố định với hai scheduler ([07](07-esg-3-tang.md)) |
| Tải demo | `Host.exe --demo-load` | **Opt-in.** Bật lại bộ sinh burn job |

Dòng cuối sửa lỗi [M9](01-danh-gia-thiet-ke-hien-tai.md#m9--bộ-sinh-tải-demo-luôn-bật): [`server.py:216`](../server/server.py) hiện chạy vô điều kiện. Trong hệ mới nó phải tắt mặc định, nếu không sẽ làm hỏng mọi phép đo J/token.

---

## 10. Xử lý lỗi

| Tình huống | Hành vi | Nơi hiện thực |
|---|---|---|
| Worker mất mạng | `STALE` sau 10s → loại khỏi chấm điểm; giữ chỗ hết hạn → job đi máy khác | reaper loop |
| Worker chết khi đang bị gắn cờ | Gỡ cờ kẹt để ESG không cộng dồn vô hạn | đã có: [`server.py:81-90`](../server/server.py) |
| Suy luận quá giờ | Thử node tốt thứ hai; hết ứng viên → host tự chạy; hết nữa → báo lỗi kèm lý do | scheduler |
| Chưa có `model.pkl` | Dự phòng tuyến tính + badge rõ trên dashboard | đã có: [`forecaster.py:22`](../server/forecaster.py) |
| Model tải chưa xong | Node ở `JOINING`, không nằm trong tập ứng viên | máy trạng thái |
| Tunnel chết | Phòng LAN vẫn chạy; dashboard báo "mất tunnel — dùng LAN hoặc bật lại" | tunnel helper |
| Sai mật khẩu | `401`, không tiết lộ danh sách worker, tăng bộ đếm giới hạn tần suất | `room.py` |
| Vượt 10 worker | `409 ROOM_FULL` kèm sức chứa hiện tại | `room.py` |
| Cảm biến trả `null` | Dùng `power_model.json`; đánh dấu `power_source='model'` | `power.py`, [08](08-do-cong-suat.md) |
| API thời tiết hỏng | Dùng giá trị cache gần nhất; quá 6 giờ thì bỏ qua thời tiết | `weather.py` |
| Không có ứng viên nào | Job chờ trong hàng đợi, dashboard hiện "đang chờ máy rảnh" — **không** dispatch cho node bị gắn cờ | scheduler |

---

## 11. Ngân sách hiệu năng ở 10 node

| Đại lượng | Tần suất | Tải |
|---|---|---|
| Ghi telemetry | 10 node × 0,5 Hz | 5 dòng/giây |
| Vòng dự báo | 0,2 Hz | 10 truy vấn cửa sổ + 10 lần suy luận RF mỗi 5 giây |
| Vòng scheduler | 1 Hz | Chấm điểm ≤10 node — chỉ vài phép tính số học trên cache |
| Đẩy WebSocket | 0,5 Hz | Đọc cache, không tính lại |
| Suy luận LLM | Theo nhu cầu | 1 job đồng thời mỗi node |

Điểm nghẽn không nằm ở host mà ở **thông lượng suy luận trên worker**. Với mô hình 0,5B lượng tử hóa Q4 chạy CPU, ước tính 20–60 token/giây tùy máy; một câu trả lời 200 token mất 3–10 giây. Host nhàn rỗi gần như hoàn toàn — đó là lý do host cũng nên chạy một worker nội bộ (phương án P2).

Con số cụ thể sau khi chốt runtime: [`09-so-sanh-llm-runtime.md`](09-so-sanh-llm-runtime.md).
