# 04 — Đặc tả Scheduler

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Sửa các lỗi: [S1](01-danh-gia-thiet-ke-hien-tai.md#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại), [M7](01-danh-gia-thiet-ke-hien-tai.md#m7--không-có-trễ-trong-quyết-định-gắn-cờ--node-dao-động-quanh-ngưỡng), [M8](01-danh-gia-thiet-ke-hien-tai.md#m8--không-có-nhận-thức-về-hàng-đợi-và-mức-đồng-thời), [M11](01-danh-gia-thiet-ke-hien-tai.md#m11--hàm-normalize-chưa-được-định-nghĩa-và-sẽ-không-ổn-định), [M12](01-danh-gia-thiet-ke-hien-tai.md#m12--thời-tiết-trong-công-thức-chấm-điểm-gần-như-vô-nghĩa), [M13](01-danh-gia-thiet-ke-hien-tai.md#m13--trạng-thái-khởi-động-nguội-chưa-được-định-nghĩa), [M14](01-danh-gia-thiet-ke-hien-tai.md#m14--hai-chính-sách-điều-phối-chồng-lên-nhau)

Đây là trái tim của sản phẩm. Nếu tài liệu này sai, mọi thứ khác chỉ là một dashboard đẹp.

## Mục lục

- [Nguyên tắc](#1-nguyên-tắc)
- [Ba giai đoạn](#2-ba-giai-đoạn-lọc--chấm-điểm--giữ-chỗ)
- [Giai đoạn 1: Lọc ứng viên](#3-giai-đoạn-1--lọc-ứng-viên)
- [Giai đoạn 2: Chấm điểm](#4-giai-đoạn-2--chấm-điểm)
- [Giai đoạn 3: Giữ chỗ](#5-giai-đoạn-3--giữ-chỗ)
- [Băng trễ trong quyết định gắn cờ](#6-băng-trễ-trong-quyết-định-gắn-cờ)
- [Mã giả đầy đủ](#7-mã-giả-đầy-đủ)
- [Hằng số và mặc định](#8-hằng-số-và-mặc-định)
- [Bảng ca kiểm thử](#9-bảng-ca-kiểm-thử)
- [Chế độ round-robin cho A/B](#10-chế-độ-round-robin-cho-ab)

---

## 1. Nguyên tắc

| # | Nguyên tắc | Vì sao |
|---|---|---|
| 1 | **Lọc rồi mới chấm điểm.** Không dùng "điểm âm vô cùng" | Node bị loại phải có lý do đọc được, không phải một con số kỳ dị |
| 2 | **Điểm không phụ thuộc node khác** | Cắm thêm một máy nóng không được làm đổi điểm của máy khác ([M11](01-danh-gia-thiet-ke-hien-tai.md#m11--hàm-normalize-chưa-được-định-nghĩa-và-sẽ-không-ổn-định)) |
| 3 | **Mọi thành phần điểm nằm trong [0, 1]**, trọng số cộng bằng 1 | Điểm cuối cũng trong [0, 1] → so sánh và diễn giải được |
| 4 | **Chỉ một chính sách điều phối** | Bỏ `_throttled`; điểm số lo tất cả ([M14](01-danh-gia-thiet-ke-hien-tai.md#m14--hai-chính-sách-điều-phối-chồng-lên-nhau)) |
| 5 | **Mỗi quyết định gán để lại một dòng log giải thích được** | Debug được sau khi sự việc đã qua, không cần gắn debugger |
| 6 | **Scheduler chỉ đọc `ForecastCache`** | Test được bằng cache giả, không cần cơ sở dữ liệu |

---

## 2. Ba giai đoạn: Lọc → Chấm điểm → Giữ chỗ

```
Hàng đợi job (FIFO)
       │
       ▼
┌──────────────────────────────────────────┐
│ GIAI ĐOẠN 1 — LỌC                        │
│ Từ 10 node → tập ứng viên hợp lệ         │
│ Ghi log lý do loại từng node              │
└──────────────────┬───────────────────────┘
                   │  rỗng → host tự chạy (P2) hoặc job chờ tiếp
                   ▼
┌──────────────────────────────────────────┐
│ GIAI ĐOẠN 2 — CHẤM ĐIỂM                  │
│ score(node) ∈ [0,1] cho từng ứng viên     │
│ Ghi log điểm thành phần của người thắng   │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ GIAI ĐOẠN 3 — GIỮ CHỖ                    │
│ job.target = người thắng                  │
│ reserved_until = now + 20s                │
│ inflight[người thắng] += 1                │
└──────────────────────────────────────────┘
```

---

## 3. Giai đoạn 1 — Lọc ứng viên

Node bị loại nếu **bất kỳ** điều kiện nào đúng. Thứ tự kiểm tra được chọn để lý do trong log là lý do hữu ích nhất.

| # | Điều kiện loại | Mã lý do | Ghi chú |
|---|---|---|---|
| 1 | Trạng thái ∉ {`READY`, `WARMING_UP`} | `state_<trạng thái>` | Loại `JOINING`, `STALE`, `INACTIVE` |
| 2 | Đang bị gắn cờ (`AT_RISK`) | `flagged` | **Đây là cốt lõi của sản phẩm** |
| 3 | `inflight >= max_concurrent` | `busy` | Mặc định `max_concurrent = 1` |
| 4 | Chưa tải xong model | `model_not_ready` | |
| 5 | Không đủ năng lực cho loại job | `insufficient_capability` | RAM < mức tối thiểu của model |
| 6 | Đang trong thời gian phạt sau khi giữ chỗ hết hạn | `recently_failed` | Xem §5.3 |
| 7 | Mẫu telemetry cuối cũ hơn `STALE_AFTER_S` | `stale_telemetry` | Trùng một phần với 1, giữ lại làm lưới an toàn |

**Ghi log khi tập ứng viên rỗng** — đây là trường hợp gây bối rối nhất khi demo:

```
[SCHED] job a1b2c3d4 không có ứng viên nào:
        Node-A: flagged (dự báo 78,2°C ≥ 75,0°C)
        Node-B: busy (inflight 1/1)
        Node-C: stale_telemetry (lần cuối 47s trước)
        → thử host tự chạy
```

Không có dòng log này, người vận hành chỉ thấy chat "bị treo" mà không biết vì sao.

---

## 4. Giai đoạn 2 — Chấm điểm

### 4.1. Công thức

```
score(node) = w_cool   × headroom(node)
            + w_idle   × idleness(node)
            + w_power  × efficiency(node)
            + w_load   × availability(node)

            × penalty(node)
```

Bốn thành phần đầu cộng lại, sau đó nhân với hệ số phạt. Trọng số cộng bằng 1, nên phần cộng nằm trong [0, 1] và điểm cuối cũng vậy.

**Thời tiết không có mặt.** Xem [M12](01-danh-gia-thiet-ke-hien-tai.md#m12--thời-tiết-trong-công-thức-chấm-điểm-gần-như-vô-nghĩa): nếu mọi node cùng site thì số hạng này là hằng số và triệt tiêu; nếu khác site thì điều hòa đã cắt đứt quan hệ. Thời tiết được dùng ở [07 §Tầng 2](07-esg-3-tang.md) làm hệ số chi phí làm mát và ở dashboard làm ngữ cảnh. Cấu hình vẫn cho phép bật `w_weather` khi thực sự đa site, nhưng **mặc định bằng 0 và tài liệu nói rõ vì sao**.

### 4.2. `headroom` — khoảng an toàn nhiệt còn lại

Thay thế `1 − normalize(predicted_max_temp)` bằng đại lượng có nghĩa vật lý và ổn định:

```
headroom = (ngưỡng_hiệu_lực − dự_báo_max) / (ngưỡng_hiệu_lực − baseline_idle)
cắt về [0, 1]
```

- `baseline_idle` là nhiệt độ nhàn rỗi **đo được của chính máy đó** (từ pha hiệu chuẩn, lưu trong hồ sơ node). Chưa có thì dùng phân vị 5% của nhiệt độ trong 24 giờ qua.
- `ngưỡng_hiệu_lực` = `min(ngưỡng_cụm, baseline_idle + biên_tối_đa)`.

**Ví dụ minh họa vì sao chuẩn hóa theo từng máy là bắt buộc:**

| Máy | Nhàn rỗi | Ngưỡng | Dự báo | `headroom` | Diễn giải |
|---|---|---|---|---|---|
| Laptop mỏng | 52°C | 85°C | 70°C | 0,45 | Còn 45% khoảng an toàn |
| Desktop | 32°C | 75°C | 70°C | 0,12 | Còn 12% — sắp nguy |

**Cùng dự báo 70°C, hai kết luận hoàn toàn khác nhau** — và cả hai đều đúng. Chuẩn hóa min-max toàn cụm sẽ cho hai máy này cùng một điểm, tức là sai với ít nhất một trong hai.

Khi ở `WARMING_UP` (chưa có dự báo): dùng `nhiệt_hiện_tại` thay `dự_báo_max`. Sửa [M13](01-danh-gia-thiet-ke-hien-tai.md#m13--trạng-thái-khởi-động-nguội-chưa-được-định-nghĩa).

### 4.3. `idleness` — mức rảnh

```
idleness = 1 − min(cpu_util, 100) / 100
```

Nguồn: mẫu telemetry gần nhất. Có độ trễ tối đa 2 giây — đây chính là lý do cần `availability` ở §4.5.

### 4.4. `efficiency` — hiệu suất điện

```
efficiency = 1 − clamp((power_w − p_idle) / (p_max − p_idle), 0, 1)
```

`p_idle` và `p_max` là công suất nhàn rỗi và tối đa **đo được của chính máy đó**, từ `power_model.json` ([08](08-do-cong-suat.md)).

Khi `power_source = 'none'` (máy không đọc được công suất): đặt `efficiency = 0,5` và **giảm `w_power` xuống 0, phân bổ lại cho ba trọng số còn lại theo tỷ lệ**. Không được để một hằng số bịa ảnh hưởng tới thứ hạng.

### 4.5. `availability` — mức sẵn sàng, sửa lỗi dồn đàn

```
availability = 1 − inflight / max_concurrent
```

Với `max_concurrent = 1`, giá trị này là 1 hoặc 0 — mà 0 thì đã bị lọc ở Giai đoạn 1. Nghe như thừa, nhưng nó **cần thiết vì hai lý do**:

1. `inflight` là **sự thật tức thời do host tự nắm**, không có độ trễ 2 giây như `cpu_util`. Một node vừa nhận job 200 mili-giây trước vẫn báo `cpu_util = 5%` và sẽ ghi điểm rất cao — đây chính xác là cơ chế gây dồn đàn ở [M8](01-danh-gia-thiet-ke-hien-tai.md#m8--không-có-nhận-thức-về-hàng-đợi-và-mức-đồng-thời). Giai đoạn 1 chặn được vì `max_concurrent = 1`, nhưng khi nâng lên 2 trên máy nhiều nhân thì số hạng này mới thực sự làm việc.
2. Nó làm cho ý đồ hiển thị rõ trong công thức. Người đọc code sau này thấy ngay rằng mức đồng thời có được cân nhắc.

### 4.6. `penalty` — hệ số phạt

| Điều kiện | Hệ số | Lý do |
|---|---|---|
| `WARMING_UP` | 0,7 | Chưa có dự báo → quyết định kém chắc chắn hơn |
| Giữ chỗ hết hạn trong 120 giây qua | 0,5 | Node có dấu hiệu không tin cậy |
| Job lỗi liên tiếp ≥ 2 lần | 0,3 | Có gì đó đang hỏng ở máy này |
| Bình thường | 1,0 | |

Các hệ số **nhân với nhau** khi có nhiều điều kiện cùng đúng. Một node vừa `WARMING_UP` vừa có giữ chỗ hết hạn thì hệ số là 0,35 — vẫn đủ điều kiện, nhưng chỉ thắng khi không còn ai khác.

### 4.7. Trọng số mặc định

| Trọng số | Giá trị | Lý do |
|---|---|---|
| `w_cool` | 0,40 | Nhiệt là mục đích tồn tại của sản phẩm |
| `w_idle` | 0,25 | Ảnh hưởng trực tiếp tới độ trễ trả lời |
| `w_power` | 0,15 | Có ý nghĩa ESG nhưng biến thiên nhỏ giữa các máy cùng loại |
| `w_load` | 0,20 | Chống dồn đàn |

Cấu hình được qua `POST /api/settings`; server kiểm tra tổng bằng 1,0 (sai số 0,001), lệch thì trả `422`.

### 4.8. Ví dụ tính đầy đủ

Cụm 3 máy, ngưỡng 75°C, một job chat đang chờ.

| | Node-A | Node-B | Node-C |
|---|---|---|---|
| Trạng thái | READY | READY | AT_RISK |
| Nhàn rỗi (đo được) | 35°C | 40°C | 38°C |
| Dự báo max | 72,0°C | 58,0°C | 79,0°C |
| `cpu_util` | 15% | 45% | 88% |
| `power_w` (idle 15, max 65) | 22 W | 34 W | 61 W |
| `inflight` | 0 | 0 | 1 |

**Giai đoạn 1.** Node-C bị loại (`flagged`). Còn A và B.

**Giai đoạn 2.**

```
Node-A:
  headroom     = (75 − 72,0) / (75 − 35) = 3,0/40  = 0,075
  idleness     = 1 − 15/100                        = 0,850
  efficiency   = 1 − (22−15)/(65−15) = 1 − 0,14    = 0,860
  availability = 1 − 0/1                           = 1,000
  score = 0,40×0,075 + 0,25×0,850 + 0,15×0,860 + 0,20×1,000
        = 0,030 + 0,2125 + 0,129 + 0,200          = 0,5715

Node-B:
  headroom     = (75 − 58,0) / (75 − 40) = 17,0/35 = 0,486
  idleness     = 1 − 45/100                        = 0,550
  efficiency   = 1 − (34−15)/(65−15) = 1 − 0,38    = 0,620
  availability = 1 − 0/1                           = 1,000
  score = 0,40×0,486 + 0,25×0,550 + 0,15×0,620 + 0,20×1,000
        = 0,1944 + 0,1375 + 0,093 + 0,200         = 0,6249
```

**Node-B thắng** dù đang bận hơn và tốn điện hơn — vì nó còn 49% khoảng an toàn nhiệt trong khi Node-A chỉ còn 7,5%. Đây chính là hành vi mà sản phẩm muốn bán: **hy sinh một chút độ trễ để tránh đẩy một máy tới sát ngưỡng**.

Dòng log tương ứng:

```
[SCHED] job a1b2c3d4 -> Node-B (điểm 0.625)
        headroom 0.49 | rảnh 0.55 | điện 0.62 | sẵn sàng 1.00
        đối thủ: Node-A 0.572 (headroom chỉ 0.07)
        bị loại: Node-C (flagged: dự báo 79,0°C ≥ 75,0°C)
```

---

## 5. Giai đoạn 3 — Giữ chỗ

### 5.1. Cơ chế

Tận dụng trường `target` **đã có sẵn** trong [`balancer.py:29`](../server/balancer.py) và đã được tôn trọng ở [`balancer.py:64`](../server/balancer.py):

```python
job.target = người_thắng
job.reserved_until = now + RESERVATION_TIMEOUT_S
inflight[người_thắng] += 1
```

Worker gọi `GET /jobs/next` chỉ nhận được job có `target` là chính nó. Không cần thay đổi giao thức mạng, không cần mở cổng ở worker, không phá vỡ tính chất outbound-only.

### 5.2. Vì sao phải có hạn giữ chỗ

Ở PoC, `target=None` nghĩa là ai đến trước lấy trước — job không bao giờ kẹt. Khi chuyển sang giữ chỗ, **một node treo sẽ nuốt job vĩnh viễn**. Hạn giữ chỗ là bắt buộc, không phải tùy chọn. Đây là chi phí trực tiếp của việc sửa [S1](01-danh-gia-thiet-ke-hien-tai.md#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại), và phải được ghi ngay cạnh phần lợi ích.

### 5.3. Vòng thu hồi

Chạy mỗi 1 giây:

```
với mỗi job có target ≠ None và reserved_until < now:
    log: "[SCHED] job {id} giữ chỗ hết hạn ở {node} sau {timeout}s → trả về hàng đợi"
    inflight[node] -= 1
    job.target = None
    node.recently_failed_until = now + 120     # hệ số phạt 0,5 ở §4.6
    job quay lại đầu hàng đợi để chấm điểm lại
```

Đưa về **đầu** hàng đợi chứ không phải cuối: job này đã chờ lâu rồi, đẩy xuống cuối là phạt người dùng vì lỗi của máy.

### 5.4. Chống lặp vô hạn

Job mang bộ đếm `attempts`. Vượt `MAX_ATTEMPTS = 3` thì thất bại với `error.code = "NO_CAPACITY"` và thông điệp liệt kê từng node cùng lý do bị loại. Thà báo lỗi rõ ràng còn hơn quay vòng im lặng.

---

## 6. Băng trễ trong quyết định gắn cờ

Sửa [M7](01-danh-gia-thiet-ke-hien-tai.md#m7--không-có-trễ-trong-quyết-định-gắn-cờ--node-dao-động-quanh-ngưỡng). Thay thế logic ở [`server.py:91-100`](../server/server.py).

```
GẮN CỜ  khi  dự_báo_max ≥ ngưỡng
             VÀ trạng thái hiện tại là READY
             VÀ (now − lần_đổi_trạng_thái_cuối) ≥ MIN_DWELL_S

GỠ CỜ   khi  dự_báo_max ≤ ngưỡng − HYSTERESIS_C
             VÀ trạng thái hiện tại là AT_RISK
             VÀ (now − lần_đổi_trạng_thái_cuối) ≥ MIN_DWELL_S
```

Với ngưỡng 75°C và `HYSTERESIS_C = 3`: gắn cờ ở ≥75,0°C, chỉ gỡ khi ≤72,0°C. Một node dao động trong khoảng 72–75°C **giữ nguyên trạng thái hiện tại** thay vì nhấp nháy.

`MIN_DWELL_S = 30` chặn trường hợp dự báo nhảy vọt qua cả băng trễ do một mẫu nhiễu.

**Vì sao điều này quan trọng hơn với chat so với burn job.** Một burn job bị hủy giữa chừng không mất gì. Một job chat bị dời máy giữa chừng mất toàn bộ phần xử lý prompt đã làm (`prompt_eval_ms` trong [03 §5](03-hop-dong-api.md#post-jobsresult)) và phải bắt đầu lại từ đầu ở máy mới. Dao động trạng thái ở đây tốn thật, không chỉ gây rối mắt.

---

## 7. Mã giả đầy đủ

```python
# scheduler.py — chỉ đọc ForecastCache, không chạm cơ sở dữ liệu

RESERVATION_TIMEOUT_S = 20.0
MAX_ATTEMPTS = 3
FAILED_PENALTY_WINDOW_S = 120.0

def filter_candidates(cache, job, now):
    """Giai đoạn 1. Trả về (ứng_viên, lý_do_loại) — cả hai đều để ghi log."""
    candidates, rejected = [], {}
    for node, f in cache.items():
        if f.state not in ("READY", "WARMING_UP"):
            rejected[node] = f"state_{f.state.lower()}"
        elif f.state == "AT_RISK" or f.flagged:
            rejected[node] = f"flagged (dự báo {f.predicted_max_c:.1f}°C)"
        elif f.inflight >= f.max_concurrent:
            rejected[node] = f"busy ({f.inflight}/{f.max_concurrent})"
        elif not f.model_ready:
            rejected[node] = "model_not_ready"
        elif not meets_capability(f, job):
            rejected[node] = "insufficient_capability"
        elif (now - f.last_sample_ts) > STALE_AFTER_S:
            rejected[node] = f"stale_telemetry ({now - f.last_sample_ts:.0f}s)"
        else:
            candidates.append(node)
    return candidates, rejected


def score_node(f, weights, now):
    """Giai đoạn 2. Trả về (điểm, các_thành_phần) — thành phần để ghi log."""
    temp = f.predicted_max_c if f.predicted_max_c is not None else f.current_temp_c
    span = max(f.effective_threshold_c - f.idle_baseline_c, 1.0)   # tránh chia 0
    headroom = clamp((f.effective_threshold_c - temp) / span, 0.0, 1.0)

    idleness = 1.0 - clamp((f.cpu_util or 0.0) / 100.0, 0.0, 1.0)

    w = dict(weights)
    if f.power_source == "none":
        efficiency = 0.5
        w = redistribute(w, drop="power")   # không để hằng số bịa ảnh hưởng thứ hạng
    else:
        p_span = max(f.p_max_w - f.p_idle_w, 1.0)
        efficiency = 1.0 - clamp((f.power_w - f.p_idle_w) / p_span, 0.0, 1.0)

    availability = 1.0 - clamp(f.inflight / max(f.max_concurrent, 1), 0.0, 1.0)

    base = (w["cool"]  * headroom
          + w["idle"]  * idleness
          + w["power"] * efficiency
          + w["load"]  * availability)

    penalty = 1.0
    if f.state == "WARMING_UP":
        penalty *= 0.7
    if now < f.recently_failed_until:
        penalty *= 0.5
    if f.consecutive_errors >= 2:
        penalty *= 0.3

    return base * penalty, {
        "headroom": headroom, "idleness": idleness,
        "efficiency": efficiency, "availability": availability,
        "penalty": penalty,
    }


def schedule_once(cache, queue, weights, now, log):
    """Một lượt scheduler. Chạy mỗi 1 giây."""
    for job in queue.pending():                       # FIFO
        candidates, rejected = filter_candidates(cache, job, now)

        if not candidates:
            log.info("[SCHED] job %s không có ứng viên: %s", job.id, fmt(rejected))
            if host_can_infer(cache, now):
                assign_to_host(job, now)
            continue

        scored = [(score_node(cache[n], weights, now), n) for n in candidates]
        (best_score, parts), winner = max(scored, key=lambda x: x[0][0])

        job.target = winner
        job.reserved_until = now + RESERVATION_TIMEOUT_S
        job.attempts += 1
        cache[winner].inflight += 1

        log.info("[SCHED] job %s -> %s (điểm %.3f) headroom %.2f | rảnh %.2f | "
                 "điện %.2f | sẵn sàng %.2f | phạt %.2f | bị loại: %s",
                 job.id, winner, best_score, parts["headroom"], parts["idleness"],
                 parts["efficiency"], parts["availability"], parts["penalty"],
                 fmt(rejected))


def reap_expired(cache, queue, now, log):
    """Vòng thu hồi. Chạy mỗi 1 giây. BẮT BUỘC — xem §5.2."""
    for job in queue.reserved():
        if job.reserved_until >= now:
            continue
        node = job.target
        log.info("[SCHED] job %s giữ chỗ hết hạn ở %s → trả về hàng đợi "
                 "(lần thử %d/%d)", job.id, node, job.attempts, MAX_ATTEMPTS)
        cache[node].inflight = max(0, cache[node].inflight - 1)
        cache[node].recently_failed_until = now + FAILED_PENALTY_WINDOW_S
        job.target = None
        if job.attempts >= MAX_ATTEMPTS:
            queue.fail(job, code="NO_CAPACITY")
        else:
            queue.requeue_front(job)
```

---

## 8. Hằng số và mặc định

| Hằng số | Giá trị | Nguồn | Ghi chú |
|---|---|---|---|
| `HYSTERESIS_C` | 3,0 | mới | Băng trễ gắn/gỡ cờ |
| `MIN_DWELL_S` | 30,0 | mới | Thời gian lưu trú tối thiểu |
| `RESERVATION_TIMEOUT_S` | 20,0 | **ADR-005** | Xác nhận sau G3: ~59 tok/s trên máy mẫu → câu ~200 token ≈ 3–5s + biên → 20s đủ; tăng nếu đổi sang 1,5B hoặc `max_tokens` cao |
| `MAX_ATTEMPTS` | 3 | mới | Chống lặp vô hạn |
| `FAILED_PENALTY_WINDOW_S` | 120,0 | mới | Thời gian phạt sau khi giữ chỗ hết hạn |
| `MAX_CONCURRENT_DEFAULT` | 1 | **ADR-005** | Chốt = 1 (CPU, `--threads = nhân−2`); chỉ nâng sau khi đo ≥2 máy |
| `SCHEDULE_EVERY_S` | 1,0 | mới | Nhịp vòng scheduler |
| `STALE_AFTER_S` | 10,0 | [`server.py:32`](../server/server.py) | Giữ nguyên |
| `FORECAST_EVERY_S` | 5,0 | [`server.py:30`](../server/server.py) | Giữ nguyên |
| `WINDOW_S` | 180,0 | [`server.py:29`](../server/server.py) | Giữ nguyên |

**Vì sao `RESERVATION_TIMEOUT_S = 20`.** Phải lớn hơn thời gian suy luận điển hình cộng độ trễ long-poll, nếu không job bị thu hồi khi worker vẫn đang chạy đúng. Benchmark G3 ([ADR-005](adr/ADR-005-llm-runtime.md)): Qwen2.5-0.5B Q4 ≈ 59 tok/s trên máy mẫu → 3–10 giây suy luận + tối đa 1 giây nhận job + biên an toàn → 20 giây. Với mô hình lớn hơn hoặc `max_tokens` cao, giá trị này phải tăng theo — nên đặt trong cấu hình phòng, không hard-code.

---

## 9. Bảng ca kiểm thử

Toàn bộ test dưới đây chỉ cần một `ForecastCache` giả — không cần cơ sở dữ liệu, không cần worker thật. Đây là lợi ích trực tiếp của nguyên tắc 6 ở §1.

### Lọc

| # | Tình huống | Kỳ vọng |
|---|---|---|
| F1 | Node bị gắn cờ | Bị loại, lý do `flagged` |
| F2 | Node `inflight = 1`, `max_concurrent = 1` | Bị loại, lý do `busy` |
| F3 | Node `STALE` | Bị loại |
| F4 | Node `WARMING_UP` | **Không** bị loại |
| F5 | Node `JOINING` | Bị loại |
| F6 | Mọi node bị loại | Trả tập rỗng + từ điển lý do đầy đủ |
| F7 | Telemetry cũ 47s | Bị loại, lý do `stale_telemetry` |

### Chấm điểm

| # | Tình huống | Kỳ vọng |
|---|---|---|
| S1 | Ví dụ §4.8 | Node-B thắng, điểm 0,625 ± 0,001 |
| S2 | Hai node giống hệt | Điểm bằng nhau; phá hòa theo thứ tự tên (tất định) |
| S3 | Node `power_source='none'` | `w_power` phân bổ lại, tổng trọng số vẫn = 1 |
| S4 | Node `WARMING_UP` | Điểm nhân 0,7 |
| S5 | Node vừa có giữ chỗ hết hạn | Điểm nhân 0,5 |
| S6 | Cả `WARMING_UP` lẫn giữ chỗ hết hạn | Điểm nhân 0,35 |
| S7 | Dự báo vượt ngưỡng nhưng chưa gắn cờ (`MIN_DWELL`) | `headroom = 0`, không âm |
| S8 | `idle_baseline = ngưỡng` (chia 0) | Không sập; `span` bị chặn dưới bởi 1,0 |
| S9 | **Thêm node rất nóng vào cụm** | **Điểm của node cũ không đổi** — chứng minh [M11](01-danh-gia-thiet-ke-hien-tai.md#m11--hàm-normalize-chưa-được-định-nghĩa-và-sẽ-không-ổn-định) đã sửa |
| S10 | Cùng dự báo 70°C, hai máy khác `baseline` | `headroom` khác nhau rõ rệt (bảng §4.2) |

### Giữ chỗ

| # | Tình huống | Kỳ vọng |
|---|---|---|
| R1 | Job giữ chỗ cho Node-A | Node-B gọi `/jobs/next` → 204 |
| R2 | Job giữ chỗ cho Node-A | Node-A gọi `/jobs/next` → 200 |
| R3 | Giữ chỗ hết hạn | `inflight` giảm, job về đầu hàng đợi, node bị phạt |
| R4 | Hết hạn 3 lần | Job thất bại với `NO_CAPACITY` |
| R5 | Job hoàn thành | `inflight` giảm, ghi `esg_events` |
| R6 | Node bị kick khi đang giữ chỗ | Job trả về hàng đợi ngay, không đợi hết hạn |

### Băng trễ

| # | Chuỗi dự báo (ngưỡng 75) | Kỳ vọng |
|---|---|---|
| H1 | 74 → 76 | Gắn cờ |
| H2 | 76 → 74 | **Vẫn gắn cờ** (74 > 72) |
| H3 | 76 → 71 | Gỡ cờ |
| H4 | 74→76→74→76 trong 10s | Đổi trạng thái đúng **một** lần (`MIN_DWELL`) |
| H5 | 76, chờ 40s, 71 | Gỡ cờ (đã qua `MIN_DWELL`) |

### Tích hợp

| # | Tình huống | Kỳ vọng |
|---|---|---|
| I1 | 10 node giả, 50 job chat | Không job nào tới node bị gắn cờ; phân bố lệch về node mát |
| I2 | Node đang chạy job thì bị gắn cờ | Job hiện tại **chạy tiếp**; chỉ job mới bị chặn |
| I3 | Tất cả node bị gắn cờ, host chạy được | Host tự suy luận |
| I4 | Tất cả node bị gắn cờ, host không chạy được | Job chờ; dashboard hiện "đang chờ máy rảnh" |
| I5 | Worker chết giữa lúc suy luận | Hết hạn → node khác → người dùng vẫn nhận được trả lời |

---

## 10. Chế độ round-robin cho A/B

Để đo được lợi ích thật ([07 §Tầng 1](07-esg-3-tang.md)), scheduler phải chạy được ở chế độ ngây thơ để làm mốc so sánh.

```
scheduler_mode = "thermal_aware"   (mặc định)
               | "round_robin"     (mốc so sánh)
```

Ở chế độ `round_robin`: **giữ nguyên Giai đoạn 1** (vẫn không gửi job cho node đã chết hoặc đang bận — nếu không thì phép so sánh không công bằng), nhưng **bỏ qua Giai đoạn 2** và chọn xoay vòng. Đặc biệt: ở chế độ này, node bị gắn cờ **vẫn nhận job** — đó chính là điều kiện đối chứng.

Chế độ hiện tại được ghi vào từng bản ghi `esg_events`, nên báo cáo A/B tính được trực tiếp từ nhật ký mà không cần đo riêng.

Kịch bản chạy: `Host.exe --ab-benchmark` — bộ prompt cố định, chạy hai lượt, xuất bảng so sánh J/token. Chi tiết ở [07](07-esg-3-tang.md).
