# Custom stability protocols with simulated runs

Three stability protocols that follow no standard, each with a simulated run beside it. **Nothing
here was measured.** They show what a protocol can say beyond the ISOS procedures: phases run one
after another, blocks repeated a number of times or for a time, conditions held side by side, and
blocks nested in blocks.

| Protocol | What it does | What it shows |
|---|---|---|
| [Stepped stress](stepped-stress.stability.yaml) | 24 h burn-in under light, three temperature cycles 25–85 °C under light, 24 h recovery in the dark | phases in sequence; a counted repetition; light held beside a nested temperature profile; ramps at 1 K/min |
| [Diurnal emulation](diurnal-emulation.stability.yaml) | five emulated days: the light rises, peaks and sets while the temperature follows | a repetition for a time (`repeat_for: 120 h`) of two sequences run side by side |
| [Damp heat with light soaks](damp-heat-light-soaks.stability.yaml) | 85 °C and 85 % throughout; four times 20 h dark at open circuit, then 4 h light at the maximum power point | a counted repetition whose phases hold different electrical loads |

Each names the light it ages the cell under, as a protocol should: an LED solar simulator of
class AAA (stepped stress), an LED solar simulator dimmed along the day (diurnal emulation), a
1200 W metal halide light-soaking lamp with its UV filtered out (damp heat with light soaks).

Each also measures the cell's J–V curve, as its run does: before and after the ageing, and in
*Stepped stress* between its phases too. A scan is an instruction of its own in the sequence,
`{name: initial J–V, jv_scan: {order: reverse then forward, irradiance: 1000 W/m^2,
light_source: {…}}, duration: typical 2 min}`, under its own light: a class AAA xenon solar
simulator at one sun, AM1.5G. The conditions of the ageing (the chamber's temperature and
humidity, the MPP tracking) are therefore held in the ageing block, not for the whole protocol:
the cell is not tracked while its J–V curve is swept.

Open a protocol to see its timeline, and one figure per repeating block showing one pass.

## The runs

Each run is a folder named after its protocol, in the same format as the simulated ISOS runs: a
run file (`*.run.yaml`), J–V sweeps (`*_jv_*.csv`) and stability series
(`*_stability_series*.csv`), each column's unit in its header. The run of **Stepped stress** is
recorded in its three phases: one stability series per phase, with a J–V sweep after each.

```
stepped-stress/
  stepped-stress.run.yaml
  01_jv_initial.csv
  02_stability_series_burn_in.csv
  03_jv_after_burn_in.csv
  04_stability_series_temperature_cycles_under_light.csv
  05_jv_after_temperature_cycles_under_light.csv
  06_stability_series_recovery_in_the_dark.csv
  07_jv_final.csv
```

Each run becomes a *StabilityMeasurement* entry whose *plan* is the protocol beside it. Where the
protocol does not track the maximum power point, a lit cell sits at open circuit: the damp heat
run records power only during its light soaks.
