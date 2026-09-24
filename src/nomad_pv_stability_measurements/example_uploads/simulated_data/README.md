# Simulated ISOS stability runs

One simulated run of every ISOS protocol in [`isos/`](isos/), each taking the first of the
protocol's options: `ISOS-L-2 (65 °C, MPP)`, `ISOS-LC-1 (MPP, 2 h, 1:1)`, and so on. **Nothing
here was measured.** The runs show what a stability measurement looks like in NOMAD, and which
protocol entry it followed.

## One folder per run

```
ISOS-L-2/
  ISOS-L-2.run.yaml         who ran what, when, where, on which cell, and the steps in order
  01_jv_initial.csv         J–V sweep of the fresh cell, reverse then forward
  02_stability_series.csv   every quantity logged over one week, one row per sample
  03_jv_at_24_h.csv         J–V sweeps during the ageing, once a day
  …
  09_jv_final.csv           J–V sweep after the ageing
```

Each run becomes a *StabilityMeasurement* entry whose steps hold the data, and whose *plan* is
the protocol entry named in the run file (`protocol` and `variant`).

- **The stability series** has a `time` column and one column per quantity the protocol monitors
  or controls (a controller logs what it regulates), each with its unit in the header:
  `temperature (°C)`, `irradiance (W/m^2)`, `relative_humidity (%)`, and where the maximum
  power point is tracked or the cell biased, `voltage (V)`, `current_density (mA/cm^2)` and
  `power_density (mW/cm^2)`. A test in the dark has no irradiance column.
- **J–V sweeps during the ageing:** every ISOS protocol repeats its J–V scans without saying how
  often, so the runs take one every 24 h, and their `notes` say so.
- **A J–V sweep** lists `voltage (V)`, `current_density (mA/cm^2)` and `direction`, `reverse` or
  `forward`, one row per point.
- **The run file** says `institution: SIM`. That is how the parser knows which format it is
  reading: other institutions' files are laid out differently.

## How it was simulated

The conditions follow the protocol: held values with a little noise, a solar simulator drifting
within 800–1000 W/m², light–dark cycles, temperature cycles, an ambient room, an outdoor day
with clouds, a bias at the point of the fresh cell's J–V curve it names. Where the protocol
leaves something open, such as the pace of a temperature cycle, the run's `notes` say what was
assumed. The cell starts at 20 % and loses efficiency faster when
hot, lit and humid.
