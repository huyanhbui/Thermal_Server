using NodeAgent;

namespace NodeAgent.Tests;

public class EndpointRosterTests
{
    [Theory]
    [InlineData("http://127.0.0.1:8000")]
    [InlineData("http://localhost:8000")]
    [InlineData("https://192.168.1.10:8443")]
    public void Http_loopback_or_https_remote_accepted(string url)
    {
        Assert.True(EndpointRoster.TryValidateEndpoint(url, null, out var err), err);
        var roster = new EndpointRoster(url);
        Assert.Single(roster.All);
    }

    [Theory]
    [InlineData("http://192.168.1.50:8000")]
    [InlineData("http://10.0.0.2:8000")]
    [InlineData("ftp://127.0.0.1:21")]
    public void Http_lan_or_bad_scheme_rejected(string url)
    {
        Assert.False(EndpointRoster.TryValidateEndpoint(url, null, out _));
        Assert.Throws<InvalidOperationException>(() => new EndpointRoster(url));
    }

    [Fact]
    public void Secondary_cannot_downgrade_https_to_http()
    {
        var primary = new Uri("https://abc.trycloudflare.com");
        Assert.False(EndpointRoster.TryValidateEndpoint(
            "http://127.0.0.1:8000", primary, out var err));
        Assert.Contains("HTTPS", err, StringComparison.OrdinalIgnoreCase);

        var roster = new EndpointRoster("https://abc.trycloudflare.com");
        Assert.False(roster.IsTrustedSecondary("http://192.168.1.5:8000", primary));
    }

    [Fact]
    public void ResetTo_empty_throws()
    {
        var roster = new EndpointRoster("http://127.0.0.1:8000");
        Assert.Throws<InvalidOperationException>(() =>
            roster.ResetTo("http://10.0.0.1:1", null));
    }

    [Fact]
    public void ResetTo_all_invalid_preserves_previous_roster()
    {
        var roster = new EndpointRoster("http://127.0.0.1:8000");
        Assert.Throws<InvalidOperationException>(() =>
            roster.ResetTo("http://10.0.0.1:1", "ftp://bad"));
        Assert.Single(roster.All);
        Assert.Equal(
            new Uri("http://127.0.0.1:8000"),
            roster.All[0]);
        // Snapshot không rỗng — SendWithFailover không IndexOutOfRange
        var snap = roster.SnapshotUris();
        Assert.Single(snap);
    }
}

public class EnergySamplerTests
{
    [Fact]
    public void Sensor_gap_model_or_none_does_not_label_all_as_sensor()
    {
        var s = new EnergySampler();
        s.SampleAt(0, 100);   // sensor
        s.SampleAt(1, null);  // none — gap
        s.SampleAt(2, 100);   // sensor
        var (ej, src) = s.Finalize();
        // Không bridge qua gap → không có cặp sensor liền kề
        Assert.Equal("none", src);
        Assert.Null(ej);
    }

    [Fact]
    public void Contiguous_sensor_pairs_integrate_as_sensor()
    {
        var s = new EnergySampler();
        s.SampleAt(0, 100);
        s.SampleAt(1, 100);
        var (ej, src) = s.Finalize();
        Assert.Equal("sensor", src);
        Assert.NotNull(ej);
        Assert.Equal(100.0, ej!.Value, 3);
    }
}

public class JobParamGuardTests
{
    [Fact]
    public void Clamps_out_of_range_max_tokens_and_deadline()
    {
        Assert.False(JobParamGuard.TryClampMaxTokens(99999, out var mt, out _));
        Assert.Equal(JobParamGuard.MaxTokensMax, mt);
        Assert.False(JobParamGuard.TryClampDeadlineS(0, out var dl, out _));
        Assert.Equal(JobParamGuard.DeadlineMinS, dl);
        Assert.False(JobParamGuard.TryClampTemperature(double.NaN, out var t, out _));
        Assert.True(double.IsFinite(t));
        Assert.False(JobParamGuard.TryClampCores(99, 4, out var cores, out _));
        Assert.Equal(4, cores);
    }
}

public class AgentConfigAtomicTests
{
    [Fact]
    public void AtomicWriteJson_writes_and_replaces()
    {
        var dir = Path.Combine(Path.GetTempPath(), "na-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            var path = Path.Combine(dir, "config.json");
            AgentConfig.AtomicWriteJson(path, new Dictionary<string, object?>
            {
                ["nodeName"] = "N1",
                ["serverUrl"] = "http://127.0.0.1:8000",
            });
            Assert.True(File.Exists(path));
            var text = File.ReadAllText(path);
            Assert.Contains("N1", text);
            AgentConfig.AtomicWriteJson(path, new Dictionary<string, object?>
            {
                ["nodeName"] = "N2",
            });
            Assert.Contains("N2", File.ReadAllText(path));
        }
        finally
        {
            try { Directory.Delete(dir, true); } catch { /* ignore */ }
        }
    }

    [Fact]
    public void TryValidate_rejects_invalid_server_url()
    {
        Assert.False(EndpointRoster.TryValidateEndpoint(
            "not-a-url", null, out _));
    }
}
