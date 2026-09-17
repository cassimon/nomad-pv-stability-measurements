# ISOS stability protocols

The protocols of **ISOS Table 1**, from Khenkin, M. V., Katz, E. A., Abate, A. *et al.*,
"Consensus statement for stability assessment and reporting for perovskite photovoltaics based on
ISOS procedures", *Nature Energy* **5**, 35–49 (2020), <https://doi.org/10.1038/s41560-019-0529-5>.

Open any of them in the ELN, or copy one and add what your own run needs.

| Family | What it stresses | Files |
|---|---|---|
| ISOS-D | Dark storage | 5 |
| ISOS-V | Electrical bias, in the dark | 25 |
| ISOS-L | Light soaking under a solar simulator | 8 |
| ISOS-O | Outdoor exposure to sunlight | 5 |
| ISOS-LT | Solar-thermal cycling | 5 |

Within each family the number is the level of sophistication: **1** needs the least equipment,
**3** the most.

## One folder per standard, one file per option

Where the standard offers options — two temperatures, MPP or open circuit, five biases — every
combination is its own protocol, with the options in the file name:

```
ISOS-D-1/ISOS-D-1.stability.yaml                    no options
ISOS-D-2/ISOS-D-2_65degC.stability.yaml             standard: ISOS-D-2, standard_variant: 65 °C
ISOS-L-2/ISOS-L-2_85degC_MPP.stability.yaml         standard_variant: 85 °C, MPP
ISOS-V-3/ISOS-V-3_65degC_minus-Jmpp.stability.yaml  standard_variant: 65 °C, −J_MPP
```

Search for `standard` to find every variant of a protocol, and for `standard_variant` to find one.

## Reading one

```yaml
channel_settings:          # conditions that hold for the whole test
  irradiation: {hold: dark}
  temperature: {hold: RT}  # "Ambient (23 ± 4 °C)": 23 °C, ± 4 K
  atmosphere: {variable: water_vapor, control: false}   # "Ambient": not regulated
  electrical_load: {hold: open_circuit}
routine:                   # only what changes during the test
```

Only what the standard states is written. There is **no test duration, sampling interval or
measurement schedule** in any file, because ISOS Table 1 fixes none — add your own. Where the
table gives no figure (a solar simulator's irradiance, a bias measured on the fresh device), the
quantity is marked as controlled with no value, and `notes` say what the standard says about it.

## Not included yet

- **ISOS-LC** (light cycling): the cycle repeats for as long as the test runs, which a file cannot
  yet say without inventing a total duration.
- **ISOS-T** (thermal cycling), and the *step-ramping* option of ISOS-LT-1: the table gives the
  two temperatures, but not how the cycle moves between them.
