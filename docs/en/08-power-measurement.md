# Power measurement

Power measurement uses the hardware path already exposed by `SensorReader.cs`.
The supporting scripts help inspect available sources, establish an idle
baseline, and fit a power model only where direct measurement is unavailable.

Run the sensor test as Administrator. If package power is unavailable, the node
can still participate in scheduling, but its ESG evidence is inferred or absent
rather than falsely reported as a sensor measurement.
