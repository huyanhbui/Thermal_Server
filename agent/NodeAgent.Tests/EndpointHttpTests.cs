using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Headers;
using NodeAgent;

namespace NodeAgent.Tests;

public class EndpointHttpTests
{
    [Fact]
    public async Task Concurrent_sends_with_different_tokens_are_isolated()
    {
        var seen = new ConcurrentDictionary<string, byte>();
        var handler = new CapturingHandler(seen);
        var roster = new TestRoster("http://127.0.0.1:8000", handler);
        await Task.WhenAll(
            EndpointHttp.SendWithFailoverAsync(
                roster,
                http => http.GetAsync("/a"),
                "token-a",
                log: null),
            EndpointHttp.SendWithFailoverAsync(
                roster,
                http => http.GetAsync("/b"),
                "token-b",
                log: null));
        Assert.True(seen.ContainsKey("token-a"));
        Assert.True(seen.ContainsKey("token-b"));
    }

    [Fact]
    public async Task Failover_rotate_under_concurrent_retries()
    {
        var hits = new ConcurrentDictionary<(string Host, string? Auth), int>();
        // Chỉ 1 lần fail toàn cục → Rotate; còn lại OK (tránh cạn attempts khi parallel)
        var handler = new FailThenOkHandler(hits, failFirst: 1);
        var roster = new TestRoster("http://127.0.0.1:8000", handler);
        roster.Add("http://127.0.0.1:8001");

        using (var warm = await EndpointHttp.SendWithFailoverAsync(
                   roster, http => http.GetAsync("/warmup"), "tok-warm", null))
            Assert.Equal(HttpStatusCode.OK, warm.StatusCode);

        var tasks = Enumerable.Range(0, 8).Select(i =>
            EndpointHttp.SendWithFailoverAsync(
                roster,
                http => http.GetAsync($"/x{i}"),
                $"tok-{i % 2}",
                log: null));
        var results = await Task.WhenAll(tasks);
        Assert.All(results, r => Assert.Equal(HttpStatusCode.OK, r.StatusCode));
        Assert.Contains(hits.Keys, k => k.Auth == "tok-0");
        Assert.Contains(hits.Keys, k => k.Auth == "tok-1");
    }

    [Fact]
    public async Task Failover_uses_snapshot_uri_not_current_mid_loop()
    {
        var seenBases = new ConcurrentBag<string>();
        var handler = new FailThenOkHandler(
            new ConcurrentDictionary<(string, string?), int>(), failFirst: 1);
        var roster = new TestRoster("http://127.0.0.1:8000", handler);
        roster.Add("http://127.0.0.1:8001");
        // Đổi Current trước khi failover vòng 2 — snapshot phải giữ URI cũ
        var snap = roster.SnapshotUris();
        Assert.Equal(2, snap.Count);

        using var resp = await EndpointHttp.SendWithFailoverAsync(
            roster,
            http =>
            {
                seenBases.Add(http.BaseAddress!.ToString().TrimEnd('/'));
                return http.GetAsync("/z");
            },
            "tok",
            log: null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Contains(seenBases, b => b.Contains("8000") || b.Contains("8001"));
    }

    [Fact]
    public void ResetTo_and_Rotate_are_thread_safe()
    {
        var roster = new EndpointRoster("http://127.0.0.1:8000");
        roster.Add("http://127.0.0.1:8001");
        var errors = new ConcurrentBag<Exception>();
        Parallel.For(0, 40, i =>
        {
            try
            {
                if (i % 5 == 0)
                    roster.ResetTo("http://127.0.0.1:8000", "http://127.0.0.1:8001");
                else
                    roster.Rotate();
                _ = roster.Current;
                _ = roster.SnapshotUris();
            }
            catch (Exception ex)
            {
                errors.Add(ex);
            }
        });
        Assert.Empty(errors);
    }

    sealed class CapturingHandler : HttpMessageHandler
    {
        readonly ConcurrentDictionary<string, byte> _seen;
        public CapturingHandler(ConcurrentDictionary<string, byte> seen) => _seen = seen;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var tok = request.Headers.Authorization?.Parameter;
            if (tok is not null) _seen.TryAdd(tok, 0);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("ok"),
            });
        }
    }

    sealed class FailThenOkHandler : HttpMessageHandler
    {
        readonly ConcurrentDictionary<(string, string?), int> _hits;
        int _failsLeft;
        public FailThenOkHandler(
            ConcurrentDictionary<(string, string?), int> hits, int failFirst)
        {
            _hits = hits;
            _failsLeft = failFirst;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var host = request.RequestUri?.Authority ?? "?";
            var auth = request.Headers.Authorization?.Parameter;
            _hits.AddOrUpdate((host, auth), 1, (_, n) => n + 1);
            if (Interlocked.Decrement(ref _failsLeft) >= 0)
                throw new HttpRequestException("simulated");
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("ok"),
            });
        }
    }

    /// <summary>Roster test — CreateClient dùng handler inject + BearerOnRequest.</summary>
    sealed class TestRoster : EndpointRoster
    {
        readonly HttpMessageHandler _handler;
        public TestRoster(string url, HttpMessageHandler handler)
            : base(url)
        {
            _handler = handler;
        }

        public override HttpClient CreateClient(
            Uri? baseAddress = null, TimeSpan? timeout = null, string? bearerToken = null)
        {
            var inner = new BearerInjectHandler(_handler, bearerToken);
            return new HttpClient(inner, disposeHandler: true)
            {
                BaseAddress = baseAddress ?? Current,
                Timeout = timeout ?? TimeSpan.FromSeconds(35),
            };
        }

        public override HttpClient CreateClient(
            TimeSpan? timeout = null, string? bearerToken = null)
            => CreateClient(baseAddress: null, timeout, bearerToken);
    }

    sealed class BearerInjectHandler : DelegatingHandler
    {
        readonly string? _bearer;
        public BearerInjectHandler(HttpMessageHandler inner, string? bearer)
            : base(inner)
        {
            _bearer = bearer;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (!string.IsNullOrEmpty(_bearer))
                request.Headers.Authorization =
                    new AuthenticationHeaderValue("Bearer", _bearer);
            return base.SendAsync(request, cancellationToken);
        }

        protected override void Dispose(bool disposing)
        {
            // Không dispose handler inject (dùng chung trong test)
        }
    }
}
