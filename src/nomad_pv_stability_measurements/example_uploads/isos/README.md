# ISOS stability protocols

The protocols of **ISOS Table 1**, from Khenkin, M. V., Katz, E. A., Abate, A. *et al.*,
"Consensus statement for stability assessment and reporting for perovskite photovoltaics based on
ISOS procedures", *Nature Energy* **5**, 35–49 (2020), <https://doi.org/10.1038/s41560-019-0529-5>.

Open any of them in the ELN, or copy one and add what your own run needs.

| Family | What it stresses | Protocols |
|---|---|---|
| ISOS-D | Dark storage | 6 |
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
    control: true
    options:
      - specify: 65 °C                         # a single value is its own label
      - specify: 85 °C
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
  temperature: {specify: RT, monitor: true}                 # assumed 23 ± 4 °C, logged
  atmosphere:              # a channel of several variables: one setting each
    - {variable: relative_humidity, specify: ambient, monitor: true}  # Table 1's "Ambient"
    - {variable: oxygen, specify: ambient}                  # whatever the air holds
  electrical_load: {specify: mpp, control: true, monitor: true}
routine:                   # only what changes during the test
  repeat: indefinitely
  instructions:
    - {channel: irradiation, specify: {lower: 800 W/m^2, upper: 1000 W/m^2}, control: true, duration: 8 h}
    - {channel: irradiation, specify: dark, duration: 16 h}
```

**Only what the standard states is written.** There is **no test duration or sampling interval**
in any file, and the J–V scans repeat at an interval **not stated**, because the standard fixes
none — add your own. A light–dark
cycle states its period, and repeats for as long as your test runs.

- **Three things are said about each quantity, and each only where the standard says it.**
  `specify` states its value: a number, a named value (`RT`, `dark`), a point (`mpp`,
  `open_circuit`, `V_MPP`), a bound (`{below: 55 %}`), a range (`{lower: …, upper: …}`) or a
  ramp (`{from: …, to: …}`). `control: true` says something regulates it, and `monitor: true`
  that it is logged. None of them implies another: a hot plate set to 65 °C is stated and
  controlled but need not be logged, the ambient humidity is logged but neither stated nor
  regulated, and darkness is stated and nothing more.
- **Every duration says what kind it is.** A setting, in `channel_settings` or `instructions`,
  lasts as long as the test unless it says otherwise. In the `routine`, every instruction writes
  its `duration`: a length (`1 h`), a typical one where the protocol fixes none
  (`typical 1 min`, e.g. a JV scan), `open-ended` where it goes on until the test is stopped
  (the temperature cycles of ISOS-T and ISOS-LT), or `whole block` where it lasts as long as
  the parallel block it is in. A ramp given a `rate` works its duration out.
- **Every test here runs in ambient air.** Only the protocols marked "I" run in an inert
  atmosphere, so the oxygen is written `specify: ambient`: whatever the air around the sample
  holds, which need not be the 21 % of fresh air in a laboratory with people and flames in it.
  Stated, but neither regulated nor measured. It is the atmosphere's second setting, beside the
  humidity.
- **A humidity controlled only above 40 °C** (ISOS-T-3's "< 55%", ISOS-LT-2/-3's "controlled
  at 50% beyond 40 °C") is stated and monitored, but not written as controlled: control that
  depends on the temperature cannot be written yet, so the condition is in `notes`.
- **Ambient is stated, monitored, and not regulated.** Where Table 1 writes "Ambient", the file
  writes `specify: ambient`: whatever the laboratory or the weather gives, with no number. Where
  it writes "Ambient (23 ± 4 °C)", it writes `specify: RT`, the room temperature the standard
  assumes (p.36). Either is monitored, since the standard asks for every uncontrolled condition
  to be monitored and reported "even if a parameter is not controlled" (p.43); outdoors, the
  weather "preferably in tabulated format" (Table 3). ISOS-LT-1's humidity is "Monitored,
  uncontrolled", with nothing stated.
- **What is controlled is not also logged, unless the standard says so.** The standard asks for
  a controlled temperature's "sensor type" and for "RH (controlled or monitored)" (Table 3), and
  for the exact irradiance to be reported and checked periodically with a reference cell
  (p.43–44): things to report, not records. MPP tracking is monitored, since the tracker
  "measures the output" while it holds the point (p.43).
- **Humidity is relative humidity**, as the standard states it (`85 %`), with no temperature
  beside it.
- **A bias measured on the device** is specified by its point (`V_MPP`, `-J_MPP`, …): the
  protocol cannot know the number before the fresh device is measured.
- **J–V curves are measured periodically**, as a protocol instruction of its own:
  `jv_scan: {every: not stated, light_source: solar simulator}`, under Table 1's
  "Characterization light source", which may differ from the light the cell ages under:
  ISOS-O-2 measures under sunlight, ISOS-O-1 and -O-3 under a solar simulator, ISOS-D-1
  under either (two variants). ISOS-V adds one scan of the fresh device at one sun, AM1.5G,
  from which its biases are taken. Write your interval as `every: 10 min`, or
  `every: typical 1 h` where it is only a typical one.
- **The light says where it comes from.** `light_source: solar simulator` (ISOS-L, -LC, -LT)
  names no lamp and no class, as Table 1 does not; `light_source: sunlight` (ISOS-O) names no
  site, dates or orientation. Write your own: `light_source: {type: xenon lamp,
  solar_simulator: true, simulator_classification: AAA, uv_filter: true}`, or for sunlight
  `{type: sunlight, geo_location: {…}, tilt: 30°, azimuth: 180°, mounting: fixed}`. The types
  are `sunlight`, `artificial light`, `solar simulator`, `LED`, `xenon lamp`,
  `metal halide lamp` and `sulfur plasma lamp`.
- **A solar simulator is held between 800 and 1000 W/m².** The standard recommends that range
  ("Ideally, light sources with an irradiance of 800–1000 W m–² … should be applied", p.43), and
  the files read it as what the light is held at: `specify: {lower: 800 W/m^2, upper:
  1000 W/m^2}` — a range, with no target inside it.
- **A cycle is a ramp that repeats.** Linear ramping up and down is `end_of_ramp_behavior:
  triangle`. Where the standard states the two ends and not the path — ISOS-T's "RT to 65 °C",
  ISOS-LT-1's step ramping — it is `end_of_ramp_behavior: cycle`, with no rate.
