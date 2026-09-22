# Simulated runs that describe their own test

Two simulated runs whose institution keeps no protocol files: each run file describes the test
it ran instead of naming a protocol file. **Nothing here was measured.**

| Run | The test it describes |
|---|---|
| [damp-heat-at-open-circuit](damp-heat-at-open-circuit/damp-heat-at-open-circuit.run.yaml) | 1000 h at 85 °C and 85 %, in the dark, at open circuit |
| [day-and-night-at-45C](day-and-night-at-45C/day-and-night-at-45C.run.yaml) | seven times 12 h under 1000 W/m² at the maximum power point, then 12 h in the dark at open circuit, all at 45 °C |

The run file is in the same format as the other simulated runs, except that where they name a
protocol file under `run`, it says what the test was under `test conditions`: the phases run one
after another, how often the sequence repeats, and the value each quantity is held at.

```yaml
test conditions:
  name: Day and night at 45 °C
  repeat: 7
  phases:
  - {name: day, duration: 12 h, irradiance: 1000 W/m^2, temperature: 45 °C, electrical_load: mpp}
  - {name: night, duration: 12 h, irradiance: dark, temperature: 45 °C, electrical_load: open_circuit}
```

Each run file makes **two entries**: the *StabilityMeasurement* of the run, and a
*StabilityProtocol* built from its test conditions, whose timeline you can open like any other
protocol's. The run's *plan* is that protocol.
