// Stage 2 telemetry: reads CPU/GPU temperature, CPU utilization, package
// power, clock and fan via LibreHardwareMonitor. HARDWARE SENSORS ONLY —
// this file is the entire surface touching the machine; it never reads
// files or user data. Clock/fan may be null when the chipset does not expose them.
using LibreHardwareMonitor.Hardware;

public record TelemetrySample(double? CpuTemp, double? GpuTemp,
                              double? CpuUtil, double? PowerW,
                              double? CpuClockMhz = null,
                              double? FanRpm = null);

public sealed class SensorReader : IDisposable
{
    private readonly Computer _computer;

    public SensorReader()
    {
        _computer = new Computer
        {
            IsCpuEnabled = true,
            IsGpuEnabled = true,
            IsMotherboardEnabled = true,
        };
        _computer.Open();   // needs Administrator (kernel driver for CPU temps)
    }

    public TelemetrySample Read()
    {
        double? cpuTemp = null, gpuTemp = null, cpuUtil = null, powerW = null;
        double? clock = null, fan = null;
        foreach (var hw in _computer.Hardware)
        {
            hw.Update();
            if (hw.HardwareType == HardwareType.Cpu)
            {
                cpuTemp = PickTemp(hw, "Package", "Tctl");
                cpuUtil = FindSensor(hw, SensorType.Load, "CPU Total");
                powerW  = FindSensor(hw, SensorType.Power, "Package")
                          ?? FindSensor(hw, SensorType.Power, null);
                clock   = FindSensor(hw, SensorType.Clock, "Core")
                          ?? FindSensor(hw, SensorType.Clock, null);
            }
            else if (hw.HardwareType is HardwareType.GpuNvidia
                     or HardwareType.GpuAmd or HardwareType.GpuIntel)
            {
                gpuTemp ??= FindSensor(hw, SensorType.Temperature, "GPU Core")
                            ?? FindSensor(hw, SensorType.Temperature, null);
            }
            else if (hw.HardwareType == HardwareType.Motherboard)
            {
                fan ??= FindSensor(hw, SensorType.Fan, null);
                foreach (var sub in hw.SubHardware)
                {
                    sub.Update();
                    fan ??= FindSensor(sub, SensorType.Fan, null);
                }
            }
        }
        return new TelemetrySample(cpuTemp, gpuTemp, cpuUtil, powerW,
                                   clock, fan);
    }

    // Prefer a named sensor (e.g. "CPU Package"); fall back to the max of all
    // temperature sensors on the chip so per-core-only CPUs still report.
    private static double? PickTemp(IHardware hw, params string[] preferredNames)
    {
        foreach (var name in preferredNames)
        {
            var v = FindSensor(hw, SensorType.Temperature, name);
            if (v is not null) return v;
        }
        var all = hw.Sensors.Where(s => s.SensorType == SensorType.Temperature
                                        && s.Value is not null)
                            .Select(s => (double)s.Value!.Value).ToList();
        return all.Count > 0 ? all.Max() : null;
    }

    private static double? FindSensor(IHardware hw, SensorType type, string? nameContains)
    {
        var s = hw.Sensors.FirstOrDefault(s => s.SensorType == type
            && s.Value is not null
            && (nameContains is null || s.Name.Contains(nameContains,
                    StringComparison.OrdinalIgnoreCase)));
        return s?.Value is float v ? (double)v : null;
    }

    public void Dispose() => _computer.Close();
}
