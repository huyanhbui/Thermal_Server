// Trình cấu hình tương tác cho máy khách. Chỉ ghi config cục bộ đã bảo vệ;
// mọi kết nối vẫn luôn do worker chủ động tạo ra ngoài.
using System.Net;

public static class AgentSetup
{
    public static int RunInteractive(string? setupLink = null)
    {
        Console.WriteLine("Thermal Orchestrator — cấu hình máy khách");
        Console.Write("Tên node duy nhất: ");
        var nodeName = Console.ReadLine() ?? string.Empty;
        string endpoint;
        if (!string.IsNullOrWhiteSpace(setupLink))
        {
            endpoint = setupLink;
            Console.WriteLine("Đã nhận link setup worker từ Host.");
        }
        else
        {
            Console.Write("Link LAN hoặc tunnel của Host: ");
            endpoint = Console.ReadLine() ?? string.Empty;
        }
        Console.Write("Mã phòng (để trống nếu link có ?code=): ");
        var roomCode = Console.ReadLine();
        Console.Write("Mật khẩu worker: ");
        var password = ReadPassword();
        Console.WriteLine();

        if (!TryCreateConfig(nodeName, endpoint, roomCode, password, out var config,
                out var error))
        {
            Console.Error.WriteLine($"Không thể cấu hình máy khách: {error}");
            return 2;
        }
        try
        {
            AgentConfig.WriteProtectedConfig(AgentConfig.ResolveConfigPath(), config!);
            Console.WriteLine("Đã lưu cấu hình được bảo vệ cho máy này.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(
                $"Không thể lưu cấu hình máy khách: {ex.GetType().Name}");
            return 1;
        }
    }

    public static bool TryCreateConfig(string? nodeName, string? endpoint,
        string? roomCode, string? password, out AgentConfig? config,
        out string error)
    {
        config = null;
        error = string.Empty;
        if (string.IsNullOrWhiteSpace(nodeName))
        {
            error = "Tên node là bắt buộc.";
            return false;
        }
        if (!Uri.TryCreate(endpoint?.Trim(), UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            error = "Link Host phải là HTTP hoặc HTTPS hợp lệ.";
            return false;
        }
        if (IsLoopback(uri))
        {
            error = "Máy khách không được dùng localhost; hãy nhập LAN hoặc tunnel URL.";
            return false;
        }
        if (string.IsNullOrWhiteSpace(password))
        {
            error = "Mật khẩu worker là bắt buộc.";
            return false;
        }

        var code = roomCode?.Trim();
        if (string.IsNullOrWhiteSpace(code))
        {
            code = ReadQueryValue(uri.Query, "code")?.Trim();
        }
        if (string.IsNullOrWhiteSpace(code))
        {
            error = "Mã phòng bị thiếu trong link hoặc ô nhập.";
            return false;
        }
        config = new AgentConfig(nodeName.Trim(), uri.GetLeftPart(UriPartial.Authority),
            code, password);
        return true;
    }

    private static bool IsLoopback(Uri uri)
    {
        if (uri.IsLoopback || string.Equals(uri.Host, "localhost",
                StringComparison.OrdinalIgnoreCase))
            return true;
        return IPAddress.TryParse(uri.Host, out var address) &&
            IPAddress.IsLoopback(address);
    }

    private static string? ReadQueryValue(string query, string key)
    {
        foreach (var pair in query.TrimStart('?').Split('&',
                     StringSplitOptions.RemoveEmptyEntries))
        {
            var split = pair.Split('=', 2);
            if (split.Length == 2 && string.Equals(Uri.UnescapeDataString(split[0]), key,
                    StringComparison.OrdinalIgnoreCase))
                return Uri.UnescapeDataString(split[1]);
        }
        return null;
    }

    public static string ReadRedirectedPassword(TextReader input) =>
        input.ReadLine() ?? string.Empty;

    private static string ReadPassword()
    {
        if (Console.IsInputRedirected)
            return ReadRedirectedPassword(Console.In);
        var value = new System.Text.StringBuilder();
        ConsoleKeyInfo key;
        while ((key = Console.ReadKey(intercept: true)).Key != ConsoleKey.Enter)
        {
            if (key.Key == ConsoleKey.Backspace && value.Length > 0)
            {
                value.Length--;
                continue;
            }
            if (!char.IsControl(key.KeyChar)) value.Append(key.KeyChar);
        }
        return value.ToString();
    }
}
