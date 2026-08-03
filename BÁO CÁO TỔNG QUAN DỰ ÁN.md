# Báo cáo tổng quan dự án Thermal Orchestrator

Tiếng Việt | [English](PROJECT_OVERVIEW.en.md)

## 1. Mục tiêu

Thermal Orchestrator là Proof of Concept điều phối tải AI phân tán trên cụm
Windows theo nhiệt độ và công suất thực. Mục tiêu không phải chỉ hiển thị
dashboard: hệ thống phải thu telemetry thật, dự báo nguy cơ quá nhiệt, chọn
node phù hợp cho job/chat LLM và để lại audit vận hành có thể kiểm tra.

## 2. Thành phần

| Thành phần | Công nghệ | Vai trò |
|---|---|---|
| Host | Python, FastAPI, SQLite | Phòng, xác thực, telemetry, scheduler, ESG, WebSocket và tunnel. |
| NodeAgent | C#/.NET 8 | Cảm biến, rejoin outbound, lấy job, llama.cpp streaming. |
| Runtime LLM | llama.cpp | Chạy model GGUF trên CPU, thuộc vòng đời NodeAgent. |
| Dashboard | HTML/CSS/JS một file | Landing, đăng nhập, vận hành cụm, chat và cấu hình. |
| Bootstrapper | .NET single-file EXE | Cài/cập nhật payload Host + Agent với UAC. |

## 3. Luồng giá trị

1. Admin tạo phòng và đặt mật khẩu worker/admin.
2. Host tự chạy NodeAgent cục bộ; máy Host trở thành node thật sau telemetry
   đầu tiên.
3. Worker ngoài cụm dùng link setup, nhập mật khẩu worker và chủ động join
   về Host.
4. Host dự báo nhiệt, loại node stale/không READY và dispatch job đến node
   tốt nhất. Nếu chỉ có một node hợp lệ, node đó vẫn tiếp tục xử lý hàng đợi.
5. NodeAgent stream token từ llama.cpp về Host; browser nhận token qua
   WebSocket và nhận kết quả cuối theo attempt id.

## 4. Bất biến kỹ thuật

- Worker chỉ outbound; không có listener inbound trên máy khách.
- Danh tính node lấy từ token, không tin node name trong query/body.
- Số đo sensor, số suy ra và dự phòng ESG không bị cộng lẫn.
- Chat chỉ chạy trên model/hash/generation/runtime đã READY chính xác.
- Password, token, prompt và câu trả lời LLM không được ghi vào audit/log.
- Một Host chỉ chạy một NodeAgent cục bộ và một llama-server con của agent.

## 5. Kết quả xác minh hiện tại

- Sensor trên Host: CPU `40°C`, GPU `39°C`, CPU utilization `16%`, power
  `23.3 W` trong lần kiểm tra gần nhất.
- Python test: `351/351` xanh.
- NodeAgent .NET test: `55/55` xanh.
- Update EXE đã nghiệm thu từ payload cũ sang `2026.08.03.7`: Host, Agent và
  llama-server sau update đều thuộc đúng phiên bản mới.
- Agent có backoff join chung, tránh hai vòng telemetry/job luân phiên gây
  `401/429` và làm node offline.

## 6. Phạm vi và giới hạn PoC

PoC hỗ trợ Host cục bộ, worker Windows, LAN và Cloudflare Tunnel. Quick Tunnel
phù hợp demo; Named Tunnel cần token/hostname Cloudflare để nghiệm thu ổn
định. Việc thử nhiều máy thật, Named Tunnel và soak test dài cần Internet,
Cloudflare credential cùng máy worker thứ hai.

Model CPU nhỏ như Gemma 3B/E2B phù hợp kiểm thử luồng và tài nguyên. Model
30B có thể dùng để stress test nhưng không chứng minh “CPU là đủ” cho mọi nhu
cầu: tốc độ và RAM phụ thuộc lượng RAM, số luồng và định dạng quantization.

## 7. Cách chạy

Hướng dẫn vận hành đầy đủ nằm ở [README.md](README.md). Với người dùng cuối,
chạy `ThermalOrchestrator.exe`, chấp nhận UAC, tạo phòng và chờ Host agent
READY. Máy khách chạy `NodeAgent.exe --setup <worker-link>`; không sao chép
`localhost` sang máy khác.

## 8. Hướng phát triển

- Nghiệm thu Named Tunnel và worker vật lý thứ hai.
- Smoke test đầy đủ catalog model trên phần cứng mục tiêu.
- Soak test bốn giờ, kiểm tra reconnect và không còn tiến trình mồ côi.
- Ký mã EXE và hoàn thiện luồng phát hành cho môi trường doanh nghiệp.
