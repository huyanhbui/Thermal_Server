# ADR-005 — Runtime LLM và mô hình

**Trạng thái:** ✅ **Đã chốt**
**Ngày mở:** 2026-07-31
**Ngày chốt:** 2026-08-01
**Người quyết:** Chủ dự án
**Hạn:** Trước khi bắt đầu mốc M3 — đã đạt
**Tài liệu hỗ trợ:** [`09-so-sanh-llm-runtime.md`](../09-so-sanh-llm-runtime.md)

> ADR này đã chốt. M3 được phép bắt đầu trên cơ sở quyết định dưới đây. Đổi ý → viết ADR mới, không sửa phần Quyết định của ADR này.

## Bối cảnh

Bản thiết kế ghi "chat LLM 0,5B hoặc 0,8B trên CPU" nhưng không chốt runtime hay mô hình cụ thể. Quyết định này ảnh hưởng tới:

- Kiến trúc worker (tiến trình con với thư viện trong tiến trình)
- Nội dung `room_config` trong hợp đồng API ([03 §3](../03-hop-dong-api.md#post-join))
- Giá trị `max_concurrent` và `RESERVATION_TIMEOUT_S` ([04 §8](../04-dac-ta-scheduler.md#8-hằng-số-và-mặc-định))
- Khả năng được bộ phận IT phê duyệt ([06 §5](../06-bao-mat-va-quyen-rieng-tu.md#5-chuỗi-cung-ứng))
- Cách đếm token — nền tảng của [ESG Tầng 1](../07-esg-3-tang.md#31-joule-trên-token)

**Lưu ý về con số "0,8B":** không có mô hình mở phổ biến nào đúng 0,8B tham số. Các mốc thật gần đó: 0,36B, 0,5B, 0,6B, 1B, 1,5B.

## Các phương án

Phân tích đầy đủ: [`09-so-sanh-llm-runtime.md`](../09-so-sanh-llm-runtime.md).

### Runtime

| | llama.cpp | ONNX Runtime GenAI | Ollama |
|---|---|---|---|
| Kiểu tích hợp | Tiến trình con + HTTP localhost | Thư viện .NET trong tiến trình | Dịch vụ toàn máy |
| Rủi ro AV | ❌ **Cao** — không ký số | ✅ **Thấp** — DLL ký số Microsoft | ⚠️ Trung bình |
| Độ phủ mô hình nhỏ | ✅ **Rộng nhất** | ⚠️ Hạn chế | ✅ Rộng |
| Ghim SHA256 | ✅ | ✅ | ❌ **Không được** |
| Thống kê token | ✅ Đầy đủ | ✅ | ⚠️ Qua lớp trung gian |
| Kiểm soát vòng đời | ⚠️ Phải giám sát | ✅ **Đơn giản nhất** | ❌ Không kiểm soát |
| Giấy phép | MIT | MIT | MIT |

Ollama đã bị loại vì không ghim được SHA256 và chạy như dịch vụ toàn máy.

### Mô hình

Khuyến nghị **chỉ dùng mô hình Apache-2.0** — loại bỏ hoàn toàn khâu rà soát pháp lý nội bộ.

| Mô hình | Tham số | Giấy phép |
|---|---|---|
| Qwen2.5-0.5B-Instruct | 0,49B | Apache-2.0 |
| Qwen3-0.6B | 0,6B | Apache-2.0 |
| SmolLM2-360M-Instruct | 0,36B | Apache-2.0 |
| Qwen2.5-1.5B-Instruct | 1,5B | Apache-2.0 |

## Khuyến nghị (trước khi chốt)

**llama.cpp + Qwen2.5-0.5B-Instruct Q4_K_M**, kèm một lớp trừu tượng `ILlmRunner` để đổi runtime sau này chỉ tốn một lớp mới.

Ba lý do:

1. **Độ phủ mô hình quyết định trong giai đoạn này** — còn phải thử 0,5B với 0,6B với 1,5B, còn phải kiểm chất lượng tiếng Việt. Đổi mô hình với llama.cpp là đổi một tệp GGUF.
2. **Thống kê token đầy đủ và sẵn sàng** — ESG Tầng 1 dùng được ngay, không phải xấp xỉ.
3. **Rủi ro AV giảm được bằng cách khác** — ghim hash, tài liệu whitelist, và ký số chính bộ cài. Chi phí này phải bỏ ra dù chọn runtime nào, vì bản thân agent đã cần quyền Administrator.

**Chuyển sang ONNX nếu bộ phận IT chặn `llama-server.exe` và không chịu whitelist.**

## Việc đã làm TRƯỚC khi chốt

| # | Việc | Trạng thái |
|---|---|---|
| 1 | Hỏi bộ phận IT về whitelist exe chưa ký số | ⚠ **Chưa hỏi** — chấp nhận rủi ro tạm; xem Hệ quả |
| 2 | Benchmark trên ≥2 máy | Đo **1 máy** (`DESKTOP-7AV7O2F`) — hạn chế đã ghi |
| 3 | Kiểm chất lượng tiếng Việt | Mẫu in tại `scripts/bench_llm/results/vi_samples/` — chủ dự án tự đọc |
| 4 | Đo với `--threads = số nhân − 2` | Đã làm (12 → 10) |
| 5 | Đo để chốt `max_concurrent` | Giữ `1` (an toàn CPU) |

## Kết quả benchmark

> Đo ngày 2026-08-01 bằng harness độc lập [`scripts/bench_llm/`](../../scripts/bench_llm/). Báo cáo đầy đủ + mẫu tiếng Việt: [`scripts/bench_llm/results/REPORT.md`](../../scripts/bench_llm/results/REPORT.md).
>
> **Hạn chế:** chỉ **1 máy** (`DESKTOP-7AV7O2F`) — không ngoại suy sang máy dị chủng khác. threads = 12 − 2 = **10**. J/token: EPT `confidence: chưa đủ dữ liệu` → **không công bố** số tuyệt đối.
>
> Chất lượng tiếng Việt: **chưa chấm tự động** — đọc nguyên văn tại `scripts/bench_llm/results/vi_samples/`.

| Máy | Runtime | Mô hình | tok/s sinh | tok/s prompt | RAM đỉnh | Nhiệt đỉnh | J/token | Chất lượng tiếng Việt |
|---|---|---|---|---|---|---|---|---|
| DESKTOP-7AV7O2F | llama.cpp | Qwen2.5-0.5B-Instruct Q4_K_M | 58.8 | 370.2 | 579 MB | 59 °C | chưa đủ dữ liệu (raw≈1.04) | xem `vi_samples/llama/qwen25-05.md` |
| DESKTOP-7AV7O2F | llama.cpp | Qwen3-0.6B Q4_K_M | 64.9 | 575.9 | 1412 MB | 55 °C | chưa đủ dữ liệu (raw≈0.91) | xem `vi_samples/llama/qwen3-06.md` |
| DESKTOP-7AV7O2F | llama.cpp | Qwen2.5-1.5B-Instruct Q4_K_M | 26.6 | 202.9 | 1820 MB | 66 °C | chưa đủ dữ liệu (raw≈2.31) | xem `vi_samples/llama/qwen25-15.md` |
| DESKTOP-7AV7O2F | llama.cpp | SmolLM2-360M-Instruct Q4_K_M | 78.3 | 403.0 | 675 MB | 63 °C | chưa đủ dữ liệu (raw≈0.92) | xem `vi_samples/llama/smollm2-360.md` |
| DESKTOP-7AV7O2F | ONNX GenAI | Qwen2.5-0.5B-Instruct INT4 | 66.3* | 293.8 | 631 MB | 56 °C | chưa đủ dữ liệu (raw≈0.79) | xem `vi_samples/onnx/qwen25-05.md` |
| DESKTOP-7AV7O2F | ONNX GenAI | (các mô hình khác) | N/A | N/A | N/A | N/A | N/A | thiếu gói ONNX INT4 |

\* Bản đo ONNX đầu chưa cùng điều kiện threads với llama — không dùng để so tốc độ khi chốt.

## Quyết định

> **Đã chốt** ngày 2026-08-01.
>
> - **Runtime:** llama.cpp, pin tag **`b10216`**, gói Windows CPU x64 (`llama-b10216-bin-win-cpu-x64.zip`). Worker spawn `llama-server` trên `127.0.0.1`, `--threads = số nhân − 2`.
> - **Mô hình:** **Qwen2.5-0.5B-Instruct**, lượng tử hóa **Q4_K_M** (GGUF), giấy phép Apache-2.0.
> - **SHA256** (tính bằng `Get-FileHash -Algorithm SHA256` trên máy chốt, 2026-08-01 — **không** sao chép từ tài liệu khác):
>
> | Tệp | SHA256 |
> |---|---|
> | `llama-b10216-bin-win-cpu-x64.zip` | `CA78DF53654BE907193F2615F590C51960F0A009C09285D1D1A5EFA8B84D69B9` |
> | `llama-server.exe` | `DCC76B45556B0252B353A4693E84376C8A04D2EB44B5BF153EFC18A5556C54E6` |
> | `llama-server-impl.dll` | `9CC77AC1DE3F90B3BEFA47377BB578EE3E3E3979DF8B39C5EBBC92B92193C513` |
> | `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | `6EB923E7D26E9CEA28811E1A8E852009B21242FB157B26149D3B188F3A8C8653` |
>
> - **Lý do:** **khớp khuyến nghị** [`docs/09`](../09-so-sanh-llm-runtime.md) §6 — độ phủ GGUF, thống kê token đầy đủ cho ESG Tầng 1, đổi mô hình bằng một tệp. Giữ `ILlmRunner` để chuyển ONNX sau nếu cần.
> - **Phản hồi bộ phận IT:** **chưa hỏi** tại thời điểm chốt. Chấp nhận rủi ro tạm; tài liệu whitelist đã soạn sẵn ở [10](../10-phong-tunnel-trien-khai.md) §7–§7b. Nếu IT từ chối whitelist → xem xét lại theo điều kiện ở Hệ quả (có thể chuyển ONNX).

```powershell
# Cách tính lại hash — luôn tự chạy, không sao chép
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-b10216-bin-win-cpu-x64.zip
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server.exe
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server-impl.dll
Get-FileHash -Algorithm SHA256 -LiteralPath .\Qwen2.5-0.5B-Instruct-Q4_K_M.gguf
```

## Hệ quả

**Đánh đổi đã chấp nhận**

- Tiến trình con `llama-server.exe` **chưa ký số** → rủi ro AV/EDR cao hơn ONNX; giảm bằng ghim SHA256 + whitelist IT + (sau này) ký bộ cài.
- Chỉ đo benchmark trên **một máy** — thông lượng trên máy phụ khác có thể thấp hơn; `max_concurrent` giữ 1.
- IT **chưa xác nhận** whitelist — triển khai diện rộng bị chặn cho tới khi có câu trả lời.
- J/token chưa đủ mẫu để công bố ESG Tầng 1 từ phiên G3.

**Xem lại quyết định này nếu**

- IT chặn `llama-server.exe` và không whitelist → chuyển ONNX Runtime GenAI (giữ `ILlmRunner`).
- Chủ dự án đọc mẫu tiếng Việt và thấy 0,5B không đạt → cân nhắc Qwen2.5-1.5B-Instruct Q4_K_M (đổi RAM + thông lượng + `RESERVATION_TIMEOUT_S`).
- Máy yếu nhất trong cụm tok/s quá thấp khi đo máy 2+ → SmolLM2-360M hoặc hạ `max_tokens` / giữ `max_concurrent = 1`.

## Sau khi chốt — danh sách cập nhật

| # | Việc | Ở đâu | Trạng thái |
|---|---|---|---|
| 1 | Ghim phiên bản + SHA256 thật | [10](../10-phong-tunnel-trien-khai.md) §6 | ✅ Đã cập nhật |
| 2 | Cập nhật `room_config` | [03](../03-hop-dong-api.md) §3 | ✅ Đã cập nhật |
| 3 | Chốt `max_concurrent` | [04](../04-dac-ta-scheduler.md) §8 | ✅ `MAX_CONCURRENT_DEFAULT = 1` |
| 4 | Chốt `RESERVATION_TIMEOUT_S` | [04](../04-dac-ta-scheduler.md) §8 | ✅ `20,0` (xác nhận sau G3) |
| 5 | Viết tài liệu whitelist cho IT | [10](../10-phong-tunnel-trien-khai.md) §7b | ✅ Bản nháp sẵn gửi IT |
| 6 | Điền bảng benchmark ở trên | tài liệu này | ✅ |
| 7 | Đổi trạng thái ADR sang "Đã chốt" | tài liệu này | ✅ |
