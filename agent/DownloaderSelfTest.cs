// Local supply-chain checks: S10 hash mismatch, S11 bad domain, X12 retry+rehash.
// Run: NodeAgent.exe --test-downloader
using System.Security.Cryptography;
using System.Text;

namespace NodeAgent;

public static class DownloaderSelfTest
{
    public static async Task<int> RunAsync()
    {
        var failed = 0;
        void Check(string name, bool ok, string detail = "")
        {
            Console.WriteLine(ok ? $"PASS {name}" : $"FAIL {name}: {detail}");
            if (!ok) failed++;
        }

        // S11 — miền lạ hủy trước khi tải
        try
        {
            Downloader.AssertAllowedUrl(
                "https://evil.example/malware.bin",
                Downloader.DefaultAllowedDomains);
            Check("S11_bad_domain", false, "không ném");
        }
        catch (DownloadRejectedException ex)
        {
            Check("S11_bad_domain",
                ex.Message.Contains("allowlist", StringComparison.OrdinalIgnoreCase)
                || ex.Message.Contains("Miền", StringComparison.OrdinalIgnoreCase),
                ex.Message);
        }

        // S11b — không HTTPS
        try
        {
            Downloader.AssertAllowedUrl(
                "http://github.com/x", Downloader.DefaultAllowedDomains);
            Check("S11_http_blocked", false, "không ném");
        }
        catch (DownloadRejectedException)
        {
            Check("S11_http_blocked", true);
        }

        // S10 — hash lệch → xóa tệp, không “chạy”
        var dir = Path.Combine(Path.GetTempPath(), "thermal-dl-test-" + Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(dir);
        try
        {
            var path = Path.Combine(dir, "payload.bin");
            await File.WriteAllBytesAsync(path, Encoding.UTF8.GetBytes("hello"));
            var wrong = new string('0', 64);
            try
            {
                await Downloader.VerifySha256OrDeleteAsync(path, wrong);
                Check("S10_hash_mismatch", false, "không ném");
            }
            catch (DownloadRejectedException ex)
            {
                Check("S10_hash_mismatch",
                    !File.Exists(path)
                    && ex.Message.Contains("KHÔNG chạy", StringComparison.Ordinal),
                    ex.Message);
            }

            // X12 — tải local file:// không; mô phỏng: ghi partial sai rồi verify lại sau “retry”
            var good = Path.Combine(dir, "good.bin");
            var bytes = Encoding.UTF8.GetBytes("thermal-x12");
            await File.WriteAllBytesAsync(good, bytes);
            var hex = Convert.ToHexString(SHA256.HashData(bytes));
            // Corrupt then re-write + verify (resume path always re-hashes)
            await File.WriteAllBytesAsync(good, Encoding.UTF8.GetBytes("corrupt"));
            try
            {
                await Downloader.VerifySha256OrDeleteAsync(good, hex);
                Check("X12_rehash_after_corrupt", false, "phải từ chối");
            }
            catch (DownloadRejectedException)
            {
                await File.WriteAllBytesAsync(good, bytes);
                await Downloader.VerifySha256OrDeleteAsync(good, hex);
                Check("X12_rehash_after_retry", File.Exists(good));
            }

            // Hash-before-spawn: exe giả hash lệch → VerifyArtifacts từ chối
            var runtimeDir = Path.Combine(dir, "runtime");
            Directory.CreateDirectory(runtimeDir);
            var fakeExe = Path.Combine(runtimeDir, "llama-server.exe");
            var fakeDll = Path.Combine(runtimeDir, "llama-server-impl.dll");
            var fakeModel = Path.Combine(dir, "model.gguf");
            await File.WriteAllBytesAsync(fakeExe, Encoding.UTF8.GetBytes("exe"));
            await File.WriteAllBytesAsync(fakeDll, Encoding.UTF8.GetBytes("dll"));
            await File.WriteAllBytesAsync(fakeModel, Encoding.UTF8.GetBytes("gguf"));
            var dllHex = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("dll")));
            var modelHex = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("gguf")));
            var wrongExe = new string('A', 64);
            try
            {
                await LlamaCppRunner.VerifyArtifactsBeforeSpawnAsync(
                    runtimeDir, fakeModel, wrongExe, dllHex, modelHex);
                Check("S10_spawn_hash_exe", false, "phải từ chối");
            }
            catch (DownloadRejectedException ex)
            {
                Check("S10_spawn_hash_exe",
                    !File.Exists(fakeExe)
                    && ex.Message.Contains("KHÔNG chạy", StringComparison.Ordinal),
                    ex.Message);
            }
        }
        finally
        {
            try { Directory.Delete(dir, true); } catch { }
        }

        Console.WriteLine(failed == 0
            ? "Downloader self-test: ALL PASS"
            : $"Downloader self-test: {failed} FAIL");
        return failed == 0 ? 0 : 1;
    }
}
