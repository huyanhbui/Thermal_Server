# 05 — Dự báo nhiệt

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Sửa lỗi: [S4](01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình), [M10](01-danh-gia-thiet-ke-hien-tai.md#m10--build_dataset-có-độ-phức-tạp-on)
> Quyết định: [ADR-004](adr/ADR-004-du-bao-delta-t.md)

## Mục lục

- [Bài toán](#1-bài-toán)
- [Vì sao mô hình hiện tại không mở rộng được](#2-vì-sao-mô-hình-hiện-tại-không-mở-rộng-được)
- [Chuyển sang dự báo ΔT](#3-chuyển-sang-dự-báo-δt)
- [Đặc trưng](#4-đặc-trưng)
- [Xây tập dữ liệu](#5-xây-tập-dữ-liệu)
- [Huấn luyện và đánh giá](#6-huấn-luyện-và-đánh-giá)
- [Mô hình theo node](#7-mô-hình-theo-node)
- [Đường dự phòng và khởi động nguội](#8-đường-dự-phòng-và-khởi-động-nguội)
- [Giám sát chất lượng khi vận hành](#9-giám-sát-chất-lượng-khi-vận-hành)

---

## 1. Bài toán

> Cho lịch sử telemetry 180 giây gần nhất của một máy, **nhiệt độ CPU cao nhất trong 3 phút tới sẽ là bao nhiêu?**

Con số đó so với ngưỡng để quyết định gắn cờ ([04 §6](04-dac-ta-scheduler.md#6-băng-trễ-trong-quyết-định-gắn-cờ)) và để tính `headroom` cho công thức chấm điểm ([04 §4.2](04-dac-ta-scheduler.md#42-headroom--khoảng-an-toàn-nhiệt-còn-lại)).

Đây là bài toán hồi quy chuỗi thời gian có chân trời cố định. Random Forest là lựa chọn hợp lý: dữ liệu ít, quan hệ phi tuyến vừa phải, không cần suy luận nhanh (5 giây một lần), và quan trọng nhất — **giải thích được**, thứ mà một sản phẩm bán cho doanh nghiệp cần khi bị hỏi "tại sao hệ thống lại chặn máy này?".

---

## 2. Vì sao mô hình hiện tại không mở rộng được

PoC lưu đúng một `model.pkl` ([`train_model.py:46`](../server/train_model.py)) và nạp nó cho **mọi** node ([`forecaster.py:17`](../server/forecaster.py)). Ở 2 máy tương tự nhau thì không lộ. Ở 10 máy dị chủng thì vỡ, vì đặc trưng đầu vào là **nhiệt độ tuyệt đối** ([`features.py:24`](../server/features.py)):

```python
return [float(temps[-1]), float(temps.mean()), slope,
        float(utils[-1]), float(utils.mean()), float(powers[-1])]
```

| | Laptop mỏng | Desktop tản nhiệt tốt |
|---|---|---|
| Nhàn rỗi | 52°C | 32°C |
| Tải tối đa | 95°C | 68°C |
| 78°C nghĩa là | tải trung bình, bình thường | **sắp có vấn đề** |
| Dốc 6°C/phút nghĩa là | chuyện thường ngày | quạt có thể đang hỏng |

Một mô hình học trên hỗn hợp hai loại này không sai ngẫu nhiên — nó **sai có hệ thống**: đánh giá thấp rủi ro của máy nóng và đánh giá cao rủi ro của máy mát. Đúng ngược lại điều sản phẩm cần làm.

Cùng vấn đề với ngưỡng: `threshold_c` là một số tuyệt đối dùng chung cho cả cụm ([`server.py:72`](../server/server.py)). 75°C là báo động với desktop và là nhàn rỗi-tải-nhẹ với laptop mỏng.

---

## 3. Chuyển sang dự báo ΔT

**Đổi nhãn** từ nhiệt độ tuyệt đối sang mức tăng nhiệt:

```
Cũ:   y = max(nhiệt độ trong 3 phút tới)
Mới:  y = max(nhiệt độ trong 3 phút tới) − nhiệt độ hiện tại

Khi dùng:   dự_báo_max = nhiệt_hiện_tại + ΔT_dự_báo
```

Đầu ra vẫn là cùng một đại lượng để so với ngưỡng — không có gì phải đổi ở phía dùng.

### Vì sao ΔT khái quát hóa tốt hơn

ΔT phụ thuộc chủ yếu vào **tải và quán tính nhiệt**, hai thứ có bản chất giống nhau giữa các máy:

- "Chạy hết tải từ trạng thái ổn định sẽ tăng thêm bao nhiêu độ trong 3 phút?" — câu trả lời nằm trong khoảng hẹp và tương tự nhau giữa các máy
- "Nhiệt độ tuyệt đối sẽ là bao nhiêu?" — hoàn toàn phụ thuộc máy đó bắt đầu từ đâu

Một cách khác để thấy điều này: mô hình cũ phải học **cả** nền nhiệt của từng máy **lẫn** động lực học nhiệt. Nền nhiệt là thứ ta đã biết (nó nằm trong `cpu_temp` đầu vào) — bắt mô hình học lại chính thứ nó đã được cho là lãng phí sức biểu diễn và là nguồn gốc của việc trộn lẫn giữa các máy.

### Ngưỡng tương đối

Song song, ngưỡng hiệu lực tính theo từng máy:

```
ngưỡng_hiệu_lực(node) = min(ngưỡng_cụm, idle_baseline(node) + biên_tối_đa)

idle_baseline: nhiệt nhàn rỗi ĐO ĐƯỢC của máy đó
               (từ pha hiệu chuẩn, hoặc phân vị 5% của 24 giờ gần nhất)
biên_tối_đa:   mặc định 40°C
```

Cơ chế này còn là tuyến phòng thủ chống thao túng chỉ số ESG ([07 §7.1](07-esg-3-tang.md#71-sàn-ngưỡng-theo-nhiệt-nhàn-rỗi-đo-được)) — một thay đổi giải quyết hai vấn đề.

---

## 4. Đặc trưng

Giữ nguyên sáu đặc trưng hiện có ([`features.py:4`](../server/features.py)), thêm bốn:

| # | Đặc trưng | Hiện có | Ghi chú |
|---|---|:---:|---|
| 1 | `cpu_temp` (mới nhất) | ✅ | |
| 2 | `mean_temp` | ✅ | |
| 3 | `slope_c_per_min` | ✅ | Đặc trưng mạnh nhất cho ΔT |
| 4 | `cpu_util` (mới nhất) | ✅ | |
| 5 | `mean_util` | ✅ | |
| 6 | `power_w` | ✅ | |
| 7 | **`temp_above_idle`** | mới | `cpu_temp − idle_baseline` — chuẩn hóa theo máy |
| 8 | **`util_slope`** | mới | Tải đang tăng hay giảm; dự đoán ΔT tốt hơn mức tải hiện tại |
| 9 | **`temp_std`** | mới | Độ dao động — phân biệt tải ổn định với tải giật cục |
| 10 | **`fan_rpm_norm`** | mới, tùy chọn | Quạt gần tối đa = hết dư địa tản nhiệt |

**Không đưa `site_id`, tên node, hay bất kỳ định danh máy nào vào đặc trưng.** Chúng biến mô hình chung thành mô hình ghi nhớ từng máy, và một máy mới vào phòng sẽ rơi vào vùng chưa từng thấy.

**Không đưa nhiệt độ ngoài trời vào.** Cùng lý do như [M12](01-danh-gia-thiet-ke-hien-tai.md#m12--thời-tiết-trong-công-thức-chấm-điểm-gần-như-vô-nghĩa): điều hòa đã cắt đứt quan hệ, và trong phạm vi một cửa sổ 180 giây thì nó là hằng số.

Ngưỡng dữ liệu tối thiểu giữ nguyên: ≥5 mẫu trải ≥30 giây ([`features.py:7-8`](../server/features.py)).

---

## 5. Xây tập dữ liệu

### Sửa lỗi O(n²)

Hiện tại ([`train_model.py:13-19`](../server/train_model.py)) mỗi dòng quét lại toàn bộ tập dữ liệu **hai lần**:

```python
for i, row in enumerate(rows):
    window = [r for r in rows if t - window_s <= r["ts"] <= t]         # O(n)
    future = [r["cpu_temp"] for r in rows if t < r["ts"] <= t + horizon_s]  # O(n)
```

- 2 node × 11 phút ≈ 660 dòng/node → ~0,9 triệu phép so sánh, vài giây. Không ai nhận ra.
- 10 node × phiên dài (100.000 dòng) → **10¹⁰ phép so sánh**. Script treo hàng giờ, trông như bị đơ.

**Sửa: hai con trỏ trượt.** Dữ liệu đã sắp xếp tăng dần theo `ts` ([`store.py:32`](../server/store.py) dùng `ORDER BY ts ASC`), nên chỉ cần hai chỉ số chạy tiến:

```python
def build_dataset(store, horizon_s=180.0, window_s=180.0):
    """Nhãn = ΔT: mức tăng nhiệt tối đa trong horizon_s tới. O(n) mỗi node."""
    X, y, groups = [], [], []
    for node in store.nodes():
        # store.all_rows() là phương thức MỚI cần thêm vào store.py — rõ nghĩa
        # hơn thủ thuật store.recent(seconds=10**12, now=10**12) mà
        # train_model.py:11 đang dùng để lấy toàn bộ dòng.
        rows = [r for r in store.all_rows(node) if r["cpu_temp"] is not None]
        lo = hi = 0
        for i, row in enumerate(rows):
            t = row["ts"]
            while rows[lo]["ts"] < t - window_s:      # con trỏ đầu cửa sổ
                lo += 1
            while hi < len(rows) and rows[hi]["ts"] <= t + horizon_s:
                hi += 1                                # con trỏ cuối chân trời
            if rows[-1]["ts"] < t + horizon_s:
                break        # không đủ tương lai — mọi dòng sau cũng vậy
            future = rows[i + 1:hi]
            if not future:
                continue
            feats = build_features(rows[lo:i + 1], idle_baseline=baseline(node))
            if feats is None:
                continue
            X.append(feats)
            y.append(max(r["cpu_temp"] for r in future) - row["cpu_temp"])  # ΔT
            groups.append(node)     # cần cho chia tập theo node ở §6
    return X, y, groups
```

Hai điểm đáng chú ý: `break` thay vì `continue` khi hết tương lai (mọi dòng sau đó cũng thiếu), và **lọc theo từng node trước khi xử lý** thay vì để `rows` chứa lẫn lộn các máy như hiện tại.

### Thu dữ liệu

Giữ nguyên pha hiệu chuẩn hiện có ([`calibrate.py:10`](../server/calibrate.py)): nhàn rỗi → nhẹ → nặng → nguội, ~11 phút mỗi node.

Ba bổ sung:

1. **Chạy đồng thời trên mọi node**, không tuần tự. Hiện tại vòng lặp ở [`calibrate.py:24`](../server/calibrate.py) chạy hết node này mới sang node khác — với 10 máy là **110 phút**. Chạy song song đưa về 11 phút và còn cho dữ liệu về hành vi nhiệt khi cả phòng cùng nóng, đúng điều kiện vận hành thật.
2. **Ghi `idle_baseline`** từ pha nhàn rỗi vào hồ sơ node.
3. **Thêm pha bậc thang công suất** cho [08](08-do-cong-suat.md) — một lần chạy phục vụ cả hai mục đích.

---

## 6. Huấn luyện và đánh giá

### Chia tập — đây là chỗ dễ tự lừa mình nhất

PoC dùng `train_test_split(shuffle=False)` ([`train_model.py:40`](../server/train_model.py)). Không xáo trộn là đúng cho dữ liệu chuỗi thời gian, nhưng **vẫn chưa đủ**: các cửa sổ 180 giây liền kề chồng lấn nhau tới 97%. Dòng cuối tập huấn luyện và dòng đầu tập kiểm tra dùng chung gần như toàn bộ dữ liệu thô.

Hệ quả: **MAE 1–3°C mà README đang nêu là quá lạc quan.**

Ba cách chia, mỗi cách trả lời một câu hỏi khác nhau — và cần cả ba:

| Cách chia | Trả lời câu hỏi | Bắt buộc |
|---|---|---|
| **Theo thời gian, có khoảng đệm** | "Dự báo tương lai chính xác đến đâu?" | ✅ |
| **Theo node (leave-one-node-out)** | "Mô hình có dùng được cho máy chưa từng thấy không?" | ✅ **quan trọng nhất** |
| Ngẫu nhiên | (chỉ để tham chiếu — sẽ cho số đẹp giả) | ❌ |

```python
# Chia theo thời gian có đệm: bỏ horizon_s ở ranh giới để loại rò rỉ
cutoff = t_min + (t_max - t_min) * 0.8
train = [i for i, t in enumerate(ts) if t < cutoff - horizon_s]
test  = [i for i, t in enumerate(ts) if t > cutoff]
```

**Leave-one-node-out là phép thử quyết định.** Nó trả lời trực tiếp câu hỏi của [S4](01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình): huấn luyện trên 9 máy, kiểm tra trên máy thứ 10, lặp lại cho từng máy. Nếu MAE ở đây tệ hơn hẳn so với chia theo thời gian, thì mô hình chung **không dùng được** và bắt buộc phải chuyển sang mô hình theo node (§7).

### Chỉ số báo cáo

| Chỉ số | Ý nghĩa |
|---|---|
| MAE (°C) | Sai số trung bình của dự báo ΔT |
| MAE theo dải nhiệt | Sai số ở vùng gần ngưỡng quan trọng hơn ở vùng nhàn rỗi rất nhiều |
| **Tỷ lệ bỏ sót** | Thực tế vượt ngưỡng mà mô hình nói không → **lỗi nguy hiểm nhất** |
| **Tỷ lệ báo động giả** | Mô hình nói vượt mà thực tế không → gây gắn cờ thừa và thổi phồng ESG |
| Mốc so sánh: dự phòng tuyến tính | Random Forest có thật sự hơn đường thẳng không? |

**Luôn báo cáo mốc so sánh.** Nếu Random Forest không hơn phép ngoại suy tuyến tính đơn giản một cách rõ rệt, thì hãy dùng đường thẳng — nó nhanh hơn, giải thích được, và không cần huấn luyện lại. Một mô hình học máy không tốt hơn đường cơ sở là một khoản nợ kỹ thuật đội lốt tính năng.

### Tham số

```python
RandomForestRegressor(
    n_estimators=200,       # giữ như PoC
    max_depth=12,           # MỚI: PoC để None -> cây mọc tới hết, học thuộc nhiễu
    min_samples_leaf=5,     # MỚI: cùng lý do
    random_state=42,
    n_jobs=-1,
)
```

Hai tham số mới chống quá khớp. Với dữ liệu chuỗi thời gian chồng lấn, cây không giới hạn độ sâu sẽ ghi nhớ từng cửa sổ cụ thể.

---

## 7. Mô hình theo node

Chỉ làm **nếu** leave-one-node-out cho thấy mô hình chung không đủ tốt.

```
model_global.pkl        huấn luyện trên mọi node — luôn tồn tại
model_<node>.pkl        huấn luyện riêng — chỉ khi node đó có ≥500 mẫu
```

Thứ tự chọn khi dự báo:

```
1. model_<node>.pkl  nếu có VÀ node đó đã hiệu chuẩn
2. model_global.pkl  nếu có
3. dự phòng tuyến tính  (§8)
```

Dashboard hiển thị mô hình nào đang dùng cho từng node. Người vận hành phải biết mình đang nhìn số từ đâu ra.

**Đừng làm bước này sớm.** ΔT (§3) đã giải quyết phần lớn vấn đề dị chủng với chi phí thấp hơn nhiều. Mô hình theo node thêm 10 tệp phải quản lý, 10 lịch huấn luyện lại, và 10 cách hỏng khác nhau. Chỉ trả cái giá đó khi có số đo chứng minh là cần.

---

## 8. Đường dự phòng và khởi động nguội

### Dự phòng tuyến tính

Giữ nguyên logic hiện có ([`forecaster.py:36-38`](../server/forecaster.py)), chuyển sang ΔT:

```python
ΔT_dự_báo = min(max(slope, 0) × HORIZON_MIN, FALLBACK_CAP_C)
```

Trần `FALLBACK_CAP_C = 20°C` chặn trường hợp một dốc nhất thời ngoại suy thành con số vô lý.

Badge trên dashboard phải nói rõ **"dự phòng (chưa huấn luyện)"** — PoC đã làm đúng điều này ([`dashboard.html:81`](../server/static/dashboard.html)), giữ nguyên.

### Khởi động nguội

Trong 30 giây đầu, `build_features` trả `None` và không có dự báo. Định nghĩa trạng thái `WARMING_UP` ([02 §6](02-kien-truc-he-thong.md#6-máy-trạng-thái-của-node)):

| | Hành vi |
|---|---|
| Gắn cờ | Không — chưa đủ dữ liệu để kết luận |
| Nhận job | **Có** — nếu không, mọi worker mới đều vô dụng trong 30 giây đầu |
| Chấm điểm | Dùng `cpu_temp` hiện tại thay `predicted_max`, nhân hệ số phạt 0,7 |
| Hiển thị | Badge riêng, không nhầm với `OFFLINE` |

---

## 9. Giám sát chất lượng khi vận hành

MAE trên tập kiểm tra là chất lượng **tại thời điểm huấn luyện**. Chất lượng thật là chất lượng khi chạy — và nó trôi theo thời gian: bụi bám tản nhiệt, keo tản nhiệt khô, nhiệt độ phòng đổi theo mùa.

Trường `peak_temp_c` trong kết quả job ([03 §5](03-hop-dong-api.md#post-jobsresult)) cho phép đo trực tiếp:

```
sai_số_thực_tế = |peak_temp_c − predicted_max_tại_lúc_gán|
```

Đây là con số trung thực hơn nhiều để trả lời "mô hình của các anh chính xác đến đâu?", vì nó đo trên chính dữ liệu vận hành, không phải trên tập kiểm tra được chọn lọc.

**Cảnh báo khi:**

| Điều kiện | Nghĩa là |
|---|---|
| MAE trượt 7 ngày > 2× MAE lúc huấn luyện | Mô hình đã trôi — cần hiệu chuẩn lại |
| Tỷ lệ bỏ sót > 5% | **Nguy hiểm** — máy vượt ngưỡng mà không được cảnh báo |
| Tỷ lệ báo động giả > 20% | Gắn cờ thừa, thổi phồng ESG, giảm thông lượng vô ích |
| `idle_baseline` tăng > 5°C so với lúc hiệu chuẩn | Tản nhiệt bẩn hoặc quạt yếu — **một phát hiện có giá trị thật cho người dùng** |

Dòng cuối đáng được đưa lên giao diện như một tính năng, không chỉ là cảnh báo nội bộ: hệ thống phát hiện được máy nào cần vệ sinh tản nhiệt. Đó là lợi ích cụ thể, đo được, và không cần bất kỳ giả định ESG nào để biện minh.
