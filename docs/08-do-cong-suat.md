# 08 — Đo công suất

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Phục vụ: [`07-esg-3-tang.md`](07-esg-3-tang.md) Tầng 1 và Tầng 2, [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md) §4.4

Toàn bộ độ tin cậy của báo cáo ESG nằm ở câu hỏi này: **máy có đọc được số watt không, và bằng đường nào?** Nếu không đo được công suất thật, mọi con số J/token chỉ là ước lượng và phải nằm ở Tầng 2.

## Mục lục

- [Quy trình bốn bước](#1-quy-trình-bốn-bước)
- [Các nguồn công suất trên Windows](#2-các-nguồn-công-suất-trên-windows)
- [Bước 1 — Dò nguồn](#3-bước-1--dò-nguồn)
- [Bước 2 — Đo đường cong](#4-bước-2--đo-đường-cong)
- [Bước 3 — Khớp mô hình](#5-bước-3--khớp-mô-hình)
- [Bước 4 — Tính J/token](#6-bước-4--tính-jtoken)
- [Hiệu chuẩn bằng đồng hồ điện rời](#7-hiệu-chuẩn-bằng-đồng-hồ-điện-rời)
- [Quy tắc gắn nhãn nguồn](#8-quy-tắc-gắn-nhãn-nguồn)
- [Xử lý sự cố](#9-xử-lý-sự-cố)

---

## 1. Quy trình bốn bước

```
  ┌──────────────────┐   Máy này đo được công suất bằng đường nào?
  │ power_probe.ps1  │   → sensor / battery / none
  └────────┬─────────┘
           ▼
  ┌──────────────────────┐   Chạy tải bậc thang, ghi (util, temp, power)
  │ power_baseline.py    │   → power_baseline.csv
  └────────┬─────────────┘
           ▼
  ┌──────────────────────┐   Khớp P = a + b·util + c·temp
  │ power_model_fit.py   │   → power_model.json
  └────────┬─────────────┘      • đường dự phòng khi cảm biến câm
           │                     • p_idle / p_max cho scheduler
           │                     • hệ số dòng rò c cho ESG Tầng 2
           ▼
  ┌──────────────────────┐   ∫P dt ÷ tokens
  │ energy_per_token.py  │   → J/token, so sánh A/B
  └──────────────────────┘
```

Ba script Python **chỉ dùng thư viện chuẩn** — chạy được bằng Python hệ thống, không cần venv của server, không cần numpy.

---

## 2. Các nguồn công suất trên Windows

| Nguồn | Đo cái gì | Độ chính xác | Điều kiện |
|---|---|---|---|
| **LibreHardwareMonitor** (CPU package power) | Chỉ CPU | Cao — đọc từ RAPL/SMU của chip | Quyền Administrator; chip phải phơi bày |
| **Pin (`BatteryStatus` WMI)** | **Toàn máy** | Cao khi đang xả | Chỉ laptop, **và phải rút sạc** |
| **Đồng hồ điện rời ở ổ cắm** | **Toàn máy + màn hình** | Cao nhất, là chuẩn đối chiếu | Cần phần cứng, đọc thủ công |
| **Intel Power Gadget** | CPU | Cao | Intel đã ngừng phát hành; chỉ dùng nếu đã cài |
| **HWiNFO64 shared memory** | CPU + nhiều hơn | Cao | Phải cài và bật Shared Memory Support |
| **Mô hình P(util, temp)** | Ước lượng | Trung bình | Cần hiệu chuẩn một lần bằng một nguồn ở trên |

**Độ phủ theo hãng chip:**

- **Intel** — Core thế hệ 6 (Skylake) trở lên phơi bày package power qua RAPL khá nhất quán. Khả năng đọc được cao.
- **AMD** — Ryzen phơi bày qua SMU, nhưng độ phủ kém đồng đều hơn; một số mainboard/BIOS không mở.
- **Máy bàn không pin** — mất hẳn đường đo toàn máy. Nếu cảm biến CPU cũng câm thì bắt buộc dùng đồng hồ điện rời.
- **Laptop** — luôn có đường pin, nhưng **chỉ khi rút sạc**. Cắm sạc thì `DischargeRate = 0`.

**CPU package power không phải toàn bộ điện máy tiêu thụ.** Nó bỏ qua RAM, ổ đĩa, card mạng, màn hình, và tổn hao của bộ nguồn. Với suy luận LLM trên CPU, phần CPU là biến động chính nên nó vẫn phản ánh đúng *chênh lệch* giữa các chế độ scheduler — nhưng khi báo cáo con số tuyệt đối thì **phải nói rõ đây là công suất CPU, không phải công suất máy**.

---

## 3. Bước 1 — Dò nguồn

```bash
powershell -ExecutionPolicy Bypass -File scripts\measure_power\power_probe.ps1
```

Script chỉ đọc: không cài gì, không sửa gì. Chạy **với quyền Administrator** để kiểm tra được cả LibreHardwareMonitor.

Chế độ máy đọc: `-Json` xuất JSON để script khác dùng.

### Đọc kết quả

Trường `best_source` nhận một trong bốn giá trị:

| Giá trị | Nghĩa | Làm gì tiếp |
|---|---|---|
| `sensor_lhm` | Đọc được công suất CPU | Job trên máy này **vào ESG Tầng 1**. Vẫn chạy tiếp Bước 2 để có `p_idle`/`p_max` |
| `battery` | Không có cảm biến CPU nhưng đo được toàn máy qua pin | Hiệu chuẩn mô hình bằng đường pin → job vào **Tầng 2** |
| `unknown` | **Chưa kiểm tra được**, không phải đã bị loại | Build agent, chạy lại với quyền Administrator |
| `none` | Đã kiểm tra, không có nguồn nào | Bắt buộc dùng đồng hồ điện rời (§7) |

Phân biệt `unknown` với `none` là có chủ đích. Kết luận "máy không đo được công suất" chỉ hợp lệ khi **đã thực sự thử** — báo `none` cho một máy chưa build agent là kết luận sai và sẽ đẩy nhầm dữ liệu xuống Tầng 2.

### Ví dụ thực tế

Chạy trên một máy bàn Intel i5-12400F, chưa build agent:

```
  Nguồn tốt nhất: unknown

  CHƯA KẾT LUẬN ĐƯỢC. Chưa kiểm tra được LibreHardwareMonitor - đó là
  nguồn có khả năng nhất trên máy này, không phải nguồn đã bị loại.
  CPU Intel đời Core thế hệ 6 trở lên thường phơi bày package power
  qua RAPL, nên khả năng đọc được là cao. Hãy build agent
  (scripts\publish_agent.ps1) rồi chạy lại script này VỚI QUYỀN
  ADMINISTRATOR trước khi kết luận bất cứ điều gì về ESG Tầng 1.
```

Đúng kết luận cần có ở trạng thái đó: máy bàn nên không có pin, nhưng chip Intel 12th gen gần như chắc chắn báo được package power — chỉ là chưa có công cụ để đọc.

---

## 4. Bước 2 — Đo đường cong

```bash
python scripts\measure_power\power_baseline.py --db ..\..\server\telemetry.db --node Node-A
```

**Yêu cầu:** agent phải đang chạy và gửi telemetry về server, vì script đọc số nhiệt/công suất từ `telemetry.db` chứ không tự đọc cảm biến.

Script chạy tải bậc thang **0 → 25 → 50 → 75 → 100%**, mỗi bậc 2 phút (bậc nhàn rỗi 3 phút), tổng khoảng 11 phút.

### Ba chế độ

| Lệnh | Dùng khi |
|---|---|
| *(mặc định)* | Máy có cảm biến công suất — script tự lấy `power_w` từ telemetry |
| `--manual-power` | Không có cảm biến — script hỏi số trên đồng hồ điện rời sau mỗi bậc |
| `--extract-only` | Đã chạy `server.py --calibrate` trước đó — trích luôn dữ liệu đã có, không sinh tải lại |

`--extract-only` đáng chú ý: pha hiệu chuẩn hiện có ([`calibrate.py:10`](../server/calibrate.py)) đã tạo ra đúng loại dữ liệu cần thiết (chu kỳ nhàn rỗi → nhẹ → nặng → nguội). Nếu đã chạy nó rồi thì không cần đốt CPU thêm 11 phút nữa.

### Cách sinh tải

Chu kỳ nhiệm vụ (duty cycle): mỗi tiến trình bận `util × 100ms` rồi ngủ phần còn lại. Trung bình trên nhiều lát cắt, mức sử dụng hội tụ về đúng tỷ lệ mong muốn. Cách này cho tải **giữa 0 và 100%**, khác với burn job hiện có ([`JobRunner.cs:10`](../agent/JobRunner.cs)) vốn chỉ chạy được ở mức 100%.

**Chỉ lấy mẫu ở nửa sau mỗi bậc.** Nửa đầu là giai đoạn nhiệt còn đang leo; lấy cả sẽ trộn trạng thái chuyển tiếp vào dữ liệu ổn định và làm sai hệ số nhiệt.

---

## 5. Bước 3 — Khớp mô hình

```bash
python scripts\measure_power\power_model_fit.py --csv power_baseline.csv --node Node-A
```

Khớp bằng bình phương tối thiểu:

```
P = a + b·util + c·temp
```

| Hệ số | Ý nghĩa | Dùng ở đâu |
|---|---|---|
| `a` | Công suất nền (W) | Ước lượng dự phòng |
| `b` | W trên mỗi phần trăm sử dụng CPU | Ước lượng dự phòng |
| `c` | **W trên mỗi °C — hệ số dòng rò** | [ESG Tầng 2](07-esg-3-tang.md#41-điện-rò-theo-nhiệt) |
| `p_idle`, `p_max` | Biên công suất của máy | [Scheduler §4.4](04-dac-ta-scheduler.md#44-efficiency--hiệu-suất-điện) |

### Kiểm chứng phép khớp

Phần bình phương tối thiểu được viết tay (hệ phương trình chuẩn 3×3, khử Gauss có chọn phần tử trụ) để tránh phụ thuộc numpy. Đã kiểm chứng bằng dữ liệu tổng hợp có sự thật đã biết:

| Hệ số | Sự thật cài vào | Mô hình khớp lại |
|---|---|---|
| `a` | 12,00 | 12,25 |
| `b` | 0,4500 | 0,4515 |
| `c` | 0,1800 | 0,1748 |

R² = 0,998, MAE = 0,65 W trên 450 mẫu. Phép khớp đúng.

### Ba lưới an toàn

Script từ chối tạo ra số đẹp từ dữ liệu tồi:

1. **Dưới 30 dòng có đủ (util, temp, power)** → dừng, không xuất tệp, chỉ dẫn đường sửa.
2. **Dải nhiệt dưới 8°C** → tự bỏ số hạng nhiệt và cảnh báo rằng **hệ số dòng rò sẽ không khả dụng cho ESG Tầng 2**. Không thể tách ảnh hưởng của nhiệt khi nhiệt gần như không đổi.
3. **Hệ số dòng rò ngoài khoảng 0,1–1,5%/°C** → cảnh báo. Giá trị điển hình là 0,3–0,6%/°C; lệch xa hơn thường là dấu hiệu hồi quy bị nhiễu chứ không phải phần cứng đặc biệt.

Ngoài ra script loại các điểm lệch quá 3σ — cảm biến thỉnh thoảng trả một giá trị vọt, và một điểm như vậy kéo cả đường hồi quy đi rất xa.

`power_model.json` luôn mang trường `warnings` và `usage_note`. Đọc chúng trước khi tin bất cứ con số nào.

---

## 6. Bước 4 — Tính J/token

```bash
# Từ CSV job tự ghi — dùng được ngay hôm nay
python scripts\measure_power\energy_per_token.py --db ..\..\server\telemetry.db --jobs jobs.csv --ab

# Từ bảng esg_events, khi hệ thống mới đã chạy
python scripts\measure_power\energy_per_token.py --db ..\..\server\telemetry.db --from-events --ab
```

Đường CSV có chủ đích: nó cho phép **đo thử ngay bây giờ**, trước khi bảng `esg_events` được hiện thực. Chỉ cần ghi lại thời điểm bắt đầu/kết thúc và số token của vài lần chạy suy luận thủ công.

```csv
job_id,node,start_ts,end_ts,tokens_out,scheduler_mode
j001,Node-A,1735689600.0,1735689604.8,187,thermal_aware
```

### Cách tính

Tích phân hình thang trên chuỗi công suất, **có nội suy tuyến tính ở hai biên** để khoảng tích phân khớp đúng thời lượng job chứ không phải khoảng giữa hai mẫu telemetry gần nhất. Với job 4 giây và telemetry 2 giây một lần, sai lệch biên có thể lên tới 50% nếu không nội suy.

Nếu worker đã tự báo `energy_j` với `energy_source='sensor'`, script **tin số đó** thay vì tự tích phân — worker lấy mẫu dày hơn nhiều so với chu kỳ telemetry 2 giây.

### Một chi tiết quan trọng

```
J/token = Σ energy_j / Σ tokens_out        ✅ đúng
J/token = trung bình các (energy_j / tokens_out)   ❌ sai
```

Cách sai cho một job 5 token trọng số ngang một job 500 token. Script báo cả hai (`j_per_token` và `j_per_token_median_per_job`) — con số đầu là con số dùng để báo cáo, con số sau chỉ để phát hiện phân bố lệch.

### Ngưỡng công bố

| Số job | Hành vi |
|---|---|
| < 20 mỗi chế độ | In chênh lệch thô nhưng **kèm dòng "CHƯA ĐỦ DỮ LIỆU để công bố"** |
| 20 – 99 | Nhãn `sơ bộ` |
| ≥ 100 | Nhãn `ok` |

Và nếu kết quả ra **âm** — điều phối theo nhiệt tốn nhiều năng lượng hơn — script nói thẳng như vậy, kèm giải thích rằng đó là kết quả hợp lệ phải báo cáo đúng ([07 §3.2](07-esg-3-tang.md#32-so-sánh-ab--con-số-bán-hàng)).

---

## 7. Hiệu chuẩn bằng đồng hồ điện rời

Bắt buộc khi `best_source = none`. Cũng nên làm **một lần** ngay cả khi có cảm biến, để biết cảm biến CPU chiếm bao nhiêu phần trăm điện toàn máy.

### Thiết bị

Ổ cắm đo điện gia dụng, loại hiển thị watt tức thời. Ở Việt Nam giá khoảng 150.000–400.000 ₫. Không cần loại đắt tiền — sai số 2% là quá đủ cho mục đích này.

### Quy trình

```
1. Cắm CHỈ máy tính vào đồng hồ (rút màn hình ra ổ khác, hoặc ghi nhận
   riêng công suất màn hình rồi trừ đi)
2. Đóng mọi ứng dụng khác. Tắt cập nhật tự động, tắt quét virus theo lịch
3. Chạy:
      python power_baseline.py --db ... --node ... --manual-power
4. Sau mỗi bậc tải, script dừng và hỏi số trên đồng hồ — đọc lúc số
   đã ổn định (chờ ~10 giây)
5. Ghi lại số nền lúc máy hoàn toàn nhàn rỗi để đối chiếu
```

### Bốn lưu ý

- **Đọc lúc kết thúc bậc**, không phải lúc bắt đầu — công suất cần thời gian ổn định theo nhiệt.
- Nhiều đồng hồ nhấp nháy ±2 W. Đọc giá trị trung tâm, đừng chờ số đứng yên.
- Số này là **toàn máy**, gồm cả tổn hao bộ nguồn (hiệu suất 85–92%). Nếu muốn so với cảm biến CPU, phải nhớ khoảng chênh này.
- **Ghi lại điều kiện đo** vào trường `_source` của `esg_config.json`: ngày, model máy, nhiệt độ phòng. Sáu tháng sau không ai nhớ.

---

## 8. Quy tắc gắn nhãn nguồn

Đây là ranh giới quan trọng nhất trong toàn bộ hệ thống ESG. Mọi mẫu telemetry và mọi kết quả job **bắt buộc** mang trường nguồn:

| `power_source` / `energy_source` | Nghĩa | Vào tầng nào |
|---|---|---|
| `sensor` | Đọc từ phần cứng | **Tầng 1 — ĐO THẬT** |
| `model` | Ước lượng từ `power_model.json` | **Tầng 2 — SUY RA** |
| `manual` | Nhập tay từ đồng hồ điện | Tầng 1 nếu đúng quy trình, ghi rõ trong báo cáo |
| `none` | Không có số | **Không vào tầng nào** — chỉ đếm token |

**Không bao giờ được cộng số `sensor` với số `model` trong cùng một phép tính.** Nếu 3 máy có cảm biến và 2 máy không, thì J/token Tầng 1 tính trên 3 máy đó và báo cáo ghi rõ như vậy — không lấp chỗ trống bằng ước lượng để có con số "đầy đủ hơn".

Quy tắc này được ghi thành bất biến trong [`.agent/context/invariants.md`](../.agent/context/invariants.md).

---

## 9. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `power_probe.ps1` báo `unknown` | Chưa build agent hoặc thiếu quyền Administrator | `scripts\publish_agent.ps1`, rồi chạy lại PowerShell với quyền quản trị |
| Agent báo `Power: n/a` | Chip/mainboard không phơi bày package power; hoặc driver LibreHardwareMonitor bị chặn | Kiểm tra bằng `NodeAgent.exe --test-sensors`; nếu nhiệt độ cũng `n/a` thì là vấn đề quyền, không phải cảm biến |
| Pin báo `DischargeRate = 0` | Đang cắm sạc | Rút sạc rồi đo lại |
| `power_baseline.py` báo "không có mẫu telemetry" | Agent không chạy, hoặc sai tên node | `python -c "import sqlite3;print([r[0] for r in sqlite3.connect('telemetry.db').execute('SELECT DISTINCT node FROM telemetry')])"` |
| `power_model_fit.py` báo không đủ dữ liệu | Cột `power_w` toàn NULL | Chạy lại với `--manual-power`, hoặc chấp nhận máy này chỉ vào Tầng 2 |
| Cảnh báo "dải nhiệt chỉ x°C" | Bậc tải không đủ nóng, hoặc tản nhiệt quá tốt | Kéo dài `--step-seconds`, hoặc chấp nhận không có hệ số dòng rò |
| R² < 0,7 | Quan hệ không tuyến tính, hoặc có tải nền nhiễu | Đóng ứng dụng khác rồi đo lại; nếu vẫn thấp, mô hình tuyến tính không hợp với máy này |
| Hệ số dòng rò ngoài 0,3–0,6%/°C | Thường là nhiễu hồi quy | Kiểm tra lại dữ liệu **trước khi** dùng cho báo cáo ESG |
| `energy_per_token.py` bỏ qua mọi job | Mốc thời gian job không khớp khoảng có telemetry | Kiểm tra lệch đồng hồ giữa máy ghi job và máy chạy agent ([03 §4](03-hop-dong-api.md#post-ingest)) |
| Chữ tiếng Việt bị vỡ trên console | Codepage cp1252 | Các script đã tự ép UTF-8. Nếu vẫn vỡ, đặt `set PYTHONUTF8=1` |
