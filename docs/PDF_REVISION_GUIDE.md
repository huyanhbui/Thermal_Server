# Hướng dẫn sửa hồ sơ dự án Thermal_Server

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Thiết kế kỹ thuật: [`THERMAL_TRAINING_ARCHITECTURE.md`](THERMAL_TRAINING_ARCHITECTURE.md)
> Claim nào được phép nói: [`CLAIMS_RISKS_LIMITATIONS.md`](CLAIMS_RISKS_LIMITATIONS.md)
> **Trạng thái:** hướng dẫn soạn thảo — không phải đặc tả đã implement

Tài liệu này dùng để **sửa hồ sơ dự án / pitch PDF**, không dùng để sửa code.
Viết xong một câu trong hồ sơ, đối chiếu cột **SAFE CLAIM** / **DO NOT CLAIM**
của mục tương ứng trước khi chèn.

---

## Cách dùng

1. Mở hồ sơ PDF hiện tại (3 trang, nhóm PP2WIN / THERMAL_SERVER).
2. Với mỗi mục 1–7 dưới đây: đọc **OLD IDEA** → hiểu **vấn đề** → thay bằng
   **NEW IDEA** → chỉ chèn câu trong **SAFE CLAIM**.
3. Không lấy câu từ file markdown [`BÁO CÁO TỔNG QUAN DỰ ÁN.md`](../BÁO%20CÁO%20TỔNG%20QUAN%20DỰ%20ÁN.md)
   trong repo làm cấu trúc hồ sơ — file đó là báo cáo PoC kỹ thuật (8 mục),
   **không** phải bản pitch 7 mục.
4. Không thêm claim mà PDF cũ **không có** rồi “đính chính”. Ví dụ PDF **không**
   nói “ghép RAM hàng trăm PC thành siêu máy tính” — đừng viết câu đó dù
   chỉ để phủ nhận.

---

## Nguồn OLD IDEA

| Nguồn | Vai trò |
|---|---|
| PDF 3 trang *BÁO CÁO TỔNG QUAN DỰ ÁN* (Downloads, không nằm trong git) | Hồ sơ pitch — đây là thứ cần sửa |
| Tagline PDF | «Nền tảng Điều phối AI Cục bộ & Báo cáo ESG Xanh Tự động» |
| Cấu trúc PDF | §1 Vấn đề · §2.1 Giải pháp · §2.2 Cơ chế · §2.3 Lợi thế · §3 Khách hàng · §4 Business model · §5 Kế hoạch triển khai |
| [`BÁO CÁO TỔNG QUAN DỰ ÁN.md`](../BÁO%20CÁO%20TỔNG%20QUAN%20DỰ%20ÁN.md) / [`PROJECT_OVERVIEW.en.md`](../PROJECT_OVERVIEW.en.md) | PoC kỹ thuật, wording **an toàn hơn** PDF — tham khảo giới hạn, không copy cấu trúc |

Code hiện tại khớp markdown PoC hơn PDF: Host FastAPI + NodeAgent C# +
llama.cpp, scheduler filter→score→reserve, ESG 3 tầng. **Chưa có** training
phân tán, Capability Manifest fail-closed, hay phát hiện người dùng.

---

## Định vị mới (thay tagline)

**Tiếng Anh (đưa vào hồ sơ / slide quốc tế):**

> Thermal_Server is a thermal-aware orchestration platform for opportunistic
> heterogeneous AI compute. It dynamically uses available enterprise computing
> resources for AI inference, preprocessing and decentralized training while
> protecting foreground users, hardware thermal limits and data privacy.

**Tiếng Việt (đưa vào hồ sơ):**

> Thermal_Server là nền tảng điều phối AI dị thể, nhận thức nhiệt, trên tài
> nguyên doanh nghiệp đang có. Hệ thống dùng máy còn headroom nhiệt cho suy
> luận, tiền xử lý và huấn luyện phân tán kiểu expert độc lập — đồng thời bảo
> vệ người dùng đang làm việc, giới hạn nhiệt phần cứng, và dữ liệu nội bộ.

**Sáu điểm khác biệt được phép nêu** (chỉ khi không gắn số liệu chưa đo):

Thermal-aware · Human-aware · Heterogeneous · Preemptible · Local/private ·
Energy-measurable

**Không** mô tả sản phẩm là:

- “Dùng PC rẻ thay GPU đắt.”
- “Ghép RAM hàng trăm PC thành một siêu máy tính.”
- “Zero CAPEX / Zero Carbon / Zero-Trust hoàn chỉnh.”
- “Chuyển model sang máy khác dưới 1 giây.”

---

## Bản đồ PDF → 7 mục hướng dẫn

| # | Mục hồ sơ | Trong PDF cũ |
|---|---|---|
| 1 | Phân tích vấn đề | §1 |
| 2 | Giải pháp và giá trị cốt lõi | §2.1 |
| 3 | Cơ chế vận hành | §2.2 |
| 4 | Lợi thế cạnh tranh | §2.3 |
| 5 | Khách hàng | §3 |
| 6 | Business model | §4 |
| 7 | Roadmap | §5 Kế hoạch triển khai |

---

## 1. PHÂN TÍCH VẤN ĐỀ

### OLD IDEA

- «Khoảng **70%** công suất CPU/RAM của hệ thống máy trạm văn phòng không
  được khai thác…»
- «Việc tự xây dựng cụm máy chủ GPU đòi hỏi chi phí đầu tư **(CAPEX)** quá
  lớn…»
- «Thuê dịch vụ AI đám mây… nguy cơ rò rỉ dữ liệu…»
- Tổ chức «sở hữu sẵn **hàng ngàn** thiết bị máy tính văn phòng»

### Vấn đề

- **70% idle không có nguồn** trong PDF, không có phép đo trong repo. Đối thủ
  hoặc hội đồng sẽ hỏi “đo thế nào, trên mẫu nào”.
- “Hàng ngàn máy” là quy mô thị trường; PoC kỹ thuật hiện **tới 10 node**
  ([`docs/00`](00-TONG-QUAN-KY-THUAT.md)).
- Dễ bị đọc thành “PC thay GPU” hoặc “gom RAM thành siêu máy tính”. Câu siêu
  máy tính **không có** trong PDF — giữ nguyên việc không nói.

### NEW IDEA

Vấn đề thật, bám đúng sản phẩm:

1. Workload AI **dồn vào một máy** gây quá nhiệt và thermal throttling.
2. Doanh nghiệp có CPU/RAM/GPU **dị thể, đang nhàn rỗi**, nhưng không có lớp
   điều phối biết nhiệt, biết người dùng, biết năng lực từng máy.
3. Người dùng thật trên máy phải **được ưu tiên** hơn job AI nền.
4. Dữ liệu nhạy cảm nên xử lý **trong perimeter**, không mặc định đẩy cloud.
5. Hiệu quả năng lượng phải **đo**, không suy từ việc “không mua GPU mới”.

### SAFE CLAIM

> Nhiều tổ chức đã có PC và workstation phân tán. Khi chạy AI tập trung trên
> một máy hoặc một cụm nhỏ, thiết bị dễ quá nhiệt, giảm xung, và tranh CPU/GPU
> với người đang làm việc. Thuê AI đám mây tiện nhưng đưa dữ liệu ra ngoài
> perimeter. Cần một lớp điều phối dùng đúng máy còn headroom nhiệt, đúng loại
> việc (suy luận, tiền xử lý, hoặc huấn luyện expert nhỏ), và nhường tài nguyên
> khi người dùng quay lại.

### DO NOT CLAIM

- 70% hay 80% công suất văn phòng đang nhàn rỗi.
- Sẵn sàng triển khai hàng ngàn node (chưa chứng minh).
- PC văn phòng luôn rẻ hơn / mạnh hơn cụm GPU.
- Gom RAM nhiều máy thành một không gian nhớ dùng chung.

---

## 2. GIẢI PHÁP VÀ GIÁ TRỊ CỐT LÕI

### OLD IDEA

- «…hình thành một cụm điện toán phân tán phục vụ **Local LLM Inference**…»
- «Giải pháp được xây dựng trên ba trụ cột: **Zero-CAPEX, Zero-Trust** và ESG
  minh bạch (Joule/Token).»
- «khai thác **70–80%** năng lực tính toán còn nhàn rỗi…»
- «giảm đáng kể chi phí đầu tư **(Zero-CAPEX)**…»
- «Thermal Orchestrator áp dụng kiến trúc **Zero-Trust**, trong đó các Agent
  chỉ thiết lập kết nối Outbound-only…»
- «…đáp ứng các tiêu chuẩn **IFRS S1/S2, GRI và SASB**…»

### Vấn đề

- Định vị **chỉ inference** — hẹp hơn hướng sản phẩm mới, và không mô tả
  đúng novelty (điều phối nhiệt + human-first + training preemptible).
- **Zero-CAPEX** sai nếu khách phải mua GPU cho training, trả license, hoặc
  công IT whitelist. Inference trên máy sẵn có **giảm CAPEX**, không xóa CAPEX.
- **Zero-Trust hoàn chỉnh** sai: repo có token phòng, outbound-only, SHA256
  artifact LLM; LAN vẫn có thể HTTP plaintext; chưa mTLS; job training chưa
  ký; chưa trust-level dữ liệu ([`docs/06`](06-bao-mat-va-quyen-rieng-tu.md)).
  Outbound-only là **một** kiểm soát mạnh, không phải cả khung Zero Trust.
- IFRS/GRI/SASB: ESG 3 tầng của repo **không** tự chứng minh tuân thủ chuẩn
  báo cáo. Tầng 3 là ngoại suy có nhãn.

### NEW IDEA

Một nền tảng điều phối, **ba loại việc**:

| Loại việc | Runtime | Ghi chú hồ sơ |
|---|---|---|
| AI inference | llama.cpp (giữ nguyên ADR-005) | Đã có PoC |
| Preprocessing / data jobs | CPU worker (C0) hoặc GPU yếu | Phần mở rộng |
| Decentralized training | PyTorch Trainer **add-on**, không nằm trong bộ cài inference | MVP = Tầng A, expert độc lập |

Giá trị cốt lõi — **không** gộp thành một slogan Zero-\*:

1. **Thermal-aware** — dự báo ΔT, không chờ máy cháy mới chuyển việc.
2. **Human-aware** — người dùng thật > AI nền; pause tại checkpoint, không
   kill bừa.
3. **Heterogeneous** — Capability Manifest fail-closed; không bắt mọi máy làm
   cùng một việc.
4. **Preemptible** — Training Lease 120–300 giây; reclaim lịch sự.
5. **Local/private** — dữ liệu ưu tiên ở lại phòng; phân loại
   PUBLIC→RESTRICTED.
6. **Energy-measurable** — Joule/token (Tầng 1, khi có cảm biến);
   Energy-to-Target-Quality khi có thí nghiệm training.

### SAFE CLAIM

> Thermal_Server điều phối việc AI trên máy doanh nghiệp đang có: suy luận
> LLM cục bộ, tiền xử lý dữ liệu, và (module add-on) huấn luyện phân tán kiểu
> expert độc lập. Scheduler chọn máy theo headroom nhiệt dự báo và trạng thái
> tải; worker chỉ chủ động kết nối ra Host; số năng lượng được tách theo tầng
> đo / suy ra / ngoại suy, không cộng thành một con số.

### DO NOT CLAIM

- Zero-CAPEX / Zero-Trust (như trụ cột đã hoàn thành).
- Đáp ứng IFRS S1/S2, GRI, SASB.
- Cụm PC luôn xanh hơn / rẻ hơn cụm GPU.
- Đã chạy distributed training trên sản phẩm (hiện mới có thiết kế + PoC
  inference).
- Worker mặc định cài Python/PyTorch (đó là add-on; inference SKU không cần
  Python — [`docs/09`](09-so-sanh-llm-runtime.md)).

**Câu thay thế sẵn:**

- Thay «Local LLM Inference» → «nền tảng điều phối AI dị thể nhận thức nhiệt:
  inference, tiền xử lý và huấn luyện phân tán kiểu expert độc lập».
- Thay «Zero-CAPEX, Zero-Trust» → «tận dụng hạ tầng đang có, kết nối worker
  outbound, đo năng lượng theo tầng độ tin cậy».

---

## 3. CƠ CHẾ VẬN HÀNH

### OLD IDEA

- «**Mô hình nhiệt bậc một** phối hợp cùng Băng trễ **thay cho những thuật
  toán học máy** vốn có độ dự đoán kém ổn định.»
- «…chuyển giao nhiệm vụ sang máy khác trong thời gian **chưa đầy 1 giây**.»
- Host điều phối; Agent đọc cảm biến Libre Hardware Monitor; runtime
  Llama.cpp.

### Vấn đề

- Mâu thuẫn kỹ thuật: ADR-004 **học ΔT** (Random Forest hoặc dự phòng tuyến
  tính), không phải “thay ML bằng mô hình bậc một”. Băng trễ **có**
  (`HYSTERESIS_C=3`, `MIN_DWELL_S=30`) — giữ; đừng phủ nhận ML.
- «Chưa đầy 1 giây» mô tả **chu kỳ scheduler / thu hồi reservation**
  (~1 giây) hoặc gán lại job inference **mới**, không phải live-migrate mô
  hình đang chạy. Training **không** chuyển máy dưới 1 giây; thiết kế dùng
  lease + checkpoint.
- Phần llama.cpp + LHM + Host **đúng** với inference hiện tại.

### NEW IDEA

Luồng một trang (được phép vẽ trong hồ sơ):

```
Người dùng / API
    → Host (phòng, token, hàng đợi)
    → ForecastCache (ΔT 3 phút)
    → Scheduler: lọc → chấm điểm → giữ chỗ / cấp lease
    → Worker (chỉ outbound): cảm biến + (inference: llama.cpp)
                            + (training add-on: PyTorch Trainer)
```

- Job **inference**: ngắn; nếu node fail, Host gán attempt khác (không di
  chuyển bộ nhớ model đang generate).
- Job **training**: Host cấp Training Lease 120–300 giây; worker train tới
  checkpoint → xin renew; Host từ chối renew khi nóng, user active, hoặc cần
  reclaim → pause → resume trên cùng máy (ưu tiên) hoặc máy khác (nếu
  checkpoint đã về store).

### SAFE CLAIM

> Host chọn node theo nhiệt dự báo và telemetry thật. Worker không mở cổng vào;
> mọi kết nối do worker khởi tạo. Job suy luận ngắn được gán lại cho node khác
> khi node đang chạy lỗi hoặc bị gắn cờ quá nhiệt. Job huấn luyện dừng tại điểm
> checkpoint an toàn rồi resume — không di chuyển live phiên training.

### DO NOT CLAIM

- Live migration mô hình / training dưới 1 giây.
- «Chuyển tác vụ AI sang thiết bị mát hơn trong 1 giây» nếu người đọc hiểu
  là chuyển **phiên đang chạy**.
- Hệ thống **không dùng học máy** cho dự báo nhiệt (vì đang dùng ΔT / RF).
- Training đã chạy trên cụm khách hàng.

**Câu thay thế sẵn:**

- Thay «chưa đầy 1 giây» → «thu hồi lịch trình tại điểm checkpoint an toàn;
  không di chuyển live phiên training. Job suy luận mới được gán lại trong
  khoảng một chu kỳ điều phối.»

---

## 4. LỢI THẾ CẠNH TRANH

### OLD IDEA

- «Thay vì phải đối mặt với gánh nặng chi phí từ hệ thống **máy chủ GPU đắt
  đỏ**…»
- «…chuyển tác vụ AI sang thiết bị mát hơn **trong 1 giây**…»
- «…đo lường tức thời nhiệt độ **RAM/CPU**.»
- «Thiết lập hạ tầng bảo mật chuẩn **Zero-Trust chuyên sâu**…»
- «…mô hình tối ưu chi phí ban đầu **(Zero-CAPEX)**.»
- «…cắt giảm đáng kể lượng phát thải Carbon từ quá trình sản xuất, vận chuyển
  và đóng mới các cụm Máy chủ GPU đắt đỏ **(Zero Embodied Carbon)**…»
- «…tối ưu hóa chỉ số hiệu suất năng lượng trên từng tác vụ (Joule/token).»

### Vấn đề

- **Đo nhiệt RAM** — code đọc CPU/GPU package (LibreHardwareMonitor), không
  đo nhiệt RAM. Sai sự thật, dễ bị hỏi kỹ thuật.
- **Zero Embodied Carbon** không suy ra từ việc không mua GPU: máy văn phòng
  vẫn có embodied carbon; điện training vẫn phát thải. ESG repo **cấm** cộng
  tầng và **cấm** biến ngoại suy thành số đo.
- Joule/token là **đúng hướng** (Tầng 1) nhưng chỉ khi `energy_source=sensor`
  và có token thật — không dùng làm bằng chứng “cắt giảm carbon đáng kể”.

### NEW IDEA

So với Kubernetes / Slurm / Horovod / DeepSpeed: chúng **không** tối ưu
theo quỹ đạo nhiệt máy văn phòng, không human-first trên endpoint, không
fail-closed capability cho GPU không rõ VRAM.

So với Paris / Petals / DiLoCo: Thermal_Server **học pattern** (Tầng A:
expert độc lập; Tầng B: sync thưa; Tầng C: pipeline khi mạng đủ) và **thêm**
lớp nhiệt + user + lease mà paper không có. Không tuyên bố đã tái hiện kết
quả FID/FVD của Paris.

### SAFE CLAIM

> Điểm khác biệt là điều phối theo nhiệt độ và người dùng, trên phần cứng dị
> thể, có thể preempt, ưu tiên xử lý trong mạng nội bộ, và đo năng lượng theo
> tầng tin cậy. Với inference, hệ thống đã có chế độ đối chứng round-robin và
> chế độ thermal-aware. Training sẽ dùng cùng khung A/B, chưa phải thành quả
> hiện tại.

### DO NOT CLAIM

- Zero Embodied Carbon / Zero Carbon.
- Thay thế cụm GPU datacenter.
- Zero-Trust chuyên sâu / hoàn chỉnh.
- Đo nhiệt RAM.
- Live migrate trong 1 giây.
- Joule/token đã chứng minh tiết kiệm so với GPU server (chưa có thí nghiệm
  đó).

---

## 5. KHÁCH HÀNG

### OLD IDEA

- «B2B… Ngân hàng, Định chế Tài chính, Tập đoàn Viễn thông và Cơ quan Chính
  phủ.»
- «dữ liệu tuyệt đối không được rời khỏi không gian lưu trữ vật lý.»
- «cắt giảm **triệt để** chi phí hạ tầng IT… đáp ứng tự động… ESG quốc tế.»
- PoV «gói thử nghiệm **miễn phí chi phí khởi tạo**… máy tính nhân viên luôn
  mát mẻ… Hysteresis.»

### Vấn đề

- **Tunnel Cloudflare** (có trong sản phẩm) đưa lưu lượng ra ngoài LAN. Câu
  “tuyệt đối không rời không gian vật lý” **sai** khi bật tunnel.
- “Luôn mát” không chứng minh; hysteresis chỉ giảm dao động gắn cờ, không
  đảm bảo máy mát.
- “Cắt giảm triệt để” là tuyệt đối hóa.

### NEW IDEA

Khách hàng là đội AI/ML **nội bộ** tại tổ chức có máy Windows phân tán, cần:

- Chat/RAG/inference không đẩy prompt ra public cloud nếu chính sách cấm.
- Preprocess / embed / fine-tune nhỏ / train expert trên máy còn rảnh.
- Không được làm chậm nhân viên đang gõ Excel / họp.
- Dữ liệu RESTRICTED không sang worker thiếu mức tin cậy.

Đối tượng B2B (ngân hàng, telco, chính phủ) **giữ được** nếu gắn với perimeter
và audit, không gắn với Zero-Trust hoàn chỉnh.

### SAFE CLAIM

> Phù hợp tổ chức muốn giữ suy luận và (khi bật module) huấn luyện trong
> perimeter, tận dụng máy nhàn rỗi, và ưu tiên trải nghiệm nhân viên trên từng
> máy. Dữ liệu mặc định đi trong phòng Host–Worker; đường tunnel là tùy chọn
> và phải được nêu rõ khi demo khác mạng.

### DO NOT CLAIM

- Dữ liệu tuyệt đối không rời máy / không rời tòa nhà **khi bật tunnel**.
- Máy nhân viên luôn mát.
- Cắt giảm triệt để chi phí hạ tầng.
- Đã có PoV với ngân hàng / Big4 (trừ khi hợp đồng thật tồn tại — không thấy
  trong repo).

---

## 6. BUSINESS MODEL

### OLD IDEA

- «áp dụng mô hình **B2B SaaS**… định giá theo quy mô…»
- «Phí cấp phép… hàng năm dựa trên số lượng máy tính **(Nodes)**…»
- «biến mỗi máy tính văn phòng mới thành một điểm sinh lời.»
- «chính sách **0 đồng** cho phí triển khai ban đầu… chuyển toàn bộ rủi ro
  đầu tư **(CAPEX)** thành… **(OPEX)**…»
- «hợp tác… nhóm **Big4**… bán chéo…»

### Vấn đề

- “0 đồng triển khai” = Zero-CAPEX trá hình. Training add-on có chi phí:
  GPU (nếu cần), gói PyTorch, thời gian IT whitelist, điện.
- “Mỗi PC là điểm sinh lời” dễ bị đọc là đào coin trên máy nhân viên — trái
  human-first.
- Big4: chỉ nêu nếu có MOU; nếu không, để phần đối tác là *hướng đi*.

### NEW IDEA

- **SKU Inference:** Host + NodeAgent + llama.cpp (bộ cài hiện tại).
- **Add-on Training Runtime:** PyTorch trainer, Dataset Registry, Artifact
  Store — bán / bật riêng.
- Định giá: phí Host + phí node **được phép chạy AI nền** (không đếm mọi PC
  trong AD).
- PoV: đo nhiệt, số lần preempt, ảnh hưởng user, Joule/token, và khi có train
  thì Energy-to-Target-Quality. **Không** bán tín chỉ carbon.

### SAFE CLAIM

> Có thể triển khai trên máy Windows đang có. Chi phí thêm gồm license phần
> mềm và, nếu bật huấn luyện, phần cứng/IT phù hợp — không bắt buộc mua cụm
> GPU mới cho bước PoC inference. Module training là add-on, không nằm trong
> bộ cài mặc định.

### DO NOT CLAIM

- Zero CAPEX.
- 0 đồng triển khai mọi trường hợp.
- OPEX thay thế hoàn toàn CAPEX.
- Tối đa hóa doanh thu bằng cách chiếm mọi PC văn phòng.

---

## 7. ROADMAP

### OLD IDEA (PDF §5)

| Giai đoạn | Thời gian | Mục tiêu PDF |
|---|---|---|
| 1 Nghiên cứu & thiết kế | T1–T2 | Khảo sát LLM DN, thiết kế KT |
| 2 MVP | T3–T5 | Phân tải, UI, API, LLM |
| 3 Kiểm thử | T6–T8 | Hiệu năng, tiết kiệm tài nguyên, Beta |
| 4 PoV khách hàng | T9–T10 | ≥03 đơn vị, RC |
| 5 Hoàn thiện BM | T11–T12 | Doanh thu, gọi vốn |

PDF **không** có training / PyTorch / Tầng A–C.

Lộ trình kỹ thuật trong repo ([`docs/12`](12-lo-trinh-va-milestone.md)) là
M0–M6 cho **inference** (~37–59 ngày công) — khác lịch 12 tháng của PDF.

### Vấn đề

Gộp lịch thương mại với milestone kỹ thuật khiến hội đồng tưởng training đã
nằm trong T3–T5. Inference PoC **đã chạy**; training là **giai đoạn mới**.

### NEW IDEA

Tách hai trục:

**Trục kỹ thuật** (chi tiết: [`DISTRIBUTED_TRAINING_ROADMAP.md`](DISTRIBUTED_TRAINING_ROADMAP.md)):

| Phase | Tên | Ý nghĩa một câu |
|---|---|---|
| 1 | Capability Foundation | Biết máy là gì; fail-closed |
| 2 | Training Runtime | PyTorch add-on, MNIST/CIFAR, checkpoint |
| 3 | Thermal-aware Training | Lease, user, pause/resume, A/B vs round-robin |
| 4 | Tầng A | Nhiều expert độc lập + shard + router |
| 5 | Tầng B | Local SGD / DiLoCo-like, sync thưa |
| 6 | Tầng C | Nghiên cứu pipeline — **không ship** |

**Trục thương mại:** PoV inference (máy thật, soak, ký mã) độc lập với Phase
2–4. Gọi vốn / cuộc thi dùng định vị mới, không dùng Zero-\*.

### SAFE CLAIM

> Đã có PoC điều phối inference theo nhiệt trên Windows, worker outbound-only.
> Bước kỹ thuật tiếp theo là Capability Manifest fail-closed và huấn luyện
> preemptible quy mô nhỏ. MVP huấn luyện phân tán là nhiều expert độc lập, không
> đồng bộ gradient từng bước. Pipeline/model parallel là hướng nghiên cứu, chưa
> phải sản phẩm.

### DO NOT CLAIM

- Đã hỗ trợ distributed training trên repo hiện tại.
- Đã có pipeline parallel / “một mô hình xuyên nhiều máy”.
- Phase C sẽ giao trong năm nếu chưa có mạng và topology đạt yêu cầu.
- Lịch T1–T12 cũ vẫn mô tả đúng sản phẩm mới.

---

## Bảng câu cấm — dán cạnh màn hình khi sửa PDF

| Không viết | Vì sao | Viết thay |
|---|---|---|
| Zero-CAPEX / 0 đồng triển khai | Chưa đúng với training add-on và công IT | Tận dụng máy đang có; chi phí thêm là license và (nếu train) GPU/IT |
| Zero-Trust / Zero-Trust chuyên sâu | Token + outbound ≠ Zero Trust đủ | Worker chỉ kết nối ra; danh tính lấy từ token; artifact LLM ghim SHA256 |
| Zero Carbon / Zero Embodied Carbon | Không đo được bằng cách không mua GPU | Đo Joule/token và kWh/run; kết luận xanh khi có A/B |
| Chuyển tác vụ trong 1 giây | Không phải live migrate | Gán lại job inference; training pause tại checkpoint |
| 70–80% CPU/RAM nhàn rỗi | Không có nguồn | Máy văn phòng thường có lúc rảnh; tỷ lệ đo tại PoV |
| Local LLM Inference (là toàn bộ sản phẩm) | Hẹp | Inference + preprocess + decentralized training (Tầng A) |
| Đáp ứng IFRS S1/S2, GRI, SASB | Overclaim | Báo cáo năng lượng 3 tầng, có nhãn độ tin cậy |
| Đo nhiệt RAM | Sai kỹ thuật | Đo nhiệt CPU/GPU package |
| PC thay cụm GPU / siêu máy tính từ RAM | Sai kiến trúc | Mỗi job chạy trọn trên một node; không ghép bộ nhớ |
| Worker luôn có Python | Trái ADR-005 | Inference không cần Python; trainer là add-on |

---

## Đoạn tóm tắt một trang (copy vào mục Giải pháp)

Thermal_Server điều phối việc AI trên máy Windows dị thể trong mạng tổ chức.
Hệ thống **không** biến nhiều PC thành một siêu máy tính dùng chung bộ nhớ.
Mỗi việc — suy luận, tiền xử lý, hoặc huấn luyện một expert — chạy trọn trên
một máy được chọn vì còn headroom nhiệt, đủ năng lực đã khai báo, và không
đang phục vụ người dùng ở mức ưu tiên cao.

Suy luận dùng llama.cpp, đã có PoC. Huấn luyện dùng runtime PyTorch tách
biệt, giám sát bởi agent C#, cấp phép theo từng khoảng 2–5 phút. Khi máy
nóng hoặc người dùng quay lại, việc huấn luyện dừng ở checkpoint rồi resume
— không giết tiến trình giữa chừng và không hứa chuyển máy dưới một giây.

Hiệu quả năng lượng được đo (Joule/token khi có cảm biến; kWh để đạt mốc
chất lượng khi có thí nghiệm), không được suy từ việc “dùng PC sẵn có thì
tất nhiên xanh hơn GPU”.

---

## Việc không thuộc file này

- Sửa code, ADR, hay [`docs/00`](00-TONG-QUAN-KY-THUAT.md) — làm ở phase
  implement.
- Viết lại toàn bộ PDF giúp bạn — file này là **hướng dẫn**; bạn (hoặc biên
  tập hồ sơ) áp dụng từng mục.
- Cam kết số liệu thí nghiệm training — chưa chạy; xem
  [`CLAIMS_RISKS_LIMITATIONS.md`](CLAIMS_RISKS_LIMITATIONS.md).
