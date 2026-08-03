# Thermal Orchestrator

Tiếng Việt | [English](README.en.md)

Thermal Orchestrator là PoC Windows điều phối tải AI theo nhiệt độ và công
suất thật của nhiều máy. Host lưu telemetry, dự báo nhiệt, chọn node phù hợp
và truyền token chat qua WebSocket. Mỗi worker chỉ tạo kết nối outbound về
Host; worker không mở cổng lắng nghe.

## Những gì chạy thật

- `ThermalOrchestrator.exe`: Host tự chứa Python runtime, server và NodeAgent.
- `NodeAgent.exe`: đọc cảm biến CPU/GPU/công suất, nhận job và chạy llama.cpp.
- SQLite: lưu telemetry, audit vận hành và dữ liệu ESG tách theo nguồn.
- Chat LLM: chỉ dispatch đến node báo `READY` với đúng model, hash, generation
  và runtime identity.
- Tunnel Cloudflare: Quick Tunnel dùng thử hoặc Named Tunnel có hostname ổn
  định. Link chỉ được hiển thị sau khi probe HTTPS công khai thành công.

## Chạy nhanh bằng một EXE

1. Tải [ThermalOrchestrator.exe](publish/ThermalOrchestrator/ThermalOrchestrator.exe).
2. Nhấp đúp EXE và chấp nhận UAC. Lần đầu nó giải nén payload vào
   `%ProgramData%\ThermalOrchestrator\versions` rồi mở Host tại
   `http://127.0.0.1:8000`.
3. Trên landing page, chọn **Tạo phòng trên máy này**. Đặt riêng mật khẩu
   worker và admin, tối thiểu 12 ký tự Unicode.
4. Host tự khởi động NodeAgent cục bộ. Chờ trạng thái Host chuyển sang
   `READY`; lần đầu model có thể cần vài phút để tải/khởi động.
5. Đăng nhập admin, chọn model và gửi chat. Nút gửi chỉ hoạt động khi có node
   đúng model đang `READY`.

Để cập nhật, chạy lại EXE mới với tham số:

```powershell
.\ThermalOrchestrator.exe --update
```

Updater yêu cầu UAC, chỉ dừng Python/NodeAgent nằm trong thư mục phiên bản của
Thermal Orchestrator, cài payload mới và khởi động lại Host. Không dùng
Task Manager để chạy thêm NodeAgent khi Host đã có agent: một Host chỉ nên có
một NodeAgent cục bộ và một `llama-server` con của agent đó.

## Thêm máy worker

Từ dashboard admin, sao chép **Link tham gia máy khách** (không phải link
đăng nhập admin) và chuyển cùng `NodeAgent.exe` cho máy worker.

Trên worker Windows:

```powershell
.\NodeAgent.exe --setup "https://host.example/worker-setup?code=THERMAL-XXXX"
```

Wizard yêu cầu tên node duy nhất, URL Host LAN/tunnel và mật khẩu worker ở ô
ẩn. Nó từ chối `localhost` trên máy khác, ghi cấu hình đã mã hóa DPAPI theo
máy và tự chạy agent. Chấp nhận UAC để đọc cảm biến. Worker không cần mở cổng
inbound hoặc port-forward.

Với LAN, nhập URL dạng `http://192.168.x.x:8000`. Mở firewall TCP 8000 trên
Host nếu Windows Firewall đang chặn kết nối LAN.

## Tunnel và link ngoài Internet

Đăng nhập admin, vào cấu hình tunnel và chọn:

- **Quick**: URL `trycloudflare.com` ngẫu nhiên, chỉ dùng thử nghiệm.
- **Named**: cần hostname và Cloudflare token, phù hợp nghiệm thu ổn định.

Tunnel chỉ bật được khi cả hai mật khẩu phòng dài tối thiểu 12 ký tự. Sau khi
trạng thái là `READY`, dashboard có link worker để sao chép. Không gửi mật
khẩu trong link; worker vẫn nhập mật khẩu trong wizard.

## Kiểm tra cảm biến và tiến trình

Mở PowerShell Administrator:

```powershell
.\NodeAgent.exe --test-sensors
```

Ví dụ kết quả hợp lệ gồm CPU/GPU temperature, CPU utilization và power. Nếu
giá trị là `n/a`, kiểm tra UAC, driver LibreHardwareMonitor và phần cứng; đừng
coi dữ liệu cũ là dữ liệu live.

Mỗi Host hoạt động bình thường có đúng:

1. Một `python.exe` thuộc payload Thermal.
2. Một `NodeAgent.exe` thuộc cùng phiên bản payload.
3. Tối đa một `llama-server.exe`, với parent là NodeAgent.

Hai `llama-server` song song trên cùng Host không phải cơ chế chia tải; chúng
tranh CPU/RAM và cần được xử lý bằng update/restart Host, không phải mở thêm
agent.

## Chạy từ mã nguồn

Yêu cầu: Windows 10/11, Python 3.11+, .NET 8 SDK. Từ thư mục repo:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python server.py
```

Mở `http://127.0.0.1:8000`. Để publish agent và EXE Host:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\publish_agent.ps1
powershell -ExecutionPolicy Bypass -File scripts\publish_orchestrator.ps1 `
  -PythonRuntimeDir artifacts\python-runtime -Version dev
```

## Kiểm thử

```powershell
server\.venv\Scripts\python.exe -m pytest server\tests\ -q
dotnet test agent\NodeAgent.Tests\NodeAgent.Tests.csproj -c Release
```

Kết quả hiện được xác minh: Python `351/351`, .NET `55/55`.

Xem [HOW_IT_WORKS.md](HOW_IT_WORKS.md) để hiểu luồng hoạt động và xử lý sự
cố; xem [BÁO CÁO TỔNG QUAN DỰ ÁN.md](BÁO%20CÁO%20TỔNG%20QUAN%20DỰ%20ÁN.md)
để có tổng quan sản phẩm, phạm vi và giới hạn PoC.
