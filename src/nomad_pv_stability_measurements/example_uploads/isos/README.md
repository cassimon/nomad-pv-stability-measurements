# ISOS stability protocols

One `.stability.yaml` file per row of **ISOS Table 1** — the consensus stability protocols for
perovskite photovoltaics, from Khenkin, M. V., Katz, E. A., Abate, A. *et al.*, "Consensus
statement for stability assessment and reporting for perovskite photovoltaics based on ISOS
procedures", *Nature Energy* **5**, 35–49 (2020), <https://doi.org/10.1038/s41560-019-0529-5>,
which in turn reports the protocols of Reese, M. O. *et al.*, *Sol. Energy Mater. Sol. Cells*
**95**, 1253–1267 (2011).

Open any of them in the ELN, or copy one and change the lines you need — that is what they are
for.

| Family | Files | What it stresses |
|---|---|---|
| ISOS-D | `ISOS-D-1` … `-3` | Dark storage: shelf life, then an oven, then damp heat |
| ISOS-V | `ISOS-V-1` … `-3` | A held electrical bias, in the dark |
| ISOS-L | `ISOS-L-1` … `-3` | Light soaking under a solar simulator |
| ISOS-O | `ISOS-O-1` … `-3` | Outdoor exposure, with the site recorded |
| ISOS-T | `ISOS-T-1` … `-3` | Thermal cycling |
| ISOS-LC | `ISOS-LC-1` … `-3` | Light cycling — a light/dark duty cycle |
| ISOS-LT | `ISOS-LT-1` … `-3` | Solar-thermal cycling: light with a ramping temperature |

Within each family the number is the level of sophistication: **1** needs the least equipment,
**3** the most.

## How to read one

```yaml
data:
  standard: ISOS-D-2          # which protocol this is
  environment: indoor         # indoor / outdoor / other
  channel_settings:           # the conditions, each held for the whole run
    irradiation: {hold: dark}
    temperature: {hold: 65 °C}
    atmosphere: {variable: water_vapor, control: false}
    electrical_load: {hold: open_circuit}
```

`channel_settings` are **conditions**: they have no duration, so they last as long as the run
does. `routine`, where a file has one, is what *changes* during the run.

## The two rules these files follow

**1. Only what the standard actually fixes.** ISOS Table 1 fixes conditions — light,
temperature, humidity, load. It fixes **no test duration, no sampling interval, and no
measurement schedule**, so you will not find any in these files. That is deliberate: a template
is read as a specification, and a plausible-looking `duration: 1000 h` would tell the next reader
the protocol demands a thousand hours when it demands nothing of the sort. Fill in your own when
you run the test.

For the same reason, `control: false` is how a file says **ambient**. The table's "Ambient
(23 ± 4 °C)" describes a laboratory, not a setpoint — so the file records that the quantity is
not regulated, puts the nominal figure in `notes`, and claims nothing about anyone logging it.
`monitor: true` appears only where the table itself says "Monitored".

**2. Settings are what is constant; a routine is only what is not.** Dark storage holds one
temperature, one (absent) light level and one load from beginning to end — so `ISOS-D-*` have
**no routine at all**. Only the cycling families need one:

| Families | Shape |
|---|---|
| ISOS-D, -V, -L, -O | every condition constant → `channel_settings` only |
| ISOS-T, -LC, -LT | a thermal cycle, a light/dark duty cycle, a ramping temperature → that part, and only that, in `routine` |

Nothing is named unless the standard names it — hence `name: ISOS-D-1` and unnamed blocks.

## Where the table offers a choice

Where a row gives levels ("65, 85 °C"), the file takes one and names the other in `notes`; where
it gives "MPP or OC", the file tracks MPP. Those are choices among values the table states — one
line to change, and the `notes` say so.

## What these files deliberately do not say

- **The set-up and the characterization light source**, two columns of the table, are about
  instruments rather than about the protocol, so they are left out. One consequence is visible
  here: `ISOS-O-1` and `ISOS-O-2` differ *only* in that column, so the two files are the same
  protocol.
- **A bias taken from the device**, in the ISOS-V family. The table asks for V_MPP, V_oc or
  E_g/q — every one of them measured on a fresh cell. A protocol written before the measurement
  cannot know the number, so each file says in `notes` what the bias must be set from.
- **ISOS-LT-2/3's "humidity controlled at 50 % beyond 40 °C"**, a control law that depends on
  another quantity's current value. It is recorded in `notes` instead.
