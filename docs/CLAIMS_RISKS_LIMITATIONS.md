# Claim, rủi ro, giới hạn

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Hồ sơ: [`PDF_REVISION_GUIDE.md`](PDF_REVISION_GUIDE.md)
> **Trạng thái:** living document. Cập nhật khi thí nghiệm xong — **không**
> sửa claim thành “đã chứng minh” nếu chỉ mới viết thiết kế.

Dùng file này trước demo, slide, PDF, và bài nộp cuộc thi. Nếu một câu không
nằm cột **Đã chứng minh** hoặc **Wording an toàn**, đừng nói.

---

## 1. Đã chứng minh (trong repo / PoC inference)

Điều kiện: có code, có test hành vi, hoặc có phép đo đã ghi. Không có nghĩa
là “đủ cho sản phẩm doanh nghiệp”.

| Claim | Bằng chứng | Giới hạn |
|---|---|---|
| Worker chỉ outbound | Agent không listen; ADR-001 | Host vẫn listen 8000 |
| Danh tính node từ token | ADR-002, join | PoC trước đó không auth; đừng nói “từ ngày đầu” |
| Scheduler filter → score → reserve | `scheduler.py`, `test_scheduler.py` | Capability gần như fail-open |
| A/B thermal vs round-robin **inference** | `scheduler_mode`, `ab_benchmark.py`, `test_cluster_sim.py` | Job burn/chat, không phải training |
| Dự báo ΔT 3 phút, hysteresis | ADR-004, ForecastCache | Một `model.pkl` toàn cục; không phải GPU thermal |
| ESG 3 tầng, không cộng gộp | ADR-003, `esg.py` | Tầng 1 cần sensor + token; Tầng 2/3 là suy ra / dự phóng |
| LLM pin SHA256, llama.cpp | ADR-005, Downloader | Binary chưa Authenticode (D15) |
| Chat chỉ khi model READY đúng hash/generation | `model_ready` | |
| Đo công suất: sensor / model / none, không trộn trong một tổng | `power_source`, EnergySampler | Nhiều máy `none` |
| Room password, audit hashed IP | `room_audit` | LAN có thể HTTP |

Markdown PoC ([`BÁO CÁO TỔNG QUAN DỰ ÁN.md`](../BÁO%20CÁO%20TỔNG%20QUAN%20DỰ%20ÁN.md))
khớp nhóm này hơn PDF pitch.

---

## 2. Thiết kế đã viết, chưa chứng minh

Được **mô tả** trong docs training mới. Chưa được **nói là đang chạy**.

| Claim | File thiết kế | Chứng minh bằng |
|---|---|---|
| Capability Manifest fail-closed | Architecture §12, Scheduler v2 §6 | Phase 1 tests + 2–3 máy thật |
| Node class C0–G5 | Architecture §12 | Probe MEASURED |
| User-first / USER_ACTIVE | Scheduler v2 §5 | Phase 3, script last-input |
| Training Lease + pause/resume | Architecture §13 | Phase 2–3 |
| PyTorch trainer add-on | Architecture §6–7 | Phase 2; SKU tách |
| Tầng A multi-expert | Architecture §15 | Phase 4 |
| Tầng B DiLoCo-like | Roadmap Phase 5 | Prototype + bytes/round |
| Energy-to-Target-Quality | Architecture §19 | A/B training có cảm biến |
| Dataset classification / trust | Architecture §10 | Test RESTRICTED |
| Job recipe ký số | Architecture §18 | Phase 2+ |

Câu đúng hôm nay: *“Chúng tôi đang thiết kế / sẽ làm Phase n.”*
Câu sai: *“Thermal_Server đã hỗ trợ distributed training.”*

---

## 3. Chưa chứng minh — dễ bị phản biện nếu nói

| Claim | Vì sao yếu | Cách xử lý |
|---|---|---|
| 70–80% CPU/RAM văn phòng idle | Không nguồn, không protocol đo | Đo tại site PoV; nói “thường có lúc rảnh” |
| Zero-CAPEX / 0 đồng triển khai | License, IT, GPU train, điện | “Giảm CAPEX hạ tầng mới cho PoC inference” |
| Zero-Trust / chuyên sâu | Token + outbound ≠ ZTNA/mTLS/device posture | Nêu từng kiểm soát |
| Zero Carbon / Zero Embodied Carbon | Không mua GPU ≠ zero embodied; điện vẫn phát thải | Chỉ Tầng 1/2 đo được |
| IFRS S1/S2, GRI, SASB | ESG 3 tầng không map 1-1 chuẩn | “Báo cáo nội bộ 3 tầng tin cậy” |
| Chuyển tác vụ &lt; 1 giây | Tick scheduler / retry job mới, không live migrate | PDF_REVISION_GUIDE §3 |
| Đo nhiệt RAM | Code đo CPU/GPU package | Sửa wording |
| PC thay cụm GPU | C0 không train LLM có ích | “Bổ sung, không thay” |
| Ghép RAM thành siêu máy tính | ADR-007 / Tầng A: job trọn một node | Không nói |
| Cụm PC luôn xanh hơn GPU server | Chưa Energy-to-Target-Quality | Cấm đến khi có số |
| Dữ liệu không rời tòa nhà | Cloudflare tunnel | “Mặc định LAN; tunnel tùy chọn” |
| Máy nhân viên luôn mát | Hysteresis ≠ mát | “Giảm quá nhiệt so với RR, nếu A/B chỉ ra” |
| Paris/DDM quality trên office PC | Paper dùng GPU island, model lớn | Học pattern A, không copy FID |
| Worker không cần Python (sản phẩm đầy đủ) | Đúng **inference SKU**; sai nếu gộp training | Tách câu |
| Pipeline parallel sắp có | Phase 6 no-ship | “Nghiên cứu, điều kiện mạng” |
| `meets_capability` đã chặn máy yếu | Hiện fail-open | Đừng claim đến Phase 1 |

---

## 4. Điểm phản biện chủ động (tự nói trước)

### 4.1. “Đây không phải novelty, Kubernetes cũng xếp lịch.”

Kubernetes không xếp theo ΔT máy văn phòng, không human-first trên endpoint
Windows, không fail-closed VRAM UNKNOWN. Novelty là **chính sách**, không
phải “có hàng đợi job”. Đừng claim thuật toán nhiệt chưa ai làm — claim
*tích hợp* trên Host–Worker outbound.

### 4.2. “Paris đã train diffusion phi tập trung rồi.”

Đúng. Thermal_Server **không** phải Paris. Học: expert độc lập, ít sync.
Khác: preempt nhiệt, user, lease, PC dị thể, đo năng lượng. Không dùng FID
Paris 2.0 như thành tích mình.

### 4.3. “DiLoCo / Horovod mới là distributed training.”

Tầng B mới gần DiLoCo. MVP là Tầng A (thậm chí không phải data-parallel).
Nói thẳng: A là *decentralized experts*, không phải *shared-model DDP*.

### 4.4. “Không có GPU thì train gì?”

C0: preprocess. Training “có ích” cần G1+ hoặc chấp nhận CNN nhỏ trên CPU
để chứng minh **điều phối**, không chứng minh **chất lượng frontier**.

### 4.5. “Python trên máy nhân viên là rủi ro bảo mật.”

Đúng (D15). Add-on + pin hash + Job Object **giảm**, không xóa. Inference
SKU tránh Python.

### 4.6. “A/B thermal thắng RR là hiển nhiên.”

Không. Cluster sim inference có case C9; training có overhead checkpoint
có thể **thua** wall-clock, thắng max-temp. Công bố cả hai.

### 4.7. “Outbound-only chặn Tầng C.”

Đúng. Activation streaming cần kênh bền. Không hứa Petals trên office WAN.

---

## 5. Cách benchmark (để claim lên được)

### 5.1. Inference (đã có khung)

- Mode stamp lúc assign.
- Joule/token Tầng 1 chỉ sensor.
- Peak temp thermal vs RR (`test_cluster_sim` là sim, **bổ sung** máy thật).

### 5.2. Training MVP (Phase 3–4)

Protocol tối thiểu:

1. Cùng seed, cùng recipe, cùng data shard.
2. Hai mode: `thermal_aware`, `round_robin`.
3. N≥ số run đủ để không chốt từ 1 lần (ít nhất 3 run/mode nếu thời gian cho
   phép; nếu chỉ 1 — ghi “exploratory”).
4. Dừng cùng tiêu chí: step max **hoặc** val metric mốc — chọn một, ghi rõ.
5. Bảng metric: xem Roadmap Phase 3.
6. Năng lượng: không trộn sensor + model trong một ô “tiết kiệm”.
7. Không đổi trọng số scheduler giữa hai nhánh một thí nghiệm.

### 5.3. Energy-to-Target-Quality

```
E2Q = kWh_cảm_biến (Tầng 1) để val_loss ≤ Y
  hoặc accuracy ≥ X
  hoặc FID ≤ Z  (chỉ khi thực sự tính FID)
```

So sánh E2Q(thermal) với E2Q(RR) và, **nếu có**, E2Q(một GPU workstation
chạy tuần tự cùng tổng sample). Thiếu nhánh GPU workstation thì **không**
nói “xanh hơn GPU”.

### 5.4. User impact

Định nghĩa trước: ví dụ “p95 thời gian từ synthetic input đến
`cpu_util` worker < 30% trong T giây”. Không dùng cảm nhận demo.

---

## 6. Wording an toàn (copy)

**Được:**

- Nền tảng điều phối AI dị thể nhận thức nhiệt trên máy doanh nghiệp đang có.
- Worker chỉ chủ động kết nối ra; Host giữ chỗ job, không đẩy inbound.
- Suy luận LLM cục bộ bằng llama.cpp; huấn luyện là module add-on.
- MVP phân tán: expert độc lập, không AllReduce từng bước.
- Job huấn luyện preempt tại checkpoint, không live-migrate.
- Báo cáo năng lượng 3 tầng; Tầng 1 chỉ khi có cảm biến.
- A/B thermal vs round-robin cho inference đã có harness; training sẽ lặp
  protocol đó.

**Không:**

- Zero-CAPEX, Zero-Trust, Zero Carbon, Zero Embodied Carbon.
- Siêu máy tính từ RAM nhiều PC.
- Đáp ứng IFRS/GRI/SASB.
- Chuyển model dưới 1 giây.
- 70% idle.
- Đã train xong mô hình production bằng cụm văn phòng.
- Luôn xanh hơn / rẻ hơn GPU cluster.

---

## 7. Rủi ro kỹ thuật còn mở (không phải “sẽ ổn”)

| ID | Rủi ro | Mức | Ghi chú |
|---|---|---|---|
| D15 | Binary/Python chưa ký, AV | Cao | Nặng hơn khi có torch |
| — | Fail-open capability hiện tại | Cao | Phải sửa Phase 1 trước demo train |
| — | Job training chỉ RAM nếu không persist | Cao | Host restart mất giờ train |
| — | Không user-idle | Trung | Human-first chưa có |
| — | Tunnel vs RESTRICTED | Trung | Policy phải chặn |
| — | ΔT 3 phút vs lease 180s | Trung | Có thể preempt trễ |
| — | Một model.pkl cho mọi máy | Trung | Docs/05 đã cảnh báo |
| — | Tầng C vs ADR-001 | Cao nếu bị ép ship | Giữ no-ship |
| — | Overclaim hồ sơ PDF | Cao về uy tín | Dùng PDF_REVISION_GUIDE |

---

## 8. Giới hạn sản phẩm (nói rõ với khách)

- Windows 10/11 x64; không đa OS trong tầm gần.
- Quy mô thiết kế cũ: ~10 node; training không tự nâng thành 1000.
- Inference CPU nhỏ (catalog 0.5B–vài B); 30B là stress, không phải SLA.
- Không Docker bắt buộc — cũng không có isolation container mạnh.
- Không SaaS đa tenant đầy đủ.
- Không sàn carbon.
- Không tensor parallel.

Khi training add-on ra: vẫn **không** biến Thermal_Server thành thay thế
PyTorch DDP / Kubernetes. Nó là lớp **opportunistic** trên máy người ta đang
dùng.
