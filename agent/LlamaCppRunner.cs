// llama.cpp b10216 runner: download+verify → spawn llama-server on 127.0.0.1
// only → OpenAI-compatible /v1/chat/completions. --log-disable (docs/06 §4).
// Hash exe/dll/model immediately before EVERY Process.Start (docs/10 §6).
// Model filename comes from room_config (ADR-006) — never hardcode one GGUF.
using System.Diagnostics;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace NodeAgent;

public sealed class LlamaCppRunner : ILlmRunner, IDisposable
{
    private readonly string _workDir;
    private readonly Action<string> _log;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private Process? _proc;
    private HttpClient? _client;
    private WindowsProcessJob? _job;
    private int _port = 8080;
    private bool _ready;
    private string? _modelSha256;
    private string? _exeSha256;
    private string? _dllSha256;
    private string? _activeModelPath;
    private string? _activeModelId;
    private string? _activeRuntimeId;
    private long _activeModelGeneration;

    /// <summary>
    /// Test seam: sau ShutdownUnlocked khi đổi model, bỏ download/spawn.
    /// </summary>
    internal static bool SkipArtifactFetchForTests { get; set; }

    /// <summary>
    /// Test seam: gọi sau ProbeFreeLoopbackPort — có thể chiếm cổng để buộc retry.
    /// </summary>
    internal static Action<int>? AfterPortProbeForTests { get; set; }

    public LlamaCppRunner(string? workDir = null, Action<string>? log = null)
    {
        _workDir = workDir ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ThermalOrchestrator", "llm");
        _log = log ?? (_ => { });
    }

    public string? ActiveModelId => _activeModelId;
    public string? ActiveModelSha256 => _modelSha256;
    public string? ActiveRuntimeId => _activeRuntimeId;
    public long ActiveModelGeneration => _activeModelGeneration;
    public bool IsRuntimeReady => _ready && _proc is { HasExited: false };

    /// <summary>
    /// Gợi ý cổng loopback trống bằng bind ngắn.
    /// Không giữ reservation sau Stop — caller phải retry khi address-in-use.
    /// </summary>
    internal static int ProbeFreeLoopbackPort(
        IEnumerable<int>? occupiedPorts = null)
    {
        var blocked = occupiedPorts is null
            ? new HashSet<int>()
            : occupiedPorts.ToHashSet();
        for (var attempt = 0; attempt < 8; attempt++)
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var port = ((IPEndPoint)listener.LocalEndpoint).Port;
            listener.Stop(); // Port không còn reserved sau Stop
            if (!blocked.Contains(port))
                return port;
        }
        throw new InvalidOperationException(
            "Không tìm được cổng loopback trống.");
    }

    /// <summary>Alias tương thích — không claim reservation sau Stop.</summary>
    internal static int AllocateLoopbackPort(
        IEnumerable<int>? occupiedPorts = null)
        => ProbeFreeLoopbackPort(occupiedPorts);

    /// <summary>Kiểm tra cổng loopback còn bind được không (sau probe).</summary>
    internal static bool IsLoopbackPortFree(int port)
    {
        try
        {
            using var listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
            listener.Stop();
            return true;
        }
        catch (SocketException)
        {
            return false;
        }
    }

    /// <summary>Timeout tổng một lượt khởi động llama-server.</summary>
    internal static readonly TimeSpan OverallStartupTimeout =
        TimeSpan.FromSeconds(30);

    /// <summary>Timeout từng health probe.</summary>
    internal static readonly TimeSpan HealthProbeTimeout =
        TimeSpan.FromSeconds(1);

    /// <summary>Backoff ngắn khi chờ health llama-server.</summary>
    internal static TimeSpan StartupBackoffDelay(int attempt) =>
        TimeSpan.FromMilliseconds(200 * Math.Pow(2, Math.Clamp(attempt, 0, 4)));

    /// <summary>Seam test: thay Process.Start.</summary>
    internal static Func<ProcessStartInfo, Process?>? ProcessStartOverride { get; set; }

    /// <summary>Dọn Process/HttpClient idempotent — không dispose hai lần.</summary>
    internal static void CleanupServerState(
        ref Process? proc, ref HttpClient? client)
    {
        var c = Interlocked.Exchange(ref client, null);
        try { c?.Dispose(); }
        catch (ObjectDisposedException) { /* idempotent */ }

        var p = Interlocked.Exchange(ref proc, null);
        if (p is null) return;
        try
        {
            if (!p.HasExited)
            {
                try { p.Kill(entireProcessTree: true); }
                catch { /* process gone */ }
            }
        }
        catch (InvalidOperationException) { /* already disposed */ }
        try { p.Dispose(); }
        catch (ObjectDisposedException) { /* idempotent */ }
    }

    /// <summary>Overload tiện khi không cần null hóa biến ngoài.</summary>
    internal static void CleanupServerState(Process? proc, HttpClient? client)
    {
        CleanupServerState(ref proc, ref client);
    }

    public async Task<bool> EnsureReadyAsync(RoomConfig cfg, IProgress<double>? progress)
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            return await EnsureReadyUnlockedAsync(cfg, progress).ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task<bool> EnsureReadyUnlockedAsync(RoomConfig cfg, IProgress<double>? progress)
    {
        if (string.IsNullOrWhiteSpace(cfg.ModelUrl)
            || string.IsNullOrWhiteSpace(cfg.ModelSha256)
            || string.IsNullOrWhiteSpace(cfg.RuntimeUrl)
            || string.IsNullOrWhiteSpace(cfg.RuntimeSha256))
        {
            _log("[LLM] room_config missing URL/SHA256 — skip runtime");
            return false;
        }
        if (string.IsNullOrWhiteSpace(cfg.LlamaServerExeSha256)
            || string.IsNullOrWhiteSpace(cfg.LlamaServerImplDllSha256))
        {
            _log("[LLM] room_config missing exe/dll hashes — skip runtime");
            return false;
        }

        string modelFile;
        try
        {
            modelFile = cfg.ResolveModelFilename();
        }
        catch (Exception ex)
        {
            _log($"[LLM] {ex.Message}");
            return false;
        }
        var modelsDir = Path.Combine(_workDir, "models");
        Directory.CreateDirectory(modelsDir);
        var modelPath = Path.GetFullPath(Path.Combine(modelsDir, modelFile));
        var modelsRoot = Path.GetFullPath(modelsDir)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!modelPath.StartsWith(modelsRoot, StringComparison.OrdinalIgnoreCase))
        {
            _log("[LLM] model path escaped models dir — rejected");
            return false;
        }
        var sameModel = _ready
            && string.Equals(_modelSha256, cfg.ModelSha256,
                StringComparison.OrdinalIgnoreCase)
            && string.Equals(_activeModelPath, modelPath,
                StringComparison.OrdinalIgnoreCase)
            && _proc is { HasExited: false };

        if (sameModel)
        {
            progress?.Report(1.0);
            return true;
        }

        // Đổi model → dừng server cũ trước khi tải/spawn.
        // Đã giữ _gate → phải ShutdownUnlockedAsync (ShutdownAsync deadlock).
        if (_ready || _proc is { HasExited: false })
        {
            _log($"[LLM] đổi model → {_activeModelId ?? "?"} → "
                + $"{cfg.ModelId ?? modelFile}");
            await ShutdownUnlockedAsync().ConfigureAwait(false);
        }

        if (SkipArtifactFetchForTests)
        {
            _modelSha256 = cfg.ModelSha256;
            _exeSha256 = cfg.LlamaServerExeSha256;
            _dllSha256 = cfg.LlamaServerImplDllSha256;
            _activeModelPath = modelPath;
            _activeModelId = cfg.ModelId;
            _activeRuntimeId = cfg.RuntimeId;
            _activeModelGeneration = cfg.ModelGeneration;
            progress?.Report(1.0);
            return false;
        }

        _modelSha256 = cfg.ModelSha256;
        _exeSha256 = cfg.LlamaServerExeSha256;
        _dllSha256 = cfg.LlamaServerImplDllSha256;

        Directory.CreateDirectory(_workDir);
        var runtimeDir = Path.Combine(_workDir, "runtime");
        var zipPath = Path.Combine(_workDir, "llama-runtime.zip");

        var prog = progress ?? new Progress<double>(_ => { });
        // 0..0.45 runtime zip, 0.45..0.9 model, 0.9..1.0 start
        if (FindFile(runtimeDir, "llama-server.exe") is null)
        {
            await Downloader.DownloadAndVerifyAsync(
                cfg.RuntimeUrl!, zipPath, cfg.RuntimeSha256!,
                cfg.AllowedDomains,
                new Progress<double>(p => prog.Report(p * 0.45)));
            if (Directory.Exists(runtimeDir))
                Directory.Delete(runtimeDir, recursive: true);
            Directory.CreateDirectory(runtimeDir);
            ZipFile.ExtractToDirectory(zipPath, runtimeDir);
            var exe = FindFile(runtimeDir, "llama-server.exe");
            var dll = FindFile(runtimeDir, "llama-server-impl.dll");
            if (exe is null || dll is null)
                throw new DownloadRejectedException(
                    "Zip runtime thiếu llama-server.exe hoặc llama-server-impl.dll.");
            // Post-extract pin (ADR-005) — StartServerAsync will re-verify too.
            await Downloader.VerifySha256OrDeleteAsync(exe, _exeSha256!);
            await Downloader.VerifySha256OrDeleteAsync(dll, _dllSha256!);
        }
        else
        {
            prog.Report(0.45);
        }

        if (!File.Exists(modelPath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(modelPath)!);
            await Downloader.DownloadAndVerifyAsync(
                cfg.ModelUrl!, modelPath, cfg.ModelSha256!,
                cfg.AllowedDomains,
                new Progress<double>(p => prog.Report(0.45 + p * 0.45)));
        }
        else
        {
            await Downloader.VerifySha256OrDeleteAsync(modelPath, cfg.ModelSha256!);
            if (!File.Exists(modelPath))
            {
                await Downloader.DownloadAndVerifyAsync(
                    cfg.ModelUrl!, modelPath, cfg.ModelSha256!,
                    cfg.AllowedDomains,
                    new Progress<double>(p => prog.Report(0.45 + p * 0.45)));
            }
            else
                prog.Report(0.9);
        }

        await StartServerAsync(runtimeDir, modelPath);
        _activeModelPath = modelPath;
        _activeModelId = cfg.ModelId;
        _activeRuntimeId = cfg.RuntimeId;
        _activeModelGeneration = cfg.ModelGeneration;
        prog.Report(1.0);
        _ready = true;
        return true;
    }

    private static string? FindFile(string root, string name)
    {
        if (!Directory.Exists(root))
            return null;
        return Directory.EnumerateFiles(root, name, SearchOption.AllDirectories)
            .FirstOrDefault();
    }

    /// <summary>
    /// Verify SHA256 of exe, dll, and model — then spawn. Call before every start.
    /// </summary>
    internal static async Task VerifyArtifactsBeforeSpawnAsync(
        string runtimeDir, string modelPath,
        string exeSha256, string dllSha256, string modelSha256,
        CancellationToken ct = default)
    {
        var exe = FindFile(runtimeDir, "llama-server.exe")
            ?? throw new DownloadRejectedException(
                "Không tìm thấy llama-server.exe — không chạy.");
        var dll = FindFile(runtimeDir, "llama-server-impl.dll")
            ?? throw new DownloadRejectedException(
                "Không tìm thấy llama-server-impl.dll — không chạy.");
        if (!File.Exists(modelPath))
            throw new DownloadRejectedException(
                "Không tìm thấy model GGUF — không chạy.");
        await Downloader.VerifySha256OrDeleteAsync(exe, exeSha256, ct);
        await Downloader.VerifySha256OrDeleteAsync(dll, dllSha256, ct);
        await Downloader.VerifySha256OrDeleteAsync(modelPath, modelSha256, ct);
    }

    private async Task StartServerAsync(string runtimeDir, string modelPath)
    {
        if (string.IsNullOrWhiteSpace(_exeSha256)
            || string.IsNullOrWhiteSpace(_dllSha256)
            || string.IsNullOrWhiteSpace(_modelSha256))
        {
            throw new InvalidOperationException(
                "Thiếu hash ghim — không spawn llama-server.");
        }

        await ShutdownUnlockedAsync();
        await VerifyArtifactsBeforeSpawnAsync(
            runtimeDir, modelPath, _exeSha256!, _dllSha256!, _modelSha256!);

        var exe = FindFile(runtimeDir, "llama-server.exe")
            ?? throw new InvalidOperationException(
                "llama-server.exe missing after verify");

        Exception? last = null;
        using var overallCts = new CancellationTokenSource(OverallStartupTimeout);
        for (var startupAttempt = 0; startupAttempt < 3; startupAttempt++)
        {
            overallCts.Token.ThrowIfCancellationRequested();
            if (startupAttempt > 0)
            {
                var delay = StartupBackoffDelay(startupAttempt - 1);
                _log($"[LLM] retrying startup after {delay.TotalMilliseconds:F0}ms");
                await Task.Delay(delay, overallCts.Token);
            }

            // Probe cổng — không giữ reservation sau Stop; retry nếu bind fail.
            _port = ProbeFreeLoopbackPort();
            AfterPortProbeForTests?.Invoke(_port);
            var threads = Math.Max(1, Environment.ProcessorCount - 2);
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments =
                    $"--host 127.0.0.1 --port {_port} " +
                    $"--model \"{modelPath}\" --threads {threads} --log-disable",
                WorkingDirectory = Path.GetDirectoryName(exe)!,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            Process? proc = null;
            HttpClient? client = null;
            try
            {
                if (!IsLoopbackPortFree(_port))
                {
                    throw new InvalidOperationException(
                        "address already in use (port bị chiếm sau probe)");
                }
                proc = ProcessStartOverride is not null
                    ? ProcessStartOverride(psi)
                    : Process.Start(psi);
                if (proc is null)
                {
                    last = new InvalidOperationException(
                        "Không khởi động được llama-server");
                    continue;
                }
                _ = Task.Run(() => Drain(proc.StandardOutput));
                _ = Task.Run(() => Drain(proc.StandardError));

                // Client health: timeout ngắn per-probe qua CTS riêng
                client = new HttpClient
                {
                    BaseAddress = new Uri($"http://127.0.0.1:{_port}"),
                    Timeout = OverallStartupTimeout,
                };

                if (await WaitForHealthAsync(proc, client, overallCts.Token))
                {
                    _proc = proc;
                    _client = client;
                    _job = WindowsProcessJob.TryAssign(proc, _log);
                    proc = null;
                    client = null;
                    _log($"[LLM] llama-server ready on 127.0.0.1:{_port}");
                    return;
                }
                last = new TimeoutException(
                    "llama-server không sẵn sàng trong 30s");
            }
            catch (OperationCanceledException) when (overallCts.IsCancellationRequested)
            {
                last = new TimeoutException(
                    "llama-server không sẵn sàng trong 30s (overall timeout)");
                CleanupServerState(ref proc, ref client);
                break;
            }
            catch (Exception ex)
            {
                last = ex;
                var msg = ex.Message ?? "";
                // address-in-use / early-exit → cleanup rồi thử cổng khác
                if (msg.Contains("address", StringComparison.OrdinalIgnoreCase)
                    || msg.Contains("in use", StringComparison.OrdinalIgnoreCase)
                    || msg.Contains("thoát sớm", StringComparison.OrdinalIgnoreCase))
                {
                    _log($"[LLM] startup error (retry): {ex.GetType().Name}");
                }
            }

            CleanupServerState(ref proc, ref client);
        }

        throw last ?? new InvalidOperationException(
            "Không khởi động được llama-server sau nhiều lần thử");
    }

    private async Task<bool> WaitForHealthAsync(
        Process proc, HttpClient client, CancellationToken overallCt)
    {
        while (!overallCt.IsCancellationRequested)
        {
            if (proc.HasExited)
            {
                throw new InvalidOperationException(
                    $"llama-server thoát sớm (code {proc.ExitCode})");
            }
            try
            {
                using var probeCts = CancellationTokenSource.CreateLinkedTokenSource(
                    overallCt);
                probeCts.CancelAfter(HealthProbeTimeout);
                using var r = await client.GetAsync("/health", probeCts.Token)
                    .ConfigureAwait(false);
                if (r.IsSuccessStatusCode)
                    return true;
            }
            catch (OperationCanceledException) when (overallCt.IsCancellationRequested)
            {
                return false;
            }
            catch
            {
                /* still starting hoặc probe timeout */
            }
            try
            {
                await Task.Delay(StartupBackoffDelay(0), overallCt)
                    .ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }
        return false;
    }

    private static void Drain(StreamReader r)
    {
        try
        {
            while (!r.EndOfStream)
                r.ReadLine();
        }
        catch { /* process gone */ }
    }

    /// <summary>
    /// Tạo request tương thích Qwen: tắt thinking để câu trả lời không rỗng
    /// trong trường <c>reasoning_content</c>. Dùng chung cho stream và non-stream.
    /// </summary>
    internal static string BuildCompletionRequest(string prompt, GenParams p,
        bool stream)
        => JsonSerializer.Serialize(new
        {
            messages = new[] { new { role = "user", content = prompt } },
            max_tokens = p.MaxTokens,
            temperature = p.Temperature,
            stream,
            chat_template_kwargs = new { enable_thinking = false },
        });

    /// <summary>Đọc completion chuẩn llama.cpp, ưu tiên content rồi reasoning_content.</summary>
    internal static LlmResult ParseCompletionResponse(string json,
        double fallbackElapsedMs = 0)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var message = root.GetProperty("choices")[0].GetProperty("message");
        var content = StringProperty(message, "content");
        var reply = !string.IsNullOrWhiteSpace(content) ? content
            : StringProperty(message, "reasoning_content") ?? "";
        var (tin, tout, estimated) = ParseUsage(root);
        var (promptMs, predictMs) = ParseTimings(root);
        // Khi runtime cũ không đưa timings, chỉ giữ tổng wall-time thực đo được;
        // tuyệt đối không chia tỷ lệ giả giữa prompt/predict.
        if (promptMs is null && predictMs is null)
            predictMs = fallbackElapsedMs;
        return new LlmResult(reply, tin, tout, promptMs ?? 0,
            predictMs ?? 0, estimated);
    }

    public async Task<LlmResult> GenerateAsync(
        string prompt, GenParams p, CancellationToken ct,
        Func<string, Task>? onDelta = null)
    {
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (!_ready || _client is null)
                throw new InvalidOperationException("LLM runtime chưa sẵn sàng");

            var stream = onDelta is not null;
            var json = BuildCompletionRequest(prompt, p, stream);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            var t0 = Stopwatch.StartNew();
            using var request = new HttpRequestMessage(HttpMethod.Post,
                "/v1/chat/completions") { Content = content };
            using var resp = await _client.SendAsync(request,
                stream ? HttpCompletionOption.ResponseHeadersRead
                    : HttpCompletionOption.ResponseContentRead, ct).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode)
                throw new InvalidOperationException(
                    $"llama-server HTTP {(int)resp.StatusCode}");
            if (!stream)
            {
                var text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                t0.Stop();
                return ParseCompletionResponse(text, t0.Elapsed.TotalMilliseconds);
            }
            return await ReadStreamingResponseAsync(resp, onDelta!, t0, ct)
                .ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    private static async Task<LlmResult> ReadStreamingResponseAsync(
        HttpResponseMessage response, Func<string, Task> onDelta, Stopwatch elapsed,
        CancellationToken ct)
    {
        var text = new StringBuilder();
        int? tin = null;
        int? tout = null;
        double? promptMs = null;
        double? predictMs = null;
        await using var stream = await response.Content.ReadAsStreamAsync(ct)
            .ConfigureAwait(false);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        while (await reader.ReadLineAsync(ct).ConfigureAwait(false) is { } line)
        {
            if (!line.StartsWith("data:", StringComparison.Ordinal))
                continue;
            var payload = line[5..].Trim();
            if (payload == "[DONE]") break;
            using var doc = JsonDocument.Parse(payload);
            var root = doc.RootElement;
            if (TryReadDelta(root, out var delta) && delta.Length > 0)
            {
                text.Append(delta);
                await onDelta(delta).ConfigureAwait(false);
            }
            var usage = ParseUsage(root);
            tin ??= usage.TokensIn;
            tout ??= usage.TokensOut;
            var timings = ParseTimings(root);
            promptMs ??= timings.PromptMs;
            predictMs ??= timings.PredictMs;
        }
        elapsed.Stop();
        return new LlmResult(text.ToString(), tin, tout, promptMs ?? 0,
            predictMs ?? elapsed.Elapsed.TotalMilliseconds,
            tin is null || tout is null);
    }

    private static bool TryReadDelta(JsonElement root, out string delta)
    {
        delta = "";
        if (!root.TryGetProperty("choices", out var choices)
            || choices.ValueKind != JsonValueKind.Array || choices.GetArrayLength() == 0)
            return false;
        var choice = choices[0];
        if (!choice.TryGetProperty("delta", out var part)
            || part.ValueKind != JsonValueKind.Object)
            return false;
        delta = StringProperty(part, "content")
            ?? StringProperty(part, "reasoning_content") ?? "";
        return true;
    }

    private static string? StringProperty(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static (int? TokensIn, int? TokensOut, bool Estimated) ParseUsage(
        JsonElement root)
    {
        if (!root.TryGetProperty("usage", out var usage)
            || usage.ValueKind != JsonValueKind.Object)
            return (null, null, true);
        int? tin = usage.TryGetProperty("prompt_tokens", out var pi)
            && pi.TryGetInt32(out var inValue) ? inValue : null;
        int? tout = usage.TryGetProperty("completion_tokens", out var po)
            && po.TryGetInt32(out var outValue) ? outValue : null;
        return (tin, tout, tin is null || tout is null);
    }

    private static (double? PromptMs, double? PredictMs) ParseTimings(JsonElement root)
    {
        if (!root.TryGetProperty("timings", out var timings)
            || timings.ValueKind != JsonValueKind.Object)
            return (null, null);
        double? prompt = timings.TryGetProperty("prompt_ms", out var p)
            && p.TryGetDouble(out var promptValue) ? promptValue : null;
        double? predict = timings.TryGetProperty("predicted_ms", out var q)
            && q.TryGetDouble(out var predictValue) ? predictValue : null;
        return (prompt, predict);
    }

    public async Task ShutdownAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            await ShutdownUnlockedAsync().ConfigureAwait(false);
        }
        finally
        {
            _gate.Release();
        }
    }

    private Task ShutdownUnlockedAsync()
    {
        _ready = false;
        var client = _client;
        var proc = _proc;
        var job = _job;
        _client = null;
        _proc = null;
        _job = null;
        job?.Dispose();
        CleanupServerState(ref proc, ref client);
        return Task.CompletedTask;
    }

    public async Task RestartAsync(RoomConfig cfg)
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            _log("[LLM] restarting runtime after timeout/hang");
            if (!string.IsNullOrWhiteSpace(cfg.ModelSha256))
                _modelSha256 = cfg.ModelSha256;
            if (!string.IsNullOrWhiteSpace(cfg.LlamaServerExeSha256))
                _exeSha256 = cfg.LlamaServerExeSha256;
            if (!string.IsNullOrWhiteSpace(cfg.LlamaServerImplDllSha256))
                _dllSha256 = cfg.LlamaServerImplDllSha256;
            var runtimeDir = Path.Combine(_workDir, "runtime");
            var modelFile = cfg.ResolveModelFilename();
            var modelsDir = Path.Combine(_workDir, "models");
            var modelPath = Path.GetFullPath(Path.Combine(modelsDir, modelFile));
            var modelsRoot = Path.GetFullPath(modelsDir)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            if (!modelPath.StartsWith(modelsRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException(
                    "model path thoát khỏi thư mục models");
            await StartServerAsync(runtimeDir, modelPath).ConfigureAwait(false);
            _activeModelPath = modelPath;
            _activeModelId = cfg.ModelId;
            _activeRuntimeId = cfg.RuntimeId;
            _activeModelGeneration = cfg.ModelGeneration;
            _ready = true;
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// Seam test: vòng spawn+health với ProcessStartOverride, không cần file GGUF.
    /// </summary>
    internal async Task ExerciseStartupSeamAsync(
        TimeSpan? overallTimeout = null, int maxAttempts = 3)
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            await ShutdownUnlockedAsync().ConfigureAwait(false);
            Exception? last = null;
            using var overallCts = new CancellationTokenSource(
                overallTimeout ?? OverallStartupTimeout);
            for (var startupAttempt = 0; startupAttempt < maxAttempts; startupAttempt++)
            {
                overallCts.Token.ThrowIfCancellationRequested();
                if (startupAttempt > 0)
                    await Task.Delay(StartupBackoffDelay(startupAttempt - 1),
                        overallCts.Token).ConfigureAwait(false);

                _port = ProbeFreeLoopbackPort();
                AfterPortProbeForTests?.Invoke(_port);
                var psi = new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = "/c exit 0",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                Process? proc = null;
                HttpClient? client = null;
                try
                {
                    if (!IsLoopbackPortFree(_port))
                    {
                        throw new InvalidOperationException(
                            "address already in use (port bị chiếm sau probe)");
                    }
                    proc = ProcessStartOverride is not null
                        ? ProcessStartOverride(psi)
                        : Process.Start(psi);
                    if (proc is null)
                    {
                        last = new InvalidOperationException(
                            "Không khởi động được llama-server");
                        continue;
                    }
                    client = new HttpClient
                    {
                        BaseAddress = new Uri($"http://127.0.0.1:{_port}"),
                        Timeout = OverallStartupTimeout,
                    };
                    if (await WaitForHealthAsync(proc, client, overallCts.Token)
                            .ConfigureAwait(false))
                    {
                        _proc = proc;
                        _client = client;
                        proc = null;
                        client = null;
                        _ready = true;
                        return;
                    }
                    last = new TimeoutException(
                        "llama-server không sẵn sàng trong 30s");
                }
                catch (OperationCanceledException)
                    when (overallCts.IsCancellationRequested)
                {
                    last = new TimeoutException(
                        "llama-server không sẵn sàng trong 30s (overall timeout)");
                    CleanupServerState(ref proc, ref client);
                    break;
                }
                catch (Exception ex)
                {
                    last = ex;
                }
                CleanupServerState(ref proc, ref client);
            }
            throw last ?? new InvalidOperationException(
                "Không khởi động được llama-server sau nhiều lần thử");
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>Gắn client sẵn sàng để test interleave Generate/Shutdown.</summary>
    internal void ArmReadyClientForTests(HttpClient client)
    {
        _client = client;
        _ready = true;
    }

    /// <summary>Gắn trạng thái ready (không process) để test đổi model.</summary>
    internal void ArmReadyStateForTests(string modelPath, string modelSha256,
        string? modelId = null)
    {
        _ready = true;
        _activeModelPath = modelPath;
        _modelSha256 = modelSha256;
        _activeModelId = modelId;
        _proc = null;
    }

    public void Dispose()
    {
        ShutdownAsync().GetAwaiter().GetResult();
        _gate.Dispose();
    }
}
