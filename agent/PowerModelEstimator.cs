// Offline power model P = a + b·util + c·temp from power_model.json.
// Used only when hardware power sensor is silent → energy_source=model.
using System.Text.Json;

namespace NodeAgent;

public sealed class PowerModelEstimator
{
    private readonly double _a;
    private readonly double _b;
    private readonly double _c;
    private readonly bool _useTemp;

    private PowerModelEstimator(double a, double b, double c, bool useTemp)
    {
        _a = a; _b = b; _c = c; _useTemp = useTemp;
    }

    public static PowerModelEstimator? TryLoad(string? path = null)
    {
        path ??= Path.Combine(AppContext.BaseDirectory, "power_model.json");
        if (!File.Exists(path)) return null;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (!root.TryGetProperty("coefficients", out var coef))
                return null;
            var a = coef.GetProperty("a").GetDouble();
            var b = coef.GetProperty("b").GetDouble();
            var c = coef.TryGetProperty("c", out var cEl) ? cEl.GetDouble() : 0.0;
            var useTemp = root.TryGetProperty("temp_term_used", out var tu)
                && tu.GetBoolean();
            return new PowerModelEstimator(a, b, c, useTemp);
        }
        catch
        {
            return null;
        }
    }

    public double? EstimateW(double? cpuUtil, double? cpuTemp)
    {
        if (cpuUtil is null) return null;
        var p = _a + _b * cpuUtil.Value;
        if (_useTemp && cpuTemp is not null)
            p += _c * cpuTemp.Value;
        return Math.Max(0.0, p);
    }
}
