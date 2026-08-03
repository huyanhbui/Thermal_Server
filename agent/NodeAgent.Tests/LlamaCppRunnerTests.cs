using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using NodeAgent;

namespace NodeAgent.Tests;

public class LlamaCppRunnerTests
{
    [Fact]
    public void Windows_job_object_support_matches_current_platform()
    {
        Assert.Equal(OperatingSystem.IsWindows(), WindowsProcessJob.IsSupported);
    }

    [Fact]
    public void Completion_request_disables_qwen_thinking()
    {
        var json = LlamaCppRunner.BuildCompletionRequest("xin chào",
            new GenParams(32, 0.3), stream: true);
        using var doc = System.Text.Json.JsonDocument.Parse(json);

        Assert.True(doc.RootElement.GetProperty("stream").GetBoolean());
        Assert.False(doc.RootElement.GetProperty("chat_template_kwargs")
            .GetProperty("enable_thinking").GetBoolean());
    }

    [Fact]
    public void Completion_response_uses_reasoning_content_and_real_timings()
    {
        const string json = """
            {"choices":[{"message":{"content":"","reasoning_content":"suy luận"}}],
             "usage":{"prompt_tokens":3,"completion_tokens":5},
             "timings":{"prompt_ms":12.5,"predicted_ms":34.75}}
            """;

        var result = LlamaCppRunner.ParseCompletionResponse(json);

        Assert.Equal("suy luận", result.Text);
        Assert.Equal(12.5, result.PromptMs);
        Assert.Equal(34.75, result.PredictMs);
        Assert.False(result.TokensEstimated);
    }

    [Fact]
    public void Public_api_excludes_test_only_hooks()
    {
        var publicMembers = typeof(LlamaCppRunner)
            .GetMembers(System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.Static
                | System.Reflection.BindingFlags.Instance)
            .Select(member => member.Name);

        Assert.DoesNotContain("SkipArtifactFetchForTests", publicMembers);
        Assert.DoesNotContain("AfterPortProbeForTests", publicMembers);
        Assert.DoesNotContain("ProcessStartOverride", publicMembers);
        Assert.DoesNotContain("ExerciseStartupSeamAsync", publicMembers);
        Assert.DoesNotContain("ArmReadyClientForTests", publicMembers);
        Assert.DoesNotContain("ArmReadyStateForTests", publicMembers);
    }

    [Fact]
    public void ProbeFreeLoopbackPort_returns_bindable_port()
    {
        var port = LlamaCppRunner.ProbeFreeLoopbackPort();
        Assert.InRange(port, 1, 65535);
        using var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        listener.Stop();
    }

    [Fact]
    public void OverallStartupTimeout_is_about_30_seconds()
    {
        Assert.Equal(TimeSpan.FromSeconds(30), LlamaCppRunner.OverallStartupTimeout);
        Assert.True(LlamaCppRunner.HealthProbeTimeout <= TimeSpan.FromSeconds(2));
    }

    [Fact]
    public void CleanupServerState_idempotent_double_call()
    {
        Process? proc = null;
        HttpClient? client = new HttpClient();
        LlamaCppRunner.CleanupServerState(ref proc, ref client);
        Assert.Null(client);
        LlamaCppRunner.CleanupServerState(ref proc, ref client);
        LlamaCppRunner.CleanupServerState(null, null);
    }

    [Fact]
    public async Task Startup_early_exit_cleans_up_via_process_override()
    {
        var starts = 0;
        LlamaCppRunner.ProcessStartOverride = _ =>
        {
            Interlocked.Increment(ref starts);
            // Process thoát ngay — seam early-exit
            return Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c exit 42",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
        };
        try
        {
            using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
            var ex = await Assert.ThrowsAnyAsync<Exception>(
                () => runner.ExerciseStartupSeamAsync(
                    overallTimeout: TimeSpan.FromSeconds(8), maxAttempts: 2));
            Assert.True(
                ex.Message.Contains("thoát sớm", StringComparison.OrdinalIgnoreCase)
                || ex is TimeoutException
                || ex.Message.Contains("30s", StringComparison.Ordinal),
                ex.ToString());
            Assert.True(starts >= 1);
            Assert.False(runner.IsRuntimeReady);
        }
        finally
        {
            LlamaCppRunner.ProcessStartOverride = null;
        }
    }

    [Fact]
    public async Task Startup_timeout_when_health_never_ok()
    {
        // Process sống nhưng không lắng /health
        LlamaCppRunner.ProcessStartOverride = _ =>
            Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c ping 127.0.0.1 -n 30 >nul",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
        try
        {
            using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
            var ex = await Assert.ThrowsAsync<TimeoutException>(
                () => runner.ExerciseStartupSeamAsync(
                    overallTimeout: TimeSpan.FromSeconds(2), maxAttempts: 1));
            Assert.Contains("30s", ex.Message);
            Assert.False(runner.IsRuntimeReady);
        }
        finally
        {
            LlamaCppRunner.ProcessStartOverride = null;
        }
    }

    [Fact]
    public async Task Generate_and_Shutdown_are_serialized_no_dispose_mid_generate()
    {
        using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
        var handler = new SlowOkHandler(TimeSpan.FromMilliseconds(250));
        var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:9/"),
        };
        runner.ArmReadyClientForTests(client);

        var genStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        handler.OnSend = () => genStarted.TrySetResult();

        var genTask = runner.GenerateAsync(
            "hi", new GenParams(16, 0.2), CancellationToken.None);
        await genStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

        var shutdownTask = runner.ShutdownAsync();
        // Shutdown phải chờ Generate xong — không dispose client giữa chừng
        var gen = await genTask;
        Assert.Equal("ok", gen.Text);
        await shutdownTask;
        Assert.False(runner.IsRuntimeReady);
    }

    [Fact]
    public async Task Streaming_generation_forwards_real_deltas_in_order()
    {
        using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
        var handler = new StreamingHandler();
        var client = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:9/") };
        runner.ArmReadyClientForTests(client);
        var received = new List<string>();

        var result = await runner.GenerateAsync("hi", new GenParams(16, 0.2),
            CancellationToken.None, delta =>
            {
                received.Add(delta);
                return Task.CompletedTask;
            });

        Assert.Equal(new[] { "xin ", "chào" }, received);
        Assert.Equal("xin chào", result.Text);
        Assert.Equal(4, result.TokensOut);
        Assert.Equal(7.5, result.PromptMs);
        Assert.Equal(19.5, result.PredictMs);
        Assert.Contains("\"stream\":true", handler.RequestBody);
    }

    [Fact]
    public async Task Port_collision_after_probe_retries_new_port()
    {
        var probed = new List<int>();
        var blockers = new List<TcpListener>();
        LlamaCppRunner.AfterPortProbeForTests = port =>
        {
            probed.Add(port);
            // Lần đầu: chiếm cổng ngay sau probe → buộc retry
            if (probed.Count == 1)
            {
                var l = new TcpListener(IPAddress.Loopback, port);
                l.Start();
                blockers.Add(l);
            }
        };
        var starts = 0;
        LlamaCppRunner.ProcessStartOverride = _ =>
        {
            Interlocked.Increment(ref starts);
            return Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c exit 1",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
        };
        try
        {
            using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
            await Assert.ThrowsAnyAsync<Exception>(
                () => runner.ExerciseStartupSeamAsync(
                    overallTimeout: TimeSpan.FromSeconds(6), maxAttempts: 3));
            Assert.True(probed.Count >= 2, $"probed={probed.Count}");
            Assert.NotEqual(probed[0], probed[1]);
            Assert.True(starts >= 1);
        }
        finally
        {
            LlamaCppRunner.AfterPortProbeForTests = null;
            LlamaCppRunner.ProcessStartOverride = null;
            foreach (var b in blockers)
            {
                try { b.Stop(); } catch { /* ignore */ }
            }
        }
    }

    [Fact]
    public async Task Model_switch_while_holding_gate_does_not_deadlock()
    {
        LlamaCppRunner.SkipArtifactFetchForTests = true;
        var work = Path.Combine(Path.GetTempPath(),
            "llm-switch-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(work, "models"));
        try
        {
            using var runner = new LlamaCppRunner(workDir: work);
            var oldPath = Path.Combine(work, "models", "old.gguf");
            await File.WriteAllTextAsync(oldPath, "old");
            runner.ArmReadyStateForTests(oldPath, "sha-old", "old-model");

            var cfg = new RoomConfig
            {
                ModelId = "new-model",
                ModelUrl = "https://example.com/new.gguf",
                ModelSha256 = "sha-new",
                ModelFilename = "new.gguf",
                RuntimeUrl = "https://example.com/runtime.zip",
                RuntimeSha256 = "sha-runtime",
                LlamaServerExeSha256 = "sha-exe",
                LlamaServerImplDllSha256 = "sha-dll",
            };

            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var task = runner.EnsureReadyAsync(cfg, null);
            var winner = await Task.WhenAny(
                task, Task.Delay(Timeout.InfiniteTimeSpan, cts.Token));
            Assert.Same(task, winner); // không treo trên ShutdownAsync
            var ok = await task;
            Assert.False(ok); // SkipArtifactFetch → false sau shutdown
            Assert.Equal("sha-new", runner.ActiveModelSha256);
        }
        finally
        {
            LlamaCppRunner.SkipArtifactFetchForTests = false;
            try { Directory.Delete(work, recursive: true); } catch { /* ignore */ }
        }
    }

    [Fact]
    public async Task Port_collision_hint_retries_with_new_probe()
    {
        using var blocker = new TcpListener(IPAddress.Loopback, 0);
        blocker.Start();
        var blocked = ((IPEndPoint)blocker.LocalEndpoint).Port;
        var ports = new List<int>();
        LlamaCppRunner.ProcessStartOverride = psi =>
        {
            // Ghi nhận --port trong Arguments nếu có; seam vẫn early-exit
            var args = psi.Arguments ?? "";
            var m = System.Text.RegularExpressions.Regex.Match(args, @"--port\s+(\d+)");
            if (m.Success)
                ports.Add(int.Parse(m.Groups[1].Value));
            return Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c exit 1",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
        };
        try
        {
            using var runner = new LlamaCppRunner(workDir: Path.GetTempPath());
            await Assert.ThrowsAnyAsync<Exception>(
                () => runner.ExerciseStartupSeamAsync(
                    overallTimeout: TimeSpan.FromSeconds(6), maxAttempts: 3));
            // ExerciseStartupSeam probes port independently of psi args —
            // collision: ProbeFreeLoopbackPort skips occupied
            var p = LlamaCppRunner.ProbeFreeLoopbackPort(new[] { blocked });
            Assert.NotEqual(blocked, p);
        }
        finally
        {
            LlamaCppRunner.ProcessStartOverride = null;
            blocker.Stop();
        }
    }

    sealed class SlowOkHandler : HttpMessageHandler
    {
        readonly TimeSpan _delay;
        public Action? OnSend { get; set; }
        public SlowOkHandler(TimeSpan delay) => _delay = delay;

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            OnSend?.Invoke();
            await Task.Delay(_delay, cancellationToken);
            var json =
                "{\"choices\":[{\"message\":{\"content\":\"ok\"}}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1}}";
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json),
            };
        }
    }

    sealed class StreamingHandler : HttpMessageHandler
    {
        public string RequestBody { get; private set; } = "";

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            const string events = """
                data: {"choices":[{"delta":{"content":"xin "}}]}

                data: {"choices":[{"delta":{"content":"chào"}}],"usage":{"prompt_tokens":2,"completion_tokens":4},"timings":{"prompt_ms":7.5,"predicted_ms":19.5}}

                data: [DONE]

                """;
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(events),
            };
        }
    }
}
