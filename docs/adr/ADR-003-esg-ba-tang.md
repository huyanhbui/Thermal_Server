# ADR-003 — ESG ba tầng, không bao giờ cộng gộp

**Trạng thái:** Đã chốt
**Ngày:** 2026-07-31
**Liên quan:** [`01 §S3`](../01-danh-gia-thiet-ke-hien-tai.md#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được), [`07`](../07-esg-3-tang.md), [`08`](../08-do-cong-suat.md)

## Bối cảnh

Báo cáo ESG là điểm nhấn thương mại của dự án. Theo `BÁO CÁO TỔNG QUAN DỰ ÁN.md` §3.1, nó nhằm *"xuất file báo cáo định kỳ để doanh nghiệp nộp cho các cơ quan kiểm định chuẩn xanh"*.

Công thức hiện tại ([`esg.py:11`](../../server/esg.py)) không đáp ứng được mục đích đó:

```python
kwh_saved = hot_hours × node_power_kw × cooling_overhead_factor
```

Bốn vấn đề, mỗi vấn đề đủ để một người phản biện có chuyên môn bác bỏ toàn bộ panel:

1. **Đếm *thời gian né* rồi gọi là *năng lượng tiết kiệm*.** Job vẫn chạy ở máy khác. Tổng điện cụm gần như không đổi.
2. **Bị thao túng được.** Đặt `threshold_c = 40` → mọi node luôn bị gắn cờ → 10 node × 24 giờ báo cáo "tiết kiệm 7,8 kWh", trong khi hệ thống **không dispatch được job nào**. Cấu hình làm được ít việc nhất cũng là cấu hình báo cáo nhiều nhất.
3. **Không có mẫu số.** Không so với khối lượng công việc nào.
4. **Hằng số không có nguồn.** `cooling_overhead_factor = 0.5` tương đương PUE 1,5 — con số của trung tâm dữ liệu, áp lên máy tính văn phòng.

Đồng thời, thiết kế LLM mới cho sẵn thứ PoC thiếu: **một mẫu số có nghĩa — số token sinh ra**.

## Quyết định

**Ba tầng tách bạch, không bao giờ cộng gộp thành một con số.**

| Tầng | UI (EN) | Nội dung | Độ tin cậy |
|---|---|---|---|
| **1 · ĐO THẬT** | MEASURED | J/token thực đo, A/B với round-robin, giây throttle tránh được | Bảo vệ được 100% |
| **2 · SUY RA** | DERIVED | Dòng rò theo nhiệt, điện quạt, hệ số làm mát theo site | Có giả định, hiển thị ngay cạnh số |
| **3 · NGOẠI SUY** | PROJECTED | Chiếu lên N node × T thời gian, quy đổi tiền/CO₂, định giá carbon | Dán nhãn "DỰ PHÓNG" / PROJECTED |

Ba quy tắc bất di bất dịch:

1. Ba tầng là **ba đối tượng JSON riêng biệt** trong `/api/state`; ba khối riêng, ba màu, ba nhãn trên giao diện. **Không có dòng tổng ở cuối.**
2. Mỗi con số Tầng 2 hiển thị giả định của nó ngay bên cạnh.
3. Mọi con số Tầng 3 mang nhãn "DỰ PHÓNG" tại chỗ nó hiển thị, không phải trong chú thích cuối trang.

Kèm bốn cơ chế chống thao túng ([07 §7](../07-esg-3-tang.md#7-chống-thao-túng-chỉ-số)), trong đó quan trọng nhất: **sàn ngưỡng theo nhiệt nhàn rỗi đo được**, và **chỉ số chủ đạo có mẫu số**.

Và: **báo cáo tính từ nhật ký sự kiện, không phải từ biến tích lũy** — hàm thuần, cùng đầu vào cho cùng đầu ra.

## Phương án đã cân nhắc

### A. Giữ công thức cũ, chỉ thêm disclaimer

**Loại.** Disclaimer không sửa được vấn đề thao túng. Ai đó vẫn hạ ngưỡng xuống 40°C và con số vẫn tăng. Và một disclaimer đặt cạnh một con số sai không làm con số đó đúng — nó chỉ chuyển trách nhiệm sang người đọc.

### B. Chỉ giữ Tầng 1

Bỏ hết suy diễn và ngoại suy. Chỉ hiện J/token, chênh lệch A/B, giây throttle.

**Loại, nhưng là phương án đứng thứ hai.** Nó vững tuyệt đối. Nhưng nó **xóa sổ câu chuyện thương mại** — không còn kWh, không còn VNĐ, không còn CO₂, không còn tín chỉ carbon. Ở quy mô PoC, J/token cải thiện 14% là một con số kỹ thuật đúng nhưng không nói lên được tiềm năng kinh doanh.

Kiến trúc ba tầng giữ được câu chuyện đó mà **không để nó kéo phần đo được sụp theo** khi bị chất vấn. Đó là điểm cốt lõi: tách bạch để phần yếu không lây sang phần mạnh.

### C. Một con số duy nhất với khoảng tin cậy

Gộp cả ba tầng, kèm dải sai số.

**Loại.** Khoảng tin cậy giả định các nguồn sai số cùng loại và có thể cộng theo thống kê. Ở đây chúng khác hẳn nhau về bản chất: Tầng 1 là sai số **đo lường**, Tầng 3 là sai số **giả định mô hình**. Cộng chúng lại là sai về mặt phương pháp và tạo ra một con số trông chính xác hơn thực tế — điều tệ hơn cả không có con số.

### D. Bỏ hẳn ESG, chỉ làm điều phối nhiệt

**Loại.** ESG là lý do dự án tồn tại về mặt thương mại. Vấn đề nằm ở *cách đo*, không phải ở *việc đo*.

## Hệ quả

### Tích cực

- **Chống được chất vấn nghiêm túc.** Sáu câu hỏi phản biện khó nhất đều có câu trả lời trỏ được tới dữ liệu ([07 §10](../07-esg-3-tang.md#10-câu-hỏi-phản-biện-và-câu-trả-lời)).
- **Không thao túng được.** J/token có mẫu số là token: gắn cờ nhiều hơn → ít token hơn → tỷ số không tự đẹp lên. Đây là tính chất toán học, không phải một luật kiểm tra có thể quên áp dụng.
- **Kiểm toán được.** Nhật ký sự kiện cho phép truy ngược mọi con số tới nguồn gốc — điều kiện tiên quyết để báo cáo có giá trị với bên thứ ba.
- **Tính lại được.** Đổi hằng số ESG rồi tính lại toàn bộ lịch sử, không cần chạy lại thí nghiệm.
- Vẫn giữ được câu chuyện thương mại ở Tầng 3.

### Tiêu cực

- **Con số Tầng 1 sẽ nhỏ hơn nhiều so với con số cũ**, và có thể **âm**. Phải chuẩn bị tinh thần cho việc A/B cho kết quả xấu hơn round-robin. Đã có kịch bản trả lời, nhưng nó vẫn là một cuộc trò chuyện khó.
- **Giao diện phức tạp hơn.** Ba khối thay vì một danh sách. Người dùng phải hiểu khái niệm "tầng độ tin cậy" — cần thiết kế giao diện cẩn thận để không gây rối.
- **Phụ thuộc vào việc đo được công suất.** Nếu không máy nào đọc được `power_w`, Tầng 1 gần như rỗng. Đây là rủi ro có thật, khả năng xảy ra cao, và phải kiểm **ngay bây giờ** bằng `power_probe.ps1` chứ không đợi tới M4.
- **Công nhiều hơn.** Ước tính 6–10 ngày cho M4, so với khoảng 2 ngày nếu giữ công thức cũ.

### Trung tính

- `cooling_overhead_factor` giảm từ 0,5 xuống 0,25 và chuyển sang Tầng 2. Con số nhỏ hơn nhưng trung thực hơn với bối cảnh máy văn phòng.
- Định giá carbon chỉ xuất hiện ở Tầng 3, sau khi đã ngoại suy quy mô. Ở quy mô PoC con số thật là khoảng 0,15 ₫/giờ — hiển thị nó sẽ phá hỏng độ tin cậy của cả panel.

## Kiểm chứng

| Cách kiểm | Kỳ vọng |
|---|---|
| Ca E1–E14 ([11 §7](../11-chien-luoc-kiem-thu.md#7-kiểm-thử-esg)) | Toàn bộ xanh |
| **Ca E13** | Gắn cờ mọi node cả ngày → **J/token không cải thiện** |
| Ca E12 | Đặt ngưỡng dưới sàn → bị từ chối |
| Ca E8 | Kết quả âm → báo cáo đúng dấu, không giấu |
| Ca E10 | Tính lại từ nhật ký → đúng kết quả cũ |
| Ca E14 | Ba tầng là ba đối tượng JSON riêng |
| Ca X5 | Host khởi động lại → số ESG không mất |
| Buổi bảo vệ | Trả lời được cả 6 câu phản biện bằng dữ liệu, không bằng lập luận |

**Dấu hiệu quyết định này sai:** nếu sau M4 mà Tầng 1 vẫn rỗng vì không máy nào đo được công suất, thì kiến trúc ba tầng chỉ còn hai tầng suy diễn — khi đó phải cân nhắc lại, có thể là mua đồng hồ điện và hiệu chuẩn thủ công cho ít nhất một máy để có mỏ neo đo thật.
