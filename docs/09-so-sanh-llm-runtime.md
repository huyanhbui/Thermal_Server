# 09 — So sánh LLM runtime và mô hình

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> **Trạng thái: ĐÃ CHỐT** — [`adr/ADR-005-llm-runtime.md`](adr/ADR-005-llm-runtime.md) (llama.cpp `b10216` + Qwen2.5-0.5B-Instruct Q4_K_M, 2026-08-01)

Đây là tài liệu để bạn ra quyết định, không phải tài liệu ghi lại quyết định đã có. Nó khóa kiến trúc worker, nên phải chốt trước mốc M3.

## Mục lục

- [Ràng buộc](#1-ràng-buộc)
- [Ứng viên runtime](#2-ứng-viên-runtime)
- [Ứng viên mô hình](#3-ứng-viên-mô-hình)
- [Bảng so sánh quyết định](#4-bảng-so-sánh-quyết-định)
- [Đo trước khi chốt](#5-đo-trước-khi-chốt)
- [Khuyến nghị](#6-khuyến-nghị)
- [Việc phải làm sau khi chốt](#7-việc-phải-làm-sau-khi-chốt)

---

## 1. Ràng buộc

Xếp theo mức cứng. Ràng buộc 1–4 là điều kiện loại; 5–7 là tiêu chí chấm điểm.

| # | Ràng buộc | Vì sao |
|---|---|---|
| 1 | **Worker không được cần Python** | Worker là 9 máy của người khác. Agent hiện tại là một tệp `.exe` tự chứa ([`NodeAgent.csproj`](../agent/NodeAgent.csproj)) và phải giữ như vậy |
| 2 | **Chạy trên CPU** | Không giả định máy nào có GPU |
| 3 | **Windows 10/11 x64** | |
| 4 | **Đếm được token và đo được thời gian** | Không có hai số này thì không tính được J/token — [ESG Tầng 1](07-esg-3-tang.md#31-joule-trên-token) sụp đổ |
| 5 | Ít bị AV/EDR doanh nghiệp chặn | [Rủi ro D15](01-danh-gia-thiet-ke-hien-tai.md#d15--tự-tải-binary--chạy-quyền-administrator--tệp-chưa-ký-số) |
| 6 | Giấy phép rõ ràng cho dùng nội bộ doanh nghiệp | |
| 7 | Dung lượng tải nhỏ | Nhân với 9 máy |

**Ràng buộc 4 đáng chú ý.** Nó loại mọi runtime chỉ trả về chuỗi văn bản mà không kèm thống kê. Bạn *có thể* tự đếm token bằng cách tokenize lại đầu ra, nhưng như vậy sẽ lệch so với số token runtime thật sự sinh ra, và J/token là chỉ số chủ đạo của cả hệ thống — không nên xây nó trên một con số xấp xỉ.

---

## 2. Ứng viên runtime

### 2.1. llama.cpp (`llama-server`)

Máy chủ HTTP đi kèm llama.cpp. Worker C# khởi động nó như tiến trình con và gọi qua `http://127.0.0.1:<cổng>`.

**Thuận**
- Binary Windows x64 dựng sẵn, phát hành thường xuyên trên GitHub
- Hỗ trợ rộng nhất cho mô hình nhỏ ở định dạng GGUF
- Trả về thống kê đầy đủ: `tokens_predicted`, `tokens_evaluated`, `predicted_ms`, `prompt_ms` — **thỏa mãn ràng buộc 4 một cách trực tiếp**
- Điều khiển được số luồng (`--threads`) — quan trọng vì cần chừa nhân cho sensor loop và cho chính người đang dùng máy
- Giấy phép MIT
- API tương thích OpenAI, dễ thay thế về sau

**Nghịch**
- **Binary không ký số** → rủi ro AV cao nhất trong ba phương án
- Tiến trình riêng → phải giám sát vòng đời (khởi động, treo, dọn khi worker thoát)
- Nhịp phát hành rất nhanh; phải ghim phiên bản chứ không lấy "bản mới nhất"
- Thêm một cổng lắng nghe trên `127.0.0.1` — không phá vỡ nguyên tắc outbound-only ra ngoài, nhưng phải nói rõ trong tài liệu bảo mật

### 2.2. ONNX Runtime GenAI

Thư viện .NET gọi trực tiếp trong tiến trình worker, không có tiến trình con.

**Thuận**
- **Native .NET** — thêm một gói NuGet, không spawn tiến trình, không quản lý cổng
- Native DLL do Microsoft phát hành và **ký số Authenticode** → **rủi ro AV thấp nhất**. Với một sản phẩm sẽ cài lên máy đồng nghiệp trong công ty, đây là lợi thế lớn hơn vẻ ngoài của nó
- Vòng đời đơn giản hơn hẳn: worker chết là runtime chết theo
- Có API thống kê sinh token

**Nghịch**
- Ít mô hình siêu nhỏ được chuyển sẵn sang định dạng ONNX INT4 hơn so với GGUF. Có thể phải tự chuyển đổi — mà bước chuyển đổi đó **cần Python**, tuy chỉ trên máy dev chứ không phải trên worker
- Hệ sinh thái nhỏ hơn, ít ví dụ hơn, gỡ lỗi khó hơn khi gặp vấn đề lạ
- Gắn chặt với .NET — nếu sau này muốn worker đa nền tảng thì phải làm lại

### 2.3. Ollama

**Thuận:** cài đặt đơn giản nhất, có bộ cài Windows, API sạch, tự quản lý mô hình.

**Nghịch — và đây là lý do loại:**
- Chạy như **dịch vụ toàn máy**, không phải tiến trình con của ứng dụng. Không kiểm soát được vòng đời, và nó xung đột với các cài đặt Ollama sẵn có trên máy đồng nghiệp
- Tự tải mô hình theo cơ chế riêng → **không ghim được SHA256 theo cách của chúng ta** ([D15](01-danh-gia-thiet-ke-hien-tai.md#d15--tự-tải-binary--chạy-quyền-administrator--tệp-chưa-ký-số))
- Thêm một lớp trừu tượng giữa chúng ta và thống kê token

Phù hợp cho thử nghiệm cá nhân, không phù hợp cho một sản phẩm được triển khai.

### 2.4. Đã loại từ đầu

| Phương án | Lý do loại |
|---|---|
| `transformers` + PyTorch | Vi phạm ràng buộc 1 (cần Python trên worker); dung lượng hàng GB |
| llama-cpp-python | Cùng lý do |
| LM Studio | Ứng dụng có giao diện, không phải thư viện nhúng |
| Máy chủ mô hình đám mây | Cả hệ thống dựa trên việc tính toán diễn ra **trên máy phụ** — đây là toàn bộ điểm của dự án |

---

## 3. Ứng viên mô hình

### Về con số "0,8B"

Bản thiết kế ghi "0,5B hoặc 0,8B". Trong thực tế **không có mô hình mở phổ biến nào đúng 0,8B tham số**. Các mốc thật gần đó: 0,5B, 0,6B, 0,36B, 1B, 1,5B. Nên đọc "0,8B" là *"một mô hình lớn hơn một bậc so với 0,5B"* và chọn theo bảng dưới.

### Bảng ứng viên

| Mô hình | Tham số | Giấy phép | GGUF | ONNX INT4 | Ghi chú |
|---|---|---|---|---|---|
| **Qwen2.5-0.5B-Instruct** | 0,49B | **Apache-2.0** | Có, rộng rãi | Có | Ứng viên "0,5B" chuẩn mực |
| **Qwen3-0.6B** | 0,6B | **Apache-2.0** | Có | Một phần | Ứng viên "0,8B" hợp lý nhất |
| **SmolLM2-360M-Instruct** | 0,36B | **Apache-2.0** | Có | Một phần | Cho máy yếu nhất trong cụm |
| **Qwen2.5-1.5B-Instruct** | 1,5B | **Apache-2.0** | Có | Có | Nếu muốn chất lượng cao hơn hẳn |
| Llama-3.2-1B-Instruct | 1,24B | Llama Community | Có | Có | **Giấy phép riêng** — cần rà soát pháp lý nội bộ |
| Gemma 3 (bản nhỏ nhất) | ~0,27B | Gemma Terms | Có | Một phần | **Điều khoản sử dụng riêng** |

**Khuyến nghị mạnh: chỉ dùng mô hình Apache-2.0.** Đây là sản phẩm sẽ triển khai trong doanh nghiệp. Apache-2.0 loại bỏ hoàn toàn khâu rà soát pháp lý; Llama Community License và Gemma Terms thì không — chúng có điều khoản sử dụng chấp nhận được, yêu cầu ghi công, và ràng buộc phân phối lại. Không đáng đánh đổi cho một chênh lệch chất lượng nhỏ ở tầm mô hình này.

### Lượng tử hóa

| Mức | Dung lượng (0,5B) | Chất lượng | Dùng khi |
|---|---|---|---|
| Q4_K_M | ~400 MB | Tốt | **Mặc định** — cân bằng tốt nhất |
| Q5_K_M | ~450 MB | Tốt hơn chút | Nếu RAM dư dả |
| Q8_0 | ~700 MB | Gần bản gốc | Chỉ khi cần đối chiếu chất lượng |
| INT4 (ONNX) | ~400 MB | Tương đương Q4 | Khi chọn ONNX Runtime |

**Bộ nhớ khi chạy:** trọng số Q4 khoảng 400 MB, cộng KV cache (phụ thuộc độ dài ngữ cảnh, khoảng 100–300 MB với 4K token) → **dưới 1 GB**. Chạy thoải mái trên máy 8 GB RAM song song với công việc thường ngày của người dùng.

---

## 4. Bảng so sánh quyết định

| Tiêu chí | Trọng số | llama.cpp | ONNX GenAI | Ollama |
|---|:---:|:---:|:---:|:---:|
| Worker không cần Python | Loại | ✅ | ✅ | ✅ |
| Có thống kê token | Loại | ✅ đầy đủ | ✅ | ⚠️ qua lớp trung gian |
| **Rủi ro AV doanh nghiệp** | Cao | ❌ không ký số | ✅ **DLL ký số Microsoft** | ⚠️ bộ cài có ký |
| Độ phủ mô hình nhỏ | Cao | ✅ **rộng nhất** | ⚠️ hạn chế | ✅ rộng |
| Ghim được SHA256 | Cao | ✅ | ✅ | ❌ **cơ chế riêng** |
| Kiểm soát vòng đời | Trung bình | ⚠️ tiến trình con | ✅ **trong tiến trình** | ❌ dịch vụ toàn máy |
| Kiểm soát số luồng | Trung bình | ✅ `--threads` | ✅ | ⚠️ hạn chế |
| Độ trưởng thành hệ sinh thái | Trung bình | ✅ **rất lớn** | ⚠️ nhỏ hơn | ✅ lớn |
| Dung lượng tải thêm | Thấp | ~50 MB | ~100 MB (NuGet) | ~500 MB |
| Giấy phép runtime | — | MIT | MIT | MIT |

**Ba tiêu chí thực sự phân định:**

1. **Rủi ro AV** — ONNX thắng rõ ràng. DLL ký số bởi Microsoft là khác biệt về chất, không phải về lượng, trong môi trường có EDR.
2. **Độ phủ mô hình** — llama.cpp thắng rõ ràng. Mọi mô hình nhỏ mới ra đều có GGUF trong vài ngày; ONNX INT4 thì không chắc.
3. **Vòng đời** — ONNX thắng. Không có tiến trình mồ côi, không có cổng bị chiếm, không có logic giám sát phải viết và phải test.

---

## 5. Đo trước khi chốt

**Không chốt bằng tài liệu này.** Các con số thông lượng phụ thuộc nặng vào CPU cụ thể; một ước lượng trong tài liệu không thay thế được phép đo trên chính phần cứng bạn sẽ dùng.

Ước lượng sơ bộ để đặt kỳ vọng (Q4, 0,5B, **cần đo lại**):

| Loại máy | Sinh token | Câu trả lời 200 token |
|---|---|---|
| Desktop 6 nhân đời mới | ~40–80 tok/s | 3–5 s |
| Laptop 4 nhân | ~20–40 tok/s | 5–10 s |
| Laptop mỏng tiết kiệm điện | ~10–25 tok/s | 8–20 s |

### Quy trình đo

Nên làm ở mốc M3, trên **ít nhất hai máy khác nhau** trong cụm dự kiến — vì tính dị chủng của cụm chính là vấn đề mà [S4](01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình) đã nêu, và nó áp dụng cho thông lượng suy luận y như cho nhiệt độ.

```
1. Bộ 20 prompt cố định, độ dài đa dạng (ngắn / trung bình / dài)
2. Với mỗi (runtime × mô hình × máy), đo:
     - token/giây khi sinh
     - token/giây khi xử lý prompt
     - RAM đỉnh
     - nhiệt CPU đỉnh          ← đây là dữ liệu cho chính hệ thống này
     - J/token                 ← chạy scripts/measure_power/energy_per_token.py
     - thời gian khởi động lạnh (nạp mô hình)
3. Kiểm tra chất lượng đầu ra bằng tiếng Việt — mô hình 0,5B trả lời
   tiếng Việt kém hơn tiếng Anh đáng kể. Đây có thể là tiêu chí quyết định
   nếu người dùng sẽ chat bằng tiếng Việt.
4. Chạy thử với --threads = (số nhân − 2) để chừa chỗ cho sensor loop
   và cho chính người đang dùng máy
```

Bước 3 quan trọng hơn vẻ ngoài của nó. Nếu người dùng chat bằng tiếng Việt và mô hình 0,5B trả lời kém, thì lựa chọn đúng có thể là 1,5B chứ không phải 0,5B — và điều đó đổi cả ngân sách RAM lẫn thông lượng của toàn bộ thiết kế.

Bước 4 cũng vậy: nếu để llama.cpp dùng hết nhân, người sở hữu máy phụ sẽ thấy máy mình đơ mỗi lần có ai chat. Không ai để phần mềm đó chạy tới tuần thứ hai.

### Kết quả đo G3 (2026-08-01)

Harness: [`scripts/bench_llm/`](../scripts/bench_llm/). Chi tiết: [`scripts/bench_llm/results/REPORT.md`](../scripts/bench_llm/results/REPORT.md). Điền vào [ADR-005](adr/ADR-005-llm-runtime.md).

| Điều kiện | Giá trị |
|---|---|
| Số máy | **1** (`DESKTOP-7AV7O2F`) — không ngoại suy |
| CPU | Intel 12 nhân logic, `--threads` = 10 |
| llama.cpp | pin `b10216` win-cpu-x64 |
| Lượng tử | GGUF Q4_K_M; ONNX INT4 (chỉ 0.5B có gói sẵn) |

Tóm tắt tok/s sinh (median) trên máy này: SmolLM2-360 ≈ 78; Qwen2.5-0.5B llama ≈ 59 / ONNX ≈ 66; Qwen3-0.6B ≈ 65 (cần tắt thinking); Qwen2.5-1.5B ≈ 27. J/token (sensor) khoảng 0,8–2,3 tùy mô hình. Mẫu trả lời tiếng Việt in nguyên văn — **chủ dự án tự đọc, không chấm tự động**.

**Chưa có phản hồi IT** về whitelist exe chưa ký số.

---

## 6. Khuyến nghị

**Chọn llama.cpp + Qwen2.5-0.5B-Instruct Q4_K_M** làm cấu hình khởi điểm, đồng thời chuẩn bị sẵn đường sang ONNX.

Ba lý do:

1. **Độ phủ mô hình quyết định trong giai đoạn này.** Bạn còn đang thử 0,5B với 0,6B với 1,5B, còn phải kiểm tra chất lượng tiếng Việt. llama.cpp cho phép đổi mô hình bằng cách đổi một tệp GGUF; ONNX có thể buộc bạn tự chuyển đổi mỗi lần.
2. **Thống kê token đầy đủ và sẵn sàng.** `tokens_predicted`, `predicted_ms`, `prompt_ms` — [ESG Tầng 1](07-esg-3-tang.md#31-joule-trên-token) dùng được ngay, không phải xấp xỉ.
3. **Rủi ro AV giảm được bằng cách khác.** Ghim SHA256, tài liệu whitelist cho IT, và — nếu triển khai diện rộng — ký số chính bộ cài của bạn. Chi phí này phải bỏ ra dù chọn runtime nào, vì bản thân agent đã cần quyền Administrator.

**Nhưng phải xây một lớp trừu tượng.** Định nghĩa giao diện `ILlmRunner` trong worker với đúng ba phương thức:

```csharp
Task<bool>       EnsureReadyAsync(RoomConfig cfg, IProgress<double> progress);
Task<LlmResult>  GenerateAsync(string prompt, GenParams p, CancellationToken ct);
Task             ShutdownAsync();

record LlmResult(string Text, int TokensIn, int TokensOut,
                 double PromptMs, double PredictMs);
```

Đổi runtime sau này chỉ là viết một lớp mới. Chi phí bây giờ là khoảng một ngày công; chi phí nếu không làm và phải đổi ở tháng thứ ba là vài tuần.

**Chuyển sang ONNX nếu:** bộ phận IT chặn `llama-server.exe` và không chịu whitelist. Đây là kịch bản có thật, không phải giả định — hãy hỏi IT **trước** mốc M3, câu trả lời của họ có thể là yếu tố quyết định duy nhất.

---

## 7. Việc phải làm sau khi chốt

| # | Việc | Ở đâu |
|---|---|---|
| 1 | Ghi quyết định + lý do | [`adr/ADR-005-llm-runtime.md`](adr/ADR-005-llm-runtime.md) |
| 2 | Ghim phiên bản runtime + **SHA256 thật, lấy tại thời điểm chốt** | [`10-phong-tunnel-trien-khai.md`](10-phong-tunnel-trien-khai.md) |
| 3 | Ghim URL mô hình + SHA256 | như trên |
| 4 | Cập nhật `room_config` trong hợp đồng API | [`03-hop-dong-api.md`](03-hop-dong-api.md) §3 |
| 5 | Chốt `max_concurrent` theo số đo thật | [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md) §8 |
| 6 | Chốt `RESERVATION_TIMEOUT_S` theo độ trễ đo được | như trên |
| 7 | Viết tài liệu whitelist cho IT | [`10`](10-phong-tunnel-trien-khai.md) |
| 8 | Ghi kết quả benchmark vào tài liệu | tài liệu này, mục 5 |

**Không sao chép SHA256 từ bất kỳ tài liệu nào, kể cả tài liệu này.** Tự tải tệp, tự tính hash, tự ghi vào cấu hình:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server.exe
```
