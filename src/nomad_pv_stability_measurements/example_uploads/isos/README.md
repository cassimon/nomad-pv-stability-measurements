# ISOS stability protocols

The protocols of **ISOS Table 1**, from Khenkin, M. V., Katz, E. A., Abate, A. *et al.*,
"Consensus statement for stability assessment and reporting for perovskite photovoltaics based on
ISOS procedures", *Nature Energy* **5**, 35–49 (2020), <https://doi.org/10.1038/s41560-019-0529-5>.

Open any of them in the ELN, or copy one and add what your own run needs.

| Family | What it stresses | Protocols |
|---|---|---|
| ISOS-D | Dark storage | 5 |
| ISOS-V | Electrical bias, in the dark | 25 |
| ISOS-L | Light soaking under a solar simulator | 11 |
| ISOS-O | Outdoor exposure to sunlight | 7 |
| ISOS-T | Thermal cycling, in the dark | 5 |
| ISOS-LC | Light–dark cycling | 54 |
| ISOS-LT | Solar-thermal cycling | 10 |

Within each family the number is the level of sophistication: **1** needs the least equipment,
**3** the most. Not written yet: **ISOS-LC-3** and the **ISOS-I** protocols in an inert
atmosphere — see [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md).

## One file per standard, one entry per option

Where the standard offers options — two temperatures, MPP tracking, open circuit or a fixed
voltage near the MPP, five biases, a light–dark cycle period and duty cycle — the section they
belong to lists them under `options:`, and every combination becomes its own protocol entry.

```yaml
channel_settings:
  temperature:
    options:
      - hold: 65 °C                            # a single value is its own label
      - hold: 85 °C
```

Each alternative's keys are written into the section that lists it; a key is written beside the
options or inside them, never both. An alternative may list options of its own. The light–dark
cycles repeat their light command with a YAML anchor (`&light`, `<<: *light`).

Each entry is named after its alternatives, in the order the file writes them, and they are its
`standard_variant`:

```
ISOS-D-1                                          no options
ISOS-D-2 (65 °C)                                  standard_variant: 65 °C
ISOS-V-3 (65 °C, −J_MPP)
ISOS-LC-2 (85 °C, MPP, 24 h, 1:2)
ISOS-L-1 (MPP)
```

Search for `standard` to find every variant of a protocol, and for `standard_variant` to find one.

## Reading one

```yaml
channel_settings:          # conditions that hold for the whole test
  temperature: {hold: RT, control: false, monitor: true}              # assumed 23 ± 4 °C
  atmosphere: {variable: relative_humidity, control: false, monitor: true}   # ambient
  electrical_load: {hold: mpp}
instructions:              # a second atmosphere setting: one channel, one setting above
  - {channel: atmosphere, variable: oxygen, reference_point: ambient air}
routine:                   # only what changes during the test
  repeat: indefinitely
  instructions:
    - {channel: irradiation, control: true, hold_between: {lower: 800 W/m^2, upper: 1000 W/m^2}, duration: 8 h}
    - {channel: irradiation, hold: dark, duration: 16 h}
```

**Only what the standard states is written.** There is **no test duration, sampling interval or
measurement schedule** in any file, because the standard fixes none — add your own. A light–dark
cycle states its period, and repeats for as long as your test runs.

- **Every test here runs in ambient air.** Only the protocols marked "I" run in an inert
  atmosphere, so the oxygen is written as `reference_point: ambient air`, stated but neither
  regulated nor measured.
- **Ambient means monitored, not regulated.** The standard assumes room temperature to be
  23 ± 4 °C without controlling it, and asks for every uncontrolled condition to be monitored and
  reported: `control: false`, `monitor: true`.
- **What is measured is monitored, controlled or not.** The standard asks for the parameters of
  its Table 3 to be monitored and reported "even if a parameter is not controlled" (p.43): a held
  temperature (its sensor is reported), a light source (its exact irradiance, checked with a
  reference cell, p.44), a controlled humidity, and MPP tracking, which measures the output while
  it holds the point. They write `monitor: true` beside what they control. Darkness, open circuit
  and a fixed bias are conditions to report, not readings, and are not monitored.
- **Humidity is relative humidity**, as the standard states it (`85 %`), with no temperature
  beside it.
- **A bias measured on the device** says which point in `reference_point` (`V_MPP`, `-J_MPP`, …):
  the protocol cannot know the number before the fresh device is measured.
- **A solar simulator is held between 800 and 1000 W/m².** The standard recommends that range
  ("Ideally, light sources with an irradiance of 800–1000 W m–² … should be applied", p.43), and
  the files read it as what the light is held at: `hold_between: {lower: 800 W/m^2, upper:
  1000 W/m^2}` — a range, with no target inside it.
- **A cycle is a ramp that repeats.** Linear ramping up and down is `end_of_ramp_behavior:
  triangle`. Where the standard states the two ends and not the path — ISOS-T's "RT to 65 °C",
  ISOS-LT-1's step ramping — it is `end_of_ramp_behavior: cycle`, with no rate.
