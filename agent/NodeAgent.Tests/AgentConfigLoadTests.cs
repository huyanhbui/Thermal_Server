using NodeAgent;

namespace NodeAgent.Tests;

public class AgentConfigLoadTests
{
    [Fact]
    public void Default_path_uses_program_data_and_can_be_overridden_for_tests()
    {
        var root = Path.Combine(Path.GetTempPath(), "thermal-agent-config-test");

        var path = AgentConfig.ResolveConfigPath(root);

        Assert.Equal(Path.Combine(root, "config.json"), path);
    }

    [Fact]
    public void Protected_config_uses_machine_scope_and_omits_plaintext_password()
    {
        var path = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"),
            "config.json");
        var config = new AgentConfig("Node-A", "https://host.example", "ROOM-1",
            "mật-khẩu-đủ-dài");

        AgentConfig.WriteProtectedConfig(path, config);

        var raw = File.ReadAllText(path);
        Assert.DoesNotContain(config.Password, raw, StringComparison.Ordinal);
        Assert.Contains("\"passwordScope\": \"LocalMachine\"", raw,
            StringComparison.Ordinal);
    }

    [Fact]
    public void Legacy_plaintext_config_is_imported_then_scrubbed()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
        var canonical = Path.Combine(root, "machine", "config.json");
        var legacy = Path.Combine(root, "legacy", "config.json");
        const string password = "mật-khẩu-cũ-đủ-dài";
        Directory.CreateDirectory(Path.GetDirectoryName(legacy)!);
        File.WriteAllText(legacy, $$"""
            {"nodeName":"Node-A","serverUrl":"https://host.example",
            "roomCode":"ROOM-1","password":"{{password}}"}
            """);

        var loaded = AgentConfig.LoadFromPaths(canonical, legacy);

        Assert.Equal(password, loaded.Password);
        Assert.True(File.Exists(canonical));
        Assert.DoesNotContain(password, File.ReadAllText(canonical),
            StringComparison.Ordinal);
        Assert.DoesNotContain(password, File.ReadAllText(legacy),
            StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("http://localhost:8000")]
    [InlineData("http://127.0.0.1:8000")]
    [InlineData("http://[::1]:8000")]
    public void Client_setup_rejects_loopback_host_urls(string serverUrl)
    {
        var valid = AgentSetup.TryCreateConfig("Worker-1", serverUrl, "ROOM-1",
            "mật-khẩu-đủ-dài", out _, out var error);

        Assert.False(valid);
        Assert.Contains("localhost", error, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Client_setup_rejects_loopback_before_requesting_a_password()
    {
        var valid = AgentSetup.TryCreateConfig("Worker-1",
            "http://localhost:8000", "ROOM-1", "", out _, out var error);

        Assert.False(valid);
        Assert.Contains("localhost", error, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Redirected_setup_password_uses_the_input_line_without_readkey()
    {
        using var input = new StringReader("secret-from-stdin\n");

        var password = AgentSetup.ReadRedirectedPassword(input);

        Assert.Equal("secret-from-stdin", password);
    }

    [Fact]
    public void Client_setup_extracts_room_code_from_invite_url()
    {
        var valid = AgentSetup.TryCreateConfig("Worker-1",
            "https://host.example/?code=ROOM-9", null, "mật-khẩu-đủ-dài",
            out var config, out var error);

        Assert.True(valid, error);
        Assert.Equal("ROOM-9", config!.RoomCode);
        Assert.Equal("https://host.example", config.ServerUrl);
    }

    [Fact]
    public void Room_config_parses_non_negative_model_generation()
    {
        using var doc = System.Text.Json.JsonDocument.Parse("""
            {"room_config":{"model_id":"qwen","model_generation":7,
            "runtime_id":"llama-b10216"}}
            """);

        var config = RoomConfig.FromJson(doc.RootElement);

        Assert.Equal(7, config.ModelGeneration);
        Assert.Equal("llama-b10216", config.RuntimeId);
    }

    [Fact]
    public void Protected_password_round_trip_does_not_embed_plaintext()
    {
        const string password = "mật-khẩu-bảo-mật-123";

        var protectedValue = AgentConfig.ProtectPassword(password);

        Assert.NotEqual(password, protectedValue);
        Assert.DoesNotContain(password, protectedValue,
            StringComparison.Ordinal);
        Assert.Equal(password, AgentConfig.UnprotectPassword(protectedValue));
    }

    [Fact]
    public void Rotated_room_credentials_are_detected_but_endpoint_writes_are_not()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
        var canonical = Path.Combine(root, "config.json");
        var legacy = Path.Combine(root, "missing", "config.json");
        var original = new AgentConfig("Host-A", "http://127.0.0.1:8000",
            "THERMAL-AAAA", "mật-khẩu-cũ-đủ-dài");
        AgentConfig.WriteProtectedConfig(canonical, original);
        var loaded = AgentConfig.LoadFromPaths(canonical, legacy);

        // Worker tự ghi lại endpoint sau mỗi lần join — không phải rotation.
        AgentConfig.WriteProtectedConfig(canonical,
            loaded with { LanUrl = "http://127.0.0.1:8000" });
        Assert.True(loaded.HasSameJoinCredentials(
            AgentConfig.LoadFromPaths(canonical, legacy)));

        // Host tạo lại phòng: đổi cả mã phòng và mật khẩu worker.
        AgentConfig.WriteProtectedConfig(canonical,
            loaded with { RoomCode = "THERMAL-BBBB",
                Password = "mật-khẩu-mới-đủ-dài" });
        Assert.False(loaded.HasSameJoinCredentials(
            AgentConfig.LoadFromPaths(canonical, legacy)));
    }

    [Fact]
    public void A_failed_reload_still_retries_the_same_host_rewrite()
    {
        var stamp = new DateTime(2026, 8, 6, 3, 0, 0, DateTimeKind.Utc);
        var gate = new ConfigReloadGate(() => stamp);
        var rotated = new AgentConfig("Host-A", "https://host.example",
            "THERMAL-BBBB", "mật-khẩu-mới-đủ-dài");
        var failures = new List<Exception>();
        var attempts = 0;
        AgentConfig Load()
        {
            attempts++;
            if (attempts == 1)
                throw new IOException("config đang bị ghi");
            return rotated;
        }
        stamp = stamp.AddSeconds(5);

        Assert.False(gate.TryReload(Load, out _, failures.Add));
        Assert.Single(failures);

        // Lần ghi của Host chưa được ghi nhận: nạp lại phải thử tiếp cùng mốc.
        Assert.True(gate.TryReload(Load, out var loaded, failures.Add));
        Assert.Same(rotated, loaded);
        Assert.Single(failures);

        // Nạp xong mới đẩy mốc — không nạp lại vòng vo khi file không đổi.
        Assert.False(gate.TryReload(Load, out _, failures.Add));
        Assert.Equal(2, attempts);
    }

    [Fact]
    public void FilterSecondary_warns_sanitized_when_rejected()
    {
        var warnings = new List<string>();
        var primary = "https://primary.trycloudflare.com";
        var result = AgentConfig.FilterSecondary(
            primary,
            "https://secret@evil.example.com/?token=abc",
            "tunnelUrl",
            warnings.Add);
        Assert.Null(result);
        Assert.Contains(warnings, w =>
            w.Contains("đã loại tunnelUrl", StringComparison.OrdinalIgnoreCase)
            && !w.Contains("secret", StringComparison.OrdinalIgnoreCase)
            && !w.Contains("token=abc", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void FilterSecondary_warns_when_lan_untrusted()
    {
        var warnings = new List<string>();
        var primary = "https://primary.trycloudflare.com";
        var result = AgentConfig.FilterSecondary(
            primary,
            "http://192.168.1.5:8000",
            "lanUrl",
            warnings.Add);
        Assert.Null(result);
        Assert.Contains(warnings, w =>
            w.Contains("đã loại lanUrl", StringComparison.OrdinalIgnoreCase));
    }
}
