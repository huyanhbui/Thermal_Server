// Trapezoidal ∫ power_w dt during a job. Sensor → energy_source=sensor.
// If sensor silent but PowerModel available → energy_source=model (Tier 2 only).
// Never fabricate joules without a labelled source (invariant #4).
// Chỉ tích phân cặp sample cùng nguồn LIỀN KỀ trên timeline — không bridge qua gap.
namespace NodeAgent;

public sealed class EnergySampler
{
    private readonly List<(double T, double? W, string Src)> _samples = new();
    private readonly PowerModelEstimator? _model;

    public EnergySampler(PowerModelEstimator? model = null)
    {
        _model = model;
    }

    public void Sample(double? powerW, double? cpuUtil = null,
                       double? cpuTemp = null)
    {
        var t = Environment.TickCount64 / 1000.0;
        SampleAt(t, powerW, cpuUtil, cpuTemp);
    }

    /// <summary>Cho test: gắn timestamp tường minh.</summary>
    public void SampleAt(double t, double? powerW, double? cpuUtil = null,
                         double? cpuTemp = null)
    {
        if (powerW is not null)
        {
            _samples.Add((t, powerW, "sensor"));
            return;
        }
        if (_model is not null && cpuUtil is not null)
        {
            var est = _model.EstimateW(cpuUtil, cpuTemp);
            if (est is not null)
            {
                _samples.Add((t, est, "model"));
                return;
            }
        }
        _samples.Add((t, null, "none"));
    }

    public (double? EnergyJ, string EnergySource) Finalize()
    {
        if (_samples.Count == 0)
            return (null, "none");

        // Chỉ cặp liền kề cùng Src trên timeline gốc (không lọc rồi nối).
        double sensorJ = 0;
        var sensorPairs = 0;
        double modelJ = 0;
        var modelPairs = 0;
        for (var i = 1; i < _samples.Count; i++)
        {
            var (t0, w0, s0) = _samples[i - 1];
            var (t1, w1, s1) = _samples[i];
            if (w0 is null || w1 is null || s0 != s1 || s0 == "none")
                continue;
            var dt = t1 - t0;
            if (dt <= 0) continue;
            var add = 0.5 * (w0.Value + w1.Value) * dt;
            if (s0 == "sensor")
            {
                sensorJ += add;
                sensorPairs++;
            }
            else if (s0 == "model")
            {
                modelJ += add;
                modelPairs++;
            }
        }

        if (sensorPairs >= 1)
            return (sensorJ, "sensor");
        if (modelPairs >= 1)
            return (modelJ, "model");
        return (null, "none");
    }
}
