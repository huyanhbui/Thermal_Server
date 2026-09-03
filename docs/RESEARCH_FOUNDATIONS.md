# Nền tảng nghiên cứu — training phân tán và dị thể

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Ánh xạ sang sản phẩm: [`THERMAL_TRAINING_ARCHITECTURE.md`](THERMAL_TRAINING_ARCHITECTURE.md)
> Claim: [`CLAIMS_RISKS_LIMITATIONS.md`](CLAIMS_RISKS_LIMITATIONS.md)
> **Trạng thái:** tổng hợp thư mục. Không phải kết quả thí nghiệm Thermal_Server.

Quy tắc file này:

- Chỉ trích paper đã xác minh (arxiv / hội nghị). Không bịa citation.
- Số liệu (FID, FVD, GPU-days, hệ số bandwidth) là **của paper**, không phải
  của Thermal_Server.
- Thermal_Server học **pattern giao tiếp và giả định phần cứng**, không copy
  quy mô mô hình.

Ánh xạ nhanh:

| Tầng Thermal_Server | Họ nghiên cứu gần nhất |
|---|---|
| A — expert độc lập (MVP) | DDM, Paris, Paris 2.0, Heterogeneous DDM |
| B — sync thưa, một shared model | Local SGD, DiLoCo, OpenDiLoCo, Moshpit SGD |
| C — chia layer / pipeline (không ship) | SWARM, HetPipe, Petals, PipeDream, Alpa, ZeRO, Zorse |
| CPU / sparsity (tham khảo, không phải lõi) | SLIDE, Distributed SLIDE |

---

## Mục lục

- [1. Decentralized Diffusion Models](#1-decentralized-diffusion-models)
- [2. Paris](#2-paris)
- [3. Paris 2.0](#3-paris-20)
- [4. Heterogeneous Decentralized Diffusion Models](#4-heterogeneous-decentralized-diffusion-models)
- [5. Local SGD](#5-local-sgd)
- [6. DiLoCo](#6-diloco)
- [7. OpenDiLoCo](#7-opendiloco)
- [8. Moshpit SGD](#8-moshpit-sgd)
- [9. SWARM Parallelism](#9-swarm-parallelism)
- [10. SLIDE và Distributed SLIDE](#10-slide-và-distributed-slide)
- [11. HetPipe](#11-hetpipe)
- [12. Petals](#12-petals)
- [13. PipeDream](#13-pipedream)
- [14. Alpa](#14-alpa)
- [15. ZeRO](#15-zero)
- [16. Zorse](#16-zorse)
- [17. Bài học chung cho Thermal_Server](#17-bài-học-chung-cho-thermal_server)
- [18. Nguồn](#18-nguồn)

---

## 1. Decentralized Diffusion Models

**Paper:** David McAllister, Matthew Tancik, Jiaming Song, Angjoo Kanazawa.
*Decentralized Diffusion Models.* CVPR 2025, pp. 23323–23333.
arXiv: [2501.05450](https://arxiv.org/abs/2501.05450).

### Giải quyết vấn đề gì

Train diffusion quy mô lớn thường AllReduce gradient mỗi step trên cụm GPU
đồng nhất, băng thông nội cụm cao. DDM bỏ phụ thuộc fabric đó.

### Kiến trúc

Nhiều **expert diffusion** train trên **phân hoạch dữ liệu**, **cô lập hoàn
toàn** lúc train. Lúc infer: ensemble qua **router nhẹ**. Paper lập luận
ensemble tối ưu cùng objective với một model train trên toàn bộ dữ liệu.

### Communication

Train: **không** trao gradient, tham số, hay activation giữa expert.
Infer: chọn expert (router).

### Giả định phần cứng

“Compute islands” — node/cụm GPU độc lập, không cần interconnect đắt.
Paper scale tới mô hình rất lớn trên **tám GPU node** (theo abstract); đó
là GPU server, không phải laptop văn phòng.

### Ưu

Ít phụ thuộc bandwidth; expert chậm không chặn expert khác; lỗi một island
không cuốn cả run.

### Hạn chế

Chất lượng phụ thuộc cách chia data / router. Không giải quyết thermal hay
user trên endpoint. Vẫn cần GPU đủ để train **một** expert đầy đủ.

### Thermal_Server học gì

Đây là **mẫu Tầng A**: `train_expert` độc lập + job `train_router` sau.
Không cần AllReduce. Không copy tuyên bố FLOP-for-FLOP hay 24B parameters.

---

## 2. Paris

**Paper:** Zhiying Jiang, Raihan Seraj, Marcos Villagra, Bidhan Roy.
*Paris: A Decentralized Trained Open-Weight Diffusion Model.*
arXiv: [2510.03434](https://arxiv.org/abs/2510.03434) (2025).

### Giải quyết vấn đề gì

Đưa lý thuyết DDM thành **mô hình open-weight** text-to-image, train phi
tập trung thật.

### Kiến trúc

Tám expert diffusion độc lập (khoảng 129M–605M tham số mỗi expert, theo
công bố kèm theo), DiT + tối ưu kiểu PixArt-α. Không sync lúc train.
Router lúc infer.

Paper nêu dùng **1/14 dữ liệu** và **1/16 compute** so với baseline DDM
trước đó (11M vs ~154M ảnh — số của **họ**, không phải của ta).

### Communication

Train: zero inter-expert. Infer: router.

### Giả định phần cứng

GPU dị thể, phân tán địa lý — vẫn là GPU train diffusion, không phải C0.

### Ưu / hạn chế

Chứng minh DDM **làm được** ngoài lab thuật toán. Hạn chế: stack diffusion
cụ thể; không có human-preempt; không đo Joule/sample kiểu ESG 3 tầng.

### Thermal_Server học gì

Tầng A **có thể** ra artifact dùng được nếu expert vừa sức máy. Quy mô
Paris **không** phải mốc demo nội bộ. Semantic clustering dữ liệu của họ
là research; MVP được chia shard đơn giản và nói rõ.

---

## 3. Paris 2.0

**Paper:** Ali Rouzbayani, Bidhan Roy, Marcos Villagra, Zhiying Jiang.
*Paris 2.0: A Decentralized Diffusion Model for Video Generation.*
arXiv: [2605.26064](https://arxiv.org/abs/2605.26064) (2026).

### Giải quyết vấn đề gì

Video coherent theo thời gian dưới decentralized training — việc DDM ảnh
chưa giải.

### Kiến trúc

Ba expert ~11B kiểu Flux MM-DiT; router top-K từng bước denoising; VAE
Hunyuan. Train không sync gradient/param/activation.

Họ báo FVD 561.04 → 279.01 so với baseline monolithic **cùng tổng
compute** trên setup của paper. **Không** dùng số này trong hồ sơ
Thermal_Server.

### Communication / HW

Như DDM. Train trên GPU dị thế, nhiều region/cloud (công bố nhóm Bagel).

### Ưu / hạn chế

Mở video. 11B × 3 **nằm ngoài** office PC. Router lúc infer vẫn cần tải
đúng expert — lịch Thermal phải biết artifact locality.

### Thermal_Server học gì

Tầng A scale **số expert**, không scale **một** model xuyên máy. Video/11B
không nằm Phase 1–4.

---

## 4. Heterogeneous Decentralized Diffusion Models

**Paper:** Zhiying Jiang, Raihan Seraj, Marcos Villagra, Bidhan Roy.
*Heterogeneous Decentralized Diffusion Models.* CVPR 2026.
PDF: [open access](https://openaccess.thecvf.com/content/CVPR2026/papers/Jiang_Heterogeneous_Decentralized_Diffusion_Models_CVPR_2026_paper.pdf).

### Giải quyết vấn đề gì

DDM gốc (theo nhóm này) nặng: họ trích ~1176 GPU-days, objective đồng nhất
mọi expert. Muốn expert **khác objective** (DDPM ε-pred vs Flow Matching
velocity) rồi gộp lúc infer, giảm data/compute.

### Kiến trúc

Expert dị objective; convert checkpoint ImageNet-DDPM → FM; kiến trúc
AdaLN-Single (PixArt-α). Infer unify không retrain.

Họ báo ~16× compute và ~14× data so với scale DDM trước, trên
LAION-Aesthetics; đóng góp single GPU 24–48GB VRAM.

### Communication

Train: không sync giữa expert. Heterogeneity nằm ở **objective và GPU**,
không phải AllReduce.

### Ưu / hạn chế

Khớp slogan “máy khác nhau làm việc khác nhau”. Vẫn 24–48GB — class G3–G4,
không C0. Mixed objective là ML research, không phải Phase 2 MNIST.

### Thermal_Server học gì

Node class: không bắt mọi expert cùng recipe/precision. G1 LoRA, G3 expert
lớn hơn, **cùng họ Tầng A**. Không tuyên bố 16×.

---

## 5. Local SGD

**Paper:** Sebastian U. Stich. *Local SGD Converges Fast and Communicates
Little.* ICLR 2019. arXiv: [1805.09767](https://arxiv.org/abs/1805.09767).

(DiLoCo và tài liệu sau còn trích dòng Local SGD / FedAvg sớm hơn, ví dụ
Mangasarian & Solodov 1993, McMahan et al. 2017 — không mở rộng ở đây.)

### Giải quyết vấn đề gì

Giảm số lần giao tiếp so với SGD đồng bộ: mỗi worker H bước local rồi
average.

### Kiến trúc / communication

Một shared model. Sync **thưa** (parameter average). Không pipeline.

### Giả định HW

Thường homogeneous trong phân tích. Ortiz et al. 2021 (trích trong DiLoCo)
báo Local SGD **khó** ở scale ImageNet khi H nhỏ, nhiều replica, không
pretrain — DiLoCo dùng như động lực đổi outer optimizer.

### Ưu / hạn chế

Đơn giản. Hội tụ phụ thuộc H, số worker, non-IID. Không thermal-aware.

### Thermal_Server học gì

Tầng B tối thiểu: `train_local_sgd_round` + `aggregate_update`. H lớn để
lease 180s chứa được nhiều inner step. Không dùng Local SGD làm MVP (Tầng A
ít giao tiếp hơn nữa).

---

## 6. DiLoCo

**Paper:** Arthur Douillard, Qixuan Feng, Andrei A. Rusu, Rachita Chhaparia,
Yani Donchev, Adhiguna Kuncoro, Marc’Aurelio Ranzato, Arthur Szlam,
Jiajun Shen. *DiLoCo: Distributed Low-Communication Training of Language
Models.* Google DeepMind. arXiv: [2311.08105](https://arxiv.org/abs/2311.08105)
(2023).

### Giải quyết vấn đề gì

LLM train trên **nhiều đảo GPU** kết nối kém, không một siêu cụm.

### Kiến trúc

Inner: AdamW, nhiều bước local. Outer: SGD Nesterov trên **pseudo-gradient**
`θ(t) − θ(t+H)`. Biến thể FedAvg với H lớn và outer optimizer mạnh hơn
average thuần.

Abstract: 8 worker, chất lượng tương đương sync đầy đủ trên C4, giao tiếp
ít hơn ~500 lần (số **của họ**).

### Communication

Định kỳ, kích thước ~ full weights (hoặc tương đương) mỗi outer step — ít
**lần**, vẫn nặng **byte** nếu model lớn và đường văn phòng chậm.

### Giả định HW

Mỗi worker chứa **bản sao model** (cộng inner optimizer state). Đảo là cụm
GPU, không phải iGPU 4GB.

### Ưu

Ít lần sync; robust worker ra/vào (theo paper); non-IID khá ổn trên setup
họ.

### Hạn chế

Bắt buộc đủ VRAM cho full replica → loại C0/C1. Outer sync vẫn có
straggler nếu bắt đủ mọi worker. Không có user/thermal preempt trong
thuật toán.

### Thermal_Server học gì

Tầng B: inner steps nằm trong lease; outer step = job `aggregate_update`
khi **đủ** worker xong round hoặc hết timeout (cần chính sách straggler —
paper “robust to unavailable” nhưng ta phải thiết kế timeout, không copy
mù). Không AllReduce mỗi step.

---

## 7. OpenDiLoCo

**Paper:** Sami Jaghouar, Jack Min Ong, Johannes Hagemann.
*OpenDiLoCo: An Open-Source Framework for Globally Distributed
Low-Communication Training.* arXiv: [2407.07852](https://arxiv.org/abs/2407.07852)
(2024).

### Giải quyết vấn đề gì

Tái hiện DiLoCo mã mở, train xuyên lục địa (Hivemind). Họ báo ~90–95%
compute utilization trên setup đa quốc gia; scale lớn hơn thí nghiệm gốc
(tới ~tỷ tham số, theo abstract).

### Kiến trúc / communication

Như DiLoCo; triển khai Hivemind DHT / torch.distributed. Ablation: all-reduce
pseudo-grad FP16.

### HW

GPU phân tán toàn cầu — vẫn GPU train LLM, không office CPU.

### Ưu / hạn chế

Có code để học. Repo OpenDiLoCo được nhóm sau chuyển hướng sang stack
PRIME/INTELLECT (ghi chú vận hành, không phải paper). WAN thật sự vẫn cần
băng thông outer step.

### Thermal_Server học gì

Đừng tự viết framework DHT. Tầng B trên **LAN Host-centered** đơn giản hơn
Hivemind, khớp outbound-only: worker upload delta/ckpt lên Host, Host
aggregate. Hivemind P2P dễ phá mô hình IT.

---

## 8. Moshpit SGD

**Paper:** Max Ryabinin, Eduard Gorbunov, Vsevolod Plokhotnyuk,
Gennady Pekhimenko. *Moshpit SGD: Communication-Efficient Decentralized
Training on Heterogeneous Unreliable Devices.* NeurIPS 2021.

### Giải quyết vấn đề gì

Decentralized SGD khi máy dị thể, rớt mạng, không có parameter server ổn
định. Dùng butterfly all-reduce / averaging theo nhóm (“moshpit”) thay vì
cây toàn cục cứng.

### Communication

Collective **thưa và cục bộ hơn** AllReduce đầy đủ mọi vòng; vẫn là
shared-model, không phải expert cô lập.

### HW

Thiết bị không tin cậy, dị thể — gần **tình huống** Thermal hơn DiLoCo
paper (đảo GPU). Vẫn giả định machine learning shared params.

### Ưu / hạn chế

Fault tolerance. Phức tạp triển khai. Không thermal.

### Thermal_Server học gì

Straggler và máy biến mất là **bình thường**. Tầng A tránh bài toán này
(không average). Tầng B cần drop worker chậm chứ không treo round. Không
cần copy butterfly topology Phase 5.

---

## 9. SWARM Parallelism

**Paper:** Max Ryabinin, Tim Dettmers, Michael Diskin, Alexander Borzunov.
*SWARM Parallelism: Training Large Models Can Be Surprisingly
Communication-Efficient.* arXiv: [2301.11913](https://arxiv.org/abs/2301.11913)
(ICML 2023).

### Giải quyết vấn đề gì

Model **lớn hơn một GPU**, thiết bị dị thể, mạng kém: kết hợp pipeline +
data parallel với định tuyến linh hoạt, không pipeline cứng một dây.

### Communication

Activation giữa **stage** pipeline (P2P theo đường đi), không full AllReduce
mọi layer mỗi step. Vẫn thường xuyên hơn Tầng A.

### HW

GPU volunteer / kém tin cậy. Cần nhiều máy đồng thời tạo thành **đường**
layer.

### Ưu / hạn chế

Cho model không fit một máy. Nhạy latency; node chết giữa pipeline phải
reroute; **xung đột** preempt nhiệt (cắt một stage = cắt cả microbatch).

### Thermal_Server học gì

Tầng C. Office + lease 180s + USER_ACTIVE làm pipeline **dễ vỡ**. Phase 6:
đo RTT × activation size; mặc định no-go. Không ship SWARM trong agent.

---

## 10. SLIDE và Distributed SLIDE

**SLIDE:** Beidi Chen, Tharun Medini, James Farwell, Sameh Gobriel,
Charlie Tai, Anshumali Shrivastava. *SLIDE: In Defense of Smart Algorithms
over Hardware Acceleration for Large-Scale Deep Learning Systems.* MLSys
2020. arXiv: [1903.03129](https://arxiv.org/abs/1903.03129).

**Distributed SLIDE:** Minghao Yan, Nicholas Meisburger, Tharun Medini,
Anshumali Shrivastava. *Distributed SLIDE: Enabling Training Large Neural
Networks on Low Bandwidth and Simple CPU-Clusters via Model Parallelism
and Sparsity.* arXiv: [2201.12667](https://arxiv.org/abs/2201.12667) (2022).

### Giải quyết vấn đề gì

SLIDE: train mạng lớn trên CPU bằng **hashing / sparsity**, tránh dense
GEMM GPU. Distributed SLIDE: model-parallel + sparsity trên cụm CPU băng
thông thấp; abstract nêu mục tiêu dùng CPU idle (họ nêu mốc “hơn 70% cloud
compute trả rồi để idle” — **số của paper**, không dùng làm số Thermal).

### Communication

Sparsity giảm volume so với dense model-parallel. Vẫn chia **tham số**,
không phải expert DDM.

### HW

CPU nhiều nhân, cluster đơn giản. Không thay LLM decoder hiện đại trên
office dual-core.

### Ưu / hạn chế

C0 có việc **thuật toán** chứ không chỉ preprocess. Hệ sinh thái không phải
PyTorch training LLM thông dụng; không khớp GGUF/llama.cpp hiện tại.

### Thermal_Server học gì

Đừng hứa “CPU cluster = GPU”. C0: preprocess, embed nhỏ, **có thể** nghiên
cứu sparse sau — không phải Phase 2. Không lấy “70% idle” của họ bỏ vào
hồ sơ mình.

---

## 11. HetPipe

**Paper:** Jay H. Park, Gyeongchan Yun, Chang M. Yi, Nguyen T. Nguyen,
Seungmin Lee, Jaesik Choi, Sam H. Noh, Young-ri Choi. *HetPipe: Enabling
Large DNN Training on (Whimpy) Heterogeneous GPU Clusters through
Integration of Pipelined Model Parallelism and Data Parallelism.* USENIX
ATC 2020.

### Giải quyết vấn đề gì

Cụm GPU **dị thế**, GPU yếu không train nổi model một mình: gói GPU thành
virtual worker pipeline, nhiều virtual worker data-parallel. Wave
Synchronous Parallel (WSP).

### Communication

Activation trong virtual worker + sync DP giữa virtual worker (không phải
mỗi GPU độc lập DDP thuần).

### HW

GPU cluster quản trị (datacenter / lab), không phải laptop tự join/leave
theo user.

### Ưu / hạn chế

Khai thác GPU yếu trong **cùng** pipeline. Giả định cụm ổn định hơn office.
Họ báo hội tụ nhanh hơn DP SOTA trên setup heterogeneous của paper (tới
~49% — số **của họ**).

### Thermal_Server học gì

Heterogeneous **không** nghĩa “mọi GPU làm cùng kernel”. Virtual worker =
ý tưởng gần Tầng C. Thermal preempt một GPU “whimpy” trong pipe = vỡ
wave — lại ủng hộ Tầng A trước.

---

## 12. Petals

**Paper:** Alexander Borzunov, Dmitry Baranchuk, Tim Dettmers, Max Ryabinin,
Younes Belkada, Artem Chumachenko, Pavel Samygin, Colin Raffel.
*Petals: Collaborative Inference and Fine-tuning of Large Models.*
arXiv: [2209.01188](https://arxiv.org/abs/2209.01188). ACL 2023 demo.
Bài liên quan: *Distributed Inference and Fine-tuning of Large Language
Models Over The Internet* (NeurIPS 2023).

### Giải quyết vấn đề gì

Chạy / fine-tune LLM 100B+ khi không ai giữ đủ GPU: mỗi server giữ một
cụm layer, client ghép pipeline qua Internet.

### Communication

Activation + KV cache theo chuỗi server. Fine-tune: adapters / prompt /
một số layer. Fault: client reroute khi server chết, gửi lại prefix.

### HW

GPU volunteer, Internet. Paper Petals: BLOOM-176B khoảng 1 step/s trên
GPU consumer (số **của họ**). Bài NeurIPS 2023 mở rộng fault-tolerant
routing trên Internet.

### Ưu / hạn chế

Model lớn hơn VRAM một máy. Latency Internet; bảo mật layer-hosting (dữ
liệu activation rời máy); **server listen** — trái outbound-only nếu copy
nguyên.

### Thermal_Server học gì

Tầng C **inference** cũng không copy Petals vào NodeAgent (phá ADR-001 trừ
khi mọi stage là process local). Fine-tune adapter trên **một** máy = Tầng
A `train_lora`, không phải swarm layer. Privacy: activation đi máy lạ =
bài toán RESTRICTED.

---

## 13. PipeDream

**Paper:** Deepak Narayanan, Aaron Harlap, Amar Phanishayee, Vivek Seshadri,
Nikhil R. Devanur, Gregory R. Ganger, Phillip B. Gibbons, Matei Zaharia.
*PipeDream: Generalized Pipeline Parallelism for DNN Training.* SOSP 2019.
(Bản arXiv sớm: Harlap et al., 1806.03377.)

### Giải quyết vấn đề gì

Pipeline inter-batch để overlap compute/comm; weight versioning vì
forward/backward lệch version; partition layer tự động.

### Communication

Activation / grad giữa stage kề; DP trên stage replicate dùng NCCL (trên
cụm họ).

### HW

Cụm GPU gắn chặt, băng thông cao, máy không rời đi vì nhân viên mở Outlook.

### Ưu / hạn chế

Throughput pipeline cổ điển. Checkpoint theo stage. Bubble, memory
activation, giả định ổn định. Không thermal.

### Thermal_Server học gì

Checkpoint **từng stage** phức tạp hơn ckpt một expert. Tầng C kế thừa
ý “không flush toàn cục mọi lúc” — vẫn quá nặng cho MVP. 1F1B / versioning
không implement Phase 1–4.

---

## 14. Alpa

**Paper:** Lianmin Zheng, Zhuohan Li, Hao Zhang, Yonghao Zhuang, Zhifeng Chen,
Yanping Huang, Yida Wang, Yuanzhong Xu, Danyang Zhuo, Eric P. Xing,
Joseph E. Gonzalez, Ion Stoica. *Alpa: Automating Inter- and Intra-Operator
Parallelism for Distributed Deep Learning.* OSDI 2022.

### Giải quyết vấn đề gì

Tự tìm kế hoạch intra-op (tensor/ZeRO-like) vs inter-op (pipeline) trên
cluster có cấu trúc.

### Communication

Intra-op: collective nặng. Inter-op: P2P giữa stage, ít volume hơn, có
bubble.

### HW

Cluster biên dịch được, thiết bị biết trước, thường TPU/GPU homogroup theo
lớp. Không join động 10 PC.

### Ưu / hạn chế

Compiler song song hóa mạnh. Overkill và **sai giả định** cho opportunistic
office: topology thay đổi vì nhiệt/user từng phút.

### Thermal_Server học gì

Đừng viết auto-parallel compiler. `compute_mode` A/B/C là **chọn tay theo
net class + VRAM**, không search space Alpa. Intra-op AllReduce = mặc định
**cấm**.

---

## 15. ZeRO

**Paper:** Samyam Rajbhandari, Jeff Rasley, Olatunji Ruwase, Yuxiong He.
*ZeRO: Memory Optimizations Toward Training Trillion Parameter Models.*
SC 2020. arXiv: [1910.02054](https://arxiv.org/abs/1910.02054).

### Giải quyết vấn đề gì

Shard optimizer state / grad / param giữa GPU data-parallel để giảm bộ nhớ
mỗi card, giữ ngữ nghĩa DP.

### Communication

All-gather / reduce-scatter **thường xuyên**, giả định băng thông nội node
/ nội cụm (NVLink, InfiniBand).

### HW

Cụm GPU đồng nhất, interconnect mạnh. Ngược với office Ethernet và tunnel.

### Ưu / hạn chế

Nền tảng DeepSpeed, fit model lớn. Communication **tăng** khi shard sâu —
xấu cho Thermal Tầng A/B mục tiêu.

### Thermal_Server học gì

ZeRO là Tầng C / datacenter. Không dùng ZeRO-3 trên 3 PC văn phòng. Ghi
rõ trong hồ sơ: **không** “ghép VRAM nhiều máy kiểu ZeRO”.

---

## 16. Zorse

**Paper:** Runsheng Guo, Utkarsh Anand, Khuzaima Daudjee, Rathijit Sen.
*Zorse: Optimizing LLM Training Efficiency on Heterogeneous GPU Clusters.*
MLSys 2026.

### Giải quyết vấn đề gì

Cụm GPU **nhiều thế hệ**: partition sao cho máy yếu không thành bottleneck.
Kết hợp PP + DP mà không trả giá memory như DP+PP thuần, cũng không trả giá
comm như tensor parallel / sharded DP chồng pipeline. Pipeline-Efficient
ZeRO DP + heterogeneous pipeline (stage lệch, batch lệch). Planner tự chọn
cấu hình.

Họ báo tới ~3× trên setup đánh giá của paper (số **của họ**).

### Communication / HW

Cụm GPU quản trị, planner biết spec mọi card. Không phải NodeAgent tự join.

### Ưu / hạn chế

Heterogeneous **trong datacenter** gần G1–G5 hơn Paris. Vẫn pipeline + ZeRO
→ nhạy máy biến mất. Planner phức tạp.

### Thermal_Server học gì

Planner = phiên bản nghèo: **node class + min_vram + net class**, không
search PP/DP/TP. Zorse xác nhận dị thể là bài toán thật — và xác nhận giải
pháp họ chọn (PP+ZeRO) **không** phải MVP Thermal.

---

## 17. Bài học chung cho Thermal_Server

1. **Ít giao tiếp thắng trên mạng xấu.** Tầng A (zero sync lúc train) khớp
   LAN/tunnel hơn ZeRO/Alpa/Petals.
2. **Dị thể:** recipe khác nhau (Heterogeneous DDM, HetPipe, Zorse) chứ không
   một kernel cho mọi máy.
3. **Máy biến mất:** Moshpit/SWARM/Petals xử lý; Thermal thêm **nhiệt và
   user** như nguồn preempt — paper gần như không có.
4. **Full replica DiLoCo** loại máy nhỏ → Tầng B chỉ G-class đủ VRAM.
5. **Pipeline** (SWARM, PipeDream, Petals, HetPipe, Zorse) = Tầng C, đòi
   mạng và sự ổn định mà office + human-first không cho.
6. **Không lấy số paper làm số sản phẩm.** FID/FVD/500×/3×/70% idle đều
   gắn citation, không gắn logo Thermal_Server.
7. **CPU SLIDE** không cứu “train LLM trên C0”; C0 làm data jobs.

Thứ tự bám paper: A (DDM/Paris) → B (Local SGD/DiLoCo) → C (phần còn lại,
research).

---

## 18. Nguồn

Chỉ các mục trên. Nếu cần paper không có ở đây (ví dụ GPipe, Megatron-LM,
FedAvg gốc): thêm dòng mới với arxiv/DOI, **không** trích miệng.

File này **không** thay thế việc đọc paper trước khi implement Phase 5–6.
