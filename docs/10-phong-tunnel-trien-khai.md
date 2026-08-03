# 10 — Phòng, tunnel và triển khai

> Tài liệu chủ: [`00-TONG-QUAN-KY-THUAT.md`](00-TONG-QUAN-KY-THUAT.md)
> Sửa lỗi: [D16](01-danh-gia-thiet-ke-hien-tai.md#d16--cloudflare-quick-tunnel-không-đủ-tin-cậy-để-xây-tính-năng-lên-trên), [D18](01-danh-gia-thiet-ke-hien-tai.md#d18--room-directory-service-nên-cắt-khỏi-phạm-vi)
> Liên quan: [06](06-bao-mat-va-quyen-rieng-tu.md), [09](09-so-sanh-llm-runtime.md)

## Mục lục

- [Mô hình phòng](#1-mô-hình-phòng)
- [Vào phòng bằng cách nào](#2-vào-phòng-bằng-cách-nào)
- [Vì sao cắt Room Directory](#3-vì-sao-cắt-room-directory)
- [Tunnel](#4-tunnel)
- [Đóng gói và cài đặt](#5-đóng-gói-và-cài-đặt)
- [Tải thành phần lúc chạy](#6-tải-thành-phần-lúc-chạy)
- [Ma trận mạng](#7-ma-trận-mạng)
- [Gỡ cài](#8-gỡ-cài)

---

## 1. Mô hình phòng

**Host là nguồn sự thật duy nhất.** Mọi quyền vào phòng, mật khẩu, danh sách worker và cấu hình nằm trên máy host. Không có dịch vụ đám mây bắt buộc.

```
Phòng = {
    mã phòng          THERMAL-4F2A     — sinh ngẫu nhiên khi tạo
    tên hiển thị      "Phòng 4F"
    hash mật khẩu     Argon2id + muối riêng
    model_id          khóa cho cả phòng — mọi node dùng chung một mô hình
    ngưỡng            °C, có sàn theo nhiệt nhàn rỗi
    site_id           dùng cho thời tiết và hệ số làm mát
    max_workers       mặc định 10
    trọng số score    xem 04-dac-ta-scheduler.md §4.7
}
```

**Vì sao khóa `model_id` cho cả phòng.** Nếu Node-A chạy mô hình 0,5B và Node-B chạy 1,5B, thì so sánh J/token giữa hai máy trở nên vô nghĩa, và người dùng nhận được câu trả lời chất lượng khác nhau tùy máy nào rảnh. Cả hai đều không chấp nhận được. Muốn đổi mô hình thì tạo phòng mới.

Vòng đời phòng: `tạo → đang chạy → tạm dừng → đóng`. Đóng phòng thu hồi mọi token và ngắt tunnel.

---

## 2. Vào phòng bằng cách nào

### Cách chính: landing + link mời + mật khẩu

Mở `http://127.0.0.1:8000/` (hoặc URL tunnel của Host):

1. **Tạo phòng** — trên máy Host (bootstrap chỉ localhost), đặt mật khẩu worker/admin
2. **Tham gia bằng link** — dán URL LAN/`*.trycloudflare.com` + mật khẩu **admin** → dashboard Host đó
   (Host local đã khóa: mở localhost → tab Tham gia tự điền invite)

Sau khi tạo, Host hiện link mời:

```
http://192.168.1.50:8000/join?code=THERMAL-4F2A   (LAN)
https://abc-def.trycloudflare.com/join?code=…      (tunnel)
```

Worker (đóng góp CPU): wizard / `config.json` + NodeAgent — không chỉ mở web.

**Không cần dịch vụ trung gian.** Mỗi máy chọn chế độ Host = một phòng độc lập. Không có Room Directory (§3).

**Web ≠ chia sẻ CPU.** Chỉ mở dashboard = quản trị + chat. Đóng góp tính toán cần **NodeAgent** (outbound).

**Mật khẩu phải gửi qua kênh khác với link.**

CLI Host: ưu tiên `THERMAL_WORKER_PASSWORD` / `THERMAL_ADMIN_PASSWORD`, hoặc không đặt → bootstrap-open (landing). Không ghi plaintext cạnh `server/` trừ `--write-credentials-once` vào `%LOCALAPPDATA%\…\config\`.

### Mã QR — cùng cơ chế, đỡ phải gõ

Host hiện mã QR chứa chính link mời. Đồng nghiệp cầm điện thoại quét rồi gửi lại cho mình, hoặc đọc mã phòng từ màn hình. Không cần dịch vụ nào.

### Tại LAN

Không cần tunnel. Worker dùng `http://<IP-LAN-của-host>:8000`. Host tự phát hiện và hiển thị IP LAN của mình — [`open_firewall.ps1`](../scripts/open_firewall.ps1) đã có logic này.

---

## 3. Vì sao cắt Room Directory

Bản thiết kế đề xuất một dịch vụ mỏng ánh xạ mã phòng → URL tunnel, để người dùng chỉ cần gõ mã thay vì dán link.

| Được | Mất |
|---|---|
| Gõ 12 ký tự thay vì dán một URL | Một dịch vụ hosted phải nuôi, giám sát, vá lỗi |
| | Một điểm hỏng mới nằm ngoài tầm kiểm soát |
| | Mâu thuẫn trực tiếp với tuyên bố "tự host 100%" của chính thiết kế |
| | Một bề mặt tấn công mới (ai cũng tra được mã → URL) |
| | Chi phí vận hành thường xuyên |

**Quyết định: cắt.**

Lợi ích thuần túy là thẩm mỹ, và có cách rẻ hơn để đạt cùng trải nghiệm: dùng **named tunnel** để hostname cố định giữa các lần khởi động, rồi in mã QR trên màn hình host. Người dùng quét là xong — nhanh hơn cả gõ mã, và không cần dịch vụ nào.

Ghi lại quyết định này để sau không ai vô tình thêm lại: [`adr/`](adr/).

---

## 4. Tunnel

### LAN trước, tunnel là ngoại lệ

| | LAN | Tunnel |
|---|---|---|
| Độ trễ | Thấp nhất | +30–100 ms mỗi lượt |
| Phụ thuộc | Không | Cloudflare |
| Bề mặt tấn công | Trong mạng nội bộ | **Internet công cộng** |
| Cài đặt | Mở một cổng tường lửa trên host | Tải và chạy `cloudflared` |
| Khi nào dùng | Mọi máy cùng mạng | Có máy ở mạng khác |

**Mặc định: tunnel tắt.** Người dùng phải chủ động bật và thấy cảnh báo ([06 §3](06-bao-mat-va-quyen-rieng-tu.md#3-phơi-nhiễm-qua-tunnel)).

### Quick tunnel với named tunnel

| | Quick (`trycloudflare.com`) | Named (cần tài khoản) |
|---|---|---|
| Tài khoản Cloudflare | Không | Có |
| Tên miền | Ngẫu nhiên, **đổi mỗi lần khởi động** | Cố định |
| Giới hạn tần suất | Có | Cao hơn nhiều |
| Cam kết dịch vụ | Không | Có |
| Link mời | Phải gửi lại sau mỗi lần khởi động | Gửi một lần dùng mãi |
| Phù hợp | Thử nghiệm, demo một lần | **Sản phẩm dùng thật** |

Mục tiêu của dự án là "bán sản phẩm — dùng thật được", nên **named tunnel là lựa chọn đúng** nếu cần truy cập ngoài mạng. Quick tunnel dùng cho demo một lần thì được, nhưng đừng xây tính năng nào dựa trên tính ổn định của nó.

### Khi tunnel chết

```
Mất tunnel:
  ✅ Phòng LAN vẫn chạy bình thường
  ✅ Worker trên LAN không bị ảnh hưởng
  ❌ Worker ở mạng khác mất kết nối → chuyển sang STALE sau 10s
                                     → job đang giữ chỗ được thu hồi
  → Dashboard: "Mất tunnel — worker trên LAN vẫn hoạt động.
                Bật lại tunnel hoặc chuyển worker sang mạng nội bộ."
  → Tự thử nối lại: 5s, 10s, 20s, 40s… trần 5 phút
```

Cấu trúc dữ liệu quan trọng: worker lưu **cả hai** địa chỉ (URL tunnel và IP LAN) từ lúc `/join`, và tự chuyển sang đường còn lại khi một đường hỏng. Chi tiết nhỏ nhưng loại bỏ hẳn một nhóm sự cố.

### Mạng doanh nghiệp chặn cloudflared

Xảy ra thường xuyên. Đường dự phòng phải luôn có và phải nằm trong tài liệu vận hành:

1. Mọi máy chuyển về cùng mạng LAN, hoặc
2. IT mở một quy tắc chuyển tiếp cổng tới host, hoặc
3. Dùng VPN sẵn có của công ty, hoặc
4. Chấp nhận cụm nhỏ hơn, chỉ gồm máy trong LAN

---

## 5. Đóng gói và cài đặt

### Hai bộ cài

| | Host | Worker |
|---|---|---|
| Dung lượng | ~150 MB (kèm Python nhúng) | ~80 MB (.NET tự chứa) |
| Cần cài trước | Không | Không |
| Quyền | Người dùng thường + tường lửa một lần | Administrator (đọc cảm biến) |
| Thành phần | Engine Python, dashboard, launcher | Agent, sensor, LLM runner |

**Host cài Python nhúng.** Nghe nặng nề, nhưng host là **một máy duy nhất do người triển khai kiểm soát**, còn worker là 9 máy của người khác. Ràng buộc "không cần cài gì" chỉ áp dụng cho worker. Đổi lại, ta giữ được toàn bộ engine Python đang có với 32 test đang xanh, thay vì viết lại sang C#.

### Cấu trúc thư mục

```
%LOCALAPPDATA%\ThermalOrchestrator\
   ├─ bin\           tệp thực thi
   ├─ runtime\       runtime LLM đã tải (worker)
   ├─ models\        tệp mô hình đã tải (worker)
   ├─ data\          telemetry.db, model.pkl, power_model.json (host)
   ├─ config\        settings.json, esg_config.json, room.json
   └─ logs\          server.log, agent.log
```

Đặt trong `%LOCALAPPDATA%` chứ không phải `Program Files`: **cài được mà không cần quyền quản trị**. Agent vẫn cần Administrator lúc *chạy* để đọc cảm biến, nhưng lúc *cài* thì không — bớt được một rào cản đáng kể ở môi trường doanh nghiệp.

### Trình hướng dẫn lần đầu

```
Bước 1  Bạn muốn làm gì?
          ( ) Mở phòng mới (máy này làm chủ)
          ( ) Vào phòng có sẵn

Bước 2  [Chủ]  Tên phòng, mật khẩu, chọn mô hình, ngưỡng, khu vực
        [Phụ]  Dán link mời + mật khẩu

Bước 3  Đang tải thành phần...
          ✅ Runtime suy luận          52 MB   [kiểm tra hash: ok]
          ⏳ Mô hình ngôn ngữ         398 MB   ████████░░  74%
          ⬜ Kiểm tra cảm biến

Bước 4  Kiểm tra
          ✅ Đọc được nhiệt độ CPU     42,3°C
          ⚠️  Không đọc được công suất — ESG sẽ dùng ước lượng
          ✅ Runtime phản hồi           38 token/giây
          ✅ Kết nối tới phòng
```

Bước 4 đáng chú ý: nó chạy đúng phép kiểm tra mà `power_probe.ps1` làm, và **nói ngay cho người dùng biết máy họ đóng góp được vào ESG Tầng nào**. Thà biết ngay lúc cài còn hơn phát hiện khi xuất báo cáo.

---

## 6. Tải thành phần lúc chạy

### Quy trình bắt buộc

```
1. Đọc URL + SHA256 kỳ vọng từ room_config
2. Kiểm tra miền có nằm trong allowed_domains không → không thì HỦY
3. Tải qua HTTPS, hiện tiến độ
4. Tính SHA256 của tệp vừa tải
5. So với hash kỳ vọng
      khớp   → chuyển vào thư mục đích
      lệch   → XÓA, báo lỗi rõ ràng, KHÔNG chạy
6. Chỉ đến bước này mới được thực thi
```

Bước 4–6 là điểm mấu chốt: **kiểm hash trước khi thực thi lần đầu**. Kiểm sau khi chạy là không kiểm.

### Phiên bản + SHA256 đã ghim (ADR-005, 2026-08-01)

Tính bằng `Get-FileHash -Algorithm SHA256` trên máy chốt — **không** sao chép từ chỗ khác khi tái xác minh.

| Thành phần | Nguồn / tên tệp | SHA256 |
|---|---|---|
| Runtime zip | `llama-b10216-bin-win-cpu-x64.zip` ([release b10216](https://github.com/ggml-org/llama.cpp/releases/download/b10216/llama-b10216-bin-win-cpu-x64.zip)) | `CA78DF53654BE907193F2615F590C51960F0A009C09285D1D1A5EFA8B84D69B9` |
| Runtime exe | `llama-server.exe` (trong zip) | `DCC76B45556B0252B353A4693E84376C8A04D2EB44B5BF153EFC18A5556C54E6` |
| Runtime DLL | `llama-server-impl.dll` (trong zip) | `9CC77AC1DE3F90B3BEFA47377BB578EE3E3E3979DF8B39C5EBBC92B92193C513` |
| Mô hình | `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` ([bartowski](https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf)) | `6EB923E7D26E9CEA28811E1A8E852009B21242FB157B26149D3B188F3A8C8653` |

`room_config.runtime_sha256` = hash **zip**; sau giải nén bắt buộc kiểm thêm exe + DLL. Chi tiết quyết định: [ADR-005](adr/ADR-005-llm-runtime.md).

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-b10216-bin-win-cpu-x64.zip
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server.exe
Get-FileHash -Algorithm SHA256 -LiteralPath .\llama-server-impl.dll
Get-FileHash -Algorithm SHA256 -LiteralPath .\Qwen2.5-0.5B-Instruct-Q4_K_M.gguf
```

### Thông điệp khi hash lệch

```
❌ Tệp tải về không khớp chữ ký số dự kiến.

   Tệp:    llama-server.exe
   Nhận:   <hash vừa tính>
   Kỳ vọng: <hash trong room_config / ADR-005>

   Đã xóa tệp. KHÔNG chạy.

   Nguyên nhân có thể: tải hỏng, proxy công ty sửa nội dung,
   hoặc phiên bản trên máy chủ đã đổi.
   Kiểm tra kết nối rồi thử lại. Nếu vẫn lệch, báo quản trị viên.
```

Nói ra được cả nguyên nhân lành tính (proxy công ty chèn nội dung là chuyện có thật) lẫn nguyên nhân nghiêm trọng, mà không hạ thấp mức nghiêm trọng.

### Kho dùng chung trong nội bộ

Với 10 máy tải cùng một tệp 400 MB, nên cân nhắc: host phục vụ luôn tệp mô hình cho worker trong LAN. Tiết kiệm 3,6 GB băng thông ra ngoài và **loại bỏ phụ thuộc vào Internet cho 9 máy phụ** — riêng điểm sau đã đủ để đáng làm trong môi trường doanh nghiệp.

Hash vẫn kiểm y như khi tải từ nguồn ngoài.

---

## 7. Ma trận mạng

Dùng cho tài liệu whitelist gửi IT.

### Host

| Chiều | Cổng | Giao thức | Đích | Bắt buộc |
|---|---|---|---|---|
| Vào | 8000 | TCP | Từ LAN | ✅ |
| Ra | 443 | HTTPS | `github.com`, `huggingface.co` | Chỉ khi tải thành phần |
| Ra | 443 | HTTPS | `api.openweathermap.org` | Tùy chọn (thời tiết) |
| Ra | 7844 | TCP/QUIC | Cloudflare edge | Chỉ khi bật tunnel |

### Worker

| Chiều | Cổng | Giao thức | Đích | Bắt buộc |
|---|---|---|---|---|
| Vào | — | — | **KHÔNG CÓ** | — |
| Ra | 8000 | HTTP | IP LAN của host | ✅ |
| Ra | 443 | HTTPS | URL tunnel của host | Chỉ khi khác mạng |
| Ra | 443 | HTTPS | `github.com`, `huggingface.co` | Chỉ khi tải thành phần |
| Nội bộ | ngẫu nhiên | HTTP | `127.0.0.1` (runtime LLM) | ✅ |

**Dòng "Vào: KHÔNG CÓ" ở worker là điểm bán hàng chính với bộ phận IT.** Không cần quy tắc tường lửa vào, không cần chuyển tiếp cổng, không cần IP tĩnh trên 9 máy. Đây là tính chất đã có sẵn từ PoC ([`HOW_IT_WORKS.md`](../HOW_IT_WORKS.md) §3) và mọi thay đổi sau này phải bảo toàn nó.

Cổng `127.0.0.1` của runtime LLM chỉ nghe trên loopback — không tiếp cận được từ mạng, nhưng vẫn phải khai báo vì EDR sẽ thấy nó.

### 7b. Bản nháp whitelist gửi IT (ADR-005)

> **Trạng thái:** bản nháp — **chưa gửi / chưa có phản hồi IT** tại thời điểm chốt ADR-005. Điền tên tổ chức và gửi trước khi triển khai 9 máy phụ.

**Tiêu đề thư gợi ý:** Yêu cầu whitelist thành phần runtime LLM nội bộ (Thermal Orchestrator)

```
Kính gửi bộ phận IT / An ninh thông tin,

Chúng tôi triển khai PoC "Thermal Orchestrator" trên Windows 10/11 nội bộ
(tối đa ~10 máy). Worker chỉ kết nối ra ngoài (outbound) tới host trong LAN
hoặc tunnel — không mở cổng vào trên máy nhân viên.

Thành phần cần whitelist / loại trừ quét chủ động (EDR):

  Tên tệp:     llama-server.exe  (+ llama-server-impl.dll đi kèm)
  Nguồn:       gói zip llama.cpp release b10216 (win-cpu-x64), MIT
  Mục đích:    suy luận LLM nhỏ (Qwen2.5-0.5B Q4) trên CPU, localhost only
  Quyền:       cùng máy với agent cảm biến (có thể cần Administrator cho cảm biến;
               runtime LLM chỉ nghe 127.0.0.1)
  Kiểm soát:   SHA256 ghim trong cấu hình phòng; lệch hash → không chạy
  Gỡ bỏ:       xóa thư mục cài + dừng tiến trình (xem mục Gỡ cài)

SHA256 (Get-FileHash, máy chốt ADR-005):
  zip:  CA78DF53654BE907193F2615F590C51960F0A009C09285D1D1A5EFA8B84D69B9
  exe:  DCC76B45556B0252B353A4693E84376C8A04D2EB44B5BF153EFC18A5556C54E6
  dll:  9CC77AC1DE3F90B3BEFA47377BB578EE3E3E3979DF8B39C5EBBC92B92193C513

Nếu không thể whitelist exe chưa ký số: phương án dự phòng là
ONNX Runtime GenAI (DLL ký Authenticode Microsoft) — đã chuẩn bị lớp
trừu tượng ILlmRunner trong thiết kế worker.

Xin phản hồi: cho phép whitelist / từ chối / điều kiện bổ sung.
```

---

## 8. Gỡ cài

Phải sạch, và phải nằm trong tài liệu whitelist. IT sẽ hỏi.

```
1. Rời phòng (thu hồi token phía host)
2. Dừng và gỡ đăng ký driver LibreHardwareMonitor
3. Xóa quy tắc tường lửa (chỉ host)
4. Dừng và xóa cloudflared (nếu có)
5. Chạy Uninstall.ps1 — mặc định GIỮ data\
   Xóa data\ cần xác nhận kép: -RemoveData -ConfirmRemoveData
   Interactive: luôn gõ đúng DELETE-ESG (không chấp nhận yes)
6. Xóa khóa registry nếu có đăng ký khởi động cùng Windows
```

**Hỏi trước khi xóa `data\`** — `telemetry.db` chứa nhật ký sự kiện ESG. Mặc định **giữ lại**. `-RemoveData` một mình **không đủ**; interactive cũng phải gõ `DELETE-ESG`.
