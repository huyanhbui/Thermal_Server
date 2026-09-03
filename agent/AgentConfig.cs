// Loads the machine-scoped config: node identity, room credentials, and Host URL.
// Password is used only for POST /join — never logged or kept as plaintext on disk.
// LanUrl + TunnelUrl: dual path (G6) — worker lưu cả hai từ /join.
using System.Text.Json;
using System.Security.Cryptography;
using System.Text;
using System.Runtime.InteropServices;
using NodeAgent;

public record AgentConfig(
    string NodeName,
    string ServerUrl,
    string RoomCode,
    string Password,
    string? LanUrl = null,
    string? TunnelUrl = null)
{
    private const string ConfigDirectoryEnvironmentVariable =
        "THERMAL_AGENT_CONFIG_DIR";

    /// <summary>
    /// Cấu hình là state theo máy, không nằm cạnh executable có thể bị thay thế khi
    /// cập nhật. Biến môi trường chỉ dùng cho test hoặc triển khai cô lập.
    /// </summary>
    public static string ResolveConfigPath(string? dataDirectory = null)
    {
        var root = dataDirectory;
        if (string.IsNullOrWhiteSpace(root))
            root = Environment.GetEnvironmentVariable(
                ConfigDirectoryEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(root))
        {
            root = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.CommonApplicationData),
                "ThermalOrchestrator", "agent");
        }
        return Path.Combine(root, "config.json");
    }

    public static string LegacyConfigPath =>
        Path.Combine(AppContext.BaseDirectory, "config.json");

    public static AgentConfig Load(Action<string>? log = null)
        => LoadFromPaths(ResolveConfigPath(), LegacyConfigPath, log);

    /// <summary>
    /// Nạp config chuẩn hoặc import an toàn config cũ. Tách path để kiểm thử migration
    /// mà không phụ thuộc vào thư mục executable thật.
    /// </summary>
    public static AgentConfig LoadFromPaths(string canonicalPath, string legacyPath,
        Action<string>? log = null)
    {
        var path = File.Exists(canonicalPath) ? canonicalPath : legacyPath;
        if (!File.Exists(path))
            throw new FileNotFoundException(
                $"Không tìm thấy config.json tại {path}. Sao chép cạnh exe và " +
                "điền nodeName, serverUrl, roomCode, password.");
        var raw = File.ReadAllText(path);
        var cfg = JsonSerializer.Deserialize<AgentConfig>(raw,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        using var doc = JsonDocument.Parse(raw);
        var protectedPassword = doc.RootElement.TryGetProperty("passwordProtected",
            out var protectedEl) && protectedEl.ValueKind == JsonValueKind.String
            ? protectedEl.GetString() : null;
        if (cfg is null)
            throw new InvalidDataException("config.json không hợp lệ.");
        if (!string.IsNullOrWhiteSpace(protectedPassword))
        {
            try
            {
                cfg = cfg with { Password = UnprotectPassword(protectedPassword) };
            }
            catch (CryptographicException ex)
            {
                throw new InvalidDataException(
                    "Không giải mã được passwordProtected trên tài khoản Windows này.", ex);
            }
        }
        if (string.IsNullOrWhiteSpace(cfg.NodeName)
                        || string.IsNullOrWhiteSpace(cfg.ServerUrl)
                        || string.IsNullOrWhiteSpace(cfg.RoomCode)
                        || string.IsNullOrWhiteSpace(cfg.Password))
            throw new InvalidDataException(
                "config.json phải có nodeName, serverUrl, roomCode, password.");
        if (!EndpointRoster.TryValidateEndpoint(cfg.ServerUrl, primary: null,
                out var err))
            throw new InvalidDataException(
                $"serverUrl không hợp lệ: {err}");
        cfg = cfg with
        {
            LanUrl = FilterSecondary(cfg.ServerUrl, cfg.LanUrl, "lanUrl", log),
            TunnelUrl = FilterSecondary(
                cfg.ServerUrl, cfg.TunnelUrl, "tunnelUrl", log),
        };
        if (!string.Equals(path, canonicalPath,
                StringComparison.OrdinalIgnoreCase))
        {
            // Nhập một lần config cũ rồi loại password thuần ở cả vị trí cũ.
            WriteProtectedConfig(canonicalPath, cfg);
            WriteProtectedConfig(path, cfg);
            log?.Invoke("[AGENT] đã chuyển config cũ sang kho cấu hình theo máy");
        }
        return cfg;
    }

    /// <summary>
    /// True when a reloaded config still joins with the same identity and
    /// secret. Record equality cannot answer this: the worker rewrites lanUrl
    /// and tunnelUrl after every successful join, while the Host rewrites the
    /// room code and password when its room is recreated.
    /// </summary>
    public bool HasSameJoinCredentials(AgentConfig? other) =>
        other is not null
        && string.Equals(NodeName, other.NodeName, StringComparison.Ordinal)
        && string.Equals(ServerUrl, other.ServerUrl, StringComparison.Ordinal)
        && string.Equals(RoomCode, other.RoomCode, StringComparison.Ordinal)
        && string.Equals(Password, other.Password, StringComparison.Ordinal);

    public static string? FilterSecondary(
        string primaryUrl, string? secondary, string label,
        Action<string>? log = null)
    {
        if (string.IsNullOrWhiteSpace(secondary)) return null;
        var trimmed = secondary.Trim().TrimEnd('/');
        if (!Uri.TryCreate(primaryUrl.Trim().TrimEnd('/'), UriKind.Absolute,
                out var primary))
            return null;
        var probe = new EndpointRoster(primaryUrl);
        if (!probe.IsTrustedSecondary(trimmed, primary))
        {
            log?.Invoke(
                $"[AGENT] đã loại {label} không tin cậy: "
                + EndpointRoster.SanitizeEndpointForLog(trimmed));
            return null;
        }
        if (!EndpointRoster.TryValidateEndpoint(trimmed, primary, out var err))
        {
            log?.Invoke(
                $"[AGENT] đã loại {label} không hợp lệ: {err}");
            return null;
        }
        return trimmed;
    }

    public void SaveEndpoints(string? lanUrl, string? tunnelUrl)
    {
        var path = ResolveConfigPath();
        try
        {
            WriteProtectedConfig(path, this with
            {
                LanUrl = lanUrl,
                TunnelUrl = tunnelUrl,
            });
        }
        catch (Exception ex)
        {
            // Không chặn vòng chính; không lộ password trong log
            Console.Error.WriteLine(
                $"[AGENT] không ghi được config.json: {ex.GetType().Name}");
        }
    }

    /// <summary>
    /// Bí mật join dùng DPAPI LocalMachine để không lệch tài khoản UAC; file config
    /// không mang password thuần văn bản và ACL giới hạn Administrators/SYSTEM.
    /// </summary>
    public static string ProtectPassword(string password)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(password);
        var bytes = Encoding.UTF8.GetBytes(password);
        var encrypted = ProtectDpapi(bytes);
        return Convert.ToBase64String(encrypted);
    }

    public static string UnprotectPassword(string protectedValue)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(protectedValue);
        var encrypted = Convert.FromBase64String(protectedValue);
        var bytes = UnprotectDpapi(encrypted);
        return Encoding.UTF8.GetString(bytes);
    }

    /// <summary>Schema config mới: chỉ ghi passwordProtected, không ghi password.</summary>
    public static void WriteProtectedConfig(string path, AgentConfig config)
    {
        var obj = new Dictionary<string, object?>
        {
            ["nodeName"] = config.NodeName,
            ["serverUrl"] = config.ServerUrl,
            ["roomCode"] = config.RoomCode,
            ["passwordProtected"] = ProtectPassword(config.Password),
            ["passwordScope"] = "LocalMachine",
            ["lanUrl"] = config.LanUrl,
            ["tunnelUrl"] = config.TunnelUrl,
        };
        AtomicWriteJson(path, obj);
        RestrictConfigAcl(path);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob
    {
        public int Size;
        public IntPtr Data;
    }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CryptProtectData(ref DataBlob input,
        string? description, IntPtr optionalEntropy, IntPtr reserved,
        IntPtr promptStruct, int flags, out DataBlob output);

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CryptUnprotectData(ref DataBlob input,
        IntPtr description, IntPtr optionalEntropy, IntPtr reserved,
        IntPtr promptStruct, int flags, out DataBlob output);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr LocalFree(IntPtr memory);

    private const int CryptProtectLocalMachine = 0x4;

    private static byte[] ProtectDpapi(byte[] input) =>
        InvokeDpapi(input, protect: true);

    private static byte[] UnprotectDpapi(byte[] input) =>
        InvokeDpapi(input, protect: false);

    private static byte[] InvokeDpapi(byte[] input, bool protect)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("DPAPI chỉ hỗ trợ Windows.");
        var inputBlob = new DataBlob
        {
            Size = input.Length,
            Data = Marshal.AllocHGlobal(input.Length),
        };
        try
        {
            Marshal.Copy(input, 0, inputBlob.Data, input.Length);
            DataBlob output;
            var ok = protect
                ? CryptProtectData(ref inputBlob, null, IntPtr.Zero, IntPtr.Zero,
                    IntPtr.Zero, CryptProtectLocalMachine, out output)
                : CryptUnprotectData(ref inputBlob, IntPtr.Zero, IntPtr.Zero,
                    IntPtr.Zero, IntPtr.Zero, 0, out output);
            if (!ok)
                throw new CryptographicException(Marshal.GetLastWin32Error());
            try
            {
                var result = new byte[output.Size];
                Marshal.Copy(output.Data, result, 0, output.Size);
                return result;
            }
            finally
            {
                if (output.Data != IntPtr.Zero) LocalFree(output.Data);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(inputBlob.Data);
        }
    }

    /// <summary>Ghi temp cùng thư mục → flush → Replace (atomic trên Windows).</summary>
    private static void RestrictConfigAcl(string path)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            // icacls là công cụ tích hợp Windows. ArgumentList không đưa bí mật vào
            // shell command và vẫn xử lý đúng đường dẫn có khoảng trắng.
            using var process = System.Diagnostics.Process.Start(
                new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "icacls.exe",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardError = true,
                    RedirectStandardOutput = true,
                    ArgumentList =
                    {
                        path,
                        "/inheritance:r",
                        "/grant:r",
                        "*S-1-5-18:(F)",
                        "*S-1-5-32-544:(F)",
                    },
                });
            process?.WaitForExit(10_000);
            if (process is null || process.ExitCode != 0)
                throw new InvalidOperationException("icacls không đặt được ACL");
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException(
                "Không thể giới hạn ACL cho cấu hình agent.", ex);
        }
    }

    public static void AtomicWriteJson(string path, object obj)
    {
        var dir = Path.GetDirectoryName(path) ?? ".";
        Directory.CreateDirectory(dir);
        var tmp = Path.Combine(dir, $".config.{Guid.NewGuid():N}.tmp");
        var json = JsonSerializer.Serialize(obj,
            new JsonSerializerOptions { WriteIndented = true });
        try
        {
            File.WriteAllText(tmp, json);
            using (var fs = new FileStream(tmp, FileMode.Open, FileAccess.ReadWrite,
                       FileShare.None))
            {
                fs.Flush(true);
            }
            File.Move(tmp, path, overwrite: true);
        }
        catch
        {
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch { /* ignore */ }
            throw;
        }
    }
}
