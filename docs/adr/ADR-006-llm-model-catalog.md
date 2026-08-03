# ADR-006 — Catalog mô hình chat chọn được trên dashboard

**Trạng thái:** ✅ **Đã chốt**
**Ngày mở:** 2026-08-01
**Ngày chốt:** 2026-08-01
**Người quyết:** Chủ dự án
**Thay thế / bổ sung:** Bổ sung [ADR-005](ADR-005-llm-runtime.md) — **không** sửa phần Quyết định ADR-005
**Tài liệu hỗ trợ:** [`03`](../03-hop-dong-api.md), [`room_assets.py`](../../server/room_assets.py)

## Bối cảnh

ADR-005 ghim một model mặc định (Qwen2.5-0.5B Q4_K_M) và runtime llama.cpp `b10216`. Demo và so sánh chất lượng cần đổi model mà không sửa code — admin chọn từ catalog cố định trên dashboard.

Ràng buộc giữ nguyên:

- Một model / phòng (so sánh J/token giữa node mới có nghĩa).
- SHA256 phải ghim — không URL tùy ý, không “latest”.
- Worker chỉ outbound; tải GGUF theo `room_config` từ `/join`.
- Không sửa ADR-005 đã chốt.

## Quyết định

> **Đã chốt** ngày 2026-08-01.
>
> - **Catalog sản phẩm** (4 mục), admin chọn qua `settings.model_id` + dashboard:
>
> | model_id | Hiển thị | ~dung lượng |
> |---|---|---|
> | `qwen2.5-0.5b-instruct-q4_k_m` | Qwen2.5-0.5B (mặc định ADR-005) | ~0.4 GB |
> | `qwen3-0.6b-q4_k_m` | Qwen3-0.6B | ~0.4 GB |
> | `qwen3.5-2b-q4_k_m` | Qwen3.5-2B | ~1.4 GB |
> | `gemma-4-e2b-it-q4_k_m` | Gemma 4 E2B (≈2.3B) | ~3.1 GB |
>
> - **Không** đưa Qwen2.5-1.5B vào catalog sản phẩm nữa (vẫn có trong `scripts/bench_llm/models.json` để bench lịch sử).
> - **Runtime:** giữ **`b10216`** (ADR-005). `b10216` mới hơn các bản đã có gemma4/qwen35 trên upstream; nếu load GGUF mới thất bại → viết ADR runtime riêng, không im lặng.
> - **Hash model mới:** SHA256 = Hugging Face LFS OID của blob Q4_K_M (tree API), ghi uppercase trong `room_assets.py`. Worker so sánh không phân biệt hoa/thường. Xác nhận lại bằng `Get-FileHash` sau lần tải đầu.
> - **Chỉ text GGUF** — không phân phối mmproj / vision.
> - `POST /join` trả `room_config` theo `settings.model_id` hiện tại; thêm `model_filename`.
> - `GET /api/models` (admin): catalog + `selected`.
> - Đổi model: log `[LLM]`; state có `llm_model_id` / `llm_model_display`; worker phát hiện đổi → leave/join + tải lại.

## Phương án đã cân nhắc

| Phương án | Lý do |
|---|---|
| Giữ 1.5B trong catalog | Thay bằng Qwen3.5-2B + Gemma4-E2B theo yêu cầu sản phẩm |
| URL model do người dùng dán | Không ghim được chuỗi cung ứng; vi phạm docs/06 |
| Nâng llama.cpp ngay | Chỉ khi smoke load fail — tránh mở lại rủi ro AV/whitelist |
| Nhiều model cùng lúc trên các node | Phá so sánh J/token trong phòng |

## Hệ quả

### Tích cực

- Admin đổi model không cần rebuild agent / sửa hash tay.
- Catalog dưới ~4B params, phù hợp CPU office.

### Tiêu cực

- Gemma ~3 GB — tải lần đầu chậm; cần cảnh báo UI.
- Hash LFS OID chưa chạy `Get-FileHash` local tại thời điểm chốt — worker sẽ fail rõ nếu upstream đổi file (đúng hành vi mong muốn).
- Đổi model giữa phiên: worker phải leave/join; chat đang chạy có thể lỗi ngắn.

### Trung tính

- Mặc định vẫn 0.5B (ADR-005 không đổi).

## Kiểm chứng

- `list_models()` trả đúng 4 id; 1.5B không có.
- `room_config_llm(model_id=…)` đổi URL/SHA/filename.
- `POST /api/settings` với `model_id` lạ → `422 UNKNOWN_MODEL`.
- Pytest xanh; agent lấy filename từ `room_config`, không hardcode 0.5B.
