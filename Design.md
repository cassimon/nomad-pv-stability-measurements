# Design — `nomad-pv-stability-measurements`

**Status: design complete for iteration 1 — ready to implement.**
Every NOMAD/pint behaviour this document relies on was checked against this distro (marked
**verified**). One open point remains (§11); it does not block implementation.

**In one paragraph.** A PV stability test is a *protocol* — a recipe of setpoints over time on
a few stress channels (temperature, irradiation, atmosphere, electrical load, mechanical) — and
the *results* measured on a solar-cell sample while it runs. The protocol is authored as a small
tree in a readable `.archive.yaml`; the schema expands it into a timeline, validates it,
summarizes it for search, and plots it. Measurements reference the protocol and the sample.

```yaml
protocol:                                  # ISOS-L-2 (full file in §8)
  name: light soak
  mode: parallel
  steps:
    - {channel: chuck_T, hold: 65 °C}
    - {channel: sun, hold: 1 sun}
    - subprotocol: daily cycle
      repetitions: 42
      steps:
        - {channel: bias, track: mpp, duration: 24 h}
        - {channel: bias, variable: voltage, sweep: {from: -0.2 V, to: 1.3 V, rate: 50 mV/s}}
```

---

## 1. Decisions

**Scope**

| # | Decision |
|---|---|
| D1 | **Read-only data schema.** Describes runs that already happened; never drives hardware. |
| D2 | **Depends on `nomad-lab` only.** `nomad-measurements` / `perovskite-solar-cell-database` are listed in the distro's `[tool.uv.sources]` but are not installed — integrate later. |
| D3 | **Three layers kept apart:** authored protocol → derived timeline vs. observed measurement (§3). |

**Channels** (§4.1)

| # | Decision |
|---|---|
| D4 | **One device per `Channel`, for measurement and/or control. A channel is a table of named *variables*** — each controllable and/or monitorable — plus *control groups* (which variables can be commanded at the same time). A new channel type = one subclass supplying that table. All behaviour lives once in the base class. |
| D5 | **Variables have physical names** (`humidity`, `oxygen`, `temperature` …); **the unit selects the quantity kind** (relative, molar ratio, dew point …). Values stay in the kind they were given — no cross-kind conversion. |
| D6 | **Every value is a unit string** (`65 °C`, `85 %RH`, `1 sun`), parsed and dimension-checked against its variable. **Ambiguity is an error:** bare numbers, and bare `%` on humidity/oxygen. The one documented convention: `ppm`/`ppb` are molar (ppmv) — the glovebox standard. |
| D7 | **The four ISOS stress axes are always reported.** A temperature / irradiation / atmosphere / electrical-load channel that is not declared appears in the derived layers as *uncontrolled and unmonitored* — never written into the authored channels. UV content is a property of the irradiation spectrum, not a channel; encapsulation belongs to the sample. |
| D8 | **`uncontrolled` is universal and the default; `off` is irradiation-only** (deliberate dark — the ISOS-D distinction). |
| D9 | **Monitoring is a channel field** (`monitor_every`), not a state. |
| D10 | **The regulation law (PID, on/off …) belongs to the channel**, orthogonal to the setpoint shape. |

**Protocol** (§4.2, §5)

| # | Decision |
|---|---|
| D11 | **Two node classes: the root `Protocol` and `SubProtocol(Protocol)` for every step below it.** A step opens with `channel:` (it *acts*) or `subprotocol:` (it *contains* further `steps`); the keyword makes the YAML read as structure. Step-only fields (`channel`, `subprotocol`, `variable`, the state slots) live on `SubProtocol`, so the root cannot act. Not named `Step`: a step can also be a command. |
| D12 | **`mode: sequential \| parallel`** on a node says how its `steps` run. Children of a `parallel` node must write disjoint control groups (rule R3). **Join-all:** a parallel block ends when its longest bounded child ends. |
| D13 | **Lifetime by lexical scope.** A state holds exactly for its node's span; no start/stop pairs; states have no duration of their own. *Channels own "what", the tree owns "when".* |
| D14 | **Termination lives on the node:** `repetitions`, `duration`, `stop_when` — whichever comes first. No `WaitUntil`. |
| D15 | **`stop_when` is a readable text condition** (`pce_relative < 80 %`), parsed into a structured form in `normalize()`. The grammar can grow (`and`, `or`, `for 10 min`) without invalidating stored text. |
| D16 | **A ramp needs a `rate` or a `duration`** — exactly one. |
| D17 | **A JV sweep during MPP tracking is its own step.** Both at once is not expressible (same control group). |

**YAML ergonomics** (§9)

| # | Decision |
|---|---|
| D18 | **Named state slots** (`hold:`, `ramp:` …) instead of polymorphic sub-sections — `m_def` is never hand-written except at the root. |
| D19 | **Human strings** for durations, rates and values, parsed in `normalize()`. |
| D20 | **References by `key` string**, resolved in `normalize()` — never `#/data/...` paths. |

**Derived outputs and provenance** (§4.3–§4.5)

| # | Decision |
|---|---|
| D21 | **Timeline as column arrays.** Expansion is exact in memory; a simulated timeline is persisted with a fixed budget of 3000 sparse points (it is a visualization, not data). |
| D22 | **A non-editable `ProtocolSummary`** of flat scalars, derived in `normalize()`, searchable across the Oasis. |
| D23 | **The protocol entry is a `PlotSection`** plotting the timeline — one row per target, implicit channels included; later *intended vs. actual*. |
| D24 | **One reference protocol YAML per upload**; the upload's measurements reference it, and **each measurement carries its own `ProtocolSummary`**. Duplicate protocols across uploads are accepted — they are what makes each upload self-contained and immune to later edits elsewhere. |

---

## 2. NOMAD building blocks

All ship with `nomad-lab`. Import paths **verified**:

| Class | Import from | Use for |
|---|---|---|
| `ArchiveSection`, `EntryData` | `nomad.datamodel.data` | every section; standalone entries |
| `BaseSection` | `nomad.datamodel.metainfo.basesections` | base of `StabilityProtocol` (`name`, `datetime`, `lab_id`, `description`) |
| `Measurement`, `MeasurementResult` | ″ | base of `StabilityMeasurement` / `StabilityResult` |
| `CompositeSystemReference` | ″ | **the link to the solar-cell sample** (`Measurement.samples`) |
| `InstrumentReference` | ″ | channel → instrument provenance |
| `PlotSection`, `PlotlyFigure` | `nomad.datamodel.metainfo.plot` | protocol and results plots (plotly 5.24 installed) |
| `ELNAnnotation`, `SectionDisplayAnnotation` | `nomad.datamodel.metainfo.annotations` | editable fields; ELN field order |
| `HDF5Reference`, `HDF5Dataset` | `nomad.datamodel.hdf5` | large result arrays |
| `Quantity`, `SubSection`, `SectionProxy`, `Section`, `MEnum`, `Any`, `SchemaPackage` | `nomad.metainfo` | |
| `ureg` | `nomad.units` | the shared pint registry (read-only use!) |

**Deliberately not used:**
- **`Activity` as protocol base** — its `normalize()` appends to `results.eln.methods` and
  *overwrites* `workflow2.tasks`. A protocol is a plan, not something that happened.
- **`ActivityStep` / `ProcessStep` as node base** — `start_time` is an absolute `Datetime`;
  protocol time is relative to t₀.
- **`SolarCellJV`** (core ELN) — reusable for JV snapshots later, but heavy for iteration 1.

There is no `Protocol`/`Recipe` base section in NOMAD core — this is new ground.

---

## 3. Architecture

```
  AUTHORED                  DERIVED                      OBSERVED
  StabilityProtocol   ──►   ProtocolTimeline      vs     StabilityMeasurement
  channels + a tree         column arrays of             what the instrument
  of Protocol nodes         setpoint events              actually logged
  (hand-written)            (normalize() output)         (parsed from files)
```

- The timeline is **never hand-authored**. It is produced by a **pure-Python expander** working
  on plain dataclasses, unit-testable without an archive — the only place timing semantics live.
- The same `ProtocolTimeline` class can later be filled from an **instrument command log**
  (`source = logged`), which makes the headline plot *intended vs. actual*.

**The core model — four concepts:**

```
Channel               a device: named variables it can control / monitor
Protocol              the tree: a root, and SubProtocol nodes below it.
                      Names a channel -> sets it to a state.
                      Has steps -> runs them per its `mode`.
ProtocolTimeline      the expanded events (derived)
StabilityMeasurement  observed data, linked to protocol + sample (+ StabilityResult)
```

**Three rules:**

> **R1** — a node that names a channel puts (one variable of) it into a state for the node's span.
>
> **R2** — a node's `mode` says how its `steps` run: `sequential` (default) or `parallel`.
>
> **R3** — the children of a `parallel` node write **disjoint control groups** (static set check).

Mixed sequencing composes by nesting — "A, then B ∥ C, then D":

```yaml
steps:
  - A
  - {subprotocol: fork, mode: parallel, steps: [B, C]}
  - D
```

Why this shape holds up:
- **Readability is structural.** Because of R3, "what is channel X doing at time t?" is
  answered by walking the tree — at most one branch can write X.
- **Reordering is safe where it should be.** Reordering children of a `parallel` node changes
  nothing; reordering a `sequential` node is visibly meaningful.
- **Channels own *what*, the tree owns *when*.** Channel subclasses add capabilities and
  physics; timing never leaks into them.

> **Pitfall — do not give states a `duration`.** It looks like a convenient shortcut
> ("hold 65 °C for 500 h inside a 1000 h protocol"), but it lets two states on one channel
> overlap and turns R3's set check into time-interval arithmetic. Put the duration on the
> node: `{channel: chuck_T, hold: 65 °C, duration: 500 h}`. (Sweeps, tabulated states and
> ramps given a `rate` *determine* their node's length — still exactly 1:1 with the scope.)

---

## 4. Schema

### 4.0 Field order — **verified**

1. Inherited quantities come first (`BaseSection` → `name, datetime, lab_id, description`).
2. **All quantities serialize before all sub-sections**, regardless of declaration order.
3. Declaration order is kept within each group.

Sketches below are in true serialization order. Hand-written YAML may use any key order.
The ELN order can be overridden on the section definition with
`m_def = Section(a_display=SectionDisplayAnnotation(order=[...]))` — use it on `SubProtocol` to
keep the state slots together (they straddle rule 2). **Verified:** the older
`a_eln=ELNAnnotation(properties=SectionProperties(order=[...]))` still works but is marked
*deprecated* in this NOMAD version; use `a_display`. Check in the GUI whether quantities and
sub-sections interleave; if not, the split is cosmetic only.

### 4.1 Channels — `channels.py`

```
Channel(ArchiveSection)                    # abstract
    # --- quantities
    name           str             # human, renameable
    key            str             # REQUIRED, stable — YAML references, timeline, parsers
    monitor_every  str             # "60 s"; omitted => not monitored
    monitored      str[]  (opt)    # which variables; default: all monitorable ones
    limits         Any    (opt)    # {variable: [min, max]} as unit strings;
                                   #   plain [min, max] allowed for single-variable channels
    idle           enum{uncontrolled, off}   # state between steps; default uncontrolled
                                   #   (YAML reads a bare `off` as false — see §4.2 pitfall)
    variables      str[]           # DERIVED from the class table (shown in the ELN)
    is_controlled  bool            # DERIVED: some step sets a state other than `uncontrolled`
    is_monitored   bool            # DERIVED: monitor_every is set
    # --- sub-sections
    regulation     RegulationLaw (opt)
    instrument     InstrumentReference (opt)

RegulationLaw(ArchiveSection)                    # metadata only
    kind enum{open_loop, pid, on_off, external};  kp, ki, kd, hysteresis
```

> **Pitfall — `JSON` accepts dicts only (verified).** `Quantity(type=JSON)` rejects a list
> (`Shape mismatch`, and the type itself raises `needs to be a dict`), so the single-variable
> form `limits: [20 °C, 90 °C]` would fail to load. `limits` is therefore `Quantity(type=Any)`
> (`nomad.metainfo.Any`), which stores both forms as given and round-trips through
> `m_to_dict`. Cost: no ELN widget (there is no JSON edit component either) — limits are
> authored in YAML.

**Subclasses — the whole per-channel specificity is this table:**

| Subclass (container slot) | Variables (canonical unit, display) | Control groups | Extra states | Extra fields | Always reported |
|---|---|---|---|---|---|
| `TemperatureChannel` (`temperature`) | `temperature` (K, °C) | {temperature} | — | — | ✅ |
| `IrradiationChannel` (`irradiation`) | `irradiance` (W/m², W/m²) | {irradiance} | `off` | `spectrum` str (`AM1.5G`) | ✅ |
| `AtmosphereChannel` (`atmosphere`) | `humidity` (multi-kind), `oxygen` (multi-kind), `total_pressure` (Pa, mbar) | {humidity}, {oxygen}, {total_pressure} | — | `balance_gas` str (`N2`, `air`, `Ar`) | ✅ |
| `ElectricalLoadChannel` (`electrical_load`) | `voltage` (V), `current` (A), `resistance` (Ω, control only) | {voltage, current, resistance} | `track`, `sweep` | — | ✅ |
| `MechanicalChannel` (`mechanical`) | `bend_radius` (m, mm), `strain` (dimensionless, %) | {bend_radius, strain} | — | — | ❌ |

All variables are controllable and monitorable unless noted. Generic states
(`uncontrolled`, `hold`, `ramp`, `cycle`, `tabulated`) are accepted by every channel.

**Not channels:** *UV content* follows from irradiance × the UV fraction of the spectrum, so
it belongs to the irradiation channel's spectrum (derivable for a known standard such as
AM1.5G; a custom lamp or a UV filter needs the spectrum described — deferred, §12).
*Encapsulation* is a property of the device, described on the sample and back-populated into
the measurement's summary later.

```python
@dataclass(frozen=True)
class Variable:                       # a schema constant, NOT metainfo
    kinds: tuple[Kind, ...] | str     # a str is shorthand for one kind with that unit
    display: str | None = None        # plot unit, e.g. 'degC'
    control: bool = True
    monitor: bool = True

class AtmosphereChannel(Channel):
    variables = {
        'humidity':       Variable(HUMIDITY_KINDS),
        'oxygen':         Variable(OXYGEN_KINDS),
        'total_pressure': Variable('Pa', display='mbar'),
    }
    control_groups = [{'humidity'}, {'oxygen'}, {'total_pressure'}]
    accepted_states = GENERIC_STATES
    always_reported = True
```

**Base-class interface** (implemented once):

```
can_control(variable) / can_monitor(variable) -> bool
group_of(variable)                            -> frozenset
parse(variable, text)                         -> (kind, canonical float)   # §6
```

Control groups encode physics: humidity and oxygen are set independently by a gas mixer
(separate groups — both can be held in parallel); a cell's voltage and current are tied by its
I–V curve (one group — commanding `voltage` makes `current` measured-only for that span).

#### Quantity kinds (humidity, oxygen)

The kind usually reflects what the instrument regulates (climate chamber → %RH, glovebox →
ppm, dry room → dew point), so it is recorded, not converted.

| Variable | Kind | Written as | Canonical |
|---|---|---|---|
| `humidity` | `relative` | `85 %RH` | fraction |
| | `molar_ratio` | `0.5 ppm`, `500 ppb`, `ppmv`, `ppbv`, `mol%`, `mol/mol` | mol/mol |
| | `mass_ratio` | `10 g/kg`, `ppmw`, `ppbw`, `wt%` | kg/kg |
| | `absolute` | `12 g/m^3` | kg/m³ |
| | `dew_point` | `-40 °C` | K |
| | `partial_pressure` | `1.2 kPa` | Pa |
| `oxygen` | `molar_ratio` | `21 vol%`, `mol%`, `ppm`, `ppb`, `ppmv`, `ppbv`, `mol/mol` | mol/mol |
| | `mass_ratio` | `23 wt%`, `g/kg`, `ppmw`, `ppbw` | kg/kg |
| | `partial_pressure` | `212 mbar` | Pa |

**Bare `%` is rejected** on these two variables (relative? molar? mass?). The error names
the alternatives — `'85 %' is ambiguous for humidity: write 85 %RH, 85 mol% or 85 wt%`.
Bare `%` stays valid where a variable has only one dimensionless kind (`strain: 2 %`,
`pce_relative < 80 %`).

**`ppm` / `ppb` mean molar** — the glovebox standard, which is how the glovebox readouts
authors copy from mean it. A mass ratio must say so: `ppmw`, `ppbw`. This is the schema's
only unit convention; it is documented here and in the `ppm` row of the parser's token
table (§6), and nowhere else.

- **Within one state, all values share one kind** — `ramp: {from: 85 %RH, to: 500 ppm}` is an error.
- **Across steps, kinds may differ** (the sample moved from chamber to glovebox). The timeline
  target is therefore *(channel, variable, kind)* — one plot row per kind, never a shared axis.

#### Implicit channels and `uncontrolled` vs `off`

For every always-reported type with **no declared channel**, the derived layers add one
implicit target (keyed by the container slot name, e.g. `atmosphere`) with an `uncontrolled`
event at t = 0. It is never written into `channels`, and no step can command it — *if you
control it, declare it.* Every protocol plot therefore shows the same four axes.

| Channel | `uncontrolled` means | `off` means |
|---|---|---|
| Temperature | ambient, drifting | — (not accepted) |
| Irradiation | **lab light** | **deliberately dark** (shielded / lamp off) |
| Atmosphere | ambient air | — |
| Electrical load | disconnected = open circuit | — |

So an ISOS-D (dark) protocol must *say* `off`; one that says nothing is honestly recorded as
sitting in uncontrolled light. **`off` counts as controlled** in the summary.

#### Container

One repeating slot per type, so no `m_def` is needed (adding a channel type = subclass + one
line here):

```
Channels(ArchiveSection)
    temperature      TemperatureChannel[]
    irradiation      IrradiationChannel[]
    atmosphere       AtmosphereChannel[]
    electrical_load  ElectricalLoadChannel[]
    mechanical       MechanicalChannel[]
```

### 4.2 Protocol nodes and states — `protocol.py`, `states.py`

```
Protocol(ArchiveSection)                          # the ROOT node
    # --- quantities
    name          str        # root: authored. Below: DERIVED ('daily cycle', 'bias: track mpp')
    mode          MEnum(sequential, parallel)  # default sequential
    duration      str        # "24 h": the node's span — or a time cap if it would run longer
    repetitions   str        # "42" or "forever"; omitted => 1
    stop_when     str        # "pce_relative < 80 %" — a text condition, §4.2.1
    duration_s    float [s]  # DERIVED
    # --- sub-sections
    steps         SubProtocol[]  # SubSection(section_def=SectionProxy('SubProtocol'), repeats=True)

SubProtocol(Protocol)                             # every node below the root
    # --- quantities: inherited ones first, then
    channel       str        # channel KEY  -> this step ACTS         } exactly one
    subprotocol   str        # block name   -> this step CONTAINS     }
    variable      str        # see "variable rule" below
    uncontrolled  bool   ┐
    off           bool   │  scalar state slots
    hold          str    │  "65 °C"
    track         MEnum(mpp, voc, jsc) ┘
    # --- sub-sections: inherited `steps`, then
    ramp          Ramp       ┐
    cycle         Cycle      │  section state slots
    tabulated     Tabulated  │
    sweep         Sweep      ┘
```

`SubProtocol` inherits `steps`, so it nests without limit. On a `subprotocol` node the derived
`name` repeats the `subprotocol` text; it exists so that `channel` nodes get a label too.

**At most one state slot per node; a `channel` node needs exactly one.** Expose them through
one Python property (`node.state`) so the expander sees a single canonical state object.

**States** (`states.py`, every value a unit string):

| Slot | Fields | Semantics |
|---|---|---|
| `uncontrolled` | `true` | release the variable/channel |
| `off` | `true` | irradiation only: deliberate dark |
| `hold` | scalar | constant setpoint |
| `ramp` | `from`, `to`, `rate` (opt) | linear. **Exactly one of `rate` or the node's `duration`** — with `rate`, **intrinsic length** = \|to−from\|/rate. `rate` is a positive magnitude (`0.4 K/h`, `5 %RH/h`); the direction comes from `from` → `to` |
| `cycle` | `waveform{square, triangle, sine}`, `low`, `high`, `period`, `duty_cycle` (float, square only) | square: `high` for duty·period, then `low`; triangle/sine: start at `low`, peak at period/2 |
| `tabulated` | `time[]`, `value[]`, `interpolation{linear, step}` = linear | times relative to node start; **intrinsic length** = last time |
| `track` | `mpp` / `voc` / `jsc` | electrical only; acts on the whole control group |
| `sweep` | `from`, `to`, `rate`, `direction{forward, reverse, both}` | electrical only, on `voltage` or `current`; **intrinsic length** = \|to−from\|/rate (×2 for `both`) |

Three sweeps in a row: `repetitions: 3` on the sweep's node.

> **Pitfall — `from` is a Python keyword.** **Verified** workaround:
> `from_ = Quantity(type=str, aliases=['from'])` reads `from:` from YAML, but NOMAD
> re-serializes it as `from_`. Acceptable; the alternative is renaming to `start`/`end`.

> **Pitfall — `off` is a YAML 1.1 boolean (verified).** NOMAD reads `.archive.yaml` with
> `yaml.SafeLoader`, which turns a bare `off` (like `on`, `yes`, `no`) into a boolean —
> **also as a mapping key**. `{channel: oven_dark, off: true}` arrives as
> `{'channel': 'oven_dark', False: True}` and parsing crashes; `idle: off` arrives as
> `idle: false` and fails the enum. Workaround, so §8 loads as written: override
> `m_update_from_dict` in exactly the two places `off` is valid —
> `SubProtocol` maps a `False` *key* back to `'off'`, `Channel` maps `idle: False` back to
> `'off'`. JSON and ELN input carry the string and are unaffected. Quoting (`'off': true`)
> also works but will be forgotten. The alternative is renaming the state (e.g. `dark`).

**The `variable` rule.** `hold`, `ramp`, `cycle`, `tabulated`, `sweep` target one variable;
`variable` is **required when the channel has more than one controllable variable** (on an
atmosphere channel, `hold: 5 mol%` would fit humidity *and* oxygen). `uncontrolled`, `off`
and `track` act on the whole channel and take no `variable` (or, for `uncontrolled`,
optionally one).

#### 4.2.1 Stop conditions — `conditions.py`

`stop_when` is authored as **text and parsed**, like every other value. Recorded, not
simulated (§5).

```yaml
- subprotocol: aging
  repetitions: forever
  stop_when: pce_relative < 80 %                  # T80
  steps: [...]
- {channel: chuck_T, ramp: {from: 25 °C, to: 85 °C, rate: 2 K/min},
   stop_when: chuck_T.temperature >= 84.5 °C}     # a state condition
```

**Grammar, iteration 1** — one comparison:

```
condition  := observable op value
observable := <channel_key>.<variable>     # a monitored channel variable
            | <metric>                     # pce, voc, jsc, ff, pmpp, and each *_relative
                                           #   (fraction of the initial value)
op         := <  |  <=  |  >  |  >=
value      := unit string, parsed against the observable (§6)
```

Parsed into IR dataclasses (`Comparison(observable, op, value, kind)`) by a small
hand-written tokenizer + recursive-descent parser (no dependency). Anything beyond one
comparison fails with *"only single comparisons are supported so far"*.

**Why text is the extensible choice.** The stored text is the source of truth and the
structured form is derived, so later grammar versions only *add* IR node types; every stored
condition stays valid and no migration is needed. Planned extensions, in likely order:

```
cond and cond / cond or cond / ( … )       # And, Or
cond for 10 min                            # Sustained — debounces noisy signals
chuck_T.temperature within 1 K of setpoint # Settled — "wait until stable"
```

A fixed metainfo section (`observable`/`operator`/`value`) would need a schema change and a
data migration for each of these.

Validation: unknown channel key / variable / metric; value dimension mismatch; an observable
on an **unmonitored** variable (*warning* — nothing logged could ever trigger it).

### 4.3 Protocol entry, summary, plot — `protocol.py`

```
StabilityProtocol(BaseSection, EntryData, PlotSection)
    # --- quantities
    name, datetime, lab_id, description             # inherited
    version             str
    isos_specification  str        # 'ISOS-L-2' (free text for now)
    isos_deviations     str
    horizon             str        # "1000 h" — required only if the tree is unbounded
    # --- sub-sections
    channels   Channels
    protocol   Protocol            # root node
    timeline   ProtocolTimeline    # DERIVED
    summary    ProtocolSummary     # DERIVED
    figures    PlotlyFigure[]      # inherited from PlotSection, DERIVED
```

```
ProtocolSummary(ArchiveSection)           # DERIVED, flat, scalars only, no a_eln => read-only
    total_duration                  float [h]
    truncated / estimated           bool
    temperature_controlled / _monitored        bool
    irradiation_controlled / _monitored        bool
    humidity_controlled / _monitored           bool     # atmosphere split per variable
    oxygen_controlled / _monitored             bool
    electrical_load_controlled / _monitored    bool
    temperature_min / _max / _mean  float [K]      # time-weighted over setpoints; null if uncontrolled
    irradiance_mean                 float [W/m^2]  # 'off' counts as 0
    humidity_kind                   str            # 'relative' … or 'mixed'
    humidity_mean                   float          # canonical unit of that kind; null if mixed
    atmosphere_label                str            # balance_gas, or 'ambient' if uncontrolled
    load_condition_label            str            # e.g. 'track mpp + sweep'
    channels_used                   str            # 'bias, chuck_T, sun' — see pitfall
    states_used                     str            # 'hold, sweep, track'
    is_cyclic                       bool           # any cycle state or repetitions > 1
    n_jv_sweeps                     int            # up to total_duration
```

> **Pitfall — search indexing (verified).** `archive.results.properties` has a fixed core
> schema; plugin fields cannot be added there. Plugin quantities under `data` are indexed
> automatically as `search_quantities`, addressed in apps as
> `data.summary.temperature_controlled#nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol`.
> **Only scalar quantities (`shape == []`) are indexed** — hence comma-joined strings above,
> not `str[]`.

**Plot.** Two figures from the timeline: (1) the whole protocol, one step-plot row per
target — implicit channels as a flat "uncontrolled" band — in each variable's `display` unit;
(2) the first full repetition of the outermost repeating block, in detail.

### 4.4 Timeline — `timeline.py`

```
ProtocolTimeline(ArchiveSection)
    source        MEnum(simulated, logged)
    estimated     bool          # stop_when present — expansion assumed it never fires
    truncated     bool          # cut at horizon
    downsampled   bool
    total_duration float [h]
    n_points      int
    messages      str[]         # validation messages + what downsampling dropped
    # column arrays — one section, not 10^5
    time          float[] [s]
    target_index  int[]         # -> targets
    state_index   int[]         # -> state_labels
    value         float[]       # canonical unit of the target's kind; NaN where the state has
                                #   no number (uncontrolled, track); 0 for off
    path_index    int[]         # -> paths
    # lookup tables
    targets       str[]         # 'chamber.humidity[relative]', 'atmosphere' (implicit)
    target_units  str[]         # canonical unit per target
    state_labels  str[]
    paths         str[]         # 'light soak/daily cycle[7]/bias: track mpp'
```

**Exact in memory, sparse on disk.** Validation runs on the complete event list. For
`source = simulated`, persist at most a budget (default 3000 points):
keep (1) every discrete state transition, (2) the first full repetition of each repeating
block at full detail, (3) spend the rest densifying ramps and cycles; set `downsampled` and
record drops in `messages`. A `logged` timeline is data — HDF5-backed, not budgeted (iteration 2).

### 4.5 Results — `results.py` (iteration 2 sketch)

```
StabilityMeasurement(Measurement, EntryData, PlotSection)
    # inherited: samples (CompositeSystemReference[]) = the solar cell, instruments, results …
    protocol         -> StabilityProtocol
    protocol_summary ProtocolSummary  # DERIVED — each measurement carries its own (D24)
    t_zero           Datetime
    aging_time       float [h]        # pauses during interruptions
    wall_clock_time  float [h]
    interruptions    Interruption[]   # start, end (relative, str), reason
    actual_timeline  ProtocolTimeline # source = logged

StabilityResult(MeasurementResult)
    channel_series      ChannelTimeSeries[]   # channel KEY (str), variable, kind, time[], value[] — HDF5
    performance_series  PerformanceTimeSeries # PCE, Voc, Jsc, FF, Pmpp vs time — HDF5
    jv_snapshots        JVSnapshot[]
    metrics             StabilityMetrics      # t80, ts80, tT80, te80, t90 [h]; initial_efficiency …
```

A 1000 h MPPT log at 1 Hz does not fit in plain metainfo lists — use `HDF5Reference` from the
first real upload. Efficiency-type scalars *can* go into core
`results.properties.optoelectronic.solar_cell`; stability metrics stay under `data`.

**Upload layout (D24).** Every upload ships its reference protocol; measurements point to it
with NOMAD's same-upload reference syntax (**verified** in `nomad.metainfo`):

```
upload/
  protocol.archive.yaml                  # StabilityProtocol
  cell_A1.archive.yaml                   # StabilityMeasurement
     data:
       protocol: ../upload/archive/mainfile/protocol.archive.yaml#data
```

Searching "all measurements with uncontrolled humidity" then hits the measurements directly,
through their own `protocol_summary`. Later, sample-derived fields such as encapsulation are
back-populated into it from `samples`.

> **Pitfall — never read the protocol's *derived* fields from a measurement (verified).**
> Entries of one upload are processed in no guaranteed order. If the protocol is not
> processed yet, NOMAD's `ServerContext.load_archive` falls back to **parsing its raw YAML**:
> the authored channels and tree are there, but `summary` and `timeline` are not. So
> `StabilityMeasurement.normalize()` **re-runs the pure pipeline** (§7 steps 1–4) on the
> referenced protocol's authored content and computes its own summary — deterministic, and
> identical to the protocol's.
>
> **Also:** NOMAD does not re-normalize referencing entries when the referenced one changes.
> After editing an upload's protocol, reprocess the upload so the measurements catch up.

---

## 5. Timing semantics — the expander spec

**Natural length `L(node)`** — bottom-up; `None` = unbounded:

```
one pass P = leaf:        intrinsic(state) for sweep / tabulated / ramp-with-rate, else None
             sequential:  Σ L(child)                  (None if any child is None)
             parallel:    max over bounded children   (None if none is bounded)
L = P × repetitions            (None if P is None or repetitions = forever)
if duration:  L = duration if L is None else min(L, duration)
```

One rule for every node: `duration` *is* the span of an otherwise unbounded node
(`{track: mpp, duration: 24 h}`) and a *cap* on a bounded one. A node with `L = None` fills
whatever span it is given.

**Actual span** — top-down:

```
root:                 S = L(root); if None -> horizon; if horizon < L -> cut, truncated = True
child of sequential:  starts where the previous sibling ended;
                      S = L(child), or the rest of the parent's pass if None
child of parallel:    starts with the parent's pass; S = L(child), or the whole pass if None
```

Consequences, all intended:
- An unbounded child of a `parallel` node **spans the whole parallel block** — "hold 65 °C as
  long as the cycling runs" needs no duplicated duration (§8).
- A bounded parallel child that ends early releases its channel to the channel's `idle` state.
- `duration` on a repeating node is the **time break condition**: `repetitions: forever` +
  `duration: 500 h` repeats until 500 h, cutting the last pass.
- `stop_when` cannot be simulated: the expander assumes it never fires and sets `estimated`.

**Join-all vs. first-to-finish (D12).** The question is only *when a `parallel` block ends*
if its bounded children have different lengths. Unbounded children never "finish", so
blocks like ISOS-L-2 (§8) behave identically under both rules. The difference:

| Heater `hold 65 °C, 500 h` ∥ cycling of 1000 h | **Join-all** (chosen) | First-to-finish |
|---|---|---|
| The block ends at | 1000 h — the longest child | 500 h — the shortest child |
| The heater | goes to `idle` at 500 h; the cycling continues | — |
| The cycling | runs to completion | is cut at 500 h, mid-cycle |
| "Stop everything when X" | `duration` / `stop_when` on the parallel node | built in, but only for "when a child ends" |

Join-all never cuts a branch silently; everything first-to-finish offers is still available
explicitly through the break conditions on the node itself.

**Written set `W(node)`** for R3 — bottom-up set of `(channel, control group)`:
a leaf writes the group of its `variable`, or all the channel's groups if it has none;
a container writes the union of its children. For a `parallel` node the children's `W` must be
pairwise disjoint.

> **Pitfall — R3 is deliberately static.** Two parallel branches touching the same group at
> *different* times are still rejected. Restructure instead (usually: the channel's steps
> become one sequential branch). That is what keeps the tree readable.

---

## 6. Unit parsing spec — `units.py`

One function, never ad-hoc pint calls. The channel's `parse()` delegates here.

```
parse(text, variable) -> (kind, float in the kind's canonical unit)
  0. normalise: U+2212 minus -> '-', µ/μ -> 'u', strip thin/nbsp spaces
  1. split "number unit" ourselves; a bare number -> error (D6)
  2. alias time tokens: h -> hour, min -> minute, d -> day   (always, token-wise)
  3. resolve the KIND:
       dimensionless tokens -> own factor table, pint NOT used:
         '%RH' 'vol%' 'mol%' 'wt%' 1e-2 · 'ppmv' 'ppmw' 1e-6 · 'ppbv' 'ppbw' 1e-9 ·
         'g/kg' 1e-3 · 'mol/mol' 1                       (token -> kind per §4.1 table)
         'ppm' 1e-6, 'ppb' 1e-9 -> molar_ratio            (glovebox convention, D6)
         '%' 1e-2 -> only if the variable has exactly one dimensionless kind;
                     otherwise "ambiguous" error listing the options
       everything else -> pint dimension -> the variable's kind with that dimension
  4. 'sun' -> 1000 W/m^2 (handled here, never via ureg.define)
  5. check the dimension; convert to canonical; any mismatch fails LOUDLY
parse_duration(text)       -> seconds    (expected dimension [time])
parse_rate(text, variable) -> (kind, canonical per second)
       split at the LAST '/': numerator via parse(), denominator via parse_duration()
       -> works for '5 %RH/h' and '2 K/min', where pint alone cannot
```

**Verified pint behaviour this spec exists for** (`nomad.units.ureg`):

| Input | Naive `ureg.Quantity(text)` | Handled by step |
|---|---|---|
| `24 h`, `10 K/h` | **silently** Planck's constant | 2 (+ 5 catches it loudly) |
| `1 min` | **milli-inch** | 2 |
| `42 d` | undefined | 2 |
| `65 °C` | `OffsetUnitCalculusError` | 1 — `ureg.Quantity(65, '°C')` works |
| `1 sun`, `%RH`, `vol%`, `wt%`, `ppb`, `ppmv` | undefined | 3, 4 |
| `5 %RH/h` | undefined, and `h` is Planck again | `parse_rate` split |
| `%`, `ppm`, `g/kg`, `mol/mol` | all dimensionless, `mol/mol` loses its token | 3 (read before pint) |
| `−40 °C` (U+2212) | `float()` fails | 0 |
| `50 mV/s`, `212 mbar`, `12 g/m³`, `100 mW/cm^2`, `1000 hours` | correct | — |

Never call `ureg.define()` — the registry is shared with every other plugin.

---

## 7. `normalize()` pipeline and validation

**Verified:** NOMAD normalizes sub-sections *before* their parent, and catches and logs
exceptions ("could not normalize section"). Therefore:

- Run the whole pipeline in **`StabilityProtocol.normalize()`** (it runs last). The one exception is
  a node's derived `name`: `SubProtocol.normalize()` sets it, since it depends on the node
  alone. Channel sections need no `normalize()` of their own.
- **Do not raise.** Collect messages, `logger.error/warning` them, copy them to
  `timeline.messages`, and skip expansion on errors — a raised exception just leaves the entry
  half-derived.
- **Be idempotent.** `normalize()` runs on every save and reprocess: rebuild `timeline`,
  `summary` and `figures` from scratch (reset `self.figures = []`), never append.

```
1. collect channels  -> key index (+ implicit always-reported targets)
2. build IR          -> plain dataclasses: resolve keys, parse every string (§6)
3. validate          -> §7 list below, on the IR
4. expand            -> exact event list (§5)
5. write back        -> derived fields on nodes (name, duration_s), timeline (budgeted),
                        summary, figures
```

Steps 1–4 take the authored protocol content as input and touch no archive, so
`StabilityMeasurement.normalize()` reuses them unchanged to build its own summary (§4.5).

**Validation** (all errors unless marked *warning*):

| Area | Check |
|---|---|
| Structure | unknown key, with did-you-mean (§9 pitfall) · every `SubProtocol` has exactly one of `channel` / `subprotocol` (the root has neither field) · `subprotocol` without `steps` · `channel` with `steps` · `channel` without a state slot · more than one state slot · `mode: parallel` without children (*warning*) |
| References | unknown channel key (with did-you-mean) · duplicate keys · stepping on an implicit channel |
| Variables & states | missing / unknown / non-controllable `variable` · state not in `accepted_states` · sweep on a variable other than voltage/current · ramp with neither or both of `rate` and `duration` · non-positive `rate` |
| Units | unparseable string · bare number · ambiguous unit (bare `%` on humidity or oxygen) · dimension mismatch · mixed kinds within one state · value outside `limits` (compared only within the same kind) |
| Conditions | unparseable `stop_when` · unknown observable · value dimension mismatch · observable not monitored (*warning*) — §4.2.1 |
| Timing | unbounded child that is not last in a `sequential` node · repeating node (`repetitions` ≠ 1) whose pass is unbounded · unbounded root without `horizon` · `repetitions` not an integer ≥ 1 or `forever` · `duration` cuts a node short of its natural length (*warning*) · `stop_when` present (*warning*: estimated) |
| R3 | overlapping written sets among the children of a `parallel` node |

---

## 8. Worked examples

### ISOS-L-2 — light soak, 65 °C, 1 sun, MPP with a daily JV sweep

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: ISOS-L-2 light soak, 65 C, MPP with daily JV
  isos_specification: ISOS-L-2

  channels:
    temperature:
      - key: chuck_T
        limits: [20 °C, 90 °C]
        regulation: {kind: pid, kp: 2.0, ki: 0.1}
        monitor_every: 60 s
    irradiation:
      - key: sun
        spectrum: AM1.5G
        monitor_every: 60 s
    electrical_load:
      - key: bias
        monitor_every: 60 s
    # no atmosphere declared -> implicit "atmosphere: uncontrolled" row

  protocol:
    name: light soak
    mode: parallel
    steps:
      - {channel: chuck_T, hold: 65 °C}          # unbounded -> spans the block
      - {channel: sun, hold: 1 sun}              # unbounded -> spans the block
      - subprotocol: daily cycle                 # bounded: 42 × (24 h + sweep)
        repetitions: 42
        steps:
          - {channel: bias, track: mpp, duration: 24 h}
          - channel: bias
            variable: voltage
            sweep: {from: -0.2 V, to: 1.3 V, rate: 50 mV/s, direction: both}
```

*"Hold 65 °C and 1 sun while running the daily cycle 42 times; a daily cycle is 24 h of MPP
tracking followed by a JV sweep."* No `horizon` needed: the tree is bounded. R3 holds —
`chuck_T`, `sun`, `bias` are disjoint; inside `daily cycle` both steps write `bias`, which is
fine because that node is sequential.

**Variant — heater ramped down over the last 100 h.** Only the temperature line changes:

```yaml
      - subprotocol: thermal profile
        steps:
          - {channel: chuck_T, hold: 65 °C, duration: 900 h}
          - {channel: chuck_T, ramp: {from: 65 °C, to: 25 °C}, duration: 100 h}
```

Equivalently `ramp: {from: 65 °C, to: 25 °C, rate: 0.4 K/h}` — a ramp takes a rate *or* a
duration, never neither (D16).

### ISOS-D-3 — damp heat, 85 °C / 85 %RH, dark

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: ISOS-D-3 damp heat
  isos_specification: ISOS-D-3
  horizon: 1000 h                                  # every step is unbounded

  channels:
    temperature: [{key: oven_T, monitor_every: 10 min}]
    irradiation: [{key: oven_dark}]
    atmosphere:  [{key: oven_air, balance_gas: air, monitor_every: 10 min}]

  protocol:
    name: damp heat
    mode: parallel
    steps:
      - {channel: oven_T, hold: 85 °C}
      - {channel: oven_air, variable: humidity, hold: 85 %RH}
      - {channel: oven_dark, off: true}            # deliberately dark: D, not "bench"
```

Electrical load is not declared → implicit, uncontrolled = open circuit.

---

## 9. YAML ergonomics — why the file looks like §8

**Named slots instead of `m_def` — verified.** For a polymorphic sub-section `state: State`:

| YAML | Result |
|---|---|
| `state: {value: 1}` | **silently** instantiates the base class |
| `state: {m_def: Hold, value: 1}` | `MetainfoReferenceError` — only the ~60-char qualified name works |
| `hold: ...` (named slot) | ✅ |

Same trick for channels via the `Channels` container. Cost: "exactly one slot" is a runtime
check (§7), not a schema constraint.

**Strings instead of unit-ful quantities — verified.** `Quantity(type=float, unit='second')`
accepts only a bare number *in seconds*: `dur: 24` is 24 s, while `"24 hour"` and
`{value: 24, unit: hour}` both raise. So authored values are `Quantity(type=str)`, parsed into
derived unit-ful quantities. A `str` quantity accepts YAML integers (`repetitions: 42` → `'42'`,
**verified**). Cost: the ELN shows text fields, not numeric widgets.

**Keys instead of paths.** NOMAD would write `#/data/channels/0` — unreadable and broken by
reordering. `channel: chuck_T` resolves in `normalize()` with a did-you-mean on typos.

**Recursion — verified.** `SubSection(section_def=SectionProxy('SubProtocol'), repeats=True)`
on `Protocol`, inherited by `SubProtocol`, nests without limit; the children load as
`SubProtocol` without any `m_def`. It must be a `SubSection` (containment):
`Quantity(type=SubProtocol)` is a *reference*, and a nested YAML dict loaded into it silently
becomes an unresolvable proxy. The proxy is needed because `SubProtocol` does not exist yet
while `Protocol`'s body is executed; it is resolved by name later. Any tree needs it — a
class that contains itself always refers to a name that is not defined yet.
Side effect (**verified**): `m_to_dict()` writes `m_def` on every nested step. Its check
(`sub_section != m_def`) compares the proxy with the resolved definition — two objects,
though both are `SubProtocol`. Harmless: the stored archive reloads, and hand-written YAML
needs no `m_def`. Tests that compare against authored dicts strip it.

> **Pitfall — unknown keys are dropped silently (verified).** NOMAD's YAML parser ignores
> keys that are not fields of the section: a typo (`chanel: bias`, `hodl: 65 °C`) or a field
> on the wrong node (`channel:` on the root `Protocol`) vanishes without an error, and
> `normalize()` can no longer see it. This is a validation gap, not a design driver — the
> structure is chosen as if unknown keys raised. Mitigation (**verified** with `m_from_dict`):
> override `m_update_from_dict` — the same hook as the `off` fix — to note the keys not in
> `m_def.all_properties` on the instance (a plain attribute, not metainfo; it only has to
> live until `normalize()`, which runs right after parsing), then report them in §7 with a
> did-you-mean.

**Still worth knowing:**
- the root `m_def` is unavoidable (one line);
- YAML 1.1 reads bare `off` / `on` / `yes` / `no` as booleans; of the schema's words only
  `off` collides, and it is handled (§4.2 pitfall);
- deep trees get deeply indented — flow style (`{channel: …, hold: …}`) keeps leaves to one line;
- **modelling tip:** use a `cycle` state for periodic *stress* (one line, no depth) and
  `repetitions` only for repeating *structure*. Two channels with incommensurate periods are
  simply two branches of a `parallel` node — no LCM flattening.

---

## 10. Module layout and implementation order

```
src/nomad_pv_stability_measurements/
  schema_packages/
    __init__.py       one SchemaPackage / entry point, imports all modules below
    units.py          parse / parse_duration / parse_rate, kind tables        (§6)
    conditions.py     stop_when tokenizer + parser -> IR                     (§4.2.1)
    channels.py       Variable, Kind, Channel + 5 subclasses, Channels, RegulationLaw
    states.py         Ramp, Cycle, Tabulated, Sweep
    protocol.py       Protocol, SubProtocol, StabilityProtocol, ProtocolSummary, normalize pipeline, plot
    timeline.py       ProtocolTimeline
    results.py        StabilityMeasurement, StabilityResult, …                (iteration 2)
  simulation/
    ir.py             plain dataclasses the expander works on
    expander.py       §5 — pure Python, no metainfo
    validate.py       §7
tests/
  data/               the two §8 examples as .archive.yaml
```

Suggested order — each step is testable on its own:

1. **`units.py` + tests** — table-driven from §6; the highest bug density lives here.
   `conditions.py` follows naturally — it reuses `parse()` for its values.
2. **`channels.py`** — variable tables, `parse()` delegation, control groups.
3. **`simulation/`** — IR, expander, validation; test with plain dataclasses, no archive.
4. **`states.py`, `protocol.py`** — metainfo, IR builder, `normalize()`, summary.
5. **`timeline.py` + plot** — budgeting and the two figures.
6. **End-to-end** — process both §8 examples with NOMAD; check the ELN order and search.
7. **Iteration 2** — `results.py`, parsers, HDF5.

---

## 11. Open points

Everything else was settled in review and is folded into §1 (names, no bare `%` on
humidity/oxygen, `ppm` = molar, join-all,
text conditions, 3000-point budget, no depth warning, no ramp list-shorthand, the
always-reported set, one protocol per upload).

| | Question | Iteration 1 |
|---|---|---|
| O9 | **Cross-kind search** — a best-effort `water_molar_ratio_mean` in the summary, computed only when temperature is *controlled* over the span and null otherwise (never guessed from an uncontrolled channel)? | left out; revisit after the first real data |

## 12. Deferred on purpose

All additive — none reworks the core.

- **ISOS conformance checking** — ship ISOS envelopes as YAML data and validate the expanded
  timeline against them. Not as a class hierarchy (`ISOSL2Protocol` would not survive an ISOS
  revision).
- **Workflow integration** — a tree of `Protocol` nodes maps naturally onto NOMAD's nested
  `TaskReference` workflow.
- **Parsers** for instrument files and command logs (`source = logged`).
- **Reuse** of `SolarCellJV`, `nomad-measurements`, `perovskite-solar-cell-database`.
- **Spectrum** — a structured `SpectrumDefinition` instead of the `spectrum` string, from
  which UV irradiance (and a summary `uv_irradiance_mean`) is derived.
- **Sample-derived summary fields** — encapsulation etc., back-populated from the sample
  into each measurement's `protocol_summary`.
- **Richer `stop_when` grammar** — `and` / `or`, `for <duration>`, `within … of setpoint`
  (§4.2.1).
- **More channels** — enclosure, reverse-bias polarity.
