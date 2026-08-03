# 11 — Chiến lược kiểm thử

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Liên quan: [`04-dac-ta-scheduler.md`](04-dac-ta-scheduler.md) §9 (bảng ca kiểm thử scheduler)

## Mục lục

- [Nguyên tắc](#1-nguyên-tắc)
- [Nền móng hiện có](#2-nền-móng-hiện-có)
- [Tháp kiểm thử](#3-tháp-kiểm-thử)
- [Bộ giả lập 10 node](#4-bộ-giả-lập-10-node)
- [Kiểm thử hỗn loạn](#5-kiểm-thử-hỗn-loạn)
- [Kiểm thử bảo mật](#6-kiểm-thử-bảo-mật)
- [Kiểm thử ESG](#7-kiểm-thử-esg)
- [Kiểm thử thủ công](#8-kiểm-thử-thủ-công)
- [Diễn tập demo](#9-diễn-tập-demo)
- [CI](#10-ci)

---

## 1. Nguyên tắc

| # | Nguyên tắc | Vì sao |
|---|---|---|
| 1 | **Kiểm hành vi, không kiểm cài đặt** | Test sống sót qua refactor. PoC đã làm đúng — giữ nguyên phong cách |
| 2 | **Không cần 10 máy thật** | Giả lập 10 node trong tiến trình; CI phải chạy được trên một máy |
| 3 | **Thời gian là tham số, không phải `time.time()`** | PoC đã làm đúng: mọi hàm nhận `now`. Nhờ vậy test hàng giờ vận hành trong vài mili-giây |
| 4 | **Mỗi lỗi đã sửa để lại một test** | 18 phát hiện ở [01](01-danh-gia-thiet-ke-hien-tai.md) → 18 test hồi quy |
| 5 | **Test đọc được như đặc tả** | Tên test mô tả hành vi, không mô tả hàm được gọi |

Nguyên tắc 3 là tài sản đã có. [`server.py:70`](../server/server.py) `run_forecast_cycle(state, now)`, [`esg.py:41`](../server/esg.py) `report(self, now)` — mọi thứ phụ thuộc thời gian đều nhận `now` từ ngoài. Kiến trúc mới phải giữ nguyên kỷ luật này; nó là lý do bộ test hiện tại chạy trong chưa tới một giây.

---

## 2. Nền móng hiện có

32 test đang xanh, chia đều theo module:

| Tệp | Bao phủ |
|---|---|
| [`test_store.py`](../server/tests/test_store.py) | Chèn, truy vấn cửa sổ, lấy mẫu mới nhất |
| [`test_features.py`](../server/tests/test_features.py) | Vector đặc trưng, ngưỡng dữ liệu tối thiểu |
| [`test_forecaster.py`](../server/tests/test_forecaster.py) | Dự phòng tuyến tính, có/không có model |
| [`test_balancer.py`](../server/tests/test_balancer.py) | FIFO, gắn cờ, giới hạn hàng đợi, job có đích |
| [`test_esg.py`](../server/tests/test_esg.py) | Công thức, cộng dồn |
| [`test_settings.py`](../server/tests/test_settings.py) | Lưu/đọc, kiểm tra dải giá trị |
| [`test_calibrate.py`](../server/tests/test_calibrate.py) | Chuỗi pha hiệu chuẩn |
| [`test_train_model.py`](../server/tests/test_train_model.py) | Xây tập dữ liệu |
| [`test_server.py`](../server/tests/test_server.py) | **Vòng lặp đầu-cuối** |

Hai test đáng chú ý vì chúng bảo vệ đúng phần logic tinh tế nhất ([01 §G2](01-danh-gia-thiet-ke-hien-tai.md#g2--xử-lý-node-ma-và-cờ-kẹt)):

- `test_stale_flagged_node_gets_cleared_and_stops_accruing_esg` — cờ kẹt khi agent chết
- `test_ghost_node_from_old_session_excluded_from_active_state` — node ma từ phiên cũ

**Cả hai phải tiếp tục xanh sau khi tái cấu trúc.** Chúng là hợp đồng, không phải chi tiết.

`POC_NO_BACKGROUND=1` ([`server.py:141`](../server/server.py)) cho phép dựng app mà không chạy vòng lặp nền. Giữ nguyên cơ chế này.

---

## 3. Tháp kiểm thử

```
        ╱╲          Thủ công — demo, phần cứng thật (§8, §9)
       ╱  ╲         vài chục ca, chạy tay trước mỗi mốc
      ╱────╲
     ╱      ╲       Hỗn loạn — worker chết, tunnel đứt (§5)
    ╱        ╲      ~15 ca, chạy hằng đêm
   ╱──────────╲
  ╱            ╲    Tích hợp — 10 node giả, đầu-cuối (§4)
 ╱              ╲   ~30 ca, chạy trong CI
╱────────────────╲
      Đơn vị        Scheduler, ESG, dự báo, xác thực
   ~120 ca          chạy mỗi lần commit, dưới 5 giây
```

### Đơn vị — trọng tâm

| Vùng | Số ca ước tính | Nguồn |
|---|---|---|
| Scheduler: lọc, chấm điểm, giữ chỗ, băng trễ | ~30 | [04 §9](04-dac-ta-scheduler.md#9-bảng-ca-kiểm-thử) — đã liệt kê đầy đủ |
| Xác thực phòng | ~20 | [06 §2](06-bao-mat-va-quyen-rieng-tu.md#2-xác-thực-và-phân-quyền) |
| ESG ba tầng | ~25 | [07](07-esg-3-tang.md) |
| Đặc trưng và dự báo | ~20 | [05](05-du-bao-nhiet.md) |
| Ước lượng công suất | ~10 | [08](08-do-cong-suat.md) |
| Hiện có, giữ nguyên | 32 | |

Toàn bộ test scheduler chỉ cần một `ForecastCache` giả — không cần cơ sở dữ liệu, không cần worker. Đó là lợi ích trực tiếp của quy tắc phụ thuộc ở [02 §3](02-kien-truc-he-thong.md#ranh-giới-module).

---

## 4. Bộ giả lập 10 node

Thành phần hạ tầng test quan trọng nhất cần xây.

```python
class FakeNode:
    """Một worker mô phỏng có mô hình nhiệt riêng.

    Mô hình nhiệt bậc một, đủ để sinh ra hành vi cần kiểm: nóng lên khi
    có tải, nguội về nền khi rảnh, mỗi máy có hằng số thời gian riêng.
    """
    def __init__(self, name, idle_temp, max_temp, heat_rate,
                 cool_rate, cores, has_power_sensor=True,
                 tokens_per_s=40.0):
        ...

    def tick(self, dt, under_load):
        """Cập nhật nhiệt độ. Không dùng đồng hồ thật — dt do test truyền vào."""
        target = self.max_temp if under_load else self.idle_temp
        rate = self.heat_rate if under_load else self.cool_rate
        self.temp += (target - self.temp) * rate * dt

    def telemetry(self, now):
        return {"ts": now, "cpu_temp": self.temp, "cpu_util": …,
                "power_w": … if self.has_power_sensor else None,
                "power_source": "sensor" if self.has_power_sensor else "none"}
```

### Cụm mẫu — cố ý dị chủng

Phản ánh đúng vấn đề của [S4](01-danh-gia-thiet-ke-hien-tai.md#s4--một-modelpkl-chung-cho-10-máy-dị-chủng-là-sai-mô-hình):

| Node | Loại | Nhàn rỗi | Tối đa | Nóng lên | Cảm biến điện | tok/s |
|---|---|---|---|---|---|---|
| Node-01..03 | Desktop mạnh | 32°C | 68°C | chậm | ✅ | 70 |
| Node-04..06 | Laptop văn phòng | 45°C | 88°C | trung bình | ✅ | 35 |
| Node-07..08 | Laptop mỏng | 52°C | 95°C | **nhanh** | ❌ | 18 |
| Node-09 | Desktop cũ, quạt bẩn | 48°C | 92°C | nhanh | ✅ | 25 |
| Node-10 | Không quyền quản trị | — | — | — | ❌ | 40 |

Node-10 không báo nhiệt độ — kiểm chế độ hoạt động hạn chế ở [06 §6](06-bao-mat-va-quyen-rieng-tu.md#6-quyền-administrator).
Node-09 mô phỏng máy cần vệ sinh tản nhiệt — kiểm cảnh báo ở [05 §9](05-du-bao-nhiet.md#9-giám-sát-chất-lượng-khi-vận-hành).

### Ca tích hợp

| # | Kịch bản | Khẳng định |
|---|---|---|
| C1 | 10 node, 100 job chat | Không job nào tới node bị gắn cờ |
| C2 | Như trên | Phân bố lệch rõ về node có headroom cao |
| C3 | Chỉ Node-01 mát | Node-01 nhận đa số nhưng **không phải tất cả** (còn `max_concurrent`) |
| C4 | Mọi node bị gắn cờ | Job chờ; **không** dispatch cho node bị cờ; dashboard báo đúng |
| C5 | Node-07 nóng rất nhanh | Bị gắn cờ trước Node-01 dù nhiệt tuyệt đối thấp hơn ban đầu |
| C6 | Tải kéo dài | Không node nào vượt ngưỡng quá `MIN_DWELL_S` |
| C7 | 10 node vào phòng đồng thời | Không có tranh chấp; đúng 10 token cấp ra |
| C8 | Node thứ 11 vào | `409 ROOM_FULL` |
| C9 | So sánh round-robin với thermal-aware | Nhiệt đỉnh cụm ở chế độ thermal-aware **thấp hơn** |
| C10 | Node-10 (không nhiệt) | Vẫn nhận job; **không** vào ESG Tầng 1 |

Ca C9 là ca quan trọng nhất về mặt thương mại: nếu nó không xanh thì sản phẩm không làm được điều nó hứa.

---

## 5. Kiểm thử hỗn loạn

Mỗi ca dưới đây tương ứng một dòng trong bảng xử lý lỗi ở [02 §10](02-kien-truc-he-thong.md#10-xử-lý-lỗi). Bảng đó là đặc tả; những test này là bằng chứng.

| # | Sự cố tiêm vào | Kỳ vọng |
|---|---|---|
| X1 | Worker ngừng gửi telemetry giữa chừng | `STALE` sau 10s; giữ chỗ được thu hồi; job đi máy khác |
| X2 | Worker nhận job rồi chết | Hết hạn giữ chỗ → chấm điểm lại → **người dùng vẫn nhận được trả lời** |
| X3 | Worker trả kết quả sau khi đã hết hạn | Bỏ qua kết quả muộn; không đếm `inflight` hai lần |
| X4 | Toàn bộ worker biến mất | Host tự suy luận nếu chạy được; nếu không, báo lỗi rõ |
| X5 | Host khởi động lại | **Số liệu ESG tính lại được từ nhật ký sự kiện** ([07 §6](07-esg-3-tang.md#6-nhật-ký-sự-kiện--nguồn-gốc-của-mọi-con-số)) |
| X6 | Tunnel đứt | Worker LAN không ảnh hưởng; worker xa chuyển `STALE` |
| X7 | Đồng hồ worker lệch 5 phút | Server dùng `ts` của mình; ghi cảnh báo một lần |
| X8 | Đồng hồ worker chạy lùi | Không sập; mẫu vẫn vào cửa sổ đúng |
| X9 | `telemetry.db` bị khóa | Thử lại có backoff; không mất mẫu |
| X10 | Runtime LLM treo | Timeout job; khởi động lại runtime; node bị phạt điểm |
| X11 | Ổ đĩa đầy | Ngừng ghi telemetry, **giữ nguyên nhật ký sự kiện ESG**; cảnh báo |
| X12 | Mất kết nối giữa lúc tải mô hình | Tải tiếp từ chỗ dở hoặc tải lại; **luôn kiểm hash** |
| X13 | Hai worker cùng tên | Worker thứ hai nhận `409 NODE_NAME_TAKEN` |
| X14 | Ngưỡng đổi giữa lúc job đang chạy | Job hiện tại chạy tiếp; job mới theo ngưỡng mới; ghi sự kiện |
| X15 | 100 yêu cầu chat cùng lúc | Hàng đợi có giới hạn; trả `429`, không sập |

X5 là ca đáng giá nhất — nó là bằng chứng trực tiếp rằng [S5](01-danh-gia-thiet-ke-hien-tai.md#s5--toàn-bộ-trạng-thái-esg-và-cờ-chỉ-nằm-trong-ram) đã được sửa.

---

## 6. Kiểm thử bảo mật

Mỗi ca là một đường tấn công cụ thể đã nêu trong [06](06-bao-mat-va-quyen-rieng-tu.md).

| # | Tấn công | Kỳ vọng |
|---|---|---|
| S1 | `POST /ingest` không có token | `401` |
| S2 | `POST /ingest` với token của Node-A nhưng body ghi `node: Node-B` | `403 IDENTITY_MISMATCH` + ghi kiểm toán |
| S3 | `GET /jobs/next?node=Node-B` với token của Node-A | Nhận job của **Node-A**, tham số bị bỏ qua |
| S4 | Token worker gọi `POST /api/settings` | `403 FORBIDDEN` |
| S5 | 10 lần `/join` sai mật khẩu trong 1 phút | `429` từ lần thứ 6, có backoff |
| S6 | Token của worker đã bị kick | `401 TOKEN_REVOKED` |
| S7 | Token hết hạn | `401 TOKEN_EXPIRED` |
| S8 | Sai mã phòng và sai mật khẩu | **Cùng một thông điệp lỗi** |
| S9 | Bật tunnel khi chưa đặt mật khẩu | Bị chặn ở tầng mã |
| S10 | Tệp tải về sai SHA256 | Xóa tệp, **không thực thi**, báo lỗi rõ |
| S11 | Tải từ miền ngoài `allowed_domains` | Hủy trước khi tải |
| S12 | Tìm mật khẩu/token trong mọi tệp log | **Không có kết quả nào** |
| S13 | Tìm nội dung prompt trong log worker | **Không có kết quả nào** |
| S14 | Đặt ngưỡng dưới sàn nhiệt nhàn rỗi | `422 THRESHOLD_TOO_LOW` |
| S15 | Node ma bơm telemetry mà không có token | `401`; không xuất hiện trên dashboard |

S12 và S13 nên là test tự động quét toàn bộ thư mục log sau một lượt chạy đầy đủ, không phải kiểm tra bằng mắt.

---

## 7. Kiểm thử ESG

Phần này bảo vệ điều dễ mất nhất: **tính trung thực của con số**.

| # | Ca | Kỳ vọng |
|---|---|---|
| E1 | Job có `energy_source='sensor'` | Vào Tầng 1 |
| E2 | Job có `energy_source='model'` | Vào Tầng 2, **không** vào Tầng 1 |
| E3 | Job có `energy_source='none'` | **Không vào tầng nào**; chỉ đếm token |
| E4 | Trộn 3 máy có cảm biến + 2 không | J/token Tầng 1 tính trên đúng 3 máy |
| E5 | Dưới 20 job | **Không hiện phần trăm cải thiện** |
| E6 | Đúng 20 job | Hiện, nhãn `sơ bộ` |
| E7 | 100 job | Nhãn `ok` |
| E8 | Thermal-aware tệ hơn round-robin | Báo cáo **số âm**, không giấu, không đổi dấu |
| E9 | Ngưỡng đổi giữa kỳ | Báo cáo **tách khoảng**, không cộng gộp |
| E10 | Tính lại từ nhật ký sự kiện | Cho **đúng kết quả cũ** |
| E11 | Đổi hằng số ESG rồi tính lại | Số đổi tương ứng; nhật ký không đổi |
| E12 | Thử đặt ngưỡng 40°C với nhàn rỗi 45°C | Bị từ chối |
| E13 | Gắn cờ mọi node cả ngày | **J/token không cải thiện** — chống thao túng |
| E14 | Cấu trúc JSON `/api/state` | Ba tầng là **ba đối tượng riêng** |

E13 là bài kiểm tra trực tiếp cho [S3.2](01-danh-gia-thiet-ke-hien-tai.md#vấn-đề-32--chỉ-số-bị-thao-túng-hạ-ngưỡng-là-số-tự-đẹp-lên). E14 kiểm rằng việc cộng gộp ba tầng là khó về mặt cú pháp, không chỉ bị cấm bằng lời.

---

## 8. Kiểm thử thủ công

Không thay được bằng tự động — cần phần cứng thật.

### Trước mỗi mốc

| # | Ca | Xác nhận |
|---|---|---|
| M1 | Host + 1 worker trên LAN | Vào phòng được, telemetry chảy, chat trả lời |
| M2 | Host + worker qua tunnel | Như trên, qua Internet |
| M3 | Host một mình | Tự suy luận (phương án P2) |
| M4 | 3+ máy thật, cấu hình khác nhau | Điều phối hoạt động, không có máy nào bị bỏ quên |
| M5 | Rút mạng của một worker | Chuyển `STALE`, job đi máy khác, người dùng vẫn có trả lời |
| M6 | Chạy `power_probe.ps1` trên mọi máy | Biết máy nào vào Tầng 1, máy nào Tầng 2 |
| M7 | Cài từ đầu trên máy sạch | Trình hướng dẫn chạy trơn, không cần thao tác thủ công |
| M8 | Gỡ cài | Sạch; hỏi trước khi xóa dữ liệu ESG |
| M9 | Chạy 4 giờ liên tục | Không rò bộ nhớ, không rò tiến trình, log không phình quá mức |
| M10 | Máy phụ dùng bình thường trong lúc chạy worker | **Người dùng không thấy máy chậm rõ rệt** |

M10 là bài kiểm tra sống còn của sản phẩm. Nếu đồng nghiệp thấy máy mình đơ mỗi lần có ai chat, họ sẽ tắt phần mềm trong tuần đầu tiên và không ai dùng nữa. Kiểm bằng cách đặt `--threads = số nhân − 2` rồi thao tác bình thường trong lúc có job chạy.

---

## 9. Diễn tập demo

Kịch bản 10 phút, chạy thử **ít nhất hai lần trước buổi thật**.

```
0:00  Mở dashboard. 3 máy, tất cả xanh, badge OK.
      → Nói: đây là nhiệt thật từ cảm biến, không phải mô phỏng.

1:00  Gửi vài câu chat. Chỉ vào nhãn "chạy trên Node-B".
      → Nói: hệ thống chọn máy, không phải máy giành việc.

2:30  Hạ ngưỡng xuống ~5°C trên nhiệt hiện tại của Node-A.
      → Node-A chuyển vàng rồi đỏ, badge AT RISK.
      → Chỉ vào lý do hiển thị: "dự báo 71,2°C ≥ ngưỡng 70,0°C".

3:30  Gửi tiếp 5 câu chat.
      → Tất cả đi sang Node-B và Node-C. Không câu nào tới Node-A.
      → Đây là khoảnh khắc trung tâm của buổi demo.

5:00  Chỉ vào panel ESG. Bắt đầu từ Tầng 1.
      → "Đây là số đo: J/token, so với mốc round-robin."
      → Rồi mới sang Tầng 2, Tầng 3. THEO ĐÚNG THỨ TỰ NÀY.

7:00  Node-A nguội xuống, cờ tự gỡ, xanh trở lại, nhận job.
      → Chỉ vào băng trễ: gỡ ở 67°C chứ không phải 70°C.

8:00  Rút mạng của Node-B.
      → STALE sau 10 giây, job đang chạy chuyển sang máy khác.

9:00  Xuất báo cáo CSV. Mở ra, chỉ vào nhật ký sự kiện.
      → "Mọi con số truy ngược được tới sự kiện gốc."
```

### Bốn quy tắc

1. **Luôn nói Tầng 1 trước.** Bắt đầu bằng số dự phóng là mời người ta chất vấn ngay từ đầu.
2. **Không giấu con số bất lợi.** Nếu độ trễ ở chế độ thermal-aware cao hơn, hãy nói và giải thích tại sao đánh đổi đó là có chủ đích.
3. **Chuẩn bị sẵn câu trả lời phản biện** — [07 §10](07-esg-3-tang.md#10-câu-hỏi-phản-biện-và-câu-trả-lời).
4. **Có phương án dự phòng.** Bản ghi màn hình của một lượt chạy thành công, phòng khi mạng hỏng tại chỗ.

---

## 10. CI

```yaml
# Chạy mỗi commit — mục tiêu dưới 60 giây
- pytest server/tests/ -v          # đơn vị + tích hợp, gồm 32 test hiện có
- ruff check server/ scripts/      # lint
- dotnet build agent/              # agent phải biên dịch được

# Chạy hằng đêm
- pytest server/tests/ -m chaos    # bộ hỗn loạn
- pytest server/tests/ -m security # bộ bảo mật
- python scripts/scan_logs_for_secrets.py   # ca S12, S13
```

**CI không được cần phần cứng thật.** Toàn bộ 10 node là giả lập; cảm biến là giá trị bơm vào; thời gian là tham số. Đó là lý do bộ test hiện tại chạy trong chưa tới một giây, và kiến trúc mới phải giữ được tính chất đó.

### Cổng chất lượng

| Chỉ số | Ngưỡng |
|---|---|
| Bao phủ dòng ở `scheduler.py`, `room.py`, `esg.py` | ≥90% |
| Bao phủ dòng toàn server | ≥80% |
| Test hiện có (32) | **Phải xanh 100%** |
| Test bảo mật | **Phải xanh 100%** — không có ngoại lệ |
| Thời gian chạy bộ đơn vị | <60 giây |
