# Scheduler v2 — thermal, user, capability, lease

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Scheduler đang chạy: [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md)
> Kiến trúc train: [`THERMAL_TRAINING_ARCHITECTURE.md`](THERMAL_TRAINING_ARCHITECTURE.md)
> **Trạng thái:** thiết kế. Công thức inference hiện tại **giữ**. Số hạng mới
> có trọng số mặc định 0 cho đến khi đo được.

Đây là lớp điều phối cho **job dài / preemptible** (training, preprocess nặng).
Job `chat`/`burn` tiếp tục dùng [`scheduler.py`](../server/scheduler.py) như
docs/04 trừ khi một số hạng v2 đã có dữ liệu tin cậy (capability fail-closed
áp dụng cho **mọi** loại job khi đã implement).

---

## Mục lục

- [1. Việc v1 làm đúng](#1-việc-v1-làm-đúng)
- [2. Việc v1 không đủ cho training](#2-việc-v1-không-đủ-cho-training)
- [3. Hai lớp trạng thái](#3-hai-lớp-trạng-thái)
- [4. Mô hình nhiệt](#4-mô-hình-nhiệt)
- [5. User activity](#5-user-activity)
- [6. Capability fail-closed](#6-capability-fail-closed)
- [7. Energy](#7-energy)
- [8. Network](#8-network)
- [9. Checkpoint locality](#9-checkpoint-locality)
- [10. Training leases](#10-training-leases)
- [11. Scoring v2](#11-scoring-v2)
- [12. Lọc ứng viên v2](#12-lọc-ứng-viên-v2)
- [13. A/B và tune trọng số](#13-ab-và-tune-trọng-số)
- [14. Log quyết định](#14-log-quyết-định)
- [15. Việc chưa đóng](#15-việc-chưa-đóng)

---

## 1. Việc v1 làm đúng

Giữ nguyên nguyên tắc docs/04:

1. Lọc rồi mới chấm — lý do loại đọc được.
2. Điểm một node không phụ thuộc node khác (trừ tie-break tên).
3. Thành phần trong [0, 1], trọng số cộng 1.
4. Một chính sách (không `_throttled` song song).
5. Mỗi gán một dòng log.
6. Scheduler chỉ đọc snapshot cache (+ registry), nhận `now`.

Công thức đang chạy ([`scheduler.py`](../server/scheduler.py)):

```
score = (w_cool·headroom + w_idle·idleness
       + w_power·efficiency + w_load·availability) × penalty
```

Mặc định: `cool=0.40`, `idle=0.25`, `power=0.15`, `load=0.20`.

- `headroom`: `(threshold − temp) / (threshold − idle_baseline)`, `temp` =
  `predicted_max_c` nếu có, không thì `current_temp_c`; không có nhiệt → 0.5.
- `idleness`: `1 − cpu_util/100` — **đây là CPU rảnh, không phải người dùng**.
- `efficiency`: chuẩn hóa power theo `p_idle`/`p_max`; `power_source=none` →
  trung lập + `redistribute` bỏ `w_power`.
- `availability`: `1 − inflight/max_concurrent`.
- `penalty`: WARMING_UP ×0.7; recently_failed ×0.5; consecutive_errors≥2 ×0.3.

Chế độ `round_robin` bỏ qua cờ AT_RISK — **đối chứng A/B**, không phải sản
phẩm. Giữ cho thí nghiệm training.

`ΔT_avoided` đóng dấu lúc gán (nhiệt đối thủ) phục vụ ESG Tầng 2 — giữ.

---

## 2. Việc v1 không đủ cho training

| Hạng | v1 | Cần cho train |
|---|---|---|
| Nhiệt | Một scalar `predicted_max` 3 phút | Quỹ đạo + headroom GPU + cooling |
| User | Không | USER_ACTIVE bắt buộc |
| Capability | `meets_capability` True khi thiếu RAM | Fail-closed VRAM/backend/precision |
| Energy | Hiệu suất tức thời | kWh còn lại đến mốc, không chỉ W thấp |
| Network | Không | RTT/bandwidth; chặn Tầng B/C |
| Locality | Không | Checkpoint/shard đã có trên đĩa |
| Thời hạn | Reservation 20s, chat ~60s | Lease 120–300s + renew |
| Preempt | Flag chặn job **mới**; job đang chạy chạy nốt | Deny renew → pause |

v2 **không** thay v1 bằng một công thức “chính xác khoa học” khi chưa có số.
v2 thêm **chỗ cắm** số hạng và mặc định an toàn.

---

## 3. Hai lớp trạng thái

**Lớp nhiệt** (KEEP, ForecastCache.state):

`JOINING | WARMING_UP | READY | AT_RISK | STALE | INACTIVE`

**Lớp occupancy** (NEW):

| Occupancy | Nghĩa | Training lease |
|---|---|---|
| `IDLE` | Không job AI nền | Có thể cấp |
| `INFERENCE` | Đang chat/burn | Thường không chồng (max_concurrent=1) |
| `TRAINING` | Đang trainer | Đang giữ lease |
| `COOLING` | Vừa preempt vì nhiệt; chờ hạ | Không cấp đến khi headroom phục hồi |
| `USER_ACTIVE` | Người dùng tương tác | **Không cấp / không renew** |
| `DRAINING` | Sắp leave/kick; chỉ checkpoint | Không cấp mới |
| `OFFLINE` | Không ingest | Không |

Scheduler lọc **tích** hai lớp. Ví dụ `READY` + `USER_ACTIVE` → loại train.
`AT_RISK` + `IDLE` → loại train (trừ round_robin).

`COOLING` không phải state nhiệt mới: đó là occupancy sau `paused` vì
`deny_preempt` lý do nhiệt, với `cool_until = now + dwell`. Tránh gán ngay
lại máy vừa nóng.

---

## 4. Mô hình nhiệt

### 4.1. Nguồn sự thật

Vẫn ForecastCache. Vòng 5 giây ghi ΔT 3 phút (ADR-004). Scheduler không gọi
`forecaster` lần hai (M6).

### 4.2. Tín hiệu dùng để quyết định train

| Tín hiệu | Nguồn | Dùng |
|---|---|---|
| `current_temp_c` | ingest | headroom tức thời |
| `predicted_max_c` | forecast | filter AT_RISK, headroom |
| `delta_t_c` | forecast | quỹ đạo: đang lên hay xuống |
| `gpu_temp` | ingest (thường null) | nếu MEASURED, lấy max(cpu, gpu) cho job GPU |
| `cpu_util` | ingest | idleness v1 |
| `min_clock_mhz` lúc job | result | throttle (ESG Tầng 1) — **không** có trước khi gán |

Chưa có mô hình nhiệt **GPU riêng**. Khi `gpu_temp` UNKNOWN, job đòi CUDA
vẫn có thể chạy nếu VRAM MEASURED — nhưng headroom chỉ dựa CPU: **ghi log**
`thermal_proxy=cpu`. Không bịa nhiệt GPU.

### 4.3. Headroom v2 (cùng công thức v1, đầu vào rõ hơn)

```
temp_eff = predicted_max_c  nếu có
         else current_temp_c
         else UNKNOWN → không cho điểm headroom tối đa (0.5) và
                         không nhận job train nếu recipe require_temp=true
                         (mặc định true cho train, false cho chat như v1)
```

Job train mặc định **đòi** cảm biến nhiệt. Máy không đo được nhiệt không
phải ứng viên train (fail-closed), vẫn có thể chat nếu v1 cho phép.

### 4.4. Không chỉ “temp > threshold → stop”

Trong lease: AT_RISK hoặc `predicted_max` vượt ngưỡng **có hysteresis** →
deny renew, không kill giữa step. Đó là khác biệt với gắn cờ v1 (chỉ chặn
job mới).

Quỹ đạo: nếu `delta_t_c` lớn dương (đang nóng nhanh) dù `predicted_max` còn
dưới ngưỡng, giảm `progress_score` (số hạng `thermal_trend`), không lọc cứng
— tránh over-filter khi mô hình ΔT còn nhiễu. Trọng số mặc định thấp.

---

## 5. User activity

v1 `idleness` = CPU. Máy 5% CPU vẫn có người đang soạn Word.

### 5.1. Tín hiệu

Agent đo `seconds_since_last_input` (Win32 `GetLastInputInfo`). Không bắt
phím, không screenshot.

Ngưỡng cấu hình phòng (mặc định đề xuất):

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `user_idle_after_s` | 120 | Dưới ngưỡng → `USER_ACTIVE` |
| `user_active_dwell_s` | 30 | Tránh nhấp nháy khi chạm chuột một lần |

False positive: screensaver / chuột rơi. False negative: user đọc màn hình
không input. **PoV phải đo** “user responsiveness” (thời gian từ input đến
CPU trả lại), không tuyên bố hoàn hảo.

### 5.2. Chính sách human-first

Thứ tự ưu tiên:

1. Tương tác người dùng trên máy đó.
2. Job inference tương tác (`chat`) nếu policy phòng `chat_while_user=true`
   (mặc định **false** trên worker, **true** trên host console nếu admin
   đang demo — cấu hình, không hardcode).
3. Training / preprocess.

Khi đang TRAINING và chuyển USER_ACTIVE:

- Không `KillProcess` ngay.
- `pause` → checkpoint → `result=paused`.
- Occupancy COOLING không bắt buộc; về IDLE khi trainer đã chết và CPU hạ.

---

## 6. Capability fail-closed

### 6.1. Lỗ hổng v1

```python
# scheduler.meets_capability — hiện tại
have = getattr(f, "ram_gb", None)
if have is None:
    return True   # FAIL-OPEN
```

Join agent gửi `ram_gb: 0`, `has_gpu: false`. Filter capability gần như chết.

### 6.2. Quy tắc v2

Mỗi yêu cầu job (`min_ram_gb`, `min_vram_mb`, `required_backend`,
`precision`, `min_compute_capability`) đối chiếu manifest:

- Thiếu field hoặc `status=UNKNOWN` → **không đủ**.
- `ram_gb=0` với `status=DECLARED` không được bịa thành “đủ”.
- `has_gpu=false` MEASURED → loại job `cuda`.
- FP16/BF16 UNKNOWN → không nhận recipe `fp16`/`bf16`.

Node class (C0…G5) là **rút gọn** để dashboard và lọc thô; điều kiện cứng
vẫn là field manifest.

### 6.3. Ước lượng hiệu năng

`est_samples_per_s` từ `benchmark_device` hoặc lịch sử job cùng
`(type, backend, model_id)`. UNKNOWN → dùng cận dưới theo class, **không**
dùng cận trên (lạc quan). Ghi `perf_status=UNKNOWN|MEASURED`.

---

## 7. Energy

v1 `efficiency` thích máy đang **tiêu ít watt** — có thể là máy yếu, train
lâu hơn, **tốn hơn** đến mốc chất lượng.

v2 tách:

| Số hạng | Ý | Mặc định |
|---|---|---|
| `efficiency` v1 | W tức thời thấp | Giữ cho chat |
| `energy_progress` | samples/s / watt (nếu W MEASURED) | 0 cho đến khi có benchmark |

Energy-to-Target-Quality **không** nằm trong vòng 1 giây. Đó là metric báo
cáo sau run A/B ([`CLAIMS_RISKS_LIMITATIONS.md`](CLAIMS_RISKS_LIMITATIONS.md)).

`power_source=none`: không dùng `energy_progress` (redistribute như v1).
Không bịa W.

Tầng ESG: Joule/sample chỉ Tầng 1 khi sensor. Scheduler không cộng Tầng 2/3
vào điểm.

---

## 8. Network

Probe chậm: RTT, jitter, throughput thô (tải file nhỏ từ Host, hash sẵn).

| Net class | Gợi ý | Mode |
|---|---|---|
| N0 | RTT cao / không đo | Chỉ A, shard đã local |
| N1 | LAN office | A; B nếu round hiếm |
| N2 | LAN tốt, ≥ vài trăm Mbps | A, B |
| N3 | Interconnect giả lập datacenter | mới xét C |

UNKNOWN net → N0. Tầng C **không** bật vì “có Ethernet”.

Scheduler: `network_fit ∈ [0,1]` = 1 nếu mode A và shard local; giảm nếu
phải kéo shard lớn trên RTT cao. Lọc cứng: `compute_mode=B` đòi N1+;
`C` đòi N3 (thực tế không có trên PoC văn phòng — đúng ý “không ship C”).

---

## 9. Checkpoint locality

```
locality = 1  nếu node có sha256 ckpt hoặc shard cần thiết trên đĩa
         = 0.3 nếu cùng LAN, Host còn bản
         = 0   nếu phải kéo từ xa / tunnel
```

Dùng trong điểm, trừ `require_local_checkpoint=true` (lọc).

Migration cost (mẫu số scoring): ước `size_bytes / throughput_bps + penalty`.
Nếu cost > `estimated_remaining_train_s` * hệ số → không chuyển máy, chờ
node cũ hết USER_ACTIVE/COOLING.

---

## 10. Training leases

### 10.1. Quan hệ với reservation v1

| | Inference | Training |
|---|---|---|
| Gán | `target` + `reserved_until=now+20` | cùng `target` |
| Claim | `GET /jobs/next` | giống |
| Chạy | `active_deadline` ~ timeout chat | `lease_until` 120–300s |
| Gia hạn | không | `POST .../lease/renew` |
| Hết hạn không claim | requeue, recently_failed | giống |
| Hết hạn đang chạy | `LEASE_EXPIRED` | deny ngầm: agent phải pause; nếu chết, reap + ckpt nếu có |

`lease_s` nằm trong recipe, clamp Host `[60, 600]`. Mặc định 180.

### 10.2. Renew

Host **granted** nếu tất cả:

- state ∈ {READY, WARMING_UP} (WARMING_UP vẫn phạt điểm lúc gán, nhưng
  đang chạy thì không cắt chỉ vì thiếu mẫu forecast — tránh preempt giả).
- occupancy ∉ {USER_ACTIVE, DRAINING, OFFLINE}
- không AT_RISK nếu `thermal_policy=preempt_on_atrisk_or_user`
- ingest không stale
- run chưa bị admin hủy

**deny_preempt** kèm `reason` đọc được: `user_active`, `at_risk`,
`stale`, `reclaim`, `run_cancelled`.

Agent luôn checkpoint trước khi kết thúc lease nếu trainer sống.

### 10.3. Không phải live migration

Khoảng 1 giây chỉ là **chu kỳ scheduler**. Người đọc hồ sơ phải thấy chữ
checkpoint. Xem [`PDF_REVISION_GUIDE.md`](PDF_REVISION_GUIDE.md) §3.

---

## 11. Scoring v2

Khái niệm (chưa đóng hệ số):

```
expected_progress = perf_hat × remaining_fraction × locality_boost

cost = w_th·thermal_cost
     + w_en·energy_cost
     + w_us·user_cost
     + w_net·network_cost
     + w_mig·migration_cost

score_train = expected_progress / max(cost, ε)
sau đó chuẩn hóa theo cách không phụ thuộc node khác
  → map từng thành phần về [0,1] rồi trọng số cộng, giống v1
```

Để không phá nguyên tắc “điểm không phụ thuộc node khác”, **không** chia
cho max toàn cụm. Làm như v1: mỗi cost map về [0,1] bằng ngưỡng **của chính
máy** (threshold nhiệt, p_max, RTT_ref của phòng).

Đề xuất thành phần [0,1] khi implement:

| Thành phần | Map |
|---|---|
| `headroom` | như v1 |
| `thermal_trend` | 1 − clamp(delta_t / cap, 0, 1) |
| `idleness` | CPU như v1 |
| `user_quiet` | 1 nếu không USER_ACTIVE (sau lọc thường đã =1) |
| `energy_progress` | clamp(samples_per_j / ref, 0, 1) hoặc 0.5 nếu unknown + drop weight |
| `availability` | như v1 |
| `locality` | §9 |
| `network_fit` | §8 |
| `reliability` | 1 − recent_error_rate (penalty v1 đã có một phần) |

`user_cost` sau lọc cứng thường không còn trên ứng viên; giữ trong renew.

Trọng số mặc định **giai đoạn đầu** (chỉ bật cái đo được):

```
w_cool=0.40  w_idle=0.20  w_power=0.10  w_load=0.15
w_locality=0.15
w_trend=0  w_energy_progress=0  w_net=0
```

Khi chưa có benchmark, `w_trend`/`w_energy_progress`/`w_net` = 0 và
`redistribute` — **không** cho 0.5 giả tạo làm đổi hạng.

Chat job: không dùng locality/net/energy_progress trừ khi đã MEASURED và
config bật.

---

## 12. Lọc ứng viên v2

Thứ tự đề xuất (lý do log hữu ích trước):

| # | Điều kiện | Mã |
|---|---|---|
| 1 | occupancy `USER_ACTIVE` (train) | `user_active` |
| 2 | occupancy `COOLING` và `now < cool_until` | `cooling` |
| 3 | state ∉ {READY, WARMING_UP} | `state_*` |
| 4 | AT_RISK và không round_robin | `flagged` |
| 5 | stale telemetry | `stale_telemetry` |
| 6 | inflight ≥ max_concurrent | `busy` |
| 7 | capability UNKNOWN/thiếu | `insufficient_capability` |
| 8 | node class không khớp gợi ý **và** VRAM dưới min | `class_or_vram` |
| 9 | data classification > worker trust | `trust` |
| 10 | compute_mode B/C vs net class | `network_mode` |
| 11 | chat: `model_ready` | `model_not_ready` |
| 12 | train: trainer add-on không ready | `trainer_not_ready` |

`recently_failed` vẫn **phạt điểm**, không lọc (quyết định G2 docs/04) —
trừ khi consecutive_errors vượt ngưỡng run.

---

## 13. A/B và tune trọng số

Giữ `settings.scheduler_mode`: `thermal_aware` | `round_robin`.

Thí nghiệm Phase 3 ([`DISTRIBUTED_TRAINING_ROADMAP.md`](DISTRIBUTED_TRAINING_ROADMAP.md)):

- Cùng recipe, cùng 2–3 máy, đổi mode.
- Không tune trọng số giữa chừng một cặp A/B.
- Ghi stamp `scheduler_mode` lúc assign (đã có với chat).

Sau khi có số: chỉnh trọng số **một** lần, chạy lại A/B. Không tuyên bố
công thức tối ưu toàn cục.

Harness inference [`ab_benchmark.py`](../server/ab_benchmark.py) là mẫu;
training cần harness riêng (metric khác: max temp, preemption, quality).

---

## 14. Log quyết định

Tiền tố `[SCHED]`. Mỗi gán train:

```
[SCHED] job 12ab train_expert mode=A target=Node-B score=0.62
        headroom=0.71 idle=0.80 locality=1.0 cap=G1
        rejected Node-A: user_active; Node-C: insufficient_capability vram=UNKNOWN
        lease_s=180 thermal_policy=preempt_on_atrisk_or_user
```

Mỗi deny renew:

```
[SCHED] lease deny job 12ab node=Node-B reason=at_risk pred=78.2
```

Không log đường dẫn dataset, không log sample.

---

## 15. Việc chưa đóng

- Hệ số số học cuối cùng của `score_train` — **cố ý** chưa khóa.
- GPU thermal model riêng.
- `chat_while_user` mặc định sản phẩm vs demo.
- Persist lease qua Host restart (bắt buộc trước soak training).
- Công thức energy_progress khi chỉ có power model (Tầng 2) — **không** đưa
  vào Tầng 1 scoring; có thể dùng nhãn `model` với trọng số tách.

Khi implement: test hành vi (loại USER_ACTIVE, UNKNOWN VRAM, deny renew)
chứ không test giá trị số hạng cụ thể — cùng triết lý docs/04.
