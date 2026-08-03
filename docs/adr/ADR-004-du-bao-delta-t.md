# ADR-004 — Dự báo ΔT thay vì nhiệt độ tuyệt đối

**Trạng thái:** Đã chốt
**Ngày:** 2026-07-31
**Liên quan:** [`01 §S4`](../01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình), [`05`](../05-du-bao-nhiet.md)

## Bối cảnh

PoC lưu đúng một `model.pkl` ([`train_model.py:46`](../../server/train_model.py)) và nạp nó cho **mọi** node ([`forecaster.py:17`](../../server/forecaster.py)). Nhãn huấn luyện là **nhiệt độ tuyệt đối** trong 3 phút tới, và đặc trưng đầu vào cũng là nhiệt độ tuyệt đối ([`features.py:24`](../../server/features.py)).

Ở 2 máy tương tự nhau, được hiệu chuẩn trong cùng một phiên rồi trộn chung dữ liệu, mô hình học được một hàm trung bình đủ dùng. Ở 10 máy dị chủng thì vỡ:

| | Laptop mỏng | Desktop tản nhiệt tốt |
|---|---|---|
| Nhàn rỗi | 52°C | 32°C |
| Tải tối đa | 95°C | 68°C |
| 78°C nghĩa là | tải trung bình, bình thường | **sắp có vấn đề** |
| Dốc 6°C/phút nghĩa là | chuyện thường ngày | quạt có thể đang hỏng |

Một mô hình học trên hỗn hợp hai loại này **không sai ngẫu nhiên — nó sai có hệ thống**: đánh giá thấp rủi ro của máy nóng và đánh giá cao rủi ro của máy mát. Đúng ngược lại điều sản phẩm cần làm.

Cùng vấn đề với ngưỡng: `threshold_c` là một số tuyệt đối dùng chung cho cả cụm ([`server.py:72`](../../server/server.py)).

## Quyết định

**Đổi nhãn từ nhiệt độ tuyệt đối sang mức tăng nhiệt:**

```
Cũ:   y = max(nhiệt độ trong 3 phút tới)
Mới:  y = max(nhiệt độ trong 3 phút tới) − nhiệt độ hiện tại

Khi dùng:  dự_báo_max = nhiệt_hiện_tại + ΔT_dự_báo
```

Đầu ra vẫn là cùng một đại lượng để so với ngưỡng — không đổi gì ở phía dùng.

Kèm hai thay đổi bổ trợ:

1. **Thêm đặc trưng `temp_above_idle`** = `cpu_temp − idle_baseline` — cho mô hình biết vị trí tương đối trong dải nhiệt của chính máy đó.
2. **Ngưỡng tương đối theo từng máy:**
   ```
   ngưỡng_hiệu_lực(node) = min(ngưỡng_cụm, idle_baseline(node) + biên_tối_đa)
   ```

**Mô hình theo node (`model_<node>.pkl`) chỉ làm nếu leave-one-node-out cho thấy mô hình gộp không đủ tốt.** Không làm trước.

## Phương án đã cân nhắc

### A. Giữ nhiệt tuyệt đối, thêm mô hình riêng cho từng node ngay từ đầu

**Loại ở giai đoạn này.** Nó giải quyết được vấn đề, nhưng đắt: 10 tệp mô hình phải quản lý, 10 lịch huấn luyện lại, 10 cách hỏng khác nhau, và **node mới vào phòng không có mô hình nào cho tới khi hiệu chuẩn xong**.

ΔT giải quyết phần lớn cùng vấn đề với chi phí thấp hơn nhiều, và **vẫn để ngỏ đường đi tới mô hình theo node** nếu số đo chứng minh là cần. Thứ tự đúng là: làm cái rẻ trước, đo, rồi mới quyết có trả giá đắt hay không.

### B. Chuẩn hóa nhiệt tuyệt đối theo min-max của từng máy

`temp_norm = (temp − idle) / (max − idle)`, giữ nguyên nhãn tuyệt đối.

**Loại:** cần biết `max` của mỗi máy, mà `max` chỉ đo được khi đã đẩy máy tới giới hạn — điều ta đang cố tránh. Ngoài ra nếu tản nhiệt xuống cấp, `max` thay đổi và toàn bộ thang đo trôi theo.

`temp_above_idle` giữ được phần lớn lợi ích mà chỉ cần biết `idle_baseline`, thứ đo được an toàn trong 3 phút.

### C. Học một mô hình vật lý (RC nhiệt) thay vì học máy

Mô hình mạch nhiệt bậc một với hằng số thời gian ước lượng cho từng máy.

**Hấp dẫn, nhưng hoãn.** Nó khái quát hóa tốt nhất và cần rất ít dữ liệu. Nhưng nó cần công sức mô hình hóa đáng kể, và **đề án đã cam kết Random Forest** — đổi sang mô hình vật lý là thay đổi câu chuyện kỹ thuật của cả dự án.

Ghi lại như hướng đi có giá trị cho phiên bản sau. Trong lúc đó, mốc so sánh tuyến tính ở [05 §6](../05-du-bao-nhiet.md#chỉ-số-báo-cáo) đóng vai trò tương tự: nếu Random Forest không hơn được đường thẳng, đó là tín hiệu nên chuyển sang mô hình vật lý.

### D. Thêm định danh máy vào đặc trưng

Cho `node_id` hoặc thông số phần cứng vào vector đặc trưng.

**Loại:** biến mô hình chung thành mô hình ghi nhớ từng máy. Máy mới vào phòng rơi vào vùng chưa từng thấy, và Random Forest ngoại suy rất kém ngoài miền huấn luyện.

## Hệ quả

### Tích cực

- **Một mô hình dùng được cho nhiều máy khác nhau** — máy mới có dự báo hợp lý ngay, không cần hiệu chuẩn riêng
- **ΔT dễ diễn giải hơn** cho người dùng: "máy này sẽ nóng thêm 8°C trong 3 phút" rõ hơn "máy này sẽ đạt 78°C"
- Ngưỡng tương đối là **một thay đổi giải quyết hai vấn đề**: vừa xử lý dị chủng, vừa là tuyến phòng thủ chống thao túng chỉ số ESG ([07 §7.1](../07-esg-3-tang.md#71-sàn-ngưỡng-theo-nhiệt-nhàn-rỗi-đo-được))
- Mô hình không phải học lại nền nhiệt của từng máy — thứ đã nằm sẵn trong đầu vào

### Tiêu cực

- **Cần `idle_baseline` cho mỗi máy.** Thêm một thứ phải đo, phải lưu, và phải cập nhật. Máy chưa hiệu chuẩn phải dùng phân vị 5% của 24 giờ gần nhất — kém chính xác hơn.
- **`idle_baseline` trôi theo thời gian.** Tản nhiệt bẩn, keo tản nhiệt khô, nhiệt phòng đổi theo mùa. Cần giám sát và cập nhật ([05 §9](../05-du-bao-nhiet.md#9-giám-sát-chất-lượng-khi-vận-hành)).

  *Đổi lại, chính sự trôi này là một tính năng:* `idle_baseline` tăng >5°C là dấu hiệu máy cần vệ sinh tản nhiệt — một phát hiện cụ thể, đo được, có ích thật cho người dùng, và không cần bất kỳ giả định ESG nào để biện minh.
- **Sai số cộng dồn.** `dự_báo = nhiệt_hiện_tại + ΔT_dự_báo` mang cả sai số cảm biến lẫn sai số mô hình. Cần theo dõi sai số thực tế qua `peak_temp_c`.
- **Phải huấn luyện lại từ đầu.** Mô hình cũ không dùng lại được vì nhãn đã đổi.

### Trung tính

- Nhãn ΔT thường có phương sai nhỏ hơn nhãn tuyệt đối, nên MAE sẽ **trông đẹp hơn**. Đây là ảo giác do đổi đơn vị đo, không phải cải thiện thật — **phải so cùng đơn vị khi báo cáo**, và luôn kèm mốc tuyến tính.
- Ngưỡng cụm vẫn tồn tại như một trần chung; ngưỡng hiệu lực là `min` của hai giá trị.

## Kiểm chứng

| Cách kiểm | Kỳ vọng |
|---|---|
| **Leave-one-node-out** ([05 §6](../05-du-bao-nhiet.md#chia-tập--đây-là-chỗ-dễ-tự-lừa-mình-nhất)) | **Phép thử quyết định.** ΔT phải tốt hơn rõ rệt so với nhãn tuyệt đối trên máy chưa từng thấy |
| Chia theo thời gian có đệm | MAE trung thực, không rò rỉ do cửa sổ chồng lấn |
| So với mốc tuyến tính | Random Forest phải hơn rõ rệt, nếu không thì dùng đường thẳng |
| Ca S10 ([04 §9](../04-dac-ta-scheduler.md#chấm-điểm)) | Cùng dự báo 70°C, hai máy khác `baseline` → `headroom` khác rõ rệt |
| Ca C5 ([11 §4](../11-chien-luoc-kiem-thu.md#ca-tích-hợp)) | Node nóng nhanh bị gắn cờ trước, dù nhiệt tuyệt đối ban đầu thấp hơn |
| Sai số thực tế khi vận hành | \|`peak_temp_c` − `predicted_max`\| trong ngưỡng chấp nhận |

**Dấu hiệu quyết định này chưa đủ:** nếu leave-one-node-out vẫn cho MAE tệ hơn đáng kể so với chia theo thời gian, thì ΔT chưa giải quyết hết vấn đề dị chủng và phải chuyển sang mô hình theo node ([05 §7](../05-du-bao-nhiet.md#7-mô-hình-theo-node)).
