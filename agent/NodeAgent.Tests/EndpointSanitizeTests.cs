using NodeAgent;

namespace NodeAgent.Tests;

public class EndpointSanitizeTests
{
    [Fact]
    public void TryValidate_rejects_userinfo()
    {
        Assert.False(EndpointRoster.TryValidateEndpoint(
            "https://secret@host.example.com/", null, out var err));
        Assert.Contains("userinfo", err, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void TryValidate_rejects_query()
    {
        Assert.False(EndpointRoster.TryValidateEndpoint(
            "http://127.0.0.1:8000/?token=abc", null, out var err));
        Assert.Contains("query", err, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void SanitizeEndpointForLog_strips_secrets()
    {
        var raw = "https://secret@host.example.com:8443/path?token=abc#frag";
        var safe = EndpointRoster.SanitizeEndpointForLog(raw);
        Assert.DoesNotContain("secret", safe, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("token", safe, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("host.example.com", safe);
    }

    [Fact]
    public void SanitizeEndpointForLog_parse_fail_always_placeholder_never_raw()
    {
        string[] bad =
        [
            "not-a-url?token=supersecret",
            ":::api_key=AKIA123&access_key=xyz",
            "junk authorization=Bearer%20tok",
            "relative/path?api_key=1&access_key=2",
            "ftp://x?password=p",
        ];
        foreach (var raw in bad)
        {
            var safe = EndpointRoster.SanitizeEndpointForLog(raw);
            Assert.Equal("<invalid-url>", safe);
            Assert.DoesNotContain("supersecret", safe);
            Assert.DoesNotContain("AKIA", safe);
            Assert.DoesNotContain("Bearer", safe);
            Assert.DoesNotContain("password", safe);
            Assert.DoesNotContain(raw, safe);
        }
    }

    [Fact]
    public void SanitizeEndpointForLog_malformed_userinfo_stripped_when_parseable()
    {
        var safe = EndpointRoster.SanitizeEndpointForLog(
            "http://user:password=leak@127.0.0.1:8000/x");
        Assert.DoesNotContain("password", safe, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("user", safe, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("127.0.0.1", safe);
    }

    [Fact]
    public void Rotate_logs_sanitized_url()
    {
        var logs = new List<string>();
        var roster = new EndpointRoster("http://127.0.0.1:8000", logs.Add);
        roster.Add("http://127.0.0.1:8001");
        roster.Rotate();
        Assert.Contains(logs, l =>
            l.Contains("chuyển endpoint")
            && !l.Contains("secret", StringComparison.OrdinalIgnoreCase));
    }
}
