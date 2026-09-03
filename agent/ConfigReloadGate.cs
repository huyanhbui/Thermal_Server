// Cổng nạp lại config theo mtime: chỉ đọc file khi Host đã ghi lại nó.
// Tách khỏi Program.cs để kiểm được hành vi "nạp lỗi thì vẫn thử lại".
namespace NodeAgent;

/// <summary>
/// Ghi nhớ mtime của config đã nạp thành công. Mốc thời gian chỉ được đẩy lên
/// SAU khi nạp thành công: nếu một lần đọc thất bại (file đang bị ghi, DPAPI
/// lỗi tạm thời) mà đã đẩy mốc thì lần ghi đó bị "đốt" và worker không bao giờ
/// thử lại cho tới lần Host ghi kế tiếp — tức là mất cặp thông tin đăng nhập
/// mới trong khi vẫn phát lại bí mật cũ đã bị Host loại bỏ.
/// </summary>
public sealed class ConfigReloadGate
{
    private readonly Func<DateTime> _readStamp;
    private DateTime _seen;

    public ConfigReloadGate(Func<DateTime> readStamp)
    {
        _readStamp = readStamp;
        // Đọc mốc trước lần nạp đầu tiên: Host ghi chen vào giữa vẫn được lần
        // nạp lại kế tiếp phát hiện, thay vì bị bỏ qua vĩnh viễn.
        _seen = readStamp();
    }

    /// <summary>
    /// True kèm config mới khi file đổi và nạp được. False khi file không đổi
    /// hoặc nạp lỗi — trường hợp lỗi giữ nguyên mốc cũ để còn thử lại.
    /// </summary>
    public bool TryReload(Func<AgentConfig> load, out AgentConfig? loaded,
        Action<Exception>? onLoadFailed = null)
    {
        loaded = null;
        var stamp = _readStamp();
        if (stamp == _seen)
            return false;
        try
        {
            loaded = load();
        }
        catch (Exception ex)
        {
            onLoadFailed?.Invoke(ex);
            return false;
        }
        _seen = stamp;
        return true;
    }
}
