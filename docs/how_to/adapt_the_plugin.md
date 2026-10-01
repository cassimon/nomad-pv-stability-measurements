# Adapt the plugin to your lab

## Read your institution's stability runs

Every lab's measurement station writes its own files. To have the plugin read yours, add
one Python module. The plugin finds your files and makes the entries itself.

1. Copy `src/nomad_pv_stability_measurements/file_reading/file_reading_TEMPLATE.py` to
   `file_reading_<INSTITUTION>.py`, for example `file_reading_HZB.py`, and set
   `INSTITUTION = 'HZB'`.
2. Fill in the two required functions:
    - `stability_run_belongs_to_this_institution(path, content)`: is this the file that
      stands for one of your runs?
    - `read_stability_run(path)`: the run as a dict, meaning who ran it, when, on which
      sample, which protocol it followed, and its steps, each with a `kind` and a `file`.
3. Write one reader per kind of step file, for example your tracking file and your J–V
   file, and list them in `STEP_READERS = {'stability_series': ..., 'jv': ...}`.
4. Optional: `derive_stability_protocol_from_stability_run`, if your files name no
   protocol (see [Given and derived protocols](#given-and-derived-protocols)), and
   `read_collection_all_measurements_on_device`, to collect all runs on one device into
   one entry.
5. Add your module to `INSTITUTIONS` in `parsers/measurement_parser.py`.

Every function returns plain Python data: dicts, lists, text, datetimes and quantities
with units. The docstrings in the template show the exact form. `file_reading_SIM.py` is
a short complete example, and `file_reading_UNITOV.py` uses the optional functions.
Check your module with `pytest tests/file_reading`.

## Write a protocol

A protocol says what a stability test is meant to do: the conditions it holds, for how
long, and what it measures. Write it as a `*.stability.yaml` file and upload it, and it
becomes a protocol entry with a timeline.

**Conditions that hold for the whole test** go under `channel_settings`, and **measurements**
under `instructions`:

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: Dark storage
  channel_settings:
    irradiation: {specify: dark}
    temperature: {specify: RT, monitor: true}
    electrical_load: {specify: open_circuit}
  instructions:
    - jv_scan: {every: 24 h}
```

**Phases one after another** go in a `routine`. A block with `mode: parallel` runs its
instructions at the same time. `whole block` means "as long as the block". A length marked
`typical` is not fixed by the protocol.

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: Light soak at 65 °C
  routine:
    name: measured, aged, measured
    repeat: 1
    instructions:
      - {name: initial J–V, jv_scan: {irradiance: 1000 W/m^2}, duration: typical 2 min}
      - name: light soak
        repeat: 1
        mode: parallel
        instructions:
          - {channel: irradiation, specify: 1000 W/m^2, control: true, monitor: true, duration: 1000 h}
          - {channel: temperature, specify: 65 °C, control: true, monitor: true, duration: whole block}
          - {channel: electrical_load, specify: mpp, control: true, monitor: true, duration: whole block}
      - {name: final J–V, jv_scan: {irradiance: 1000 W/m^2}, duration: typical 2 min}
```

**Alternatives** go under `options`, and each combination becomes its own entry. The
file below makes four entries: 65 °C and 85 °C, each at MPP and at open circuit.

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: Light soak
  channel_settings:
    irradiation: {specify: 1000 W/m^2, control: true}
    temperature:
      control: true
      options:
        - specify: 65 °C
        - specify: 85 °C
    electrical_load:
      options:
        - {label: MPP, specify: mpp, control: true, monitor: true}
        - {label: OC, specify: open_circuit}
```

The ISOS protocols in `example_uploads/isos/` and the lab protocols in
`example_uploads/custom_protocols/` are ready to copy. [The rule book](#the-rule-book)
explains every key.

## The rules of stability protocol specification

Each rule builds on the ones before it. Rules 1 to 4 are enough for a test whose
conditions never change. The later rules add change over time.

### 1. A protocol sets conditions on channels

There are four channels: `irradiation`, `temperature`, `atmosphere` and
`electrical_load`. A condition states a value with `specify`: `65 °C`, `1000 W/m^2`,
`85 %`. A few words work too: `dark`, `RT`, `ambient`, `mpp`, `open_circuit`.

The atmosphere has two variables. It takes a list, one item per `variable`:
`relative_humidity` and `oxygen`. The load takes `mpp` or `open_circuit`. A fixed voltage
adds `variable: voltage`.

### 2. Stating is not regulating

`specify` only states a value. `control: true` says it is regulated. `monitor: true`
says it is logged. The three are independent. `RT` and `ambient` are usually stated
only.

### 3. Settings hold for the whole test

Conditions under `channel_settings` start with the test and last until its end. A test
with constant conditions needs nothing else.

### 4. Measurements are instructions

`jv_scan` measures the cell. Under the protocol's `instructions`, it runs for the
whole test, like a setting. Without `every`, it measures once. `every: 24 h` measures
periodically. `every: not stated` measures periodically at an interval the protocol
leaves open. A J–V scan takes over the electrical load while it measures. Then the
load returns.

### 5. Change over time goes into the routine

The `routine` lists instructions that run one after another. Each one states its
`duration`. `1000 h` is exact. `typical 2 min` is a usual length, not a requirement: it
only draws the timeline and adds up.

### 6. Blocks group instructions and repeat them

An instruction can itself be a block with its own `instructions`. `repeat: 1` runs it
once. `repeat: 5` runs it five times. `repeat_for: 1000 h` runs it again and again for
that long. **Without `repeat`, a block repeats forever.**

### 7. Parallel blocks run instructions side by side

`mode: parallel` starts all instructions of a block together. A condition there can
last `whole block`, as long as its block. The block lasts as long as its longest other
instruction. One after another, `whole block` is not allowed: nothing runs beside it.

### 8. A block's length is worked out

A block never states a `duration`. It is added up from its instructions. A ramp works
out its own length from its rate: `specify: {from: 25 °C, to: 85 °C, rate: 1 K/min}`.

### 9. Open-ended means stopped from outside

`open-ended` lasts until someone stops it. Anything after it in the same sequence never
starts.

### 10. The routine overrides the settings

Settings and routine start together. Where the routine addresses a channel, its value
holds for that span. Everywhere else, the setting holds.

### 11. The test ends with its routine

The protocol lasts as long as its routine. A `duration` on the protocol sets its length
instead. A routine that repeats forever, with no protocol `duration`, never ends.

### 12. Options make variants

`options` lists alternatives for one key. Every combination becomes a protocol of its
own. Its name comes from the `label`s. A single value is its own label.

## Given and derived protocols

A run can carry two plans, and the plugin never mixes them up:

- **Given protocol (`plan`)**: the protocol the lab says the run followed. The run file
  either names a protocol file in the same upload, by its path and variant, or describes
  the test itself. Only what the lab stated goes here.
- **Derived protocol (`derived_plan`)**: a protocol the plugin works out where the files
  state none. It is based on how the files are laid out, what was recorded (for example,
  the mean of a voltage held), and conditions the institution normally uses
  (`ASSUMED_CONDITIONS`). Its `notes` list every value that was assumed or worked out
  rather than read.

A derived protocol describes what happened, but nobody planned it. Compare runs by their
given protocols, and use a derived one only where a run has none.
