// Giới hạn tham số job từ host — tránh CPU vô hạn / NaN (finding #13).
namespace NodeAgent;

public static class JobParamGuard
{
    public const int MaxTokensMin = 1;
    public const int MaxTokensMax = 4096;
    public const double TempMin = 0.0;
    public const double TempMax = 2.0;
    public const int DeadlineMinS = 5;
    public const int DeadlineMaxS = 600;
    public const int DurationMinS = 1;
    public const int DurationMaxS = 300;

    public static bool TryClampMaxTokens(int raw, out int value, out string? reason)
    {
        if (raw < MaxTokensMin || raw > MaxTokensMax)
        {
            reason = $"max_tokens={raw} ngoài [{MaxTokensMin},{MaxTokensMax}]";
            value = Math.Clamp(raw, MaxTokensMin, MaxTokensMax);
            return false;
        }
        value = raw;
        reason = null;
        return true;
    }

    public static bool TryClampTemperature(double raw, out double value, out string? reason)
    {
        if (double.IsNaN(raw) || double.IsInfinity(raw)
            || raw < TempMin || raw > TempMax)
        {
            reason = $"temperature={raw} không hợp lệ (cần [{TempMin},{TempMax}] finite)";
            value = double.IsFinite(raw) ? Math.Clamp(raw, TempMin, TempMax) : 0.7;
            return false;
        }
        value = raw;
        reason = null;
        return true;
    }

    public static bool TryClampDeadlineS(int raw, out int value, out string? reason)
    {
        if (raw < DeadlineMinS || raw > DeadlineMaxS)
        {
            reason = $"deadline_s={raw} ngoài [{DeadlineMinS},{DeadlineMaxS}]";
            value = Math.Clamp(raw, DeadlineMinS, DeadlineMaxS);
            return false;
        }
        value = raw;
        reason = null;
        return true;
    }

    public static bool TryClampDurationS(int raw, out int value, out string? reason)
    {
        if (raw < DurationMinS || raw > DurationMaxS)
        {
            reason = $"duration_s={raw} ngoài [{DurationMinS},{DurationMaxS}]";
            value = Math.Clamp(raw, DurationMinS, DurationMaxS);
            return false;
        }
        value = raw;
        reason = null;
        return true;
    }

    public static bool TryClampCores(
        int raw, int processorCount, out int value, out string? reason)
    {
        var max = Math.Max(1, processorCount);
        if (raw < 0)
        {
            reason = $"cores={raw} âm — không coi như 0=all";
            value = 1;
            return false;
        }
        if (raw == 0)
        {
            value = 0;
            reason = null;
            return true;
        }
        if (raw > max)
        {
            reason = $"cores={raw} vượt processorCount={max}";
            value = max;
            return false;
        }
        value = raw;
        reason = null;
        return true;
    }
}
