// Supply-chain downloader: allowlist domain → HTTPS only → SHA256 before
// first execute. Mismatch → DELETE file, never run (docs/10 §6, docs/06 §5).
using System.Net;
using System.Security.Cryptography;
using System.Text;

namespace NodeAgent;

public sealed class DownloadRejectedException : Exception
{
    public DownloadRejectedException(string message) : base(message) { }
}

public static class Downloader
{
    public static readonly string[] DefaultAllowedDomains =
    [
        "github.com",
        "objects.githubusercontent.com",
        "huggingface.co",
        "cdn-lfs.huggingface.co",
    ];

    public static void AssertAllowedUrl(string url, IReadOnlyList<string>? allowedDomains)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
            throw new DownloadRejectedException($"URL không hợp lệ: {url}");
        if (!string.Equals(uri.Scheme, "https", StringComparison.OrdinalIgnoreCase))
            throw new DownloadRejectedException(
                $"Chỉ cho phép HTTPS. Nhận scheme={uri.Scheme}.");
        var domains = (allowedDomains is { Count: > 0 })
            ? allowedDomains : DefaultAllowedDomains;
        var host = uri.Host;
        var ok = domains.Any(d =>
            host.Equals(d, StringComparison.OrdinalIgnoreCase)
            || host.EndsWith("." + d, StringComparison.OrdinalIgnoreCase));
        if (!ok)
            throw new DownloadRejectedException(
                $"Miền không nằm trong allowlist: {host}. Hủy trước khi tải.");
    }

    public static string FormatHashMismatch(string fileName, string got, string expected)
    {
        return
            "❌ Tệp tải về không khớp chữ ký số dự kiến.\n" +
            "\n" +
            $"   Tệp:    {fileName}\n" +
            $"   Nhận:   {got}\n" +
            $"   Kỳ vọng: {expected}\n" +
            "\n" +
            "   Đã xóa tệp. KHÔNG chạy.\n" +
            "\n" +
            "   Nguyên nhân có thể: tải hỏng, proxy công ty sửa nội dung,\n" +
            "   hoặc phiên bản trên máy chủ đã đổi.\n" +
            "   Kiểm tra kết nối rồi thử lại. Nếu vẫn lệch, báo quản trị viên.";
    }

    public static async Task<string> ComputeSha256HexAsync(string path, CancellationToken ct = default)
    {
        await using var fs = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(fs, ct);
        return Convert.ToHexString(hash);
    }

    public static async Task VerifySha256OrDeleteAsync(
        string path, string expectedHex, CancellationToken ct = default)
    {
        var got = await ComputeSha256HexAsync(path, ct);
        if (!got.Equals(expectedHex.Trim(), StringComparison.OrdinalIgnoreCase))
        {
            var name = Path.GetFileName(path);
            try { File.Delete(path); } catch { /* best effort */ }
            throw new DownloadRejectedException(
                FormatHashMismatch(name, got, expectedHex.Trim().ToUpperInvariant()));
        }
    }

    /// <summary>
    /// Download with progress. Domain check BEFORE bytes. Hash AFTER download
    /// and BEFORE caller may execute. Retries on transient network errors (X12)
    /// and always re-hashes.
    /// </summary>
    public static async Task DownloadAndVerifyAsync(
        string url,
        string destPath,
        string expectedSha256,
        IReadOnlyList<string>? allowedDomains,
        IProgress<double>? progress = null,
        int maxAttempts = 3,
        CancellationToken ct = default)
    {
        AssertAllowedUrl(url, allowedDomains);
        var dir = Path.GetDirectoryName(destPath);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        Exception? last = null;
        for (var attempt = 1; attempt <= maxAttempts; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            var partial = destPath + ".partial";
            try
            {
                if (File.Exists(partial))
                    File.Delete(partial);

                using var http = new HttpClient { Timeout = TimeSpan.FromHours(2) };
                using var resp = await http.GetAsync(
                    url, HttpCompletionOption.ResponseHeadersRead, ct);
                resp.EnsureSuccessStatusCode();
                var total = resp.Content.Headers.ContentLength ?? -1L;
                await using (var src = await resp.Content.ReadAsStreamAsync(ct))
                await using (var dst = File.Create(partial))
                {
                    var buf = new byte[81920];
                    long written = 0;
                    int n;
                    while ((n = await src.ReadAsync(buf.AsMemory(0, buf.Length), ct)) > 0)
                    {
                        await dst.WriteAsync(buf.AsMemory(0, n), ct);
                        written += n;
                        if (total > 0)
                            progress?.Report(Math.Min(1.0, (double)written / total));
                    }
                }

                // Hash BEFORE promoting to final path / execute.
                await VerifySha256OrDeleteAsync(partial, expectedSha256, ct);
                if (File.Exists(destPath))
                    File.Delete(destPath);
                File.Move(partial, destPath);
                progress?.Report(1.0);
                return;
            }
            catch (DownloadRejectedException)
            {
                try { if (File.Exists(partial)) File.Delete(partial); } catch { }
                throw;
            }
            catch (Exception ex) when (ex is HttpRequestException or IOException or WebException)
            {
                last = ex;
                try { if (File.Exists(partial)) File.Delete(partial); } catch { }
                if (attempt == maxAttempts)
                    break;
                await Task.Delay(1000 * attempt, ct);
            }
        }
        throw new DownloadRejectedException(
            $"Tải thất bại sau {maxAttempts} lần: {last?.Message}");
    }
}
