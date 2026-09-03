# 13 — Vận hành và sự cố

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Kế thừa và mở rộng bảng gỡ lỗi trong [`HOW_IT_WORKS.md`](../HOW_IT_WORKS.md) §5

Tài liệu này viết cho người đang gặp sự cố lúc 11 giờ đêm. Ngắn, tra cứu được, không có phần dẫn nhập.

## Mục lục

- [Vận hành hằng ngày](#1-vận-hành-hằng-ngày)
- [Đọc nhật ký](#2-đọc-nhật-ký)
- [Bảng triệu chứng → nguyên nhân](#3-bảng-triệu-chứng--nguyên-nhân)
- [Quy trình chẩn đoán](#4-quy-trình-chẩn-đoán)
- [Khôi phục](#5-khôi-phục)
- [Bảo trì định kỳ](#6-bảo-trì-định-kỳ)
- [WAL, telemetry cũ, sức khỏe agent](#7-wal-telemetry-cũ-và-sức-khỏe-agent)

---

## 1. Vận hành hằng ngày

### Kiểm tra buổi sáng

```
1. Dashboard mở được chưa?
2. Đủ số node mong đợi chưa? Có node nào STALE không?
3. Có cảnh báo bảo mật nào không? (số lần vào phòng thất bại)
4. Ổ đĩa còn chỗ không? (telemetry.db tăng ~30 MB/ngày ở 10 node)
5. Sai số dự báo có trong ngưỡng không? (xem 05 §9)
```

### Ngưỡng cảnh báo

| Chỉ số | Bình thường | Cảnh báo | Nghiêm trọng |
|---|---|---|---|
| Node STALE | 0 | 1–2 | >2 hoặc kéo dài >10 phút |
| Chiều dài hàng đợi chat | 0–3 | 4–16 | ≥32 (đầy, `max_queue=32`) |
| Tỷ lệ giữ chỗ hết hạn | <1% | 1–5% | >5% |
| Số lần `join_failed`/giờ | 0–2 | 3–10 | >10 từ một IP |
| Sai số dự báo (trung bình trượt 7 ngày) | < MAE huấn luyện | 1–2× | >2× |
| Ổ đĩa còn trống | >20% | 10–20% | <10% |
| `idle_baseline` so với lúc hiệu chuẩn | ±2°C | +3–5°C | **>+5°C — tản nhiệt bẩn** |

Dòng cuối là một phát hiện có giá trị thật cho người dùng, không chỉ là cảnh báo nội bộ: hệ thống nhận ra máy nào cần vệ sinh tản nhiệt.

---

## 2. Đọc nhật ký

### Vị trí

| Tệp | Nội dung |
|---|---|
| `logs\server.log` | Toàn bộ nhật ký host |
| `logs\agent.log` | Nhật ký worker, nằm cạnh tệp thực thi |
| `data\telemetry.db` → `esg_events` | Nhật ký sự kiện ESG |
| `data\telemetry.db` → `room_audit` | Nhật ký kiểm toán bảo mật |

### Tiền tố

Kế thừa quy ước của PoC, thêm ba tiền tố mới:

| Tiền tố | Nghĩa | Nơi sinh |
|---|---|---|
| `[FORECAST]` | Dự báo, gắn cờ, gỡ cờ | Host |
| `[SCHED]` | **Mới** — chấm điểm, gán job, thu hồi giữ chỗ | Host |
| `[ROOM]` | **Mới** — vào phòng, rời phòng, đuổi, token | Host |
| `[LLM]` | **Mới** — vòng đời runtime, kết quả suy luận | Worker |
| `[BALANCER]` | Hàng đợi job | Host |
| `[SETTINGS]` | Đổi ngưỡng, đổi trọng số | Host |
| `[JOB]` | Bắt đầu/kết thúc job | Worker |
| `[TELEMETRY]` | Gửi telemetry | Worker |
| `[AGENT]` | Khởi động worker | Worker |
| `[CALIBRATE]` | Tiến trình hiệu chuẩn | Host |

### Ba dòng log quan trọng nhất

**Quyết định gán job** — trả lời "tại sao job này đi máy đó":

```
[SCHED] job a1b2c3d4 -> Node-B (điểm 0.625)
        headroom 0.49 | rảnh 0.55 | điện 0.62 | sẵn sàng 1.00 | phạt 1.00
        đối thủ: Node-A 0.572 (headroom chỉ 0.07)
        bị loại: Node-C (flagged: dự báo 79,0°C ≥ 75,0°C)
```

**Không có ứng viên** — trường hợp gây bối rối nhất khi demo:

```
[SCHED] job a1b2c3d4 không có ứng viên nào:
        Node-A: flagged (dự báo 78,2°C ≥ 75,0°C)
        Node-B: busy (inflight 1/1)
        Node-C: stale_telemetry (lần cuối 47s trước)
        → thử host tự chạy
```

**Thu hồi giữ chỗ** — dấu hiệu sớm của node có vấn đề:

```
[SCHED] job a1b2c3d4 giữ chỗ hết hạn ở Node-B sau 20s → trả về hàng đợi
        (lần thử 2/3)
```

### Truy vấn nhanh

```bash
# Vì sao Node-A bị gắn cờ hôm nay?
grep "Node-A" logs/server.log | grep FORECAST

# Job đi đâu trong 1 giờ qua?
grep "\[SCHED\] job" logs/server.log | tail -50

# Có ai đang dò mật khẩu không?
sqlite3 data/telemetry.db \
  "SELECT source_ip, COUNT(*) FROM room_audit
   WHERE action='join_failed' AND ts > strftime('%s','now')-3600
   GROUP BY source_ip ORDER BY 2 DESC"

# Node nào bị thu hồi giữ chỗ nhiều nhất?
grep "giữ chỗ hết hạn" logs/server.log | grep -oP 'ở \S+' | sort | uniq -c | sort -rn
```

---

## 3. Bảng triệu chứng → nguyên nhân

### Kết nối và phòng

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Dashboard không có node nào | `agent.log`: `[TELEMETRY] send failed` | Sai URL trong cấu hình, tường lửa, hoặc host chưa chạy |
| Worker không vào được phòng | Mã lỗi HTTP | `401` sai mật khẩu · `409` phòng đầy hoặc trùng tên · `429` bị giới hạn tần suất |
| Worker vào được rồi rớt ngay | `agent.log`: `TOKEN_EXPIRED` / `TOKEN_REVOKED` | Token hết hạn hoặc đã bị kick — vào lại phòng |
| Node hiện `OFFLINE?` | Lần cuối gửi mẫu | Agent dừng, mạng rớt, hoặc máy ngủ |
| Node biến mất hoàn toàn | Quá 900s không có mẫu | Đúng theo thiết kế ([02 §6](02-kien-truc-he-thong.md#6-máy-trạng-thái-của-node)) — vào lại phòng |
| Mất tunnel | Nhật ký `cloudflared` | Worker LAN không ảnh hưởng; bật lại tunnel hoặc chuyển worker về LAN |

### Cảm biến

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Nhiệt độ `n/a` | `NodeAgent.exe --test-sensors` | Chưa chạy quyền Administrator, hoặc AV chặn driver |
| Công suất `n/a` nhưng nhiệt độ có | `power_probe.ps1` | Chip không phơi bày package power — máy này chỉ vào ESG Tầng 2 ([08](08-do-cong-suat.md)) |
| Nhiệt độ nhảy loạn | Dữ liệu thô trong `telemetry.db` | Cảm biến lỗi, hoặc đọc nhầm cảm biến — kiểm `SensorReader` |
| Toàn bộ node mất cảm biến cùng lúc | Bản cập nhật Windows gần đây | Bản vá có thể đã chặn driver — cài lại LibreHardwareMonitor |

### Điều phối

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Job không đi đâu cả | `[SCHED] không có ứng viên` | Đọc lý do từng node trong chính dòng log đó |
| Mọi job dồn về một máy | Điểm của các node trong `/api/state` | `idle_baseline` của máy khác có thể sai — hiệu chuẩn lại |
| Node bị gắn cờ mãi không gỡ | Dự báo so với `ngưỡng − 3` | Băng trễ đang hoạt động đúng; hoặc máy thật sự đang nóng |
| Trạng thái nhấp nháy | `MIN_DWELL_S` | Nếu vẫn nhấp nháy thì băng trễ chưa được áp dụng — lỗi |
| Giữ chỗ hết hạn liên tục ở một node | `agent.log` của node đó | Runtime LLM treo, máy quá tải, hoặc mạng chập chờn |
| Chat rất chậm | `inflight`, chiều dài hàng đợi | Tăng `max_concurrent`, hoặc thêm worker, hoặc dùng mô hình nhỏ hơn |
| Node không bao giờ được gắn cờ | Ngưỡng so với nhiệt thật của máy | Ngưỡng quá cao cho phần cứng này — dùng ngưỡng tương đối ([05 §3](05-du-bao-nhiet.md#ngưỡng-tương-đối)) |

### Dự báo

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Badge "Forecast: Linear fallback (not ML)" | `model.pkl` trong `THERMAL_DATA_DIR` (Host: `%ProgramData%\ThermalOrchestrator\shared`) | Train từ telemetry hiện có: `python train_model.py` (tôn trọng `THERMAL_DATA_DIR`), rồi **restart Host**; kỳ vọng log `[FORECAST] Loaded trained model` và `forecast_source=ml` |
| Dự báo sai nhiều | Sai số thực tế ([05 §9](05-du-bao-nhiet.md#9-giám-sát-chất-lượng-khi-vận-hành)) | Mô hình đã trôi — hiệu chuẩn lại |
| Node mới dự báo rất tệ | Model theo node có chưa | Chưa hiệu chuẩn — đang dùng model gộp, chấp nhận được tạm thời |
| Dự báo `null` mãi | Số mẫu trong 180 giây | Cần ≥5 mẫu trải ≥30 giây |

### ESG

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Tầng 1 trống | Có job nào `energy_source='sensor'` không | Không máy nào đọc được công suất — [08](08-do-cong-suat.md) |
| Không hiện phần trăm cải thiện | Số job mỗi chế độ | Cần ≥20 — đúng theo thiết kế |
| Số ESG về 0 sau khi khởi động lại | Bảng `esg_events` có dữ liệu không | Nếu có dữ liệu mà số vẫn 0 → lỗi ở hàm báo cáo |
| Đặt ngưỡng bị từ chối | `422 THRESHOLD_TOO_LOW` | Dưới sàn nhiệt nhàn rỗi — đúng theo thiết kế ([07 §7.1](07-esg-3-tang.md#71-sàn-ngưỡng-theo-nhiệt-nhàn-rỗi-đo-được)) |
| A/B ra số âm | Đủ mẫu chưa | Nếu đủ mẫu thì đây là kết quả thật — **báo cáo đúng như vậy** |

### Bảo mật

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Nhiều `join_failed` từ một IP | `room_audit` | Bị dò mật khẩu — chặn IP, cân nhắc tắt tunnel |
| `join_failed` từ nhiều IP | `room_audit` | Đang bị quét — **tắt tunnel ngay**, đổi mật khẩu |
| Node lạ trên dashboard | Danh sách token đã cấp | Token rò rỉ — kick node đó, thu hồi toàn bộ token, đổi mật khẩu |
| `IDENTITY_MISMATCH` trong log | Node nào gây ra | Lỗi lập trình phía worker, hoặc có người đang thử mạo danh |

---

## 4. Quy trình chẩn đoán

### "Chat không trả lời"

```
1. Có node nào READY không?
   /api/state → nodes[].state
   Không có  → xem bước 2
   Có        → xem bước 3

2. Vì sao không node nào READY?
   grep "\[SCHED\] không có ứng viên" logs/server.log
   → dòng log liệt kê lý do TỪNG node. Đọc nó.

3. Job có được gán không?
   grep "job <id>" logs/server.log
   Không có dòng [SCHED] → scheduler không chạy, kiểm vòng lặp nền
   Có gán, không có kết quả → xem bước 4

4. Worker có nhận job không?
   Xem agent.log của node được gán
   Không nhận → long-poll hỏng, hoặc mạng
   Nhận, không xong → runtime LLM treo, xem bước 5

5. Runtime LLM còn sống không?
   grep "\[LLM\]" agent.log
   → khởi động lại worker
```

### "Số ESG trông sai"

```
1. Ở tầng nào?
   Tầng 1 → xem bước 2
   Tầng 2 → kiểm giả định hiển thị cạnh số; có thể đúng nhưng khó tin
   Tầng 3 → là dự phóng, không phải số đo. Kiểm scale_nodes, scale_days

2. Có bao nhiêu job vào Tầng 1?
   sqlite3 data/telemetry.db "SELECT COUNT(*) FROM esg_events
     WHERE event='job_completed'
     AND json_extract(detail,'$.energy_source')='sensor'"
   = 0  → không máy nào đọc được công suất, xem 08
   < 20 → chưa đủ dữ liệu, đúng theo thiết kế

3. Tính lại từ nhật ký sự kiện có ra cùng số không?
   python scripts/measure_power/energy_per_token.py --db ... --from-events --ab
   Khác  → lỗi ở hàm báo cáo
   Giống → số đúng, chỉ là không như kỳ vọng
```

### "Một máy luôn bị gắn cờ"

```
1. Nhiệt thật của nó là bao nhiêu?  → /api/state
2. idle_baseline có đúng không?     → so với lúc hiệu chuẩn
   Tăng >5°C → TẢN NHIỆT BẨN. Đây là phát hiện đúng, không phải lỗi.
3. Ngưỡng hiệu lực của nó là bao nhiêu?
   = min(ngưỡng_cụm, idle_baseline + biên)
   Nếu idle_baseline cao thì ngưỡng hiệu lực có thể thấp bất ngờ.
4. Dự báo có hợp lý không?
   So predicted_max với peak_temp_c thực tế
   Lệch nhiều → mô hình trôi, hiệu chuẩn lại
```

---

## 5. Khôi phục

### Host khởi động lại

```
1. Khởi động lại host
2. Worker tự nối lại (token còn hạn) hoặc vào phòng lại
3. Số ESG tính lại từ esg_events — KHÔNG MẤT
4. Job đang chạy dở bị mất → người dùng gửi lại
```

Bước 3 là lý do tồn tại của [S5](01-danh-gia-thiet-ke-hien-tai.md#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram). Kiểm bằng ca X5 ([11 §5](11-chien-luoc-kiem-thu.md#5-kiểm-thử-hỗn-loạn)).

### `telemetry.db` hỏng

```bash
sqlite3 data/telemetry.db "PRAGMA integrity_check;"

# Nếu hỏng, cứu nhật ký sự kiện TRƯỚC — đó là thứ không tái tạo được
sqlite3 data/telemetry.db ".dump esg_events" > esg_events_backup.sql
sqlite3 data/telemetry.db ".dump room_audit" > room_audit_backup.sql

# Rồi mới dựng lại cơ sở dữ liệu
mv data/telemetry.db data/telemetry.db.hong
# khởi động host để tạo lược đồ mới
sqlite3 data/telemetry.db < esg_events_backup.sql
sqlite3 data/telemetry.db < room_audit_backup.sql
```

Telemetry thô mất thì chấp nhận được — nó tự sinh lại. **Nhật ký sự kiện mất thì không tái tạo được.**

### Nghi ngờ rò rỉ token

```
1. Đóng phòng      → thu hồi TOÀN BỘ token
2. Đổi mật khẩu    → mật khẩu mới, mạnh hơn
3. Tắt tunnel      → cắt đường vào từ ngoài
4. Xem room_audit  → tìm IP lạ, xác định phạm vi
5. Mở phòng lại    → mọi worker vào lại
6. Nếu prompt có thể đã lộ → báo người dùng
```

### Ổ đĩa đầy

```bash
# Cắt telemetry thô cũ hơn 7 ngày. KHÔNG ĐỘNG VÀO esg_events.
sqlite3 data/telemetry.db \
  "DELETE FROM telemetry WHERE ts < strftime('%s','now') - 7*86400;
   VACUUM;"
```

---

## 6. Bảo trì định kỳ

| Việc | Tần suất | Lệnh / cách làm |
|---|---|---|
| Kiểm dung lượng ổ | Tuần | Cắt telemetry cũ hơn 7 ngày |
| Xoay vòng nhật ký | Tuần | `server.log` chỉ tăng, không tự xoay ([`server.py:26`](../server/server.py)) |
| Sao lưu nhật ký sự kiện | Tuần | `.dump esg_events` ra nơi khác |
| Kiểm sai số dự báo | Tháng | So `peak_temp_c` với `predicted_max` |
| Hiệu chuẩn lại | Quý, hoặc khi sai số >2× | `--calibrate` rồi `train_model.py` |
| Đo lại đường cong công suất | Quý | `power_baseline.py` → `power_model_fit.py` |
| Kiểm `idle_baseline` trôi | Quý | Trôi >5°C = cần vệ sinh tản nhiệt |
| Cập nhật hệ số CO₂ | Năm | `esg_config.json` → `co2_source_year` |
| Rà soát nhật ký kiểm toán | Tháng | Tìm mẫu bất thường trong `room_audit` |
| Cập nhật runtime LLM | Khi có bản mới | **Tính lại SHA256**, thử nghiệm trước khi đưa vào `room_config` |

### Ghi chú về xoay vòng nhật ký

`FileHandler` hiện tại ([`server.py`](../server/server.py)) ghi nối tiếp không giới hạn. Ở 10 node chạy liên tục, `server.log` tăng nhanh hơn PoC 2 node đáng kể. Nên đổi sang `RotatingFileHandler` (10 MB × 5 tệp) ở mốc M6 — việc nhỏ nhưng bỏ qua thì sáu tháng sau sẽ có một tệp log vài GB.

---

## 7. WAL, telemetry cũ, và sức khỏe agent

### Kiểm WAL (`telemetry.db`)

Host dùng chế độ WAL. Mỗi ~5 phút (sau vòng refresh thời tiết) server thử `PRAGMA wal_checkpoint(PASSIVE)` — không chặn writer, không xóa DB.

```bash
# Chế độ journal
sqlite3 data/telemetry.db "PRAGMA journal_mode;"

# Kích thước file WAL (quan sát)
dir data\telemetry.db-wal
```

Trong `server.log`, tìm dòng `[STORE] WAL checkpoint PASSIVE` — `checkpointed` tăng dần là bình thường; `busy=1` kéo dài nhiều giờ → ingest/forecast đang giữ lock lâu, cân nhắc giảm tải hoặc chạy checkpoint thủ công lúc ít traffic:

```bash
sqlite3 data/telemetry.db "PRAGMA wal_checkpoint(PASSIVE);"
```

**Không** dùng `TRUNCATE` hoặc xóa `telemetry.db-wal` khi server đang chạy.

### Telemetry STALE trên dashboard

Node có badge `OFFLINE?` / `state=STALE` nghĩa là **không còn mẫu trong 10 giây** (`STALE_AFTER_S`). Dashboard **không** hiển thị nhiệt/công suất cũ như số live — các ô trống, banner cảnh báo `telemetry cũ`.

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| Một node STALE, các node khác OK | `agent.log` node đó | Khởi động lại agent; kiểm tra mạng |
| Mọi node STALE cùng lúc | Host còn chạy? | Restart host; kiểm tra cổng `POC_PORT` |
| STALE >10 phút | Token còn hạn? | Agent chết — vào lại phòng hoặc reboot máy |

### Sức khỏe agent (worker)

```bash
# Telemetry gửi được không?
grep "\[TELEMETRY\]" logs\agent.log | tail -20

# Long-poll job
grep "\[JOB\]" logs\agent.log | tail -20

# Cảm biến (cần Admin)
NodeAgent.exe --test-sensors
```

Agent khỏe khi: log `[TELEMETRY]` đều ~2s/lần, không có `send failed`, `/jobs/next` trả 200/204 (không 429 liên tục). `429 TOO_MANY_POLLS` = hai long-poll trùng node — bình thường nếu agent restart nhanh; kéo dài → kiểm tra duplicate process.

### Ngoại lệ loopback LLM (ADR-005 / invariants §1)

Worker **không** mở listener ra LAN. Runtime `llama-server` chỉ bind `127.0.0.1` (cổng ngẫu nhiên ~18080–18179) trên chính máy worker — đây là ngoại lệ đã chốt để HTTP localhost tới tiến trình con.

| Rủi ro | Mức | Ghi chú |
|---|---|---|
| Máy khác trên LAN gọi LLM | Không | Không bind `0.0.0.0` / interface public |
| Process khác trên cùng máy | Có | Cùng user có thể gọi `/completion` local |
| Downgrade HTTPS host → HTTP LAN | Chặn | Agent từ chối secondary HTTP khi primary HTTPS; HTTP chỉ loopback |

Nếu bộ phận IT yêu cầu **không** có listener nào kể cả loopback → cần ADR mới và chuyển runner stdio/in-process (ONNX) — không tự ý phá ADR-005 trong PoC này.

