# Architecture Decision Records (ADR)

Mỗi tệp ghi lại **một quyết định kiến trúc**: bối cảnh dẫn tới nó, lựa chọn đã chốt, các phương án bị loại, và hệ quả phải chấp nhận.

## Vì sao cần ADR

Tài liệu thiết kế nói *cái gì*. ADR nói *tại sao* — và quan trọng hơn, nói *phương án nào đã bị loại và vì lý do gì*. Không có phần đó, sáu tháng sau sẽ có người đề xuất lại đúng phương án đã bị loại, và cuộc tranh luận diễn ra lại từ đầu.

## Danh sách

| # | Quyết định | Trạng thái |
|---|---|---|
| [001](ADR-001-reservation-thay-vi-push.md) | Giữ chỗ job qua trường `target`, không đổi sang push | ✅ Đã chốt |
| [002](ADR-002-xac-thuc-token.md) | Xác thực bằng token có trạng thái; danh tính từ token | ✅ Đã chốt |
| [003](ADR-003-esg-ba-tang.md) | ESG ba tầng, không bao giờ cộng gộp | ✅ Đã chốt |
| [004](ADR-004-du-bao-delta-t.md) | Dự báo ΔT thay vì nhiệt độ tuyệt đối | ✅ Đã chốt |
| [005](ADR-005-llm-runtime.md) | Runtime LLM và mô hình | ✅ Đã chốt |
| [006](ADR-006-llm-model-catalog.md) | Catalog mô hình chat chọn được | ✅ Đã chốt |

## Quy tắc

- **Một tệp, một quyết định.** Nếu phải dùng chữ "và" trong tiêu đề, có lẽ là hai ADR.
- **ADR không sửa, chỉ thay thế.** Đổi ý thì viết ADR mới, đánh dấu ADR cũ là `Bị thay thế bởi ADR-00X`. Lịch sử quyết định có giá trị riêng.
- **Luôn ghi phương án bị loại và lý do.** Đây là phần có giá trị nhất.
- **Luôn ghi hệ quả tiêu cực.** Một ADR chỉ toàn ưu điểm là một ADR chưa suy nghĩ đủ.

## Khuôn mẫu

```markdown
# ADR-00X — <Tiêu đề ngắn, ở thể khẳng định>

**Trạng thái:** Đề xuất | Đã chốt | Bị thay thế bởi ADR-00Y
**Ngày:** YYYY-MM-DD

## Bối cảnh
Vấn đề là gì? Ràng buộc nào? Dẫn chứng từ code hoặc số đo.

## Quyết định
Chốt cái gì. Cụ thể, không mơ hồ.

## Phương án đã cân nhắc
Từng phương án + lý do loại.

## Hệ quả
### Tích cực
### Tiêu cực — phải nêu, không được bỏ trống
### Trung tính

## Kiểm chứng
Làm sao biết quyết định này đúng hay sai?
```
