# bench_llm — Harness đo LLM (G3)

Công cụ **độc lập**, không phải phần hệ thống. Mục tiêu: thu số liệu để chủ dự án chốt [ADR-005](../../docs/adr/ADR-005-llm-runtime.md). Agent đo và báo cáo; **không** tự chốt ADR.

## Điều kiện tiên quyết

- Windows 10/11 x64, Python 3.10+
- Kết nối mạng lần đầu (tải `llama-server` + GGUF)
- (Khuyến nghị) `publish/NodeAgent/NodeAgent.exe` — harness tự lấy mẫu nhiệt/công suất qua `--test-sensors` (sensor bridge), không cần server
- (Tuỳ chọn) hoặc server + agent ghi vào `server/telemetry.db`
- (Tuỳ chọn ONNX) `pip install onnxruntime-genai`; đặt gói có `genai_config.json` vào `assets/onnx/<id>/`

## Cách chạy

```powershell
# Tải binary + GGUF
powershell -ExecutionPolicy Bypass -File scripts\bench_llm\download_assets.ps1

# Đo llama.cpp (mặc định threads = số nhân − 2)
$env:PYTHONUTF8 = "1"
python scripts\bench_llm\run_bench.py --runtime llama --models all

# Đo cả hai runtime; thử convert ONNX nếu chưa có
python scripts\bench_llm\run_bench.py --runtime all --models all --convert-onnx

# Chỉ định telemetry / node
python scripts\bench_llm\run_bench.py `
  --runtime llama `
  --telemetry-db server\telemetry.db `
  --node DESKTOP-XXX
```

## Đầu ra

| Tệp | Nội dung |
|---|---|
| `results/machine.json` | Cấu hình máy, số threads |
| `results/summary.json` | Mọi hàng số liệu |
| `results/REPORT.md` | Báo cáo + khuyến nghị + nhắc IT |
| `results/vi_samples/` | ≥5 cặp (prompt VI, trả lời) / mô hình — **bạn tự đọc** |
| `results/<runtime>_<model>/raw.json` | Chi tiết từng prompt |

## Ràng buộc đo

- `--threads = max(1, cpu_count - 2)` — chừa nhân cho sensor + người dùng
- Chỉ mô hình Apache-2.0 trong `models.json`
- Không tự chấm điểm tiếng Việt
- Một máy ≠ cả cụm — ghi rõ hạn chế trong báo cáo

## Ollama

Đã loại (xem `docs/09` §2.3). Không có adapter Ollama ở đây.
