# 07 — ESG ba tầng

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Sửa lỗi: [S3](01-danh-gia-thiet-ke-hien-tai.md#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được), [S5](01-danh-gia-thiet-ke-hien-tai.md#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram)
> Quyết định: [ADR-003](adr/ADR-003-esg-ba-tang.md) · Cách lấy số watt: [08](08-do-cong-suat.md)

## Mục lục

- [Vì sao phải làm lại](#1-vì-sao-phải-làm-lại)
- [Nguyên tắc ba tầng](#2-nguyên-tắc-ba-tầng)
- [Tầng 1 — ĐO THẬT](#3-tầng-1--đo-thật)
- [Tầng 2 — SUY RA](#4-tầng-2--suy-ra)
- [Tầng 3 — NGOẠI SUY](#5-tầng-3--ngoại-suy)
- [Nhật ký sự kiện](#6-nhật-ký-sự-kiện--nguồn-gốc-của-mọi-con-số)
- [Chống thao túng chỉ số](#7-chống-thao-túng-chỉ-số)
- [Trình bày trên dashboard](#8-trình-bày-trên-dashboard)
- [Cấu hình](#9-cấu-hình)
- [Câu hỏi phản biện và câu trả lời](#10-câu-hỏi-phản-biện-và-câu-trả-lời)

---

## 1. Vì sao phải làm lại

Công thức trong PoC — [`esg.py:11`](../server/esg.py):

```python
kwh_saved = hot_hours × node_power_kw × cooling_overhead_factor
```

Bốn vấn đề, mỗi vấn đề đủ để một người phản biện có chuyên môn bác bỏ toàn bộ panel:

| # | Vấn đề | Minh chứng |
|---|---|---|
| 1 | Đếm *thời gian né* rồi gọi là *năng lượng tiết kiệm* | Job vẫn chạy ở máy khác. Tổng điện cụm gần như không đổi |
| 2 | Bị thao túng được | Đặt ngưỡng 40°C → mọi node luôn bị gắn cờ → "tiết kiệm" tăng tuyến tính trong khi hệ thống **không dispatch được job nào** |
| 3 | Không có mẫu số | Không so với khối lượng công việc nào. Làm ít việc nhất = báo cáo tiết kiệm nhiều nhất |
| 4 | Hằng số không có nguồn | `cooling_overhead_factor = 0.5` tương đương PUE 1,5 — con số của trung tâm dữ liệu, áp lên máy văn phòng |

Phân tích đầy đủ: [01 §S3](01-danh-gia-thiet-ke-hien-tai.md#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được).

**Điều tốt lành:** thiết kế LLM mới cho sẵn thứ mà PoC thiếu — **một mẫu số có nghĩa: số token sinh ra**. Nhờ đó chỉ số hiệu quả năng lượng trở thành một đại lượng đo được, không phải một giả định.

---

## 2. Nguyên tắc ba tầng

```
┌───────────────────────────────────────────────────────────────┐
│  TẦNG 1 — ĐO THẬT                          bảo vệ được 100%   │
│  Con số lấy trực tiếp từ cảm biến và bộ đếm.                  │
│  J/token · so sánh A/B · giây throttle tránh được             │
├───────────────────────────────────────────────────────────────┤
│  TẦNG 2 — SUY RA                    có giả định, ghi rõ ràng  │
│  Con số tính từ mô hình vật lý dựa trên số đo Tầng 1.         │
│  Điện rò theo nhiệt · điện quạt · hệ số làm mát theo site     │
├───────────────────────────────────────────────────────────────┤
│  TẦNG 3 — NGOẠI SUY                     dự phóng, không phải  │
│  Chiếu tuyến tính lên quy mô lớn hơn.        kết quả đo       │
│  N node × T thời gian · VNĐ · CO₂ · định giá carbon           │
└───────────────────────────────────────────────────────────────┘
```

**Ba quy tắc bất di bất dịch:**

1. **Không bao giờ cộng gộp ba tầng thành một con số.** Trong API chúng là ba đối tượng JSON riêng ([03 §7](03-hop-dong-api.md#get-apistate)); trên giao diện là ba khối tách bạch có màu và nhãn khác nhau.
2. **Mỗi con số Tầng 2 phải hiện giả định ngay cạnh nó**, không giấu trong tài liệu.
3. **Mọi con số Tầng 3 phải mang nhãn "DỰ PHÓNG"** ở đúng chỗ nó hiển thị.

Cách này không làm câu chuyện thương mại yếu đi. Nó làm câu chuyện **đứng vững** — vì phần bị chất vấn (Tầng 3) không kéo theo phần đo được (Tầng 1) sụp đổ.

---

## 3. Tầng 1 — ĐO THẬT

### 3.1. Joule trên token

Chỉ số chủ đạo của toàn hệ thống.

```
J_per_token = Σ energy_j / Σ tokens_out      (trên tập job đã hoàn thành)
```

Cả hai đại lượng đến từ `POST /jobs/result` ([03 §5](03-hop-dong-api.md#post-jobsresult)), do worker đo trong lúc chạy:

```
energy_j = ∫ P(t) dt   trên khoảng chạy job, tích phân hình thang
                        qua các mẫu công suất

tokens_out = bộ đếm của runtime LLM
```

**Điều kiện hợp lệ.** Một job chỉ được tính vào Tầng 1 khi `energy_source = 'sensor'`. Job có `energy_source = 'model'` (công suất ước lượng) đi vào Tầng 2. Job có `energy_source = 'none'` **không được tính vào bất kỳ tầng nào** — chỉ đếm token.

Đây là ranh giới quan trọng nhất của toàn bộ tài liệu: **số đo và số ước lượng không bao giờ được trộn chung một phép cộng.**

**Độ tin cậy theo cỡ mẫu.**

| Số job có `energy_source='sensor'` | Nhãn hiển thị |
|---|---|
| < 20 | `chưa đủ dữ liệu` — hiện J/token nhưng làm mờ, không hiện phần trăm cải thiện |
| 20 – 99 | `sơ bộ` |
| ≥ 100 | `ok` |

### 3.2. So sánh A/B — con số bán hàng

Đây là bằng chứng duy nhất cho câu "điều phối theo nhiệt giúp tiết kiệm năng lượng". Không có nó, mọi thứ chỉ là giả thuyết.

**Giao thức:**

```
1. Cố định một bộ prompt (khuyến nghị 50 prompt, độ dài đa dạng, lưu trong repo)
2. Cố định tham số sinh: max_tokens, temperature, seed
3. Lượt A — scheduler_mode = "round_robin":
      job chia xoay vòng, node bị gắn cờ VẪN nhận job
4. Nghỉ đủ lâu để mọi máy về nhiệt nhàn rỗi (≥10 phút, kiểm tra bằng telemetry)
5. Lượt B — scheduler_mode = "thermal_aware":
      chấm điểm đầy đủ theo 04-dac-ta-scheduler.md
6. So sánh:  J/token, độ trễ trung vị, độ trễ p95,
             tổng giây throttle, nhiệt đỉnh cụm
```

Chế độ được ghi vào từng bản ghi `esg_events`, nên báo cáo tính trực tiếp từ nhật ký — không cần công cụ đo riêng.

```
improvement_pct = (J_per_token_round_robin − J_per_token_thermal_aware)
                  / J_per_token_round_robin × 100
```

**Cảnh báo trung thực phải ghi trong báo cáo:** cải thiện có thể là **số âm**. Điều phối theo nhiệt đôi khi chọn máy chậm hơn để tránh máy nóng, và như vậy tốn nhiều Joule hơn cho cùng số token. Nếu kết quả ra âm, **phải báo cáo đúng như vậy** — và đó vẫn là một phát hiện có giá trị: nó nói rằng ở quy mô này, lợi ích nằm ở tuổi thọ phần cứng và độ ổn định hiệu năng chứ không ở hóa đơn điện. Một kết quả âm được báo cáo trung thực đáng tin hơn nhiều so với một kết quả dương không kiểm chứng được.

Chạy bằng: `Host.exe --ab-benchmark`.

### 3.3. Thời gian throttle tránh được

Đây là nguồn tiết kiệm năng lượng **thật** và **đo được**.

Cơ chế: CPU bị throttle chạy xung thấp → cùng một job mất nhiều thời gian hơn → tiêu tốn nhiều năng lượng hơn cho **cùng một khối lượng việc** (vì phần điện nền của toàn máy — RAM, ổ đĩa, màn hình, mạch nguồn — vẫn chạy suốt thời gian dài hơn đó).

Phát hiện throttle từ `cpu_clock_mhz` trong telemetry và `min_clock_mhz` trong kết quả job:

```
throttled = (cpu_clock_mhz < base_clock_mhz × 0,90)  VÀ  (cpu_util > 70)
```

Ngưỡng 90% base clock, không phải turbo clock — turbo giảm là hành vi bình thường, không phải throttle.

```
throttle_seconds_avoided = Σ giây throttle ở lượt round_robin
                         − Σ giây throttle ở lượt thermal_aware
```

Nếu `cpu_clock_mhz` không đọc được trên phần cứng của bạn, chỉ số này bị bỏ trống và được ghi rõ là "không khả dụng" — **không thay bằng ước lượng**.

### 3.4. Các số đo phụ

| Chỉ số | Đơn vị | Nguồn |
|---|---|---|
| Nhiệt đỉnh cụm | °C | max `peak_temp_c` trên mọi job |
| Số phút vận hành trên ngưỡng | phút | Đếm từ telemetry |
| Độ trễ trung vị / p95 | ms | `duration_ms` từ kết quả job |
| Sai số dự báo thực tế | °C | \|`peak_temp_c` − `predicted_max` tại lúc gán\| |

Dòng cuối đáng chú ý: nó cho **sai số dự báo trong vận hành thật**, khác với MAE trên tập kiểm tra lúc huấn luyện ([05](05-du-bao-nhiet.md)). Đây là con số trung thực hơn nhiều để nói về chất lượng mô hình.

---

## 4. Tầng 2 — SUY RA

Mỗi chỉ số ở tầng này đi kèm **giả định hiển thị ngay cạnh nó**.

### 4.1. Điện rò theo nhiệt

**Cơ chế vật lý.** Dòng rò dưới ngưỡng của transistor tăng gần như hàm mũ theo nhiệt độ. Cùng một khối lượng việc, chip ở 85°C tiêu thụ nhiều hơn chính nó ở 55°C.

**Cách đo hệ số cho chính máy của bạn** — không lấy từ tài liệu, mà tính từ dữ liệu hiệu chuẩn:

```
Lấy các mẫu có cùng mức cpu_util (±3%) nhưng khác nhiệt độ
Hồi quy:  power_w = a + b × cpu_util + c × cpu_temp
Hệ số rò = c / (a + b × 50)     → đơn vị: phần trăm trên mỗi °C
```

`power_model_fit.py` ([08](08-do-cong-suat.md)) xuất chính hệ số `c` này.

```
kwh_leakage_saved = Σ_job  (ΔT_tránh_được × c × duration_h) / 1000

trong đó ΔT_tránh_được = nhiệt_node_bị_né − nhiệt_node_được_chọn
                          tại thời điểm gán job
```

**Giả định phải hiển thị:** *"Hệ số rò c = 0,18 W/°C, đo trên Node-A ngày 15/03. Giả định các máy khác cùng hệ số."*

Giá trị điển hình: 0,3–0,6% công suất trên mỗi °C. Nếu số đo của bạn lệch xa khoảng này, nhiều khả năng phép hồi quy bị nhiễu chứ không phải phần cứng đặc biệt — hãy kiểm tra lại dữ liệu.

### 4.2. Điện quạt

Công suất quạt xấp xỉ bậc ba theo tốc độ. Chip mát hơn → quạt chậm hơn → tiết kiệm phi tuyến.

```
P_quạt ≈ P_max_quạt × (rpm / rpm_max)³
kwh_fan_saved = Σ (P_quạt_nóng − P_quạt_mát) × duration_h / 1000
```

Chỉ tính khi `fan_rpm` đọc được. Với laptop, `P_max_quạt` thường 2–4 W — đóng góp nhỏ nhưng có thật và **đo được trực tiếp qua rpm**, nên độ tin cậy khá cao so với phần còn lại của tầng này.

### 4.3. Hệ số chi phí làm mát theo site — chỗ thời tiết thực sự có ích

Đây là nơi duy nhất thời tiết có ý nghĩa vật lý, và **không phải trong công thức chấm điểm** ([M12](01-danh-gia-thiet-ke-hien-tai.md#m12--thời-tiết-trong-công-thức-chấm-điểm-gần-như-vô-nghĩa)).

Cơ chế: hiệu suất điều hòa (COP) giảm khi chênh lệch nhiệt độ trong–ngoài tăng. Cùng 1 kWh nhiệt thải ra phòng, ngày 38°C tốn nhiều điện làm mát hơn ngày 24°C.

```
cooling_factor(site, t) = base_factor × (1 + k × max(0, T_ngoài − T_tham_chiếu))

Mặc định: base_factor = 0,25   (không phải 0,5 như PoC — xem bên dưới)
          k = 0,02 mỗi °C
          T_tham_chiếu = 25°C
```

**Vì sao hạ từ 0,5 xuống 0,25.** Hằng số 0,5 tương đương PUE 1,5 — con số của một trung tâm dữ liệu có hệ thống làm mát chuyên dụng. Hệ thống này chạy trên **máy tính văn phòng trong phòng có điều hòa dùng chung với con người**. Nhiệt từ 10 máy tính là một phần nhỏ trong tổng tải nhiệt của phòng (còn người, đèn, nắng qua cửa sổ). 0,25 vẫn là ước lượng, nhưng là ước lượng **thận trọng** — và ở tầng này, thận trọng là đúng hướng.

**Giả định phải hiển thị:** *"Giả định 0,25 kWh làm mát cho mỗi 1 kWh tính toán, điều chỉnh theo nhiệt độ ngoài trời. Chưa hiệu chuẩn bằng đo thực tế."*

---

## 5. Tầng 3 — NGOẠI SUY

Mọi thứ ở tầng này mang nhãn **DỰ PHÓNG** hiển thị ngay cạnh con số, không phải trong chú thích cuối trang.

### 5.1. Chiếu lên quy mô

**Cập nhật (G4++):** không còn cộng `kwh_tier1 + kwh_tier2` thành một `kwh_projected`. Chiếu **riêng** số đo và số suy ra (bất biến ba tầng + ADR-003):

```
kwh_projected_measured = kwh_tier1 / (số_node_thật × giờ_đo)
                         × số_node_dự_phóng × giờ_dự_phóng

kwh_projected_derived  = kwh_tier2 / (số_node_thật × giờ_đo)
                         × số_node_dự_phóng × giờ_dự_phóng
```

(Công thức cũ cộng hai tầng rồi chiếu **đã bỏ** — tránh một con số trông như “tiết kiệm đo được”.)

Mặc định: 1.000 node × 365 ngày. Cấu hình được.

### 5.2. Quy đổi tiền và CO₂

```
vnd  = kwh × price_vnd_per_kwh     (mặc định 2.500 ₫/kWh)
usd  = kwh × price_usd_per_kwh     (mặc định 0,10 $/kWh)
co2  = kwh × co2_kg_per_kwh        (mặc định 0,72 kg/kWh)
```

Hệ số phát thải 0,72 kg CO₂/kWh gần với lưới điện Việt Nam. **Phải ghi nguồn và năm** — hệ số này thay đổi hằng năm khi tỷ trọng tái tạo tăng, và một báo cáo ESG dùng số cũ 5 năm sẽ bị bác.

### 5.3. Định giá carbon — nói thẳng về quy mô

Thiết kế ban đầu đề xuất `giá_trị = tấn_CO₂ × giá`. Con số thật ở quy mô PoC:

```
1 giờ node được điều phối tốt hơn
  → tiết kiệm bậc 0,01 kWh
  → 0,0072 kg CO₂
  → 0,0000072 tCO₂
  → ở giá 20 USD/tCO₂:  0,000144 USD  ≈  0,15 ₫
```

Hiển thị "**giá trị tín chỉ carbon: 0,15 ₫**" sẽ phá hỏng độ tin cậy của cả panel, kể cả những con số đúng bên cạnh.

**Quy tắc trình bày bắt buộc:**

- Chỉ hiện định giá carbon **ở Tầng 3, sau khi đã ngoại suy quy mô**
- Luôn kèm dòng: *"Ở quy mô 1.000 máy trong 1 năm. Quy mô thử nghiệm hiện tại là {N} máy trong {T} giờ."*
- Không bao giờ hiện định giá carbon cho số đo thời gian thực
- Không dùng từ "tín chỉ" mà không có chữ "tiềm năng, ước lượng" đi kèm — tín chỉ carbon là một công cụ tài chính có quy trình kiểm định riêng, và hệ thống này không tạo ra chúng

---

## 6. Nhật ký sự kiện — nguồn gốc của mọi con số

Sửa [S5](01-danh-gia-thiet-ke-hien-tai.md#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram). PoC giữ trạng thái ESG trong biến instance ([`esg.py:30`](../server/esg.py)) — host khởi động lại là mất sạch, và không có vết kiểm toán.

```sql
CREATE TABLE esg_events (
  id INTEGER PRIMARY KEY,
  node TEXT NOT NULL,
  event TEXT NOT NULL,        -- flagged | cleared | threshold_changed | job_completed
  ts REAL NOT NULL,
  threshold_at_time REAL,
  predicted_max REAL,
  detail TEXT                 -- JSON
);
```

`detail` cho `job_completed`:

```json
{
  "job_id": "a1b2c3d4",
  "tokens_out": 187,
  "tokens_in": 12,
  "energy_j": 142.6,
  "energy_source": "sensor",
  "duration_ms": 4820,
  "peak_temp_c": 71.2,
  "min_clock_mhz": 3100,
  "scheduler_mode": "thermal_aware",
  "predicted_at_dispatch": 66.1
}
```

**Báo cáo trở thành một hàm thuần túy:**

```python
def build_report(events, config, from_ts, to_ts) -> EsgReport:
    """Không có trạng thái. Cùng đầu vào → cùng đầu ra. Luôn luôn."""
```

Năm lợi ích, tất cả đều là sửa lỗi thật:

1. **Tái lập được** — khởi động lại host không mất gì
2. **Kiểm toán được** — mọi con số truy ngược tới sự kiện gốc; đây là điều kiện tiên quyết để báo cáo có giá trị với bên thứ ba
3. **Tính lại được** — đổi hằng số ESG rồi tính lại toàn bộ lịch sử, không cần chạy lại thí nghiệm
4. **Cắt theo thời gian** — báo cáo tuần, tháng, hoặc riêng một lượt A/B
5. **Test được** — nạp sự kiện giả, khẳng định kết quả; không cần chạy hệ thống thật

---

## 7. Chống thao túng chỉ số

Bốn cơ chế, mỗi cơ chế chặn một đường thao túng cụ thể.

### 7.1. Sàn ngưỡng theo nhiệt nhàn rỗi đo được

Chặn đường tấn công chính ở [S3.2](01-danh-gia-thiet-ke-hien-tai.md#vấn-đề-32--chỉ-số-bị-thao-túng-hạ-ngưỡng-là-số-tự-đẹp-lên).

```
ngưỡng_tối_thiểu = max(40, max(idle_baseline_c của mọi node hoạt động) + 8)
```

Đặt thấp hơn → `422 THRESHOLD_TOO_LOW` ([03 §7](03-hop-dong-api.md#post-apisettings)), kèm giải thích rằng ngưỡng dưới nền nhiệt nhàn rỗi sẽ gắn cờ vĩnh viễn mọi máy.

### 7.2. Chỉ số chủ đạo có mẫu số

J/token **không thể** cải thiện bằng cách gắn cờ nhiều hơn. Gắn cờ nhiều hơn → ít job hoàn thành hơn → ít token hơn → tỷ số không tự đẹp lên. Đây là tuyến phòng thủ mạnh nhất, vì nó là tính chất toán học chứ không phải một luật kiểm tra có thể quên áp dụng.

### 7.3. Ngưỡng được ghi vào từng sự kiện

`threshold_at_time` có mặt trong mọi bản ghi. Báo cáo phải hiện ngưỡng có hiệu lực trong kỳ; nếu ngưỡng đổi giữa chừng, báo cáo **tách khoảng thời gian** thay vì cộng gộp hai chế độ khác nhau thành một con số vô nghĩa.

### 7.4. Không hiện phần trăm cải thiện khi thiếu dữ liệu

Dưới 20 job có `energy_source='sensor'`, chỉ hiện J/token thô, không hiện phần trăm cải thiện. Ngăn việc trưng ra "cải thiện 40%" tính từ ba mẫu.

---

## 8. Trình bày trên dashboard

```
┌─ 💚 TIẾT KIỆM & ESG ────────────────────────────────────────┐
│                                                              │
│  ┌─ ĐO THẬT ────────────────────────────── 🟢 độ tin cậy ok ┐│
│  │  Năng lượng / token        0,78 J     ↓14,3% so mốc      ││
│  │  Mốc round-robin           0,91 J                        ││
│  │  Throttle tránh được       142 giây                      ││
│  │  Độ trễ trung vị           4,2 s   (mốc: 3,8 s)          ││
│  │  Dựa trên 87 job có đo công suất trực tiếp               ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ SUY RA ─────────────────────────────── 🟡 có giả định ──┐│
│  │  Điện rò tiết kiệm         0,0031 kWh                    ││
│  │    └ hệ số rò 0,18 W/°C, đo trên Node-A ngày 15/03       ││
│  │  Điện quạt tiết kiệm       0,0008 kWh                    ││
│  │    └ quạt ~ bậc 3 theo tốc độ, P_max 3 W                 ││
│  │  Làm mát phòng             0,0009 kWh                    ││
│  │    └ hệ số 0,25 + hiệu chỉnh thời tiết (ngoài trời 34°C) ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ DỰ PHÓNG ────────────── ⚪ KHÔNG PHẢI SỐ ĐO ───────────┐│
│  │  Nếu triển khai 1.000 máy trong 1 năm:                   ││
│  │    Điện             4.830 kWh                            ││
│  │    Chi phí          12.075.000 ₫                         ││
│  │    CO₂              3.478 kg                             ││
│  │    Tín chỉ tiềm năng (ước lượng)  ~1.740.000 ₫           ││
│  │  ⓘ Chiếu tuyến tính từ 3 máy trong 4,2 giờ.              ││
│  │    Chưa tính hiệu ứng quy mô, hạ tầng làm mát khác biệt, ││
│  │    hay biến động giá điện. Không phải cam kết.           ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  [ Xuất CSV ]  [ Xuất nhật ký sự kiện ]  [ Chạy A/B ]        │
└──────────────────────────────────────────────────────────────┘
```

Ba khối, ba màu, ba nhãn độ tin cậy. **Không có dòng tổng ở cuối** — đó là điểm cốt lõi của thiết kế này.

---

## 9. Cấu hình

`esg_config.json` mở rộng từ [tệp hiện có](../server/esg_config.json):

```json
{
  "_comment": "Hằng số ESG. Mỗi giá trị phải ghi nguồn ở trường _source tương ứng.",

  "tier1": {
    "min_samples_for_confidence": 100,
    "min_samples_to_show": 20,
    "throttle_clock_ratio": 0.90
  },

  "tier2": {
    "leakage_w_per_c": null,
    "_leakage_source": "để null cho tới khi power_model_fit.py đo được",
    "fan_max_w": 3.0,
    "_fan_source": "ước lượng cho quạt laptop; đo lại nếu có số thật",
    "cooling_base_factor": 0.25,
    "_cooling_source": "ước lượng thận trọng cho phòng văn phòng, KHÔNG phải PUE data center",
    "cooling_weather_k": 0.02,
    "cooling_reference_temp_c": 25.0
  },

  "tier3": {
    "scale_nodes": 1000,
    "scale_days": 365,
    "price_vnd_per_kwh": 2500,
    "price_usd_per_kwh": 0.10,
    "co2_kg_per_kwh": 0.72,
    "_co2_source": "hệ số lưới điện VN — CẬP NHẬT HẰNG NĂM, ghi rõ năm",
    "co2_source_year": 2024,
    "carbon_price_usd_per_tco2": 20.0,
    "_carbon_price_source": "giá tham chiếu, KHÔNG phải giá giao dịch thật"
  },

  "anti_gaming": {
    "threshold_margin_above_idle_c": 8.0
  }
}
```

Quy ước: **mỗi hằng số có một trường `_source` đi kèm.** Hằng số không có nguồn là hằng số sẽ bị chất vấn, và người viết code sáu tháng sau sẽ không nhớ nó đến từ đâu.

---

## 10. Câu hỏi phản biện và câu trả lời

Chuẩn bị sẵn cho buổi bảo vệ. Mỗi câu trả lời phải trỏ được tới dữ liệu, không phải tới lập luận.

**"Job vẫn chạy ở máy khác, sao gọi là tiết kiệm?"**
> Đúng. Đó là lý do chúng tôi không đếm thời gian né. Chúng tôi đo Joule trên mỗi token sinh ra và so với mốc round-robin trên cùng bộ prompt. Chênh lệch {X}% đến từ ba nguồn thật: giảm dòng rò do chạy mát hơn, tránh throttle, và giảm tốc độ quạt.

**"Hạ ngưỡng xuống thì số có đẹp lên không?"**
> Không. Ngưỡng bị chặn dưới bởi nhiệt nhàn rỗi đo được của máy nóng nhất cộng 8°C. Và chỉ số chủ đạo có mẫu số là số token — gắn cờ nhiều hơn nghĩa là ít token hơn, tỷ số không tự cải thiện.

**"Hệ số 0,25 cho làm mát lấy ở đâu?"**
> Đó là ước lượng thận trọng, nằm ở Tầng 2 và hiển thị kèm giả định. Nó không ảnh hưởng tới bất kỳ con số nào ở Tầng 1. Nếu bạn muốn con số chắc chắn, hãy nhìn Tầng 1.

**"Tín chỉ carbon 1,7 triệu đồng là thật?"**
> Không, đó là dự phóng cho 1.000 máy trong 1 năm, chiếu tuyến tính từ 3 máy trong 4,2 giờ. Ở quy mô thử nghiệm thật, con số là khoảng 0,15 ₫ mỗi giờ. Chúng tôi hiển thị nó ở tầng dự phóng đúng vì lý do đó.

**"Nếu đo ra kết quả xấu hơn round-robin thì sao?"**
> Chúng tôi báo cáo đúng như vậy. Điều phối theo nhiệt đôi khi chọn máy chậm hơn, và điều đó tốn Joule. Nếu xảy ra, giá trị của hệ thống nằm ở tuổi thọ phần cứng và độ ổn định hiệu năng, không ở hóa đơn điện — và chúng tôi sẽ nói như vậy thay vì đổi công thức cho tới khi ra số đẹp.

**"Máy của tôi không đọc được công suất thì sao?"**
> Job từ máy đó không được tính vào Tầng 1. Chúng tôi ước lượng công suất bằng đường cong hiệu chuẩn và đưa vào Tầng 2, đánh dấu rõ. Xem [08-do-cong-suat.md](08-do-cong-suat.md).
