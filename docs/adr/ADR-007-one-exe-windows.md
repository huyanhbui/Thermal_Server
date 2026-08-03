# ADR-007: Phát hành Windows x64 bằng một executable bootstrapper

- Trạng thái: Chấp nhận
- Ngày: 2026-08-03

## Bối cảnh

Người vận hành cần một artefact có thể bấm để cài Host và NodeAgent thay vì tự tạo
venv, publish .NET và sao chép nhiều thư mục. Máy worker vẫn phải chỉ kết nối
outbound; model GGUF không thể đi kèm bộ cài vì dung lượng lớn, thay đổi theo phòng
và cần được xác minh hash khi tải.

## Quyết định

Phát hành `ThermalOrchestrator.exe` Windows x64, self-contained, một file. EXE nhúng
payload phiên bản gồm Host Python runtime đã chuẩn bị, NodeAgent đã publish và script
khởi động. Khi chạy, executable chỉ yêu cầu một lần UAC chuẩn rồi giải nén có kiểm tra
đường dẫn vào `%ProgramData%\ThermalOrchestrator\versions\<version>` và ghi
`current.json` nguyên tử.

Payload **không** chứa GGUF. Model được tải khi người vận hành chọn catalog, có resume
và SHA-256 do Host/NodeAgent xác minh. Script đóng gói yêu cầu Python runtime di động
đã có dependency; không được đóng gói một `venv` chỉ liên kết tới Python máy build.

Cấu hình NodeAgent nằm ở
`%ProgramData%\ThermalOrchestrator\agent\config.json`, được DPAPI `LocalMachine`
mã hóa và ACL chỉ Administrators/SYSTEM. Config plaintext cũ cạnh executable được
nhập một lần, sau đó cả bản cũ và bản chuẩn đều được ghi lại không còn trường
`password`.

## Hệ quả

- Không cần Docker, không tắt UAC/Defender/tường lửa và không có cờ bỏ qua bảo mật.
- Một bản cập nhật mới có thể cùng tồn tại với bản cũ; `repair` chỉ thay đúng thư mục
  phiên bản đích. Gỡ cài đặt mặc định giữ dữ liệu và model để tránh mất ledger ESG.
- Bộ build phải cấp Python runtime di động hợp lệ; đây là điều kiện phát hành, không
  phải fallback bí mật sang Python cài sẵn trên máy khách.
- Đường chạy chia sẻ tài nguyên không đổi: tunnel chỉ mang control-plane/WebSocket;
  mỗi NodeAgent chạy job hoàn chỉnh trên CPU/GPU của chính máy đó, không tensor-shard.
