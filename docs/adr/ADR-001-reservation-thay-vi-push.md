# ADR-001 — Giữ chỗ job qua trường `target`, không chuyển sang push

**Trạng thái:** Đã chốt
**Ngày:** 2026-07-31
**Liên quan:** [`01 §S1`](../01-danh-gia-thiet-ke-hien-tai.md#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại), [`04`](../04-dac-ta-scheduler.md)

## Bối cảnh

Bản thiết kế đưa ra công thức chấm điểm 5 số hạng và kết luận "Host chấm điểm node → gán chat job". Nhưng cơ chế hiện tại không có bước gán.

[`balancer.py:57`](../../server/balancer.py):

```python
def next_job(self, node, node_temps):
```

Hàm này trả lời *"node đang hỏi có được nhận việc không?"* — nó **lọc**, không **chọn**. Không có chỗ nào trong toàn bộ code so sánh các node với nhau. Node nào gọi `GET /jobs/next` trước thì lấy job trước; agent poll mỗi 1 giây ([`Program.cs:83`](../../agent/Program.cs)) nên thứ tự thực chất là ngẫu nhiên theo độ lệch đồng hồ.

Nếu code thẳng theo bản thiết kế, ta sẽ có một hàm `score()` đầy đủ, có test đơn vị xanh, và **không ảnh hưởng gì tới việc job đi đâu**. Tính năng bán hàng chính của sản phẩm sẽ im lặng không tồn tại.

**Ràng buộc cứng:** worker chỉ outbound. Không worker nào được lắng nghe cổng. Đây là tài sản kiến trúc lớn nhất của PoC — nó là lý do máy phụ không cần bất kỳ quy tắc tường lửa vào nào, và là điểm bán hàng chính với bộ phận IT.

## Quyết định

Host chấm điểm rồi **giữ chỗ job cho node thắng** bằng trường `target` đã có sẵn:

```python
job.target = người_thắng
job.reserved_until = now + RESERVATION_TIMEOUT_S    # mặc định 20s
inflight[người_thắng] += 1
```

Worker gọi `GET /jobs/next` chỉ nhận được job có `target` là chính nó — logic này **đã tồn tại** ở [`balancer.py:64`](../../server/balancer.py):

```python
if job["target"] in (None, node):
```

Bổ sung bắt buộc: **vòng thu hồi giữ chỗ quá hạn** chạy mỗi giây, trả job về đầu hàng đợi khi node được chọn không đến lấy.

Nâng cấp `/jobs/next` sang **long-poll** (`?wait=25`) để giảm độ trễ từ tối đa 1 giây xuống gần như tức thời, vẫn giữ nguyên chiều kết nối.

## Phương án đã cân nhắc

### A. Host đẩy job xuống worker qua HTTP

Host gọi `POST http://<worker>:port/job`.

**Loại:** phá vỡ nguyên tắc outbound-only. Worker phải mở cổng → cần quy tắc tường lửa trên 9 máy → cần IP tĩnh hoặc phát hiện dịch vụ → không dùng được với laptop di chuyển giữa các mạng. Đánh mất chính thứ làm cho hệ thống dễ triển khai.

### B. WebSocket bền từ worker tới host

Worker mở WebSocket, host đẩy job qua kênh đó. Vẫn outbound-only vì worker khởi tạo kết nối.

**Hoãn, không loại.** Đây là hướng đúng về lâu dài: độ trễ thấp nhất, host biết ngay worker còn sống mà không cần đợi timeout. Nhưng nó cần xử lý nối lại, đệm khi mất kết nối, và tim đập — khoảng 3–4 ngày công. Long-poll đạt được 90% lợi ích với 10% công sức, và ở quy mô 10 node thì chênh lệch còn lại không đáng kể.

Ghi vào bảng "tạm" ở [`12 §3`](../12-lo-trinh-va-milestone.md#3-tạm-cho-demo-với-vĩnh-viễn).

### C. Giữ nguyên "ai đến trước", chỉ tinh chỉnh cơ chế throttle

Mở rộng `_throttled` ([`balancer.py:45`](../../server/balancer.py)) thành nhiều mức thay vì cách-một-lượt.

**Loại:** đây là xấp xỉ thô của việc ưu tiên, không phải việc chọn. Nó không thể diễn đạt được "Node-B có headroom cao hơn nên đáng nhận job dù đang bận hơn". Và nó tạo ra hai chính sách điều phối song song — xem [M14](../01-danh-gia-thiet-ke-hien-tai.md#m14--hai-chính-sách-điều-phối-chồng-lên-nhau).

### D. Worker tự chấm điểm mình rồi tự quyết có lấy job không

**Loại:** worker không biết điểm của các worker khác. Nó không thể biết mình có phải lựa chọn tốt nhất hay chỉ là lựa chọn duy nhất đang rảnh. Ngoài ra, để worker tự đánh giá là mở đường cho worker giả mạo luôn tự cho mình điểm cao.

## Hệ quả

### Tích cực

- Công thức chấm điểm **thực sự có tác dụng** — sửa lỗi chặn chính
- Bảo toàn nguyên tắc outbound-only
- Tái dùng trường `target` đã có, đã được tôn trọng, đã có test (`test_targeted_job_only_goes_to_target`)
- Không đổi giao thức mạng, không đổi mô hình tường lửa
- Long-poll giảm độ trễ mà không thêm phức tạp đáng kể

### Tiêu cực

- **Bắt buộc phải có hạn giữ chỗ.** Ở cơ chế cũ, `target=None` nghĩa là job không bao giờ kẹt. Giờ một node treo sẽ nuốt job vĩnh viễn nếu không có vòng thu hồi. Đây là độ phức tạp mới, có thật, và phải được test kỹ (ca R3–R6).
- **Thêm một đường có thể lệch trạng thái.** `inflight` do host nắm và phải khớp với thực tế ở worker. Sai lệch tích lũy sẽ làm node bị coi là bận vĩnh viễn. Cần đối chiếu định kỳ.
- **Chậm hơn một chút trong trường hợp tốt nhất.** Cơ chế cũ: worker rảnh lấy job ngay. Cơ chế mới: chờ tới lượt scheduler (tối đa 1 giây). Chấp nhận được vì suy luận mất 3–10 giây.
- Kết quả trả về sau khi giữ chỗ đã hết hạn phải bị bỏ qua — thêm một trường hợp biên (ca X3).

### Trung tính

- `_throttled` và `_poll_count` bị xóa. Ghi ở đây để sau này không ai thêm lại.
- `RESERVATION_TIMEOUT_S` phải lớn hơn thời gian suy luận điển hình. Nó phụ thuộc mô hình và `max_tokens`, nên **đặt trong cấu hình phòng, không hard-code**.

## Kiểm chứng

| Cách kiểm | Kỳ vọng |
|---|---|
| Ca R1–R6 ([04 §9](../04-dac-ta-scheduler.md#giữ-chỗ)) | Giữ chỗ và thu hồi hoạt động đúng |
| Ca X2 ([11 §5](../11-chien-luoc-kiem-thu.md#5-kiểm-thử-hỗn-loạn)) | Worker chết giữa chừng → người dùng **vẫn nhận được trả lời** |
| Ca C1, C2 ([11 §4](../11-chien-luoc-kiem-thu.md#ca-tích-hợp)) | Phân bố job lệch rõ về node có headroom cao |
| Ca C9 | Nhiệt đỉnh cụm ở thermal-aware **thấp hơn** round-robin |
| Ma trận mạng ([10 §7](../10-phong-tunnel-trien-khai.md#7-ma-trận-mạng)) | Worker vẫn có 0 cổng vào |

**Dấu hiệu quyết định này sai:** tỷ lệ giữ chỗ hết hạn vượt 5% trong vận hành bình thường. Khi đó long-poll không đủ tin cậy và cần chuyển sang phương án B.
