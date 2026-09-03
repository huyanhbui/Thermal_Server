// Bootstrapper một file. Executable phát hành nhúng payload phiên bản và giải nén
// vào ProgramData sau một lần UAC thông thường.
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;

const string PayloadResource = "Thermal.Payload.zip";
const string PayloadHashFile = "payload-hash.txt";
var command = args.FirstOrDefault()?.TrimStart('-').ToLowerInvariant() ?? "install";
if (command is not ("install" or "repair" or "update" or "uninstall"))
{
    Console.Error.WriteLine(
        "Dùng: ThermalOrchestrator.exe [--install|--repair|--update|--uninstall]");
    return 2;
}
if (!OperatingSystem.IsWindows())
{
    Console.Error.WriteLine("Thermal Orchestrator chỉ hỗ trợ Windows x64.");
    return 2;
}
if (!IsAdministrator())
    return RelaunchElevated(args);

var installRoot = Path.Combine(Environment.GetFolderPath(
    Environment.SpecialFolder.CommonApplicationData), "ThermalOrchestrator");
if (command == "uninstall")
{
    Console.WriteLine("Uninstall is intentionally delegated to the installed runbook.");
    Console.WriteLine($"Dữ liệu vẫn được giữ tại {installRoot}.");
    return 0;
}

using var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream(
    PayloadResource);
if (payload is null)
{
    Console.Error.WriteLine("Gói cài đặt thiếu payload. Hãy build bằng publish_orchestrator.ps1.");
    return 1;
}
var payloadHash = ComputePayloadHash(payload);
Directory.CreateDirectory(installRoot);
var staging = Path.Combine(installRoot, ".staging-" + Guid.NewGuid().ToString("N"));
string? destination = null;
string? previousDestination = null;
try
{
    Directory.CreateDirectory(staging);
    using (var archive = new ZipArchive(payload, ZipArchiveMode.Read))
        ExtractSafely(archive, staging);

    var manifestPath = Path.Combine(staging, "payload-manifest.json");
    var version = ReadVersion(manifestPath);
    File.WriteAllText(Path.Combine(staging, PayloadHashFile), payloadHash);
    var versionsRoot = Path.Combine(installRoot, "versions");
    Directory.CreateDirectory(versionsRoot);
    // Bản mới có thư mục đích khác bản đang chạy. Dừng payload cũ trước khi
    // kiểm tra thư mục đích, nếu không cổng 8000 vẫn bị Host cũ giữ lại.
    if (command == "update")
        StopRunningPayloadProcesses(versionsRoot);
    destination = Path.Combine(versionsRoot, version);
    var replaceInstalled = command is "repair" or "update";
    if (Directory.Exists(destination) && !replaceInstalled)
    {
        // Hai lần build khác nhau có thể mang cùng nhãn version (ví dụ "dev").
        // So hash payload thay vì so tên, nếu không install sẽ âm thầm khởi
        // động lại đúng bản cũ và người dùng tưởng bản mới không có tác dụng.
        if (string.Equals(
                ReadInstalledHash(Path.Combine(destination, PayloadHashFile)),
                payloadHash, StringComparison.OrdinalIgnoreCase))
        {
            Console.WriteLine($"Thermal Orchestrator {version} đã được cài.");
            StartHost(destination);
            return 0;
        }
        Console.WriteLine(
            $"Phiên bản {version} đã cài nhưng nội dung khác; đang cài đè.");
        StopRunningPayloadProcesses(versionsRoot);
    }
    if (Directory.Exists(destination))
    {
        if (command == "repair")
        {
            Directory.Delete(destination, recursive: true);
        }
        else
        {
            // Giữ nguyên payload đang chạy cho đến khi payload mới giải nén xong.
            // Bản cập nhật lỗi có thể trả về thư mục cũ thay vì làm hỏng host.
            previousDestination = destination + ".previous-"
                + Guid.NewGuid().ToString("N");
            Directory.Move(destination, previousDestination);
        }
    }
    Directory.Move(staging, destination);
    staging = string.Empty;
    WriteCurrentVersion(installRoot, version);
    if (!string.IsNullOrWhiteSpace(previousDestination)
        && Directory.Exists(previousDestination))
    {
        try
        {
            Directory.Delete(previousDestination, recursive: true);
        }
        catch (IOException)
        {
            // Không biến một update đã hoàn tất thành lỗi chỉ vì antivirus còn giữ file cũ.
            Console.Error.WriteLine("Không thể dọn payload cũ; sẽ dọn ở lần repair sau.");
        }
    }
    Console.WriteLine($"Đã cài Thermal Orchestrator {version} tại {destination}");
    StartHost(destination);
    return 0;
}
catch (Exception ex)
{
    try
    {
        if (!string.IsNullOrWhiteSpace(previousDestination)
            && Directory.Exists(previousDestination)
            && !string.IsNullOrWhiteSpace(destination)
            && !Directory.Exists(destination))
        {
            Directory.Move(previousDestination, destination);
        }
    }
    catch (IOException)
    {
        Console.Error.WriteLine("Không thể tự hoàn tác payload cũ; chạy --repair để khôi phục.");
    }
    Console.Error.WriteLine($"Cài đặt thất bại: {ex.GetType().Name}");
    return 1;
}
finally
{
    if (!string.IsNullOrWhiteSpace(staging) && Directory.Exists(staging))
        Directory.Delete(staging, recursive: true);
}

static bool IsAdministrator()
{
    using var identity = WindowsIdentity.GetCurrent();
    return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
}

static int RelaunchElevated(string[] args)
{
    try
    {
        using var process = System.Diagnostics.Process.Start(
            new System.Diagnostics.ProcessStartInfo
            {
                FileName = Environment.ProcessPath!,
                Arguments = string.Join(" ", args.Select(Quote)),
                UseShellExecute = true,
                Verb = "runas",
            });
        process?.WaitForExit();
        return process?.ExitCode ?? 1;
    }
    catch (System.ComponentModel.Win32Exception)
    {
        Console.Error.WriteLine("Cần quyền Administrator để cài đặt theo máy.");
        return 1;
    }
}

static string Quote(string value) => '"' + value.Replace("\"", "\\\"") + '"';

static void ExtractSafely(ZipArchive archive, string destination)
{
    var root = Path.GetFullPath(destination) + Path.DirectorySeparatorChar;
    foreach (var entry in archive.Entries)
    {
        if (string.IsNullOrEmpty(entry.Name)) continue;
        var path = Path.GetFullPath(Path.Combine(destination, entry.FullName));
        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Payload contains an invalid path.");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        entry.ExtractToFile(path, overwrite: true);
    }
}

static string ComputePayloadHash(Stream payload)
{
    var hash = Convert.ToHexString(SHA256.HashData(payload));
    payload.Position = 0;
    return hash;
}

static string? ReadInstalledHash(string path)
{
    if (!File.Exists(path))
        return null;
    try
    {
        return File.ReadAllText(path).Trim();
    }
    catch (IOException)
    {
        // Không đọc được nghĩa là không chứng minh được bản cài còn nguyên vẹn;
        // coi như khác payload và cài lại.
        return null;
    }
}

static string ReadVersion(string manifestPath)
{
    using var doc = JsonDocument.Parse(File.ReadAllText(manifestPath));
    var version = doc.RootElement.GetProperty("version").GetString();
    if (string.IsNullOrWhiteSpace(version)
        || version.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0
        || version.Contains("..", StringComparison.Ordinal))
        throw new InvalidDataException("Payload version is invalid.");
    return version;
}

static void WriteCurrentVersion(string installRoot, string version)
{
    var path = Path.Combine(installRoot, "current.json");
    var temp = path + ".tmp";
    File.WriteAllText(temp, JsonSerializer.Serialize(new { version }));
    File.Move(temp, path, overwrite: true);
}

static void StopRunningPayloadProcesses(string versionsRoot)
{
    // Chỉ đụng đúng runtime nằm dưới ProgramData của ứng dụng này. Không dùng
    // tên tiến trình đơn thuần vì máy có thể đang chạy Python/NodeAgent khác.
    var root = Path.GetFullPath(versionsRoot) + Path.DirectorySeparatorChar;
    foreach (var name in new[] { "python", "NodeAgent" })
    {
        foreach (var process in System.Diagnostics.Process.GetProcessesByName(name))
        {
            try
            {
                var path = TryGetExecutablePath(process);
                if (string.IsNullOrWhiteSpace(path)
                    || !Path.GetFullPath(path).StartsWith(root,
                        StringComparison.OrdinalIgnoreCase))
                    continue;
                process.Kill(entireProcessTree: true);
                process.WaitForExit(10_000);
            }
            catch (InvalidOperationException)
            {
                // Tiến trình vừa thoát; payload không còn bị giữ file.
            }
            catch (System.ComponentModel.Win32Exception)
            {
                // UAC có thể che thông tin một tiến trình khác; không đụng nó.
            }
        }
    }
}

static string? TryGetExecutablePath(System.Diagnostics.Process process)
{
    try
    {
        return process.MainModule?.FileName;
    }
    catch (System.ComponentModel.Win32Exception)
    {
        // A non-elevated updater cannot inspect MainModule of an elevated Host.
        // WMIC remains available on supported Windows builds and lets us verify
        // the exact executable path before stopping anything.
    }

    try
    {
        using var query = System.Diagnostics.Process.Start(
            new System.Diagnostics.ProcessStartInfo
            {
                FileName = "wmic.exe",
                Arguments = $"process where ProcessId={process.Id} "
                    + "get ExecutablePath /value",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
        if (query is null)
            return null;
        var output = query.StandardOutput.ReadToEnd();
        query.WaitForExit(3_000);
        foreach (var line in output.Split(new[] { '\r', '\n' },
                     StringSplitOptions.RemoveEmptyEntries))
        {
            const string prefix = "ExecutablePath=";
            if (line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                return line[prefix.Length..].Trim();
        }
    }
    catch (System.ComponentModel.Win32Exception)
    {
        // WMIC can be removed from newer Windows installations. In that case,
        // preserve the conservative behavior and leave unknown processes alone.
    }
    catch (System.InvalidOperationException)
    {
        // The process exited while the fallback was running.
    }
    return null;
}

static void StartHost(string destination)
{
    var startScript = Path.Combine(destination, "Start-Host.cmd");
    if (!File.Exists(startScript))
        throw new InvalidDataException("Gói cài đặt thiếu Start-Host.cmd.");
    // ShellExecute trên file .cmd có thể bị AppLocker/UAC từ chối dù payload
    // đã cài thành công. Gọi cmd.exe trực tiếp để Host luôn được khởi động.
    var startInfo = new System.Diagnostics.ProcessStartInfo
    {
        FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
        WorkingDirectory = destination,
        UseShellExecute = false,
        CreateNoWindow = true,
    };
    startInfo.ArgumentList.Add("/d");
    startInfo.ArgumentList.Add("/c");
    startInfo.ArgumentList.Add(startScript);
    System.Diagnostics.Process.Start(startInfo);
    Console.WriteLine("Host đang khởi động tại http://127.0.0.1:8000/");
}
