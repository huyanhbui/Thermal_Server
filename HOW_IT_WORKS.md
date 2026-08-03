# Thermal Orchestrator hoạt động như thế nào

## Kiến trúc

```text
Browser admin ── WebSocket / HTTP ──► Host (FastAPI + SQLite)
                                      │
                           dự báo + scheduler + audit
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
          NodeAgent Host        NodeAgent worker A     NodeAgent worker B
          telemetry + LLM       telemetry + LLM        telemetry + LLM
                │                     │                     │
                └──── outbound HTTP ──┴──── outbound HTTP ──┘
```

Host không mở kết nối vào worker. Mỗi NodeAgent chủ động gửi telemetry,
long-poll job và gửi kết quả/chunk chat về Host. Vì vậy worker không cần
inbound listener, NAT rule hay port-forward.

## Vòng đời Host

1. `ThermalOrchestrator.exe` yêu cầu UAC, giải nén payload vào `%ProgramData%\ThermalOrchestrator\versions\<version>` và chạy Host ở cổng 8000.
2. Người dùng tạo hoặc khôi phục phòng. Password verifier và salt ở SQLite; token phiên chỉ nằm trong RAM.
3. Host provision cấu hình NodeAgent cục bộ bằng DPAPI và khởi động agent.
4. Agent join như một worker bình thường. Host chỉ đưa node lên dashboard sau telemetry đầu tiên.
5. NodeAgent sở hữu `llama-server` bằng Job Object. Khi Agent dừng, runtime con bị dừng cùng; không tạo runtime Host LLM thứ hai.

Các trạng thái hiển thị: `missing`, `starting`, `awaiting_uac`, `joining`,
`downloading_model`, `ready` và `error`.

## Telemetry, dự báo và điều phối

Mỗi hai giây Agent đọc CPU temperature, GPU temperature, CPU utilization và package power từ `SensorReader.cs`, rồi gửi `/ingest`. Host ghi mẫu vào SQLite, xây dựng feature window và dự báo nhiệt độ cực đại ba phút.

Scheduler ưu tiên node mát/rảnh hơn nhưng không để hàng đợi đứng im khi chỉ có một máy. Một node READY nhận job tiếp theo ngay khi hoàn tất job trước; khi có nhiều node, các job song song được phân bổ trước khi tái sử dụng node. Node có telemetry stale hoặc runtime LLM chưa READY không nhận chat.

## LLM và streaming

Node chỉ là LLM READY khi báo đúng `model_id`, SHA-256, `generation` và `runtime_id` của model đang chọn. Khi đổi model, Host tăng generation và hạ readiness toàn bộ node; chat mới chỉ được nhận khi một node báo lại đúng generation. Nếu không có node hợp lệ, `/chat` trả `NO_LLM_READY`, không tạo job treo.

NodeAgent đọc stream thật từ llama.cpp, gửi delta đến `/jobs/{job_id}/events`; Host phát `chat_token` qua WebSocket. Kết quả cuối là idempotent theo `job_id + attempt_id`. Nếu node lỗi giữa chừng, scheduler thử node phù hợp kế tiếp một lần, tránh chọn lại node vừa lỗi nếu còn lựa chọn.

## Vì sao không chạy hai llama-server trên một Host

Mỗi runtime Gemma/LLM CPU có thể dùng nhiều luồng và hàng GiB RAM. Hai `llama-server` do hai NodeAgent trên cùng máy sẽ cạnh tranh tài nguyên, làm telemetry chậm và inference trễ. Đây không phải cách chia tải.

Host ngăn Retry/UAC tạo Agent thứ hai. Khi Agent đã chạy, dashboard chỉ chờ telemetry/readiness. Updater dừng đúng Python/NodeAgent nằm dưới thư mục phiên bản Thermal rồi khởi động một cặp Host/Agent mới.

## Tunnel và máy khách

Quick Tunnel tạo URL ngẫu nhiên; Named Tunnel dùng hostname/token ổn định. Host chỉ công bố link mời worker khi probe HTTPS công khai thành công. Link worker dẫn tới `/worker-setup?code=...`, không cấp token admin và không chứa mật khẩu.

Trên máy khách, chạy:

```powershell
.\NodeAgent.exe --setup "https://host.example/worker-setup?code=THERMAL-XXXX"
```

Wizard yêu cầu node name, Host URL và worker password. `localhost` bị từ chối khi dùng trên máy khác, tránh lỗi worker tự kết nối vào chính nó.

## Dữ liệu ESG

ESG có ba lớp độc lập: **ĐO THẬT** (sensor), **SUY RA** (mô hình) và **DỰ PHÒNG** (tham chiếu). Các lớp không được cộng chung. Dashboard không hiển thị con số suy đoán lớn khi thiếu dữ liệu. Audit vận hành tách riêng và không ghi password, token, prompt hoặc nội dung trả lời LLM.

## Chẩn đoán nhanh

| Hiện tượng | Kiểm tra | Cách xử lý |
|---|---|---|
| Host không xuất hiện | local agent, `agent.log` | Chấp nhận UAC, thử lại Host agent, kiểm tra config phòng. |
| Telemetry `n/a` | `NodeAgent.exe --test-sensors` | Chạy Administrator và kiểm tra driver cảm biến. |
| Agent `401/429` | `agent.log` | Kiểm tra phòng/mật khẩu; không mở thêm agent. |
| Chat bị khóa | model/readiness | Chờ đúng model READY hoặc chọn model nhỏ hơn. |
| Máy chậm | Task Manager | Chỉ giữ một NodeAgent và một llama-server trên Host. |
| Không có link tunnel | tunnel state | Bật tunnel bằng admin, chờ `READY`, kiểm tra Internet. |
| Worker không join LAN | URL/firewall | Dùng IP LAN Host, không dùng `localhost`, mở TCP 8000 trên Host. |

## Nhật ký và dữ liệu

- Host data: `%ProgramData%\ThermalOrchestrator\shared`
- Agent config DPAPI: `%ProgramData%\ThermalOrchestrator\agent\config.json`
- Agent log: cạnh `NodeAgent.exe` trong phiên bản đang chạy
- Audit CSV: endpoint admin `/api/audit.csv`

Không chỉnh trực tiếp config đã mã hóa hoặc xóa SQLite khi Host đang chạy.
