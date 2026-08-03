// EndpointRoster: HTTP chỉ loopback; ngoài loopback bắt buộc HTTPS.
// Worker chỉ outbound — không mở cổng lắng nghe.
using System.Net.Http.Headers;

namespace NodeAgent;

/// <summary>
/// Giữ danh sách URL host (LAN + tunnel). Khi một đường lỗi mạng,
/// chuyển sang đường còn lại — worker LAN không phụ thuộc tunnel.
/// </summary>
public class EndpointRoster
{
    private readonly object _sync = new();
    private readonly List<Uri> _uris = new();
    private int _index;
    private readonly Action<string> _log;
    // Handler dùng chung — không gắn DefaultRequestHeaders mutable.
    private static readonly SocketsHttpHandler SharedSockets = new()
    {
        PooledConnectionLifetime = TimeSpan.FromMinutes(2),
        MaxConnectionsPerServer = 8,
    };

    public EndpointRoster(string primaryUrl, Action<string>? log = null)
    {
        _log = log ?? (_ => { });
        if (!TryValidateEndpoint(primaryUrl, primary: null, out var err))
            throw new InvalidOperationException(err);
        Add(primaryUrl);
        if (_uris.Count == 0)
            throw new InvalidOperationException(
                "EndpointRoster rỗng: ServerUrl không hợp lệ.");
    }

    public Uri Current
    {
        get
        {
            lock (_sync)
            {
                if (_uris.Count == 0)
                    throw new InvalidOperationException("EndpointRoster rỗng.");
                return _uris[Math.Clamp(_index, 0, _uris.Count - 1)];
            }
        }
    }

    public IReadOnlyList<Uri> All
    {
        get { lock (_sync) return _uris.ToList(); }
    }

    /// <summary>Snapshot bất biến cho failover concurrent.</summary>
    public IReadOnlyList<Uri> SnapshotUris()
    {
        lock (_sync) return _uris.ToList();
    }

    /// <summary>
    /// HTTP chỉ khi host loopback; ngoài loopback phải HTTPS.
    /// Secondary không được downgrade HTTPS primary → HTTP.
    /// </summary>
    public static bool TryValidateEndpoint(
        string? url, Uri? primary, out string error)
    {
        error = "";
        if (string.IsNullOrWhiteSpace(url))
        {
            error = "URL trống.";
            return false;
        }
        if (!Uri.TryCreate(url.Trim().TrimEnd('/'), UriKind.Absolute, out var uri))
        {
            error = "URL không phải absolute URI.";
            return false;
        }
        if (!IsAllowedScheme(uri))
        {
            error = IsLoopbackHost(uri.Host)
                ? $"Scheme không hỗ trợ: {uri.Scheme}"
                : "Ngoài loopback phải dùng HTTPS (HTTP chỉ cho 127.0.0.1/localhost).";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.UserInfo))
        {
            error = "URL không được chứa userinfo (credential trong URL).";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.Query))
        {
            error = "URL không được chứa query string.";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.Fragment))
        {
            error = "URL không được chứa fragment.";
            return false;
        }
        if (primary is not null
            && primary.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)
            && uri.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase))
        {
            error = "Secondary không được hạ HTTPS → HTTP.";
            return false;
        }
        return true;
    }

    public void Add(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        lock (_sync)
        {
            if (!TryValidateEndpoint(url, primary: _uris.Count > 0 ? _uris[0] : null,
                    out var err))
            {
                _log($"[AGENT] từ chối endpoint: {err}");
                return;
            }
            if (!Uri.TryCreate(url.Trim().TrimEnd('/'), UriKind.Absolute, out var uri))
                return;
            if (_uris.Any(u => Uri.Compare(u, uri, UriComponents.AbsoluteUri,
                    UriFormat.SafeUnescaped, StringComparison.OrdinalIgnoreCase) == 0))
                return;
            _uris.Add(uri);
        }
    }

    /// <summary>
    /// Chỉ nhận URL cùng host với primary, hoặc Cloudflare quick/named tunnel.
    /// Chặn MITM inject URL lạ rồi hút Bearer (H5).
    /// </summary>
    public bool IsTrustedSecondary(string? url, Uri primary)
    {
        if (string.IsNullOrWhiteSpace(url)) return false;
        if (!TryValidateEndpoint(url, primary, out _)) return false;
        if (!Uri.TryCreate(url.Trim().TrimEnd('/'), UriKind.Absolute, out var uri))
            return false;
        if (string.Equals(uri.Host, primary.Host, StringComparison.OrdinalIgnoreCase)
            && uri.Port == primary.Port)
            return true;
        if (IsPrivateOrLoopback(uri.Host) && IsPrivateOrLoopback(primary.Host)
            && uri.Port == primary.Port)
            return true;
        var host = uri.Host;
        if (host.EndsWith(".trycloudflare.com", StringComparison.OrdinalIgnoreCase))
            return uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase);
        if (host.EndsWith(".cfargotunnel.com", StringComparison.OrdinalIgnoreCase))
            return uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase);
        return false;
    }

    public static bool IsAllowedScheme(Uri uri)
    {
        if (uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
            return true;
        if (uri.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase))
            return IsLoopbackHost(uri.Host);
        return false;
    }

    public static bool IsLoopbackHost(string host)
    {
        if (string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase))
            return true;
        if (!System.Net.IPAddress.TryParse(host, out var ip))
            return false;
        return System.Net.IPAddress.IsLoopback(ip);
    }

    /// <summary>
    /// Parse fail → luôn placeholder cố định, không giữ raw (kể cả api_key…).
    /// </summary>
    public static string SanitizeEndpointForLog(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
            return "<empty>";
        if (Uri.TryCreate(url.Trim(), UriKind.Absolute, out var uri)
            && !string.IsNullOrEmpty(uri.Scheme)
            && (uri.Scheme.Equals("http", StringComparison.OrdinalIgnoreCase)
                || uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)))
            return SanitizeEndpointForLog(uri);
        // Parse fail hoặc scheme lạ — không bao giờ trả raw
        return "<invalid-url>";
    }

    /// <summary>Bỏ userinfo/query/fragment trước khi ghi log.</summary>
    public static string SanitizeEndpointForLog(Uri uri)
    {
        var builder = new UriBuilder(uri)
        {
            UserName = "",
            Password = "",
            Query = "",
            Fragment = "",
        };
        return builder.Uri.GetLeftPart(UriPartial.Path).TrimEnd('/');
    }

    static bool IsPrivateOrLoopback(string host)
    {
        if (IsLoopbackHost(host)) return true;
        if (!System.Net.IPAddress.TryParse(host, out var ip))
            return false;
        var b = ip.GetAddressBytes();
        if (b.Length == 4)
        {
            if (b[0] == 10) return true;
            if (b[0] == 192 && b[1] == 168) return true;
            if (b[0] == 172 && b[1] >= 16 && b[1] <= 31) return true;
        }
        return false;
    }

    public void ResetTo(params string?[] urls)
    {
        lock (_sync)
        {
            // Build list mới — không Clear trước validate (tránh roster rỗng
            // khi mọi URL lỗi → SendWithFailover snapshot[0] IndexOutOfRange).
            var next = new List<Uri>();
            foreach (var u in urls)
            {
                if (string.IsNullOrWhiteSpace(u)) continue;
                if (!TryValidateEndpoint(u, primary: next.Count > 0 ? next[0] : null,
                        out var err))
                {
                    _log($"[AGENT] từ chối endpoint: {err}");
                    continue;
                }
                if (!Uri.TryCreate(u.Trim().TrimEnd('/'), UriKind.Absolute, out var uri))
                    continue;
                if (next.Any(x => Uri.Compare(x, uri, UriComponents.AbsoluteUri,
                        UriFormat.SafeUnescaped, StringComparison.OrdinalIgnoreCase) == 0))
                    continue;
                next.Add(uri);
            }
            if (next.Count == 0)
                throw new InvalidOperationException(
                    "EndpointRoster rỗng — kiểm tra ServerUrl (HTTP chỉ loopback).");
            _uris.Clear();
            _uris.AddRange(next);
            _index = 0;
        }
    }

    public void Rotate()
    {
        lock (_sync)
        {
            if (_uris.Count <= 1) return;
            _index = (_index + 1) % _uris.Count;
            _log($"[AGENT] chuyển endpoint → {SanitizeEndpointForLog(_uris[_index])}");
        }
    }

    /// <summary>
    /// HttpClient theo endpoint, tái sử dụng SocketsHttpHandler chung.
    /// Không set DefaultRequestHeaders — Bearer gắn trên HttpRequestMessage.
    /// </summary>
    public virtual HttpClient CreateClient(
        TimeSpan? timeout = null, string? bearerToken = null)
        => CreateClient(baseAddress: null, timeout, bearerToken);

    public virtual HttpClient CreateClient(
        Uri? baseAddress, TimeSpan? timeout = null, string? bearerToken = null)
    {
        Uri baseUri;
        if (baseAddress is not null)
            baseUri = baseAddress;
        else
        {
            lock (_sync)
            {
                if (_uris.Count == 0)
                    throw new InvalidOperationException("EndpointRoster rỗng.");
                baseUri = _uris[Math.Clamp(_index, 0, _uris.Count - 1)];
            }
        }
        var inner = new BearerOnRequestHandler(SharedSockets, bearerToken);
        var http = new HttpClient(inner, disposeHandler: true)
        {
            BaseAddress = baseUri,
            Timeout = timeout ?? TimeSpan.FromSeconds(35),
        };
        return http;
    }
}

/// <summary>Gắn Authorization trên từng HttpRequestMessage — không dùng DefaultRequestHeaders.</summary>
sealed class BearerOnRequestHandler : DelegatingHandler
{
    private readonly string? _bearer;

    public BearerOnRequestHandler(HttpMessageHandler inner, string? bearer)
        : base(inner)
    {
        _bearer = bearer;
        // Không dispose inner (SocketsHttpHandler dùng chung)
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
        // Không dispose SharedSockets — bỏ qua base.Dispose(InnerHandler)
    }
}

/// <summary>Gửi request với một lần thử lại trên endpoint khác khi lỗi mạng.</summary>
public static class EndpointHttp
{
    public static async Task<HttpResponseMessage> SendWithFailoverAsync(
        EndpointRoster roster,
        Func<HttpClient, Task<HttpResponseMessage>> send,
        string? bearerToken,
        Action<string>? log = null,
        CancellationToken ct = default)
    {
        Exception? last = null;
        var snapshot = roster.SnapshotUris();
        var attempts = Math.Max(1, snapshot.Count);
        for (var i = 0; i < attempts; i++)
        {
            ct.ThrowIfCancellationRequested();
            var uri = snapshot[i];
            // Dùng URI từ snapshot — không đọc Current giữa vòng
            using var http = roster.CreateClient(
                baseAddress: uri, bearerToken: bearerToken);
            try
            {
                using var resp = await send(http).ConfigureAwait(false);
                var bytes = await resp.Content.ReadAsByteArrayAsync(ct)
                    .ConfigureAwait(false);
                var copy = new HttpResponseMessage(resp.StatusCode)
                {
                    Content = new ByteArrayContent(bytes),
                    ReasonPhrase = resp.ReasonPhrase,
                    Version = resp.Version,
                    RequestMessage = resp.RequestMessage,
                };
                foreach (var h in resp.Headers)
                    copy.Headers.TryAddWithoutValidation(h.Key, h.Value);
                foreach (var h in resp.Content.Headers)
                    copy.Content.Headers.TryAddWithoutValidation(h.Key, h.Value);
                return copy;
            }
            catch (Exception ex) when (
                ex is HttpRequestException or TaskCanceledException or IOException)
            {
                last = ex;
                log?.Invoke(
                    $"[AGENT] {EndpointRoster.SanitizeEndpointForLog(uri)} lỗi: {ex.Message}");
                if (i + 1 < attempts)
                    roster.Rotate();
            }
        }
        throw last ?? new HttpRequestException("Tất cả endpoint host đều hỏng.");
    }
}
