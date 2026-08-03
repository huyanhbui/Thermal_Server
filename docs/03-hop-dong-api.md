# 03 — Hợp đồng API

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Liên quan: [`02-kien-truc-he-thong.md`](02-kien-truc-he-thong.md), [`06-bao-mat-va-quyen-rieng-tu.md`](06-bao-mat-va-quyen-rieng-tu.md)

Đây là hợp đồng ràng buộc giữa Host và Worker, và giữa Host và giao diện. Thay đổi phá vỡ tương thích phải tăng phiên bản (§9).

## Mục lục

- [Quy ước chung](#1-quy-ước-chung)
- [Ma trận xác thực](#2-ma-trận-xác-thực)
- [Nhóm Phòng](#3-nhóm-phòng)
- [Nhóm Telemetry](#4-nhóm-telemetry)
- [Nhóm Job](#5-nhóm-job)
- [Nhóm Chat](#6-nhóm-chat)
- [Nhóm Quản trị và trạng thái](#7-nhóm-quản-trị-và-trạng-thái)
- [WebSocket](#8-websocket)
- [Đánh phiên bản](#9-đánh-phiên-bản)
- [Mã lỗi](#10-bảng-mã-lỗi)

---

## 1. Quy ước chung

| Hạng mục | Quy ước |
|---|---|
| Gốc | `http://<host>:8000` (LAN) hoặc `https://<tunnel>` |
| Định dạng | JSON, UTF-8 |
| Thời gian | Unix epoch giây, kiểu `float` |
| Nhiệt độ | °C, `float` |
| Xác thực | `Authorization: Bearer <token>` |
| Phiên bản | Header `X-API-Version: 1` |
| Lỗi | Luôn theo khuôn dạng dưới đây |

**Khuôn dạng lỗi thống nhất.** Mọi lỗi, kể cả lỗi kiểm tra đầu vào của
FastAPI/Pydantic, trả cùng khuôn dạng dưới đây để worker xử lý theo chương
trình. Lỗi vi phạm ràng buộc trường có HTTP `422` và `code: "BAD_REQUEST"`;
`detail` chứa chi tiết theo từng trường và không phải hợp đồng để client phân
tích theo chuỗi thông báo.

```json
{
  "error": {
    "code": "ROOM_FULL",
    "message": "Phòng đã đủ 10 máy.",
    "detail": { "capacity": 10, "current": 10 },
    "retry_after_s": 60
  }
}
```

`code` là hằng số máy đọc (§10). `message` là tiếng Việt cho người dùng. `retry_after_s` có mặt khi thử lại là hợp lý.

---

## 2. Ma trận xác thực

Sửa lỗi [S2](01-danh-gia-thiet-ke-hien-tai.md#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào).

| Endpoint | Ẩn danh | Token worker | Token quản trị |
|---|:---:|:---:|:---:|
| `POST /join` | ✅ có giới hạn tần suất | — | — |
| `GET /api/room/status` | ✅ `bootstrap_open`; invite chỉ loopback | — | — |
| `POST /api/room/bootstrap` | ✅ chưa mật khẩu **và** loopback | — | ✅ (đổi cấu hình) |
| `POST /api/room/close` | ❌ | ❌ | ✅ |
| `GET /api/room/invite` | ❌ | ❌ | ✅ |
| `POST /nodes/ready` | ❌ | ✅ | ✅ |
| `POST /ingest` | ❌ | ✅ | ✅ |
| `GET /jobs/next` | ❌ | ✅ | ✅ |
| `POST /jobs/result` | ❌ | ✅ | ✅ |
| `POST /chat` | ❌ | ❌ | ✅ |
| `GET /api/state` | ❌ | ✅ (rút gọn) | ✅ (đầy đủ) |
| `POST /api/settings` | ❌ | ❌ | ✅ |
| `GET /api/models` | ❌ | ❌ | ✅ |
| `POST /api/nodes/{node}/kick` | ❌ | ❌ | ✅ |
| `GET /api/esg.csv` | ❌ | ❌ | ✅ |
| `GET /` (dashboard) | ✅ trang đăng nhập | — | ✅ |
| `WS /ws` | ❌ | ✅ (rút gọn) | ✅ (đầy đủ) |

**Quy tắc bất di bất dịch:** danh tính node được suy ra **từ token**. Nếu thân yêu cầu có trường `node` khác với node gắn với token, server trả `403 IDENTITY_MISMATCH` và ghi vào `room_audit`. Không bao giờ tin `?node=` như [`server.py:162`](../server/server.py) đang làm.

---

## 3. Nhóm Phòng

### `GET /join`

Link mời / QR. Query `?code=THERMAL-…` → **302** tới `/?code=…` (landing). Không cấp token — token chỉ qua `POST /join`.

### `POST /join`

Đổi mã phòng + mật khẩu lấy token. Đây là endpoint duy nhất truy cập được khi chưa xác thực.

**Yêu cầu**
```json
{
  "room_code": "THERMAL-4F2A",
  "password": "…",
  "node_name": "Node-B",
  "capabilities": {
    "cpu_cores": 8,
    "ram_gb": 16,
    "os": "Windows 11",
    "has_gpu": true,
    "agent_version": "2.0.0"
  }
}
```

**`201 Created`**
```json
{
  "token": "<chuỗi ngẫu nhiên 256 bit, mã base64url>",
  "expires_at": 1735689600.0,
  "node_name": "Node-B",
  "room_config": {
    "model_id": "qwen2.5-0.5b-instruct-q4_k_m",
    "model_url": "https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    "model_sha256": "6EB923E7D26E9CEA28811E1A8E852009B21242FB157B26149D3B188F3A8C8653",
    "model_filename": "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    "runtime_url": "https://github.com/ggml-org/llama.cpp/releases/download/b10216/llama-b10216-bin-win-cpu-x64.zip",
    "runtime_sha256": "CA78DF53654BE907193F2615F590C51960F0A009C09285D1D1A5EFA8B84D69B9",
    "runtime_id": "llama.cpp-b10216-win-cpu-x64",
    "threshold_c": 75.0,
    "site_id": "hanoi-office-4f",
    "max_concurrent": 1,
    "telemetry_interval_s": 2.0
  }
}
```

**Lỗi**

| Mã HTTP | `code` | Khi nào |
|---|---|---|
| 400 | `BAD_REQUEST` | Thiếu trường hoặc `node_name` không hợp lệ |
| 401 | `AUTH_FAILED` | Sai mã phòng hoặc sai mật khẩu — **cùng một thông điệp cho cả hai**, không tiết lộ mã phòng nào tồn tại |
| 409 | `NODE_NAME_TAKEN` | Đã có node khác đang hoạt động với tên này |
| 409 | `ROOM_FULL` | Đã đủ `max_workers` |
| 429 | `RATE_LIMITED` | Quá số lần thử; kèm `retry_after_s` |

**Giới hạn tần suất.** 5 lần thử/phút cho mỗi cặp `IP|role` (worker và admin không chung bucket). Sau 3 lần sai liên tiếp, backoff lũy thừa: 2s, 4s, 8s… trần 5 phút; join thành công xóa cửa sổ fail của đúng role. Landing localhost điền invite **same-origin** (`location.origin`), không ưu tiên `invite_lan` vào ô join. Mọi lần thử — thành công hay thất bại — đều ghi vào `room_audit`.

**Xử lý mật khẩu.** Băm bằng Argon2id (tham số: 64 MB, 3 vòng, song song 4) hoặc PBKDF2-HMAC-SHA256 600.000 vòng nếu muốn tránh thêm phụ thuộc. So sánh bằng hàm thời gian hằng. **Không bao giờ lưu plaintext, không bao giờ ghi mật khẩu vào log.**

### `GET /api/room/status`

Công khai. Luôn có `{ "bootstrap_open": true|false }`.

- Phòng chưa khóa: có thể kèm `code_hint`.
- Phòng đã khóa + client **loopback**: thêm `code`, `invite_lan` (Host local vào lại qua Tham gia link).
- Phòng đã khóa + client mạng: **không** lộ mã/invite.

### `POST /api/room/bootstrap`

Tạo hoặc cấu hình lại phòng trên máy Host. Mỗi Host = một phòng; không có Room Directory.

- **Ẩn danh** chỉ khi phòng **chưa có mật khẩu** **và** client là loopback (`127.0.0.1` / `::1`). LAN/Internet → `403`.
- **Đã có mật khẩu** → cần token admin; đổi mật khẩu **thu hồi mọi token** cũ.
- `room.json` trên disk chỉ chứa metadata (`room_code`, `display_name`, `password_set`, …) — **không** plaintext password.
- `tunnel_ready` trong API tính từ độ dài mật khẩu **trong RAM** — không tin cờ trên disk sau restart.

**Yêu cầu**
```json
{
  "display_name": "Phòng 4F",
  "worker_password": "…",
  "admin_password": "…",
  "site_id": "hanoi-office-4f",
  "model_id": "qwen2.5-0.5b-instruct-q4_k_m",
  "threshold_c": 75,
  "regenerate_code": true
}
```

Mật khẩu ≥8 ký tự; worker ≠ admin. Tunnel (≥12) được báo qua `room.tunnel_ready` trong phản hồi / `GET /api/state`.

**`200`**
```json
{
  "ok": true,
  "room": {
    "code": "THERMAL-4F2A",
    "display_name": "Phòng 4F",
    "password_set": true,
    "tunnel_ready": true,
    "invite_lan": "http://192.168.1.50:8000/join?code=THERMAL-4F2A",
    "invite_tunnel": null
  }
}
```

### `POST /api/room/close`

Chỉ admin. Thu hồi mọi token, tắt tunnel, xóa hash mật khẩu (phòng sẵn sàng bootstrap lại).

### `POST /api/room/reopen-bootstrap`

Mở lại tạo phòng **không cần** Bearer admin — chỉ khi client **loopback** (`127.0.0.1` / `::1` / `localhost` / `testclient`). Trust model = truy cập vật lý máy Host (tương đương restart `python server.py --bootstrap-open`).

- Thu hồi mọi token, tắt tunnel, `clear_passwords()`, meta `password_set: false`.
- Non-loopback → `403 FORBIDDEN`.
- Audit: `room_reopen_bootstrap`.
- Landing Host hiện nút «Mở lại tạo phòng» khi phòng đã khóa + đang mở localhost.

### `GET /api/room/invite`

Chỉ admin. Trả link mời + `qr_svg_data_url` (SVG tối thiểu, không phụ thuộc lib QR).

### `POST /nodes/ready`

Worker báo đã tải xong model và khởi động runtime thành công.

```json
{ "model_id": "qwen2.5-0.5b-instruct-q4_k_m", "runtime_ready": true }
```

`200 {"ok": true, "state": "WARMING_UP"}`

Trước lời gọi này node ở trạng thái `JOINING` và **không nằm trong tập ứng viên nhận job** ([02 §6](02-kien-truc-he-thong.md#6-máy-trạng-thái-của-node)).

### `POST /leave`

Rời phòng chủ động. Thu hồi token, hạ `inflight` về 0, trả các job đang giữ chỗ về hàng đợi.

---

## 4. Nhóm Telemetry

### `POST /ingest`

Thay thế [`server.py:154`](../server/server.py). Khác biệt chính: **không còn trường `node` trong thân yêu cầu.**

**Yêu cầu**
```json
{
  "ts": 1735689600.0,
  "cpu_temp": 62.5,
  "gpu_temp": 48.0,
  "cpu_util": 35.0,
  "power_w": 28.4,
  "power_source": "sensor",
  "cpu_clock_mhz": 3800,
  "fan_rpm": 2400
}
```

| Trường | Bắt buộc | Ghi chú |
|---|:---:|---|
| `ts` | Không | Mặc định là giờ server. Xem quy tắc lệch đồng hồ bên dưới |
| `cpu_temp` | Không | `null` khi không đọc được (thiếu quyền quản trị) |
| `gpu_temp` | Không | |
| `cpu_util` | Không | 0–100 |
| `power_w` | Không | |
| `power_source` | **Có** | `sensor` \| `model` \| `none` — xem [08](08-do-cong-suat.md) |
| `cpu_clock_mhz` | Không | **Mới** — dùng để phát hiện throttle ([07](07-esg-3-tang.md) Tầng 1) |
| `fan_rpm` | Không | **Mới** — dùng cho ước lượng điện quạt (Tầng 2) |

**`202 Accepted`** `{"ok": true, "server_ts": 1735689600.4}`

**Quy tắc lệch đồng hồ.** PoC tin `ts` do client gửi vô điều kiện ([`server.py:156`](../server/server.py)). Ở 10 máy, đồng hồ lệch là chắc chắn, và một `ts` lệch 5 phút sẽ phá vỡ cửa sổ dự báo. Quy tắc mới:

```
nếu |ts_client − ts_server| > 30s:
    dùng ts_server
    ghi log cảnh báo một lần mỗi node mỗi 5 phút
    trả về server_ts để worker tự hiệu chỉnh
```

**Giới hạn tần suất:** tối đa 2 request/giây cho mỗi token. Vượt → `429`.

---

## 5. Nhóm Job

### `GET /jobs/next`

Thay thế [`server.py:161`](../server/server.py). Ba khác biệt: không còn tham số `?node=`, hỗ trợ long-poll, và chỉ trả job **đã giữ chỗ cho chính node này**.

**Yêu cầu:** `GET /jobs/next?wait=25` với header `Authorization: Bearer <token>`

`wait` là số giây chờ tối đa (0–30, mặc định 25). Server giữ kết nối cho tới khi có job hoặc hết giờ. Đây là long-poll: giảm độ trễ từ tối đa 1 giây xuống gần như tức thời, mà **vẫn giữ nguyên tính chất outbound-only** ([02 §1](02-kien-truc-he-thong.md#1-nguyên-tắc-kiến-trúc)).

**`200 OK` — job chat**
```json
{
  "id": "a1b2c3d4",
  "type": "chat",
  "prompt": "Giải thích ngắn gọn về điện toán phân tán",
  "params": { "max_tokens": 512, "temperature": 0.7 },
  "deadline_s": 60,
  "reserved_until": 1735689620.0
}
```

**`200 OK` — job burn** (chỉ ở chế độ `--demo-load` hoặc `--calibrate`)
```json
{ "id": "e5f6a7b8", "type": "burn", "duration_s": 10, "cores": 0 }
```

**`204 No Content`** — không có job cho node này. Không phải lỗi. Ba lý do có thể: node đang bị gắn cờ, không có job trong hàng đợi, hoặc job đã được giữ chỗ cho node khác. Worker **không cần biết lý do nào** — cứ poll tiếp.

### `POST /jobs/result`

Endpoint mới. Đây là nơi dữ liệu ESG Tầng 1 được sinh ra.

```json
{
  "job_id": "a1b2c3d4",
  "status": "ok",
  "text": "Điện toán phân tán là…",
  "tokens_in": 12,
  "tokens_out": 187,
  "duration_ms": 4820,
  "prompt_eval_ms": 340,
  "energy_j": 142.6,
  "energy_source": "sensor",
  "peak_temp_c": 71.2,
  "min_clock_mhz": 3100
}
```

| Trường | Ý nghĩa | Dùng cho |
|---|---|---|
| `tokens_out` | Số token sinh ra | **Mẫu số của J/token** |
| `energy_j` | Năng lượng tiêu thụ trong lúc suy luận | **Tử số của J/token** |
| `energy_source` | `sensor` \| `model` \| `none` | Quyết định số này vào Tầng 1 hay Tầng 2 |
| `min_clock_mhz` | Xung thấp nhất quan sát được | Phát hiện throttle |
| `peak_temp_c` | Nhiệt cao nhất | Đối chiếu với dự báo — đo sai số thật |

`status` nhận `ok` | `error` | `timeout`. Khi khác `ok`, thêm `error_message`; host thử node tốt thứ hai.

`text` là tùy chọn, tối đa **65.536 ký tự**. Vượt giới hạn này trả `422
BAD_REQUEST`; worker phải cắt kết quả hoặc báo lỗi job, không gửi lại nguyên
văn payload quá giới hạn.

**Cách worker tính `energy_j`:** lấy tích phân `power_w` theo thời gian trong khoảng chạy job, dùng quy tắc hình thang trên các mẫu cảm biến. Nếu `power_source = 'none'` thì đặt `energy_j = null` và `energy_source = 'none'` — **không được bịa số**. Chi tiết: [08](08-do-cong-suat.md).

`peak_temp_c` cho một lợi ích phụ đáng giá: đối chiếu với `predicted_max` để đo **sai số dự báo thật trong vận hành**, thay vì chỉ có MAE trên tập kiểm tra lúc huấn luyện ([05](05-du-bao-nhiet.md)).

---

## 6. Nhóm Chat

### `POST /chat`

```json
{ "prompt": "…", "max_tokens": 512, "temperature": 0.7, "stream": false }
```

`prompt` là bắt buộc và tối đa **32.768 ký tự**. Vượt giới hạn trả `422
BAD_REQUEST`; giao diện phải yêu cầu người dùng rút gọn prompt trước khi gửi
lại. Các giới hạn `max_tokens` (1–4.096) và `temperature` (0,0–2,0) cũng trả
`422 BAD_REQUEST` khi vi phạm.

**`202 Accepted`** — trả ngay, không chờ suy luận xong:
```json
{ "job_id": "a1b2c3d4", "queue_position": 2, "estimated_wait_s": 8 }
```

Kết quả đến qua WebSocket (§8) hoặc `GET /chat/{job_id}`.

**Vì sao không trả đồng bộ.** Suy luận mất 3–10 giây; giữ kết nối HTTP suốt thời gian đó sẽ gặp timeout của proxy/tunnel, và không cho biết gì về vị trí trong hàng đợi. Cách bất đồng bộ cũng cho phép giao diện hiển thị *"đang chờ máy rảnh"* thay vì treo.

### `GET /chat/{job_id}`

`200` kèm `{"status": "queued" | "running" | "done" | "error", …}`. Khi `done` có thêm `text`, `node` (máy đã chạy), `duration_ms`, `tokens_out`.

Trường `node` là thứ giao diện dùng để hiển thị *"chạy trên Node-B"* — nó biến việc điều phối thành thứ nhìn thấy được, và đó chính là điểm demo.

---

## 7. Nhóm Quản trị và trạng thái

### `GET /api/state`

Thay thế [`server.py:171`](../server/server.py). **Đọc từ cache dự báo, không tính lại** ([02 §7](02-kien-truc-he-thong.md#7-cache-dự-báo--nguồn-sự-thật-duy-nhất)).

```json
{
  "api_version": 1,
  "room": { "code": "THERMAL-4F2A", "name": "Phòng 4F", "worker_count": 3, "capacity": 10 },
  "threshold_c": 75.0,
  "model_status": { "forecaster": "random_forest", "per_node_models": ["Node-A"] },
  "queue": { "chat_pending": 2, "chat_running": 1 },
  "nodes": [
    {
      "name": "Node-B",
      "state": "READY",
      "cpu_temp": 62.5,
      "gpu_temp": 48.0,
      "cpu_util": 35.0,
      "power_w": 28.4,
      "power_source": "sensor",
      "predicted_max": 66.1,
      "delta_t": 3.6,
      "headroom": 0.71,
      "score": 0.82,
      "inflight": 0,
      "jobs_done": 14,
      "tokens_out_total": 2610,
      "reason": "dự báo 66,1°C, còn 71% khoảng an toàn",
      "site_id": "hanoi-office-4f"
    }
  ],
  "esg": {
    "tier1_measured": {
      "j_per_token": 0.78,
      "j_per_token_baseline": 0.91,
      "improvement_pct": 14.3,
      "throttle_seconds_avoided": 142.0,
      "samples": 87,
      "confidence": "ok"
    },
    "tier2_derived": {
      "kwh_leakage_saved": 0.0031,
      "kwh_fan_saved": 0.0008,
      "assumptions": ["hệ số rò 0,4%/°C", "quạt ~ bậc 3 theo tốc độ"]
    },
    "tier3_projected": {
      "scale_nodes": 1000,
      "scale_days": 365,
      "kwh_projected_measured": 1200.0,
      "kwh_projected_derived": 3630.0,
      "vnd_projected_measured": 3000000.0,
      "vnd_projected_derived": 9075000.0,
      "co2_kg_projected_measured": 864.0,
      "co2_kg_projected_derived": 2613.6,
      "label_measured": "CHIẾU TỪ SỐ ĐO (Tầng 1) — không phải tiết kiệm đã chứng minh",
      "label_derived": "DỰ PHÓNG — không phải số đo (chỉ từ Tầng 2)"
    }
  },
  "weather": {
    "hanoi-office-4f": { "temp_c": 34.0, "feels_like_c": 41.0, "updated_at": 1735689000.0 }
  }
}
```

Ba khối ESG **là ba đối tượng riêng biệt trong JSON**. Đây là quyết định thiết kế có chủ đích: nó khiến việc cộng gộp ba tầng trở nên khó về mặt cú pháp, không chỉ bị cấm bằng lời — xem [ADR-003](adr/ADR-003-esg-ba-tang.md).

Khi ngưỡng đổi giữa kỳ, thêm mảng `segments[]` (mỗi phần tử có đủ ba tầng + `threshold_c`/`from_ts`/`to_ts`). Ba object top-level luôn phản ánh **khoảng ngưỡng mới nhất** — không cộng gộp hai chế độ khác nhau.

**Chế độ rút gọn cho worker.** Token worker nhận `nodes[]` với `name`, `state`, `cpu_temp`, cộng thêm `llm_model_id` (để phát hiện admin đổi model — [ADR-006](adr/ADR-006-llm-model-catalog.md)). Không nhận `esg`, `room`, hay nội dung chat.

Admin state đầy đủ thêm `llm_model_id`, `llm_model_display` (tách biệt với `model_loaded` = Random Forest nhiệt).

### `GET /api/models`

Chỉ admin. Trả catalog cố định + model đang chọn ([ADR-006](adr/ADR-006-llm-model-catalog.md)):

```json
{
  "selected": "qwen2.5-0.5b-instruct-q4_k_m",
  "models": [
    {"model_id": "qwen2.5-0.5b-instruct-q4_k_m", "display": "Qwen2.5-0.5B-Instruct",
     "params_b": 0.49, "filename": "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
     "approx_size_gb": 0.4, "is_default": true}
  ]
}
```

### `POST /api/settings`

```json
{ "threshold_c": 72.0, "model_id": "qwen3.5-2b-q4_k_m",
  "w_cool": 0.4, "w_idle": 0.25, "w_power": 0.15, "w_load": 0.2 }
```

`model_id` phải thuộc catalog → sai → `422 UNKNOWN_MODEL`. Đổi model ghi sự kiện `model_changed` và log `[LLM]`. Một phòng một model — worker phải tải lại GGUF khớp `room_config` mới.

**Kiểm tra đầu vào — chống thao túng chỉ số.** Sửa lỗi [S3.2](01-danh-gia-thiet-ke-hien-tai.md#vấn-đề-32--chỉ-số-bị-thao-túng-hạ-ngưỡng-là-số-tự-đẹp-lên):

```
ngưỡng_tối_thiểu = max(40, max(idle_baseline_c của mọi node đang hoạt động) + 8)
```

Đặt thấp hơn → `422 THRESHOLD_TOO_LOW`, kèm `detail.minimum` và câu giải thích rằng ngưỡng thấp hơn nền nhiệt nhàn rỗi sẽ gắn cờ vĩnh viễn mọi máy và làm hỏng số liệu ESG.

Mọi lần đổi ngưỡng ghi một sự kiện `threshold_changed` vào `esg_events` — báo cáo phải hiện được ngưỡng có hiệu lực trong từng khoảng thời gian.

### `POST /api/nodes/{node}/kick`

Đuổi một worker. Thu hồi token, trả job đang giữ chỗ về hàng đợi, ghi `room_audit`.

Không thu hồi token thì tính năng "kick" chỉ là thay đổi giao diện — worker vẫn gọi API bình thường. Đây là lý do token phải thu hồi được, không thể dùng JWT không trạng thái mà không có danh sách chặn.

### `GET /api/esg.csv`

Mở rộng [`server.py:181`](../server/server.py). Xuất **nhật ký sự kiện**, không phải một dòng tổng — nếu không thì không kiểm toán được.

```csv
ts,node,event,threshold_at_time,predicted_max,tokens_out,energy_j,scheduler_mode
1735689600.0,Node-A,flagged,75.0,78.2,,,thermal_aware
1735689742.0,Node-A,cleared,75.0,71.4,,,thermal_aware
1735689801.0,Node-B,job_completed,75.0,,187,142.6,thermal_aware
```

Thêm `GET /api/esg/report.csv?from=&to=` cho bản tổng hợp theo khoảng thời gian, có phân tách ba tầng.

---

## 8. WebSocket

`WS /ws` — **không** gửi token trên query string (tránh lộ access/proxy log).

Sau khi kết nối, client **phải** gửi ngay một JSON auth (timeout 5 giây):

```json
{ "type": "auth", "token": "<bearer token từ /join>" }
```

Sai/thiếu token → đóng với mã gần `4401`. Tối đa **5** kết nối chưa auth cùng một IP; vượt → đóng ngay.

Handler: `websocket /ws` trong [`server/server.py`](../server/server.py). Sau auth thành công, host đẩy snapshot trạng thái định kỳ (cùng khuôn `GET /api/state`, worker nhận bản rút gọn).

| Loại tin | Nhịp | Nội dung |
|---|---|---|
| `state` (payload gốc) | ~2s | Cùng khuôn với `GET /api/state` |
| `chat_result` | Khi có (đặc tả mở rộng) | `{job_id, text, node, duration_ms, tokens_out}` |
| `chat_token` | Theo luồng | `{job_id, token}` — khi bật streaming |
| `node_event` | Khi có | `{node, event: "flagged"\|"cleared"\|"joined"\|"left", reason}` |
| `alert` | Khi có | `{level, message}` |

`node_event` (khi có) làm hiệu ứng Đỏ→Xanh trên dashboard xảy ra **ngay** thay vì đợi nhịp trạng thái kế tiếp.

---

## 9. Đánh phiên bản

- Header `X-API-Version: 1` bắt buộc trên mọi request từ worker.
- Host từ chối worker có phiên bản lớn hơn của mình: `426 VERSION_MISMATCH`.
- Worker cũ hơn một bậc: chấp nhận, cảnh báo trên dashboard.
- Thêm trường tùy chọn = không phá vỡ. Xóa trường, đổi ý nghĩa, siết kiểm tra = phá vỡ → tăng phiên bản.
- `room_config.model_id` gắn phòng với đúng một model. Worker có model khác phải tải lại — không có chuyện trộn model trong cùng một phòng, vì như vậy so sánh J/token giữa các node sẽ vô nghĩa. Catalog chọn được: [ADR-006](adr/ADR-006-llm-model-catalog.md).
- Hash và URL mặc định khớp [ADR-005](adr/ADR-005-llm-runtime.md) (đã chốt 2026-08-01). So sánh SHA256 **không phân biệt hoa/thường**. Sau khi giải nén zip runtime, worker còn phải kiểm `llama-server.exe` và `llama-server-impl.dll` theo hash trong ADR-005 / [10 §6](10-phong-tunnel-trien-khai.md#6-tải-thành-phần-lúc-chạy).

---

## 10. Bảng mã lỗi

| `code` | HTTP | Ý nghĩa | Worker nên làm gì |
|---|---|---|---|
| `BAD_REQUEST` | 400 | Sai khuôn dạng hoặc thiếu trường | Sửa, không thử lại |
| `BAD_REQUEST` | 422 | Vi phạm ràng buộc đầu vào, gồm giới hạn độ dài `prompt`/`text` | Sửa dữ liệu rồi gửi lại |
| `AUTH_FAILED` | 401 | Sai mã phòng hoặc mật khẩu | Hỏi lại người dùng |
| `TOKEN_EXPIRED` | 401 | Token hết hạn | Gọi lại `/join` |
| `TOKEN_REVOKED` | 401 | Đã bị đuổi | Dừng, báo người dùng |
| `IDENTITY_MISMATCH` | 403 | Thân yêu cầu mâu thuẫn với token | Lỗi lập trình — dừng và ghi log |
| `FORBIDDEN` | 403 | Cần quyền quản trị | Không thử lại |
| `NOT_FOUND` | 404 | Không có job/phòng | — |
| `NODE_NAME_TAKEN` | 409 | Trùng tên node | Đổi tên |
| `ROOM_FULL` | 409 | Đủ 10 máy | Thử lại sau `retry_after_s` |
| `THRESHOLD_TOO_LOW` | 422 | Dưới ngưỡng sàn an toàn | Hiện `detail.minimum` cho người dùng |
| `RATE_LIMITED` | 429 | Quá tần suất | Chờ `retry_after_s` |
| `VERSION_MISMATCH` | 426 | Lệch phiên bản API | Cập nhật worker |
| `INTERNAL` | 500 | Lỗi server | Thử lại có backoff |
