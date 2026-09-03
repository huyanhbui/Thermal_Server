# 01 — Đánh giá khách quan thiết kế hiện tại

> Tài liệu này rà soát bản thiết kế "Nền tảng Điều phối Nhiệt + LLM Phân tán (Chủ–Phụ)" đối chiếu với mã nguồn `Thermal-PoC` đang có. Mục đích là tìm ra chỗ nào sẽ vỡ **trước khi** viết code, không phải để chê bản thiết kế.
>
> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)

## Mục lục

- [Kết luận ngắn](#kết-luận-ngắn)
- [Cơ sở đánh giá](#cơ-sở-đánh-giá)
- [Nhóm S — Nghiêm trọng](#nhóm-s--nghiêm-trọng-chặn-mục-tiêu-dùng-thật-được)
- [Nhóm M — Trung bình](#nhóm-m--trung-bình-sẽ-cắn-ở-quy-mô-10-node)
- [Nhóm D — Rủi ro triển khai](#nhóm-d--rủi-ro-triển-khai-doanh-nghiệp)
- [Nhóm G — Điểm tốt cần giữ](#nhóm-g--điểm-tốt-cần-giữ)
- [Bảng tổng hợp](#bảng-tổng-hợp-và-thứ-tự-xử-lý)

---

## Kết luận ngắn

Bản thiết kế **đúng hướng**. Nó không đòi viết lại hệ thống: sáu module Python hiện có (`store / features / forecaster / balancer / esg / settings`) ánh xạ gần như 1-1 sang các thành phần của hệ đích. Việc thay burn-job giả bằng suy luận LLM thật còn **làm câu chuyện mạnh hơn**, vì tải sinh nhiệt trở thành tải có ích thay vì tải bịa.

Nhưng có **hai lỗi chặn** phải xử lý trước khi viết dòng code đầu tiên, và cả hai đều không hiện ra khi đọc riêng bản thiết kế — chỉ hiện ra khi đối chiếu với code:

1. **Công thức chấm điểm chọn node trong thiết kế không có đường tác động lên hệ thống hiện tại.** Cơ chế pull hiện nay để node tự đến lấy việc; ai đến trước lấy trước. Không có bước nào "chọn". (→ [S1](#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại))
2. **Không có bất kỳ xác thực nào**, trong khi thiết kế lại chủ động đưa server ra Internet công cộng qua tunnel. (→ [S2](#s2--không-có-xác-thực-trên-bất-kỳ-endpoint-nào))

Ngoài ra chỉ số ESG hiện tại **đo sai bản chất và bị thao túng được** ([S3](#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được)) — đây là rủi ro uy tín lớn nhất, vì nó là điểm nhấn thương mại của cả dự án.

Tổng cộng: **5 vấn đề nghiêm trọng, 9 vấn đề trung bình, 4 rủi ro triển khai, 5 điểm tốt cần bảo toàn.**

---

## Cơ sở đánh giá

Đánh giá dựa trên đọc toàn bộ mã nguồn tại thời điểm rà soát:

| Thành phần | Quy mô |
|---|---|
| Server Python | 6 module + 2 script, 543 dòng |
| Agent C# | 4 file, 191 dòng |
| Dashboard | 1 file HTML/JS, 155 dòng |
| Kiểm thử | 9 file, 331 dòng, 32 test |
| Tài liệu | `README.md`, `HOW_IT_WORKS.md`, `BÁO CÁO TỔNG QUAN DỰ ÁN.md` |

Ký hiệu mức độ: **S** = nghiêm trọng (chặn mục tiêu), **M** = trung bình (cắn ở quy mô), **D** = rủi ro triển khai, **G** = điểm tốt.

---

## Nhóm S — Nghiêm trọng (chặn mục tiêu "dùng thật được")

### S1 — Scheduler chấm điểm sẽ không hoạt động dưới cơ chế pull hiện tại

> ✅ **Đã xử lý trong mã nguồn.** (Hoàn thành trước vòng Chung kết)

**Bản thiết kế nói gì.** Mục 6.3 đưa ra công thức `score` với 5 số hạng có trọng số, kết luận: "*Host chấm điểm node → gán chat job*", "*pick best node*".

**Code thực tế làm gì.** [`balancer.py:57`](../server/balancer.py) — chữ ký hàm là:

```python
def next_job(self, node, node_temps):
```

Hàm này trả lời câu hỏi *"node đang hỏi có được nhận việc không?"* — nó **lọc**, không **chọn**. Không có bất cứ chỗ nào trong toàn bộ code so sánh các node với nhau rồi ra quyết định gán. Node nào gọi `GET /jobs/next` trước thì lấy job trước; agent poll mỗi 1 giây ([`Program.cs:83`](../agent/Program.cs)) nên thứ tự thực chất là ngẫu nhiên theo độ lệch đồng hồ.

**Hệ quả.** Nếu code thẳng theo bản thiết kế, bạn sẽ viết một hàm `score()` rất đẹp, có test đơn vị xanh, và nó **không ảnh hưởng gì tới việc job đi đâu**. Đây là loại lỗi tệ nhất: nó không gây crash, nó chỉ khiến tính năng bán hàng chính của sản phẩm im lặng không tồn tại. Demo vẫn "chạy", vẫn có node đỏ node xanh (vì flag vẫn hoạt động), nhưng phần "chọn máy có lợi thế nhất" thì không.

Cơ chế `_throttled` hiện tại ([`balancer.py:45`](../server/balancer.py)) — phục vụ node ấm cách một lượt — là một **xấp xỉ thô** của việc ưu tiên node mát, và nó chính là bằng chứng cho thấy tác giả PoC đã cảm nhận được thiếu sót này nhưng chưa giải quyết tận gốc.

**Cách sửa (rẻ nhất, tận dụng cái đã có).**

Trường `target` **đã tồn tại** trong job — [`balancer.py:29`](../server/balancer.py):

```python
job = {"id": ..., "duration_s": ..., "cores": ..., "target": target}
```

và đã được tôn trọng khi dispatch — [`balancer.py:64`](../server/balancer.py):

```python
if job["target"] in (None, node):
```

Nó đang được dùng cho chế độ hiệu chuẩn ([`calibrate.py:32`](../server/calibrate.py)). Chỉ cần đảo chiều luồng quyết định:

```
Cũ:  enqueue_job(target=None)  →  node nào đến trước lấy
Mới: score toàn bộ node đủ điều kiện  →  enqueue_job(target=node_thắng)  →  chỉ node đó lấy được
```

Phải bổ sung **hạn giữ chỗ (reservation timeout)**: nếu node được chọn không đến lấy trong `N` giây (máy treo, mạng đứt, agent chết), job phải được thả về hàng đợi và chấm điểm lại — nếu không một job sẽ kẹt vĩnh viễn.

Ưu điểm lớn nhất của phương án này: **bảo toàn tính chất "worker chỉ outbound"** — thứ tạo nên câu chuyện tường lửa tốt của hệ thống (xem [G1](#g1--worker-chỉ-outbound)).

**Nâng cấp về sau (không bắt buộc cho mốc đầu).** Worker mở một WebSocket bền tới host, host đẩy job xuống qua kênh đó. Vẫn là kết nối do worker khởi tạo → vẫn outbound-only → vẫn không cần mở tường lửa ở máy phụ. Lợi ích: bỏ được độ trễ poll (tối đa 1 giây, đáng kể với chat), và host biết chắc worker còn sống mà không cần đợi timeout.

> Đặc tả đầy đủ: [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md). Quyết định kiến trúc: [`adr/ADR-001-reservation-thay-vi-push.md`](adr/ADR-001-reservation-thay-vi-push.md).

---

### S2 — Không có xác thực trên bất kỳ endpoint nào

**Bản thiết kế nói gì.** Mục 5.4: "Mật khẩu bắt buộc", "Từ chối join sai mật khẩu". Mục 5.3: bật Cloudflare Tunnel để worker ở mạng khác vào được.

**Code thực tế.** Không một endpoint nào trong [`server.py`](../server/server.py) kiểm tra bất cứ thứ gì:

| Endpoint | Dòng | Ai gọi được |
|---|---|---|
| `POST /ingest` | [`server.py:154`](../server/server.py) | Bất kỳ ai |
| `GET /jobs/next?node=X` | [`server.py:161`](../server/server.py) | Bất kỳ ai, với `X` tùy ý |
| `GET /api/state` | [`server.py:171`](../server/server.py) | Bất kỳ ai |
| `POST /api/settings` | [`server.py:175`](../server/server.py) | Bất kỳ ai |
| `GET /api/esg.csv` | [`server.py:181`](../server/server.py) | Bất kỳ ai |
| `WS /ws` | [`server.py:196`](../server/server.py) | Bất kỳ ai |

Ở phạm vi LAN có tường lửa, điều này chấp nhận được cho một PoC. **Bật tunnel là đổi hoàn toàn mô hình mối đe dọa**: URL đó nằm trên Internet công cộng, không cần đăng nhập, và Cloudflare không thêm lớp xác thực nào cho quick tunnel.

**Bốn cách khai thác cụ thể, không cần kỹ năng gì đặc biệt:**

1. **Bơm node ma để cướp toàn bộ job.** Gửi `POST /ingest {"node": "Node-Ma", "cpu_temp": 25, "cpu_util": 1}` mỗi 2 giây. Node này luôn mát nhất, luôn không bị flag, và dưới scheduler chấm điểm mới nó sẽ **luôn thắng điểm**. Nó nhận hết chat job của cả cụm và không bao giờ trả kết quả. Đây là DoS bằng ba dòng `curl`.
2. **Bơm số ESG giả.** Gửi telemetry dốc nhiệt giả → node bị flag → `hot_hours_avoided` tăng. Báo cáo ESG mất giá trị kiểm toán.
3. **Đổi ngưỡng cả cụm.** `POST /api/settings {"threshold_c": 40}` → mọi node bị flag → hệ thống ngừng dispatch hoàn toàn.
4. **Dùng chùa LLM.** Khi có `/chat`, ai biết URL đều gọi được — tính cả bot quét Internet. Tunnel URL không bí mật: chúng xuất hiện trong log DNS, Certificate Transparency, và bị quét chủ động.

Ngoài ra, `GET /jobs/next?node=X` lấy danh tính node **từ query string** — nghĩa là ngay cả khi có mật khẩu phòng, một worker hợp lệ vẫn có thể mạo danh worker khác chỉ bằng cách đổi tham số.

**Cách sửa.**

```
POST /join {room_code, password}  →  201 {worker_token, room_config}
                                  →  401 nếu sai (không tiết lộ danh sách worker)

Mọi request sau đó: Authorization: Bearer <worker_token>
Danh tính node lấy TỪ TOKEN, không bao giờ từ query string hay body.
```

Kèm theo:
- Băm mật khẩu phòng bằng Argon2id (hoặc PBKDF2-HMAC-SHA256 nếu muốn tránh thêm phụ thuộc), **không lưu plaintext**.
- Giới hạn tần suất `/join`: 5 lần/phút/IP, backoff lũy thừa sau 3 lần sai liên tiếp. Không có bước này thì mật khẩu 6 ký tự bị dò trong vài giờ qua tunnel.
- Token có hạn + thu hồi được (để tính năng "Host kick worker" trong thiết kế thực sự có hiệu lực — hiện tại kick mà không thu hồi token thì worker vẫn gọi API bình thường).
- Tách quyền: token **worker** (được `/ingest`, `/jobs/*`) khác token **quản trị** (được `/api/settings`, kick, đóng phòng). Hiện tại mọi thứ chung một mức.

> Đặc tả đầy đủ: [`06-bao-mat-va-quyen-rieng-tu.md`](06-bao-mat-va-quyen-rieng-tu.md), [`03-hop-dong-api.md`](03-hop-dong-api.md).

---

### S3 — Chỉ số ESG đo sai bản chất và bị thao túng được

Đây là rủi ro **uy tín** lớn nhất của dự án, vì báo cáo ESG chính là điểm nhấn thương mại (theo `BÁO CÁO TỔNG QUAN DỰ ÁN.md` §3.1: "*xuất file báo cáo định kỳ để doanh nghiệp nộp cho các cơ quan kiểm định chuẩn xanh*").

**Công thức hiện tại** — [`esg.py:11`](../server/esg.py):

```python
def kwh_saved(hot_hours, node_power_kw, cooling_overhead_factor):
    return hot_hours * node_power_kw * cooling_overhead_factor
```

trong đó `hot_hours` là tổng thời gian các node ở trạng thái **bị gắn cờ** ([`esg.py:33-43`](../server/esg.py)).

#### Vấn đề 3.1 — "Tiết kiệm" thực chất là "chuyển chỗ"

Node-A bị flag 10 phút, job chuyển sang Node-B.

- Hệ thống báo: `0,1667 h × 0,065 kW × 0,5 = 0,0054 kWh` → `13,5 ₫` → `0,0039 kg CO₂`
- Thực tế: **job vẫn chạy**, chỉ là chạy trên Node-B. Node-B đốt điện thay Node-A. Tổng điện toàn cụm gần như không đổi — thậm chí nhỉnh hơn, vì Node-A không tắt mà vẫn tiêu thụ điện idle.

Công thức đang đếm *thời gian né* rồi gọi đó là *năng lượng tiết kiệm*. Đó là hai đại lượng khác nhau về đơn vị lẫn ý nghĩa vật lý.

#### Vấn đề 3.2 — Chỉ số bị thao túng: hạ ngưỡng là số tự đẹp lên

Ngưỡng do người dùng tự chỉnh từ dashboard, dải hợp lệ 40–100°C ([`server.py:135`](../server/server.py)). Đặt `threshold_c = 40`:

- Mọi node luôn vượt ngưỡng → luôn bị flag → `hot_hours` tăng đúng 1 giờ mỗi giờ, mỗi node
- 10 node × 24 giờ = 240 node-giờ → **7,8 kWh** → **19.500 ₫** → **5,6 kg CO₂**
- Nhưng hệ thống **không dispatch được job nào**, vì node nào cũng bị flag ([`balancer.py:59`](../server/balancer.py))

Tức là: cấu hình khiến hệ thống làm được **ít việc nhất** cũng chính là cấu hình báo cáo **tiết kiệm nhiều nhất**. Phần thưởng gắn với việc gắn cờ, không gắn với hiệu quả. Bất kỳ ai chất vấn nghiêm túc cũng sẽ hỏi: *"vậy tôi hạ ngưỡng xuống 40 là công ty tôi thành xanh nhất Việt Nam à?"* — và không có câu trả lời nào bảo vệ được.

#### Vấn đề 3.3 — Không có mẫu số

Một chỉ số hiệu quả năng lượng bắt buộc phải có mẫu số là **công việc làm được**. `hot_hours_avoided` không so với gì cả. Node bị flag 100% thời gian = làm được 0 việc = báo cáo "tiết kiệm" tối đa.

#### Vấn đề 3.4 — Định giá carbon ở quy mô PoC ra số vô nghĩa

Thiết kế đề xuất `giá_trị = tấn_CO₂ × giá_cấu_hình`. Với hằng số hiện tại, **một giờ** node bị flag sinh ra:

```
0,065 kW × 0,5 × 1 h × 0,72 kg/kWh = 0,0234 kg CO₂ = 0,0000234 tCO₂
Ở giá 20 USD/tCO₂  →  0,000468 USD  ≈  0,5 ₫
```

Hiển thị "**giá trị tín chỉ carbon: 0,5 ₫**" trên dashboard sẽ phá hỏng độ tin cậy của toàn bộ panel, kể cả những con số đúng bên cạnh nó.

#### Vấn đề 3.5 — `cooling_overhead_factor = 0.5` không có nguồn

Hằng số này nói "mỗi 1 kWh điện tính toán kéo theo 0,5 kWh điện làm mát" — tương đương PUE ≈ 1,5. Con số đó hợp lý cho *một trung tâm dữ liệu*, nhưng hệ thống đang chạy trên **máy tính văn phòng trong phòng có điều hòa dùng chung**. Chưa có tài liệu nào ghi nguồn gốc hay điều kiện áp dụng của nó.

#### Phần tiết kiệm nào là THẬT?

Có bốn nguồn tiết kiệm có thật, và bạn **đã thu thập sẵn dữ liệu** để đo ba trong số đó:

| Nguồn | Cơ chế vật lý | Đo được không |
|---|---|---|
| **Dòng rò theo nhiệt** | Dòng rò của silicon tăng theo nhiệt độ. Cùng khối lượng việc, chip ở 85°C tốn thêm vài % so với chính nó ở 55°C | **Có** — đã thu `power_w` |
| **Tránh throttle** | CPU bị throttle chạy xung thấp → cùng job mất nhiều thời gian hơn → tốn nhiều điện hơn cho **cùng lượng việc** | **Có** — suy từ nhiệt + thời lượng job |
| **Điện quạt** | Chip nóng đẩy quạt lên tốc độ cao hơn; công suất quạt tăng gần bậc ba theo tốc độ | Một phần |
| **PUE / COP điều hòa** | Dời tải khỏi khu nóng giảm tải máy lạnh | Không ở quy mô PoC — chỉ ngoại suy được |

Và thiết kế LLM mới **cho bạn sẵn một mẫu số hoàn hảo: số token sinh ra.**

Chỉ số đúng là **Joule/token** (hoặc Wh trên 1000 token): đo `power_w` trong lúc suy luận, đếm token từ runtime, chia ra. Rồi chạy **A/B**: scheduler round-robin ngây thơ **so với** scheduler nhiệt-aware, trên cùng một bộ prompt cố định. Chênh lệch J/token là con số duy nhất bạn có thể nói *"chúng tôi đo được"* thay vì *"chúng tôi giả định"*.

**Hướng xử lý đã chốt: kiến trúc ESG 3 tầng** (ĐO THẬT / SUY RA / NGOẠI SUY), tách bạch trên giao diện, không bao giờ cộng gộp thành một con số.

> Đặc tả đầy đủ: [`07-esg-3-tang.md`](07-esg-3-tang.md). Cách lấy số công suất: [`08-do-cong-suat.md`](08-do-cong-suat.md).

---

### S4 — Một `model.pkl` chung cho 10 máy dị chủng là sai mô hình

**Code hiện tại** — [`train_model.py:46`](../server/train_model.py) lưu đúng một file:

```python
joblib.dump(model, "model.pkl")
```

và [`forecaster.py:17`](../server/forecaster.py) nạp đúng một file cho **tất cả** node.

**Tại sao ở 2 node thì không lộ.** PoC hiện tại hiệu chuẩn cả hai máy trong cùng một phiên rồi trộn chung dữ liệu ([`train_model.py:11`](../server/train_model.py) lặp qua `store.nodes()` và gộp vào chung `X, y`). Với hai máy tương tự nhau, model học được một hàm trung bình đủ dùng.

**Tại sao ở 10 máy thì vỡ.** Đặc trưng đầu vào là **nhiệt độ tuyệt đối** ([`features.py:24`](../server/features.py) trả `temps[-1]`, `temps.mean()`). Nhưng:

- Laptop mỏng chạy 45°C khi rảnh, 95°C khi tải — và 95°C với nó là *bình thường*
- Desktop tản nhiệt tốt chạy 32°C khi rảnh, 68°C khi tải hết — và 78°C với nó là *bất thường*
- Cùng một độ dốc 6°C/phút: với máy thứ nhất là chuyện thường ngày, với máy thứ hai là dấu hiệu quạt hỏng

Một model học trên hỗn hợp cả hai sẽ **dự báo trung bình sai cho cả hai**. Nó không sai ngẫu nhiên — nó sai có hệ thống, theo hướng đánh giá thấp máy nóng và đánh giá cao máy mát.

Cùng vấn đề với ngưỡng: `threshold_c` là **một số tuyệt đối dùng chung cho cả cụm** ([`server.py:72`](../server/server.py)). 75°C là mức báo động cho desktop và là mức nhàn rỗi-tải-nhẹ cho laptop mỏng.

**Cách sửa.**

1. **Dự báo ΔT thay vì T.** Nhãn là *mức tăng nhiệt trong 3 phút tới* (`max(future) − current`) thay vì nhiệt độ tuyệt đối. ΔT phụ thuộc chủ yếu vào tải và quán tính nhiệt — khái quát hóa giữa các máy tốt hơn nhiều so với nhiệt tuyệt đối. Dự báo cuối = `nhiệt_hiện_tại + ΔT_dự_báo`, vẫn ra cùng đại lượng để so ngưỡng.
2. **Model theo từng node** (`model_<node>.pkl`) khi node đó đã hiệu chuẩn xong, với model gộp làm dự phòng cho node mới. Đây là bước sau; ΔT ở trên đã giải quyết phần lớn vấn đề với chi phí thấp hơn nhiều.
3. **Ngưỡng tương đối theo baseline từng máy**: lưu `idle_baseline_c` đo được cho mỗi node, ngưỡng hiệu lực = `min(ngưỡng_cụm, baseline + biên_cho_phép)`. Vừa sửa vấn đề dị chủng, vừa là cơ chế chống thao túng chỉ số ở [S3](#vấn-đề-32--chỉ-số-bị-thao-túng-hạ-ngưỡng-là-số-tự-đẹp-lên).

> Đặc tả đầy đủ: [`05-du-bao-nhiet.md`](05-du-bao-nhiet.md). Quyết định: [`adr/ADR-004-du-bao-delta-t.md`](adr/ADR-004-du-bao-delta-t.md).

---

### S5 — Toàn bộ trạng thái ESG và cờ chỉ nằm trong RAM

**Code hiện tại** — [`esg.py:28-31`](../server/esg.py):

```python
def __init__(self, config):
    self.config = config
    self._flagged_since = {}   # node -> ts when flag started
    self._accumulated_s = 0.0  # closed flag intervals
```

Tương tự, `LoadBalancer._flags` ([`balancer.py:19`](../server/balancer.py)) và cả hàng đợi job đều là biến trong bộ nhớ.

**Hệ quả cụ thể.**

- Host khởi động lại (cập nhật, mất điện, sập ứng dụng) → **toàn bộ số liệu ESG về 0**. Không có cách nào khôi phục dù `telemetry.db` vẫn còn nguyên dữ liệu thô.
- Không có **vết kiểm toán**. Báo cáo chỉ đưa ra con số tổng, không đưa ra được chuỗi sự kiện đã tạo nên con số đó. Một báo cáo ESG nộp cho bên thứ ba mà không tái lập được từ sự kiện gốc thì không dùng được — đó là toàn bộ điểm của việc kiểm định.
- Không đối chiếu chéo được. Nếu ai đó hỏi *"tại sao tháng này số cao gấp đôi tháng trước?"*, hiện tại không có dữ liệu để trả lời.
- Ngưỡng có thể đã đổi giữa chừng ([`server.py:175`](../server/server.py)) mà báo cáo không ghi nhận — hai khoảng thời gian với hai ngưỡng khác nhau bị cộng gộp thành một con số vô nghĩa.

**Cách sửa.** Ghi **nhật ký sự kiện** vào SQLite (dùng lại chính `telemetry.db`, thêm bảng):

```sql
CREATE TABLE esg_events (
  id INTEGER PRIMARY KEY,
  node TEXT NOT NULL,
  event TEXT NOT NULL,          -- 'flagged' | 'cleared' | 'threshold_changed' | 'job_completed'
  ts REAL NOT NULL,
  threshold_at_time REAL,       -- ngưỡng có hiệu lực tại thời điểm này
  predicted_max REAL,           -- dự báo đã dẫn tới quyết định
  detail TEXT                   -- JSON tự do: tokens, joules, duration...
);
```

Báo cáo trở thành một **hàm thuần túy tính từ nhật ký sự kiện**, không phải một biến tích lũy. Lợi ích dây chuyền: tái lập được, kiểm toán được, tính lại được cho khoảng thời gian bất kỳ, và test được bằng cách nạp sự kiện giả — không cần chạy thật.

---

## Nhóm M — Trung bình (sẽ cắn ở quy mô 10 node)

### M6 — Dự báo được tính hai lần ở hai nơi và có thể lệch nhau

Hai đường code độc lập cùng gọi `predict_max_temp`:

- [`server.py:75`](../server/server.py) trong `run_forecast_cycle` — chạy mỗi 5 giây, **quyết định gắn cờ**
- [`server.py:115`](../server/server.py) trong `build_state_payload` — chạy mỗi 2 giây theo nhịp WebSocket, **hiển thị lên dashboard**

Hai lời gọi này ở hai mốc thời gian khác nhau, trên hai cửa sổ dữ liệu khác nhau. Dashboard có thể hiển thị `predicted_max = 73,8°C` bên cạnh badge **AT RISK** với ngưỡng 75°C — vì quyết định flag được đưa ra 4 giây trước với con số 76,2°C. Người xem sẽ kết luận hệ thống bị lỗi, và không có cách nào bác lại.

Chi phí đi kèm: với 10 node, mỗi 2 giây là 10 truy vấn cửa sổ SQL + 10 lần suy luận Random Forest, chỉ để vẽ lại giao diện.

**Cách sửa.** Vòng forecast ghi kết quả vào cache (`node → {predicted_max, ts, flagged, reason}`); `build_state_payload` chỉ đọc cache. Sửa cùng lúc cả tính nhất quán lẫn hiệu năng, và cache này cũng chính là đầu vào cho scheduler ở [S1](#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại).

### M7 — Không có trễ trong quyết định gắn cờ → node dao động quanh ngưỡng

> ✅ **Đã xử lý trong mã nguồn.** (Hoàn thành trước vòng Chung kết)

[`server.py:91-100`](../server/server.py) gắn cờ khi `pred >= threshold` và gỡ cờ khi `pred < threshold` — **cùng một điểm cắt**. Một node dao động quanh ngưỡng (rất phổ biến, vì dự báo có nhiễu ±1-2°C) sẽ bật/tắt cờ liên tục theo nhịp 5 giây.

Hệ quả: job nhảy qua nhảy lại giữa các node; ESG cộng dồn theo cụm nhấp nháy; nhật ký ngập dòng flag/clear; và với chat LLM thì tệ hơn nhiều so với burn job — một job chat đang chạy dở bị dời máy nghĩa là mất toàn bộ ngữ cảnh đã nạp (prompt processing) và phải làm lại từ đầu.

**Cách sửa.** Băng trễ (hysteresis): gắn cờ ở `≥ T`, chỉ gỡ ở `≤ T − 3°C`. Cộng thời gian lưu trú tối thiểu (ví dụ 30 giây) trước khi cho phép đổi trạng thái lần nữa.

### M8 — Không có nhận thức về hàng đợi và mức đồng thời

Công thức score trong thiết kế có 5 số hạng (mát, rảnh, ít điện, thời tiết, đủ năng lực) nhưng **không có số hạng nào cho "node này đang chạy dở 2 job rồi"**.

Với burn job thì không sao — chúng là tải giả, chồng lên nhau cũng chẳng ai chờ. Với **chat LLM trên CPU thì đây là yếu tố áp đảo về độ trễ**: llama.cpp mặc định dùng hết số nhân vật lý. Hai phiên suy luận song song trên cùng máy không phải nhanh gấp đôi — chúng tranh nhau nhân và bộ nhớ đệm, mỗi phiên chậm hơn **hơn** hai lần, cộng thêm rủi ro cạn RAM.

Nghịch lý cụ thể: `cpu_util` được lấy từ mẫu telemetry **gần nhất**, mà telemetry gửi mỗi 2 giây. Một node vừa nhận job 200 mili-giây trước vẫn còn báo `cpu_util = 5%` → vẫn ghi điểm rất cao → nhận tiếp job thứ hai. Ở 10 node và tải chat dồn dập, hiện tượng "dồn đàn" (herd) này xảy ra thường xuyên.

**Cách sửa.** Host tự theo dõi `inflight[node]` (số job đã gán mà chưa nhận kết quả) — đây là **sự thật tức thời**, không có độ trễ như telemetry. Thêm `w_load × (1 − inflight/max_concurrent)` vào score, và **giới hạn cứng `max_concurrent = 1`** cho suy luận LLM trên CPU.

### M9 — Bộ sinh tải demo luôn bật

> ✅ **Đã xử lý trong mã nguồn.** (Hoàn thành trước vòng Chung kết)

[`server.py:216-222`](../server/server.py) `_generator_loop` bơm burn job mỗi 4 giây, vô điều kiện, ngay khi server khởi động ([`server.py:146-147`](../server/server.py)).

Trong hệ thống mới, tải chính là chat LLM. Bộ sinh burn job sẽ **đánh nhau với tải thật**: nó làm nóng chính những node mà scheduler đang cố giữ mát, làm sai lệch mọi phép đo J/token, và khiến kết quả A/B ở [S3](#s3--chỉ-số-esg-đo-sai-bản-chất-và-bị-thao-túng-được) vô nghĩa.

**Cách sửa.** Đưa về cờ opt-in `--demo-load`, mặc định tắt. Giữ lại như một chế độ trình diễn có chủ đích (thiết kế mục 9 cũng nói vậy) — nhưng phải là lựa chọn, không phải mặc định.

### M10 — `build_dataset` có độ phức tạp O(n²)

[`train_model.py:13-19`](../server/train_model.py):

```python
for i, row in enumerate(rows):
    t = row["ts"]
    window = [r for r in rows if t - window_s <= r["ts"] <= t]      # quét toàn bộ
    future = [r["cpu_temp"] for r in rows if t < r["ts"] <= t + horizon_s]  # quét toàn bộ
```

Mỗi dòng quét lại toàn bộ tập dữ liệu **hai lần**.

- Hiện tại: 2 node × 11 phút × 0,5 Hz ≈ 660 dòng/node → ~0,9 triệu phép so sánh. Chạy trong vài giây. Không ai nhận ra.
- Ở 10 node × phiên hiệu chuẩn dài (giả sử 100.000 dòng) → **10¹⁰ phép so sánh**. Script sẽ treo hàng giờ và trông như bị đơ.

**Cách sửa.** Hai con trỏ trượt cửa sổ (dữ liệu đã sắp xếp tăng dần theo `ts` — [`store.py:32`](../server/store.py) đảm bảo điều này), đưa về O(n). Đồng thời nên lọc theo từng node trước rồi mới xử lý, thay vì để `rows` chứa lẫn lộn.

### M11 — Hàm `normalize()` chưa được định nghĩa và sẽ không ổn định

Thiết kế viết `normalize(predicted_max_temp)` nhưng không nói chuẩn hóa theo cái gì. Cách làm mặc định (min-max trên tập node hiện tại) khiến điểm số **không dừng**:

> Cụm có 3 node ở 50/55/60°C. Node 60°C có điểm mát thấp nhất. Cắm thêm một máy đang chạy 90°C vào → thang đo giãn ra → node 60°C đột nhiên trở thành "khá mát" và điểm nhảy vọt, **dù không có gì thay đổi trên máy đó**.

Điều này khiến hành vi hệ thống không giải thích được và không viết được test hồi quy ổn định.

**Cách sửa.** Chuẩn hóa theo **khoảng tuyệt đối cố định**, và tốt nhất là dùng đại lượng có nghĩa vật lý:

```
headroom = (ngưỡng − dự_báo_max) / (ngưỡng − baseline_idle)
```

Cắt về khoảng [0, 1]. Ưu điểm: ổn định (không phụ thuộc node khác), tự chuẩn hóa theo từng máy (giải quyết luôn một phần [S4](#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình)), và **giải thích được cho người không kỹ thuật**: "*máy này còn 70% khoảng an toàn*" dễ hiểu hơn nhiều so với "*điểm mát 0,7*".

### M12 — Thời tiết trong công thức chấm điểm gần như vô nghĩa

Thiết kế đưa `w_weather × (1 − normalize(outdoor_heat_index))` vào score.

Vấn đề: nếu **tất cả node ở cùng một phòng** (kịch bản thực tế của bạn), số hạng này là một **hằng số giống nhau cho mọi node** → nó triệt tiêu hoàn toàn trong phép so sánh. Nó không đổi thứ hạng của bất kỳ ai. Nó chỉ tốn một lời gọi API.

Kể cả khi các node ở các phòng khác nhau trong cùng thành phố, điều hòa đã cắt đứt quan hệ giữa nhiệt độ ngoài trời và nhiệt độ chip. Cảm biến trên chip đã đo trực tiếp thứ bạn quan tâm rồi.

Và câu hỏi sẽ đến ngay trong buổi demo: *"tại sao thời tiết Hà Nội quyết định máy nào trong phòng tôi chạy chat?"* — câu trả lời trung thực là **nó không quyết định**, và trả lời như vậy sau khi đã đưa nó vào công thức thì mất điểm.

**Cách sửa — giữ thời tiết nhưng đặt đúng chỗ.** Thời tiết có giá trị thật ở ba chỗ, không phải trong score:

1. **Hệ số chi phí làm mát theo site trong ESG** (Tầng 2) — ngày nóng thì điều hòa tốn hơn cho cùng lượng nhiệt thải. Đây là quan hệ vật lý có thật.
2. **Ngữ cảnh hiển thị** trên dashboard — phân biệt rõ "Nhiệt môi trường" với "Nhiệt CPU" (thiết kế mục 8.3 đã nói đúng điều này).
3. **Chính sách theo khung giờ** — ví dụ nâng biên an toàn vào buổi chiều nóng nhất.

Trong scheduler: mặc định `w_weather = 0` khi mọi node dùng chung `site_id`; chỉ cho phép khác 0 khi thực sự đa site, và ghi rõ trong cấu hình là như vậy.

### M13 — Trạng thái khởi động nguội chưa được định nghĩa

[`features.py:7-8`](../server/features.py) yêu cầu ít nhất 5 mẫu trải ít nhất 30 giây; thiếu thì `build_features` trả `None` và `predict_max_temp` cũng trả `None` ([`forecaster.py:33`](../server/forecaster.py)).

Trong 30 giây đầu sau khi worker vào phòng: node **không bị flag** (nhánh `pred is None` ở [`server.py:81-90`](../server/server.py) chỉ xử lý trường hợp node đã chết), nhưng cũng **chưa có dự báo để chấm điểm**. Score của nó bằng bao nhiêu? Thiết kế không nói.

Hai cách sai đều dễ mắc: cho điểm 0 → worker mới không bao giờ được dùng trong 30 giây đầu; cho điểm tối đa → worker mới hút hết job trước khi ai kịp biết nó có nóng không.

**Cách sửa.** Định nghĩa trạng thái tường minh `WARMING_UP`: đủ điều kiện nhận job (không bị loại), nhưng dùng **nhiệt độ hiện tại thay cho dự báo** và nhân điểm với hệ số phạt (ví dụ 0,7) để phản ánh sự không chắc chắn. Hiển thị badge riêng trên dashboard để người xem không nhầm với OFFLINE.

### M14 — Hai chính sách điều phối chồng lên nhau

`_throttled` ([`balancer.py:45-55`](../server/balancer.py)) phục vụ node "ấm nhưng an toàn" cách một lượt. Đây là một chính sách điều phối **độc lập**, dựa trên bộ đếm lượt poll (`_poll_count`), không dựa trên điểm số.

Khi thêm scheduler chấm điểm ở [S1](#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại), sẽ có **hai luật cùng quyết định job đi đâu**, và chúng sẽ mâu thuẫn: scheduler chọn Node-A vì điểm cao nhất, rồi `_throttled` từ chối Node-A vì đang ở lượt bị bỏ qua. Job bị treo cho tới lượt sau. Không ai debug được chuyện này qua log, vì hai quyết định nằm ở hai module.

**Cách sửa.** Bỏ hẳn `_throttled` và `_poll_count`. Điểm số đã bao hàm ý đồ "ưu tiên node mát" một cách liên tục và tinh vi hơn nhiều so với luật cách-một-lượt. Ghi vào ADR để sau này không ai vô tình thêm lại.

---

## Nhóm D — Rủi ro triển khai doanh nghiệp

### D15 — Tự tải binary + chạy quyền Administrator + tệp chưa ký số

Agent **đã** cần quyền Administrator vì LibreHardwareMonitor nạp driver mức nhân để đọc nhiệt độ CPU ([`SensorReader.cs:16`](../agent/SensorReader.cs), [`app.manifest`](../agent/app.manifest) đặt `requireAdministrator`).

Thiết kế mới cộng thêm: tự tải `llama-server.exe`, tệp mô hình GGUF vài trăm MB, và `cloudflared.exe` — rồi **chạy chúng**.

Đứng từ góc nhìn của phần mềm diệt virus doanh nghiệp, đó chính xác là mô tả của một trình tải mã độc: một tệp thực thi chưa ký số, chạy quyền quản trị, nạp driver mức nhân, tải thêm tệp thực thi từ Internet rồi thực thi tiếp. Nó sẽ bị cách ly. Đây không phải rủi ro lý thuyết — đây là kết quả mặc định.

**Giảm thiểu.**
- **Ghim phiên bản + SHA256** cho mọi tệp tải về; kiểm tra hash **trước** khi chạy; từ chối và báo lỗi rõ ràng nếu lệch. Bảo vệ cả trước tấn công chuỗi cung ứng lẫn tải hỏng.
- Chỉ tải qua HTTPS từ danh sách miền đã ghim.
- Chuẩn bị **tài liệu whitelist cho bộ phận IT**: danh sách hash, đường dẫn cài, cổng dùng, giải thích tại sao cần quyền quản trị. Tài liệu này quyết định dự án được triển khai hay không, nhiều hơn bất kỳ tính năng nào.
- Cân nhắc **gói sẵn mô hình trong bộ cài** thay vì tải lúc chạy. Bộ cài nặng hơn 400 MB nhưng bỏ được toàn bộ đường tải-rồi-chạy.
- Về lâu dài: ký số tệp thực thi. Chứng chỉ ký mã khoảng vài trăm USD/năm và giải quyết phần lớn vấn đề này.

### D16 — Cloudflare quick tunnel không đủ tin cậy để xây tính năng lên trên

Quick tunnel (`*.trycloudflare.com`) không cần tài khoản, nhưng: **URL đổi mỗi lần khởi động lại**, có giới hạn tần suất, không có cam kết dịch vụ, và Cloudflare nói rõ nó dành cho thử nghiệm.

Thiết kế lại xây "Room Directory ánh xạ mã → URL" **lên trên** nền đó. Tức là xây một dịch vụ để giải quyết vấn đề do chính lựa chọn hạ tầng gây ra.

**Giảm thiểu.** LAN là đường chính (không cần tunnel, độ trễ thấp nhất, không phụ thuộc bên thứ ba). Tunnel là tùy chọn cho trường hợp khác mạng, và nếu cần ổn định thì dùng **named tunnel** với tài khoản Cloudflare → hostname cố định → link mời không đổi → **directory service trở nên không cần thiết** ([D18](#d18--room-directory-service-nên-cắt-khỏi-phạm-vi)).

Lưu ý thêm: nhiều mạng doanh nghiệp chặn `cloudflared`. Đường dự phòng LAN + IP thủ công phải luôn có và phải được ghi trong tài liệu vận hành.

### D17 — Prompt chat rời máy host sang máy đồng nghiệp

Thiết kế chưa phát biểu gì về việc worker có ghi log prompt hay không. Đây là vấn đề quản trị dữ liệu thật trong môi trường công ty: nội dung người dùng gõ vào ô chat sẽ được gửi tới máy tính cá nhân của một đồng nghiệp khác, xử lý ở đó, và có thể nằm lại trong log.

Cần phát biểu rõ trong tài liệu:
- Mặc định **không ghi log nội dung prompt ở worker**. Chỉ ghi `job_id`, số token, thời lượng, năng lượng — đủ để tính ESG mà không lưu nội dung.
- Chặng nào được mã hóa: người dùng → host qua tunnel là **có TLS**; host → worker trên LAN là **HTTP thuần** trừ khi bổ sung.
- Prompt nằm trong RAM của tiến trình worker khi đang xử lý. Không có cách nào tránh — phải nói ra thay vì để người dùng tự phát hiện.
- Ai xem được nội dung chat qua dashboard, và có phân quyền không.

### D18 — Room Directory service nên cắt khỏi phạm vi

Thiết kế mục 5.2 đề xuất một dịch vụ mỏng ánh xạ mã phòng → URL tunnel, để người dùng chỉ cần gõ mã thay vì dán link.

Đổi lại: một dịch vụ có host phải nuôi, phải cấp phát, phải bảo mật, phải xử lý hết hạn — trong khi thiết kế lại tự hào là "tự host 100%, không có cloud sản phẩm nặng". Dịch vụ này mâu thuẫn trực tiếp với tính chất đó, và lợi ích thuần túy là thẩm mỹ.

**Khuyến nghị: cắt.** Link mời + mật khẩu đã đủ, tự chủ hoàn toàn, luôn hoạt động. Nếu cần UX "chỉ gõ mã", dùng named tunnel để hostname cố định rồi in mã QR trên màn hình host — cùng trải nghiệm, không cần dịch vụ nào.

---

## Nhóm G — Điểm tốt cần giữ

### G1 — Worker chỉ outbound

Agent không bao giờ lắng nghe cổng nào; nó chỉ gọi `POST /ingest` và `GET /jobs/next` ra ngoài ([`Program.cs:34-85`](../agent/Program.cs)). Hệ quả (đã ghi trong `HOW_IT_WORKS.md` §3): chỉ máy Host cần mở tường lửa; máy phụ không cần rule inbound, không cần chuyển tiếp cổng, không cần IP tĩnh; agent chạy được trên laptop di chuyển giữa các mạng.

Đây là tài sản kiến trúc lớn nhất của PoC. **Mọi phương án cho [S1](#s1--scheduler-chấm-điểm-sẽ-không-hoạt-động-dưới-cơ-chế-pull-hiện-tại) đều phải bảo toàn nó** — kể cả phương án WebSocket, vì kết nối vẫn do worker khởi tạo.

### G2 — Xử lý node ma và cờ kẹt

Hai đoạn logic chín, hiếm gặp ở PoC:

- [`server.py:57-68`](../server/server.py) `active_nodes` — node không có mẫu nào trong 900 giây bị loại **hoàn toàn** khỏi dự báo, so sánh nhiệt và dashboard, thay vì tồn tại mãi như thẻ `OFFLINE?`. Tránh được việc `telemetry.db` từ phiên cũ làm nhiễu quyết định của phiên mới.
- [`server.py:81-90`](../server/server.py) — nếu một node đang bị flag rồi agent chết, cờ sẽ **kẹt vĩnh viễn** (không còn dữ liệu để dự báo → không bao giờ xuống dưới ngưỡng → không bao giờ được gỡ), và ESG sẽ cộng dồn "giờ nóng tránh được" không giới hạn. Đoạn code này phát hiện và gỡ cờ khi dữ liệu quá cũ.

Cả hai đều **đã có test** (`tests/test_server.py:68` và `tests/test_server.py:94`) với chú thích giải thích rõ tại sao. Mang thẳng sang hệ mới, đừng viết lại.

### G3 — Tách module sạch, ánh xạ 1-1 sang hệ đích

| Module hiện có | Vai trò trong hệ đích |
|---|---|
| [`store.py`](../server/store.py) | Giữ nguyên; thêm bảng `esg_events` ([S5](#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram)) |
| [`features.py`](../server/features.py) | Giữ nguyên; đổi nhãn sang ΔT ([S4](#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình)) |
| [`forecaster.py`](../server/forecaster.py) | Giữ nguyên; thêm model theo node |
| [`balancer.py`](../server/balancer.py) | Mở rộng thành `ChatJobQueue` + reservation; bỏ `_throttled` ([M14](#m14--hai-chính-sách-điều-phối-chồng-lên-nhau)) |
| [`esg.py`](../server/esg.py) | Mở rộng thành 3 tầng; chuyển sang tính từ event log |
| [`settings.py`](../server/settings.py) | Mở rộng thành cấu hình phòng |
| *(mới)* | `room.py` (xác thực), `scheduler.py` (chấm điểm), `llm.py` (chạy suy luận) |

Không cần viết lại kiến trúc. Đây là lý do bản thiết kế khả thi trong khung thời gian hợp lý.

### G4 — 32 test ở mức hành vi

Các test kiểm tra **hành vi quan sát được** chứ không kiểm tra chi tiết cài đặt: `test_full_loop_flags_hot_node_and_blocks_jobs` bơm telemetry rồi khẳng định job bị chặn — nó không quan tâm hàm nào gọi hàm nào. Loại test này **sống sót qua refactor**, đúng thứ cần khi sắp thay đổi lớn. Chạy chúng sau mỗi bước là lưới an toàn thật.

Điểm cộng: `POC_NO_BACKGROUND=1` ([`server.py:141`](../server/server.py)) cho phép test tạo app mà không chạy các vòng lặp nền — thiết kế test tốt, phải giữ.

### G5 — Văn hóa tài liệu và nhật ký

`HOW_IT_WORKS.md` có bảng triệu chứng → nguyên nhân, sơ đồ luồng dữ liệu, và giải thích *tại sao* chứ không chỉ *cái gì*. Nhật ký dùng tiền tố nhất quán (`[FORECAST]`, `[BALANCER]`, `[GENERATOR]`, `[CALIBRATE]`, `[SETTINGS]`, `[JOB]`, `[AGENT]`) và ghi mọi quyết định hệ trọng bằng ngôn ngữ đọc được.

Mỗi module Python đều mở đầu bằng docstring giải thích vai trò. Đây là quy ước đáng giữ và đã được ghi thành luật trong [`AGENTS.md`](../AGENTS.md).

---

## Bảng tổng hợp và thứ tự xử lý

| Mã | Vấn đề | Mức | Nơi xử lý | Mốc |
|---|---|---|---|---|
| S1 | Scheduler không có đường tác động | Nghiêm trọng | [`04`](04-dac-ta-scheduler.md), [`ADR-001`](adr/ADR-001-reservation-thay-vi-push.md) | M2 |
| S2 | Không có xác thực | Nghiêm trọng | [`06`](06-bao-mat-va-quyen-rieng-tu.md), [`ADR-002`](adr/ADR-002-xac-thuc-token.md) | M1 |
| S3 | ESG đo sai + bị thao túng | Nghiêm trọng | [`07`](07-esg-3-tang.md), [`ADR-003`](adr/ADR-003-esg-ba-tang.md) | M4 |
| S4 | Một model cho 10 máy dị chủng | Nghiêm trọng | [`05`](05-du-bao-nhiet.md), [`ADR-004`](adr/ADR-004-du-bao-delta-t.md) | M3 |
| S5 | Trạng thái ESG chỉ trong RAM | Nghiêm trọng | [`07`](07-esg-3-tang.md) §nhật ký sự kiện | M4 |
| M6 | Dự báo tính hai lần, lệch nhau | Trung bình | [`02`](02-kien-truc-he-thong.md) §cache dự báo | M2 |
| M7 | Không có băng trễ → dao động | Trung bình | [`04`](04-dac-ta-scheduler.md) §hysteresis | M2 |
| M8 | Không nhận thức đồng thời | Trung bình | [`04`](04-dac-ta-scheduler.md) §inflight | M2 |
| M9 | Bộ sinh tải demo luôn bật | Trung bình | [`02`](02-kien-truc-he-thong.md) §chế độ chạy | M1 |
| M10 | `build_dataset` O(n²) | Trung bình | [`05`](05-du-bao-nhiet.md) §huấn luyện | M3 |
| M11 | `normalize()` không ổn định | Trung bình | [`04`](04-dac-ta-scheduler.md) §headroom | M2 |
| M12 | Thời tiết trong score vô nghĩa | Trung bình | [`04`](04-dac-ta-scheduler.md), [`07`](07-esg-3-tang.md) | M5 |
| M13 | Khởi động nguội chưa định nghĩa | Trung bình | [`04`](04-dac-ta-scheduler.md) §WARMING_UP | M2 |
| M14 | Hai chính sách điều phối | Trung bình | [`04`](04-dac-ta-scheduler.md), [`ADR-001`](adr/ADR-001-reservation-thay-vi-push.md) | M2 |
| D15 | Tải binary + admin + chưa ký | Triển khai | [`10`](10-phong-tunnel-trien-khai.md) §chuỗi cung ứng | M3 |
| D16 | Quick tunnel không tin cậy | Triển khai | [`10`](10-phong-tunnel-trien-khai.md) §tunnel | M1 |
| D17 | Prompt rời máy host | Triển khai | [`06`](06-bao-mat-va-quyen-rieng-tu.md) §quyền riêng tư | M3 |
| D18 | Directory service thừa | Triển khai | [`10`](10-phong-tunnel-trien-khai.md) §quyết định cắt | — |

Lộ trình mốc M0–M6: [`12-lo-trinh-va-milestone.md`](12-lo-trinh-va-milestone.md).
