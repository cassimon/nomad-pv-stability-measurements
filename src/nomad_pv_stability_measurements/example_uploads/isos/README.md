# ISOS stability protocols

The protocols of **ISOS Table 1**, from Khenkin, M. V., Katz, E. A., Abate, A. *et al.*,
"Consensus statement for stability assessment and reporting for perovskite photovoltaics based on
ISOS procedures", *Nature Energy* **5**, 35–49 (2020), <https://doi.org/10.1038/s41560-019-0529-5>.

Open any of them in the ELN, or copy one and add what your own run needs.

| Family | What it stresses | Files |
|---|---|---|
| ISOS-D | Dark storage | 5 |
| ISOS-V | Electrical bias, in the dark | 25 |
| ISOS-L | Light soaking under a solar simulator | 22 |
| ISOS-O | Outdoor exposure to sunlight | 7 |
| ISOS-T | Thermal cycling, in the dark | 5 |
| ISOS-LC | Light–dark cycling | 108 |
| ISOS-LT | Solar-thermal cycling | 20 |

Within each family the number is the level of sophistication: **1** needs the least equipment,
**3** the most. Not written yet: **ISOS-LC-3** and the **ISOS-I** protocols in an inert
atmosphere — see [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md).

## One folder per standard, one file per option

Where the standard offers options — two temperatures, MPP tracking, open circuit or a fixed
voltage near the MPP, five biases, a light–dark cycle period and duty cycle — every combination is
its own protocol, with the options in the file name. A recommendation is an option too: every
solar-simulator protocol comes once without and once with the recommended 800–1000 W/m², named
last:

```
ISOS-D-1/ISOS-D-1.stability.yaml                     no options
ISOS-D-2/ISOS-D-2_65degC.stability.yaml              standard: ISOS-D-2, standard_variant: 65 °C
ISOS-V-3/ISOS-V-3_65degC_minus-Jmpp.stability.yaml   standard_variant: 65 °C, −J_MPP
ISOS-LC-2/ISOS-LC-2_24h_1-2_85degC_MPP.stability.yaml  standard_variant: 24 h, 1:2, 85 °C, MPP
ISOS-L-1/ISOS-L-1_MPP_800-1000Wm2.stability.yaml    standard_variant: MPP, recommended 800–1000 W/m²
```

Search for `standard` to find every variant of a protocol, and for `standard_variant` to find one.

## Reading one

```yaml
channel_settings:          # conditions that hold for the whole test
  temperature: {hold: RT, control: false, monitor: true}              # assumed 23 ± 4 °C
  atmosphere: {variable: relative_humidity, control: false, monitor: true}   # ambient
  electrical_load: {hold: mpp}
routine:                   # only what changes during the test
  repeat: indefinitely
  commands:
    - {channel: irradiation, control: true, duration: 8 h}
    - {channel: irradiation, hold: dark, duration: 16 h}
```

**Only what the standard states is written.** There is **no test duration, sampling interval or
measurement schedule** in any file, because the standard fixes none — add your own. A light–dark
cycle states its period, and repeats for as long as your test runs.

- **Ambient means monitored, not regulated.** The standard assumes room temperature to be
  23 ± 4 °C without controlling it, and asks for every uncontrolled condition to be monitored and
  reported: `control: false`, `monitor: true`.
- **Humidity is relative humidity**, as the standard states it (`85 %`), with no temperature
  beside it.
- **A bias measured on the device** says which point in `reference_point` (`V_MPP`, `-J_MPP`, …):
  the protocol cannot know the number before the fresh device is measured.
- **A recommendation is its own variant.** A solar simulator is controlled at no required
  irradiance; the variant ending in `800-1000Wm2` keeps it in the recommended range instead,
  `hold_between: {lower: 800 W/m^2, upper: 1000 W/m^2}` — a range, with no target inside it.
- **A cycle is a ramp that repeats.** Linear ramping up and down is `end_of_ramp_behavior:
  triangle`. Where the standard states the two ends and not the path — ISOS-T's "RT to 65 °C",
  ISOS-LT-1's step ramping — it is `end_of_ramp_behavior: cycle`, with no rate.
