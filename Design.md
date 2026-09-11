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
routine:                                   # ISOS-L-2 (full file in §8)
  name: light soak
  commands:
    - {channel: temperature, hold: 65 °C}
    - {channel: irradiation, hold: 1 sun}
    - name: daily cycle
      repetitions: 42
      commands:
        - {channel: electrical_load, track: mpp, duration: 24 h}
        - {channel: electrical_load, variable: voltage,
           sweep: {from: -0.2 V, to: 1.3 V, rate: 50 mV/s}}
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
| D4 | **The channels are a closed, hard-coded vocabulary — one per stress axis, never authored.** A channel is a Python class holding a table of named *variables* — each controllable and/or monitorable — plus *control groups* (which variables can be commanded at the same time). All behaviour lives once in the base class. The routine names a channel through an **enum** (`channel: temperature`), so there are no user-invented keys and no `channels:` section in the file. A new channel = a new class plus an enum member, i.e. a plugin change that everybody then shares. |
| D4a | **`channel_settings:` carries each channel's run-wide conditions** — one optional block per channel: a setpoint (`hold`), a monitor tag with its rate, plus `limits`, regulation, instrument, spectrum … It holds wherever the routine is silent; a step overrides it for its span. **Only static conditions** live there — a constant `hold` is the settings' whole vocabulary; the time-varying shapes (`ramp`, `cycle`, `tabulated`, `sweep`, `track`) are only ever set by the routine, never a field of a settings block (§4.1). |
| D4b | **The routine overrides the settings, and the warning says where.** One precedence rule for states and for monitoring: the innermost step that speaks wins for its span, the settings hold everywhere else. Because a shadowed setting is invisible in the file, `normalize()` reports it: a *warning* per (channel, field) that some step overrides, and a louder one for a setting that is **never** in effect. This must also be said in plain words in the field descriptions and the README (§10). |
| D5 | **Variables have physical names** (`humidity`, `oxygen`, `temperature` …); **the unit selects the quantity kind** (relative, molar ratio, dew point …). Values stay in the kind they were given — no cross-kind conversion. |
| D6 | **Every value is a unit string** (`65 °C`, `85 %RH`, `1 sun`), parsed and dimension-checked against its variable. **Ambiguity is an error:** bare numbers, and bare `%` on humidity/oxygen. The one documented convention: `ppm`/`ppb` are molar (ppmv) — the glovebox standard. The string is the *authored* form only: it is read into the field's own unit-ful quantity on the way in (D19). A bare number **written as text** stays an error; a plain YAML number is read in the quantity's declared unit — which is what NOMAD itself writes back when it serializes. |
| D7 | **The four ISOS stress axes are always reported.** Since the vocabulary is fixed (D4), this is structural: a channel no routine touches appears in the derived layers as *uncontrolled and unmonitored*. UV content is a property of the irradiation spectrum, not a channel; encapsulation belongs to the sample. |
| D8 | **A command says what is *asked* of a channel; the control *state* is derived, never authored.** A `ChannelCommand` carries a setpoint (`hold`) or a time-varying shape (`ramp`, `cycle`, `tabulated`, `sweep`, `track`) and nothing that names a control mode. **Asking nothing is the neutral element**: a channel no command in scope touches is not regulated, which is also what it is wherever nothing says otherwise, so every channel still has a defined state at every instant (D7). Two booleans follow per channel, **computed over time when commands are expanded into a time series, not stored on a command**: **`controlled`** (some command in scope asks for a value) and **`monitored`** (a monitor tag is in effect) — timeline rows, plottable next to the values (§4.4). On a command itself, `controlled` is only "does this carry a setpoint". *Supersedes `control = MEnum('off', 'hold', 'active')` (and, before that, the `uncontrolled`/`off` split): `hold` already said `hold`, and `active` was a label for time-varying behaviour that a single static command cannot know — a command is one clause, and what a channel is doing at hour 700 follows from all the clauses in scope. **Explicitly released** is still writable, structurally: a command that **names a channel and asks nothing of it** says "not regulated here" out loud, as against a channel nobody mentions (§4.1, "Untouched channels").* |
| D8a | **Named setpoints: a channel class may declare words that stand for values.** `IrradiationChannel` declares `dark` (= `0 W/m²`); `ElectricalLoadChannel` declares `open_circuit`. They are written wherever a value is written — `hold: dark`, `cycle: {low: dark, high: 1 sun}`, `ramp: {from: dark, to: 1 sun}` — and resolved against the channel's own table in `normalize()`, **before** `parse()` (§6). Per channel, never global: `dark` is meaningless on the temperature axis and is rejected there. A name that stands for a number becomes one, so the timeline plots `dark` as 0 instead of a NaN hole; a name that stands for no number at all (`open_circuit` is neither 0 V nor 0 A) stays NaN, like `track`. **Asking for a named setpoint is asking for something**, so `controlled` is true — that is how "deliberately dark" is said out loud *and counted*, the one thing the old irradiation-only `off` state did that D8 alone does not (§4.1). **Spelled `dark`, never `off`:** a bare `off` is a YAML 1.1 boolean (§9), so that spelling arrives as `False` and would silently invert the very flag it exists to set — and `dark` is ISOS's own word. **There is no `on`:** `dark` has a defined value and an illuminated state does not, and the irradiance is exactly what ISOS reporting needs, so it is written as a number (`hold: 1 sun`). |
| D9 | **Monitoring is a tag, not a state.** Acquiring data is an action, so it is said where the condition is said: `monitor: true` with an optional `sample_every: 60 s` or `sampling_rate: 10 Hz` — in a channel's settings (the whole run) or on a node (its span, D13). It is orthogonal to the setpoint, so the same place may set a state *and* monitor, and monitoring alone logs a channel nobody controls. |
| D10 | **The regulation law (PID, on/off …) is a channel setting**, orthogonal to the setpoint shape. |

**Routine** (§4.2, §5)

| # | Decision |
|---|---|
| D11 | **One base, two kinds of command, single inheritance throughout: `RoutineCommand` → `ChannelCommand` \| `Subroutine` → `Routine`.** A `ChannelCommand` *acts* on one axis; a `Subroutine` is a *block* that contains commands of its own. **Both live in one authored list, `commands:`** — a channel command holds for its block's whole span, a block runs where `mode` puts it. `Routine` is the root: a block authored under the protocol. **Three keywords carry the whole tree: `commands`, `channel`, `name`.** A node needs no `subroutine:` tag — a block is simply a command that names no `channel`, and it labels itself with the `name` every command already has. |
| D11a | **The mixed list decides its `m_def` by key, then lets NOMAD load it natively.** Verified: a repeating sub-section typed to a common base instantiates *the base* and silently drops whatever the subclass added, unless every entry carries the ~70-char qualified `m_def:` — schema boilerplate in every file, and the only native discriminator NOMAD has (no short form: a bare class name fails to resolve, verified). `Subroutine.m_update_from_dict` reads the keys — **a `channel` names that channel's own class, `channel: temperature` → `m_def: …TemperatureChannel` (D19a); anything else means `m_def: …Subroutine`** — writes that one field into each entry, then calls NOMAD's own, unmodified `m_update_from_dict` to do the actual building. No hand-built sections, no round-trip asymmetry (`m_to_dict` already wrote `m_def`; loading now agrees), and a nested block's own `commands` get their `m_def` too, since NOMAD calls back into this same method when it builds that block. An entry that already carries `m_def` is left alone — the sniff only fills a gap. |
| D12 | **`mode: sequential \| parallel`** on a node says how the *blocks* in its `commands` run — channel commands are conditions, not moments, so each holds for the node's whole span either way. Children of a `parallel` node must write disjoint control groups (rule R3). **Join-all:** a parallel block ends when its longest bounded child ends. |
| D13 | **Lifetime by lexical scope, with `duration` on the command itself.** No start/stop pairs. A command that gives a `duration` is an **episode** — it takes its turn in the order `mode` gives. A channel command that gives none is a **condition**, holding for its block's whole span; a block without one lasts as long as what it contains. Because `duration` sits on `RoutineCommand`, an episode needs no block wrapped around it purely to be given a lifetime. |
| D13a | **Two commands on one channel are never merged — they must be truly subsequent.** Siblings in one `commands` list have *equal* scope, so nothing in the file decides between them: `{channel: temperature, hold: 85 °C}` beside `{channel: temperature, monitor: true}` is **not** read as "hold and log", and no reader may assume it is. Two commands on the same channel are legal in one block only when each carries its own `duration` and the block is `sequential` — then they genuinely follow one another (rule R4). Everything else overlaps and is an **error**: two commands without a `duration` both span the block, a command without one covers an episode beside it, and under `mode: parallel` every child is simultaneous by definition. There is nothing to merge *because asking nothing is itself a statement* — a command that names a channel and asks nothing of it says "not regulated here" (D8), so the pair above is a contradiction, not two half-filled forms. The fix is one command carrying all the keys, or explicit nesting: where scopes differ, D4b's innermost-wins does decide, and that is the only reason this rule can be a cheap per-block set check instead of interval arithmetic. Overlaps are **reported, never repaired** — the authored file is left as written and expansion is skipped (§7). A command the block's `duration` leaves no time for is reported too (*warning*, R5).
| D14 | **Termination lives on the command:** `repetitions`, `duration`, `stop_when` — whichever comes first. No `WaitUntil`. `duration` is shared by both kinds (D13); `repetitions` and `stop_when` order blocks, so they stay on `Subroutine`. |
| D15 | **`stop_when` is a readable text condition** (`pce_relative < 80 %`), parsed into a structured form in `normalize()`. The grammar can grow (`and`, `or`, `for 10 min`) without invalidating stored text. |
| D16 | **A ramp needs a `rate` or a `duration`** — exactly one. |
| D17 | **A JV sweep during MPP tracking is its own step.** Both at once is not expressible (same control group). |

**YAML ergonomics** (§9)

| # | Decision |
|---|---|
| D18 | **Named state slots** (`hold:`, `ramp:` …) instead of polymorphic sub-sections — `m_def` is never hand-written except at the root. |
| D19 | **One field per value: the quantity itself, with the written unit read on the way in.** Every authored value is a real `Quantity(type=np.float64, unit=…)` — no `type=str` beside it, no twin. NOMAD refuses `duration: 500 h` on such a quantity (**verified**: it rejects `'24 h'` outright, reads a bare number as its declared unit, and honours no `__unit:` escape hatch anywhere in its source), so the plugin overrides the **one gateway every assignment passes through** — `MSection.m_set`, which `m_from_dict`, `m_update_from_dict` and `Section(**kwargs)` all funnel into (**verified**). A string handed to a quantity that declares a `unit` is parsed by §6 into a pint quantity, and NOMAD's own type normalization then converts and stores it (`500 h` → `1800000.0 s`, `65 °C` → `338.15 K`, **verified**). The file keeps the unit it was written with, the archive keeps a number, and unit switching, numeric search, plots and a loud `DimensionalityError` all come free from the declaration. *Supersedes the string-plus-twin pair: the twin existed only to buy back what the string cost, and reading the string one step earlier costs nothing to begin with.* |
| D19a | **Where the dimension depends on the channel, the field is declared on the channel class.** `hold` cannot sit on `ChannelCommand`: it is kelvin for temperature and W/m² for irradiation. So `ChannelCommand` does not declare it at all and each channel class declares its own — `TemperatureChannel.hold` in `K` — which is also how a channel whose setpoint is not a number at all declares an `MEnum` instead (`dark`, `open_circuit`, D8a). **Verified:** a subclass may declare what its base does not, and NOMAD then **silently drops** an authored `hold` when the same dict is loaded as the base class. That makes D11a's per-entry dispatch load-bearing rather than a convenience: it must resolve the `channel:` *value* to that channel's class (`channel: temperature` → `TemperatureChannel`), or the setpoint disappears without a word. Text the file writes that §6 cannot read is remembered where it was written and reported by `normalize()` (§7), never raised — a typo must not stop an entry from loading; an empty or blank string leaves the field unset, since asking nothing is the neutral element (D8). |
| D20 | **References by enum value** (`channel: temperature`) — never `#/data/...` paths, and never a free string that each lab spells differently. |

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
  channel settings +        column arrays of             what the instrument
  a routine tree            setpoint events              actually logged
  (hand-written)            (normalize() output)         (parsed from files)
```

- The timeline is **never hand-authored**. It is produced by a **pure-Python expander** working
  on plain dataclasses, unit-testable without an archive — the only place timing semantics live.
- The same `ProtocolTimeline` class can later be filled from an **instrument command log**
  (`source = logged`), which makes the headline plot *intended vs. actual*.

**The core model — four concepts:**

```
Channel               a stress axis from a fixed vocabulary: named variables it can
                      control / monitor, plus its authored default settings
Routine               the tree: a root, and Subroutine nodes below it.
                      Names a channel -> sets it to a state.
                      Has blocks in `commands` -> runs them per its `mode`.
ProtocolTimeline      the expanded events (derived)
StabilityMeasurement  observed data, linked to protocol + sample (+ StabilityResult)
```

**Five rules:**

> **R1** — a node that names a channel puts (one variable of) it into a state for the node's span.
>
> **R2** — a node's `mode` says how the blocks in its `commands` run: `sequential`
> (default) or `parallel`.
>
> **R3** — the children of a `parallel` node write **disjoint control groups** (static set check).
>
> **R4** — sibling commands on one channel must be *truly subsequent*: each with its own
> `duration`, in a `sequential` node. Anything that overlaps is an error, never a merge (D13a).
>
> **R5** — a command the node's own `duration` leaves no time for never runs (*warning*, D13a).

Mixed sequencing composes by nesting — "A, then B ∥ C, then D":

```yaml
commands:
  - A
  - {name: fork, mode: parallel, commands: [B, C]}
  - D
```

Why this shape holds up:
- **Readability is structural.** Because of R3, "what is channel X doing at time t?" is
  answered by walking the tree — at most one branch can write X.
- **Reordering is safe where it should be.** Reordering children of a `parallel` node changes
  nothing; reordering a `sequential` node is visibly meaningful.
- **Channels own *what*, the tree owns *when*.** Channel classes add capabilities and
  physics; timing never leaks into them.

> **Superseded — "do not give states a `duration`".** An earlier draft kept `duration` off the
> states, so "hold 65 °C for 500 h" had to be written as a block wrapping one command
> (`{duration: 500 h, commands: [{channel: temperature, hold: 65 °C}]}`). The block carried no
> information of its own, and readers asked why it was there. `duration` now sits on
> `RoutineCommand`, so the command says it directly: `{channel: temperature, hold: 65 °C,
> duration: 500 h}`. The original worry — two states on one channel overlapping, turning R3's
> set check into interval arithmetic — is unchanged and still answered by lexical scope: a
> command's span is its own, and siblings in a `sequential` block cannot overlap — which R4 now
> says out loud and checks. R3 still compares *sets* per node, never intervals. (Sweeps, tabulated states and ramps given a `rate`
> *determine* their own length instead of being given one.)

---

## 4. Schema

### 4.0 Field order — **verified**

1. Inherited quantities come first (`BaseSection` → `name, datetime, lab_id, description`).
2. **All quantities serialize before all sub-sections**, regardless of declaration order.
3. Declaration order is kept within each group.

Sketches below are in true serialization order. Hand-written YAML may use any key order.
The ELN order can be overridden on the section definition with
`m_def = Section(a_display=SectionDisplayAnnotation(order=[...]))` — use it on `Subroutine` to
keep the state slots together (they straddle rule 2). **Verified:** the older
`a_eln=ELNAnnotation(properties=SectionProperties(order=[...]))` still works but is marked
*deprecated* in this NOMAD version; use `a_display`. Check in the GUI whether quantities and
sub-sections interleave; if not, the split is cosmetic only.

### 4.1 Channels — `routine.py`

**The vocabulary is closed (D4).** `CHANNELS` lists the stress axes, one hard-coded class each,
and the routine's `channel` quantity is `MEnum(*CHANNELS)`. The ELN then offers a drop-down, a
typo is rejected by the schema rather than by a validator, and every Oasis upload uses the same
word for the same axis. Nothing in a file can introduce a channel.

```
CHANNELS = (temperature, irradiation, atmosphere, electrical_load, mechanical)
```

The only authored part is the settings — at most one block per channel. A block says what the
channel does *whenever the routine is silent*, in the same words a step uses:

```
RoutineCommand(ArchiveSection)             # the interface both kinds of command share
    name          str              # authored at the root; derived further down
    duration      float [s]        # authored as "24 h", stored in seconds (D19). This
                                   #   command's span: WITH one it is an episode and takes
                                   #   its turn; WITHOUT one a channel command is a
                                   #   condition spanning its block, and a block lasts as
                                   #   long as what it contains.
                                   # + repetitions / stop_when when termination is built

ChannelCommand(RoutineCommand)             # acts on ONE axis — in a block's `commands`,
                                           #   or as a `channel_settings` block
    channel       MEnum(*CHANNELS)  # which axis; empty in settings (the slot says it)
    variable      str   (opt)      # which variable this applies to (the "variable rule", §4.2)
    # NO `hold` here — its dimension is the axis's, so each channel class declares its
    #   own (D19a). Unset = nothing asked of the channel: the neutral element (D8). No
    #   control mode is stored either; it is derived over time (§4.4)
    monitor       bool             # acquire data here (D9)
    monitored     str[] (opt)      # which variables; default: every monitorable one
    sample_every  float [s]  ┐     # "60 s"  -> discrete measurements  } author at most
    sampling_rate float [Hz] ┘     # "10 Hz" -> a stream               } one; the other is
                                   #   derived as its reciprocal (neither: unspecified)

TemperatureChannel(ChannelCommand)         # one per CHANNELS member: the axis's own class,
                                           #   carrying its variable table and, as a
                                           #   `channel_settings` block, the run-wide extras
    # --- quantities
    hold           float [K]       # authored as "65 °C" — the setpoint, in the unit only
                                   #   this class knows (D19a)
    limits         Any    (opt)    # {variable: [min, max]} as unit strings;
                                   #   plain [min, max] allowed for single-variable channels
    variables      str[]           # DERIVED from the class table (shown in the ELN)
    is_controlled  bool            # DERIVED: here or some step asks this channel for a
                                   #   value (D8)
    is_monitored   bool            # DERIVED: here or some step carries a monitor tag (D9)
    # --- sub-sections
    regulation     RegulationLaw (opt)
    instrument     InstrumentReference (opt)

ChannelSettings(ArchiveSection)     # authored as `channel_settings:`
    temperature      TemperatureChannel      ┐  one NON-repeating slot per member of
    irradiation      IrradiationChannel      │  CHANNELS; each optional, and omitting one
    atmosphere       AtmosphereChannel       │  means "all defaults" (D7 stays structural)
    electrical_load  ElectricalLoadChannel   │
    mechanical       MechanicalChannel       ┘

RegulationLaw(ArchiveSection)                    # metadata only
    kind enum{open_loop, pid, on_off, external};  kp, ki, kd, hysteresis
```

One block sets at most **one variable** of its channel, since it has one state and one
`variable`. Holding humidity *and* oxygen constant therefore takes two routine commands — rare
enough to leave to the tree, where parallel branches already say it.

No `key`, no `name`: the slot *is* the identity. The class stays `TemperatureChannel` — it
carries the variable table as well as the settings — while the container is named for what is
authored, so the YAML reads `channel_settings: {temperature: {...}}` and a step that
says otherwise visibly overrides it.

> **Pitfall — `JSON` accepts dicts only (verified).** `Quantity(type=JSON)` rejects a list
> (`Shape mismatch`, and the type itself raises `needs to be a dict`), so the single-variable
> form `limits: [20 °C, 90 °C]` would fail to load. `limits` is therefore `Quantity(type=Any)`
> (`nomad.metainfo.Any`), which stores both forms as given and round-trips through
> `m_to_dict`. Cost: no ELN widget (there is no JSON edit component either) — limits are
> authored in YAML.

#### What a channel is for

The stress axes exist in *every* stability measurement whether anybody writes them down or not
(D7), so nothing in a file brings one into being. A channel therefore does four things:

| | Role | Used by |
|---|---|---|
| 1 | **Vocabulary** — the enum member is the one name for that axis, everywhere: the routine's `channel:`, the timeline targets, the plot rows, the summary fields, and the columns of parsed result data (`StabilityResult.channel_series`, §4.5). | everything |
| 2 | **Capability** — the class's variable table, control groups and accepted states: what this axis *can* do, and therefore what a routine may ask of it. | validation (§7) |
| 3 | **Run-wide conditions** — what holds where the routine is silent: a static state, whether the channel is logged, and at what rate. | the expander (§5) |
| 4 | **Envelope and provenance** — `limits`, `regulation`, `instrument`, `spectrum`, `balance_gas`: the metadata that makes a run reproducible and searchable. | validation, summary, search |

> **Static conditions in the settings, time-varying ones in the routine.** An earlier draft
> banned setpoints from the settings outright ("they may say *how*, never *what*"). That was too
> strict. A run-wide constant is precisely what the old `idle` field already was, only widened
> from the released states to any value, and it keeps every property §3 relies on: precedence is
> trivial (**the routine wins for its span, the settings hold everywhere else**), and there is
> nothing to resolve in time because a settings block has one value for the whole run. So `idle`
> is gone, replaced by the `hold` slot of `ChannelCommand`.
>
> What stays out — and is not a field of a settings block at all, so the schema enforces it:
> `ramp`, `cycle`, `tabulated`, `sweep`, `track`, and anything with a `duration` or
> `repetitions` — the time-varying shapes, defined only in the routine. A time-varying
> default would put a second timeline on one channel, and merging
> it with the tree's spans needs exactly the interval arithmetic that D13 and R3 exist to avoid.
>
> The payoff is visible in §8: a steady-state protocol — most of ISOS — becomes a settings table
> plus a `duration`, and the routine carries only what actually changes over time.

#### Precedence, the neutral element, and the override warning (D4b, D8)

```
state(channel, t)      = the innermost step covering t that names the channel,
                         else the channel's settings block,
                         else nothing asked                <- the neutral element
monitoring(channel, t) = the same three-step fallback, independently of the state
```

- **There is always an answer.** *Nothing asked* is the neutral element of that fallback, so
  every channel has a state at every instant and the derived layers never have a hole —
  including the channels nobody mentioned (D7). "Deliberately not regulated" is still worth
  recording as against nobody having thought about it, and needs no state to say it: **a command
  that names the channel and asks nothing of it** is the explicit release (D8). (Considered and
  rejected as a name for the neutral state, back when it was one: `inactive`. A channel is never
  inactive — the temperature still has a value; what is absent is *control over it*.)
- **State and monitoring fall back separately.** A step that only changes the sampling rate keeps
  the settings' `hold`, and a step that only sets a state keeps the settings' monitoring. This is
  what makes the JV sweep natural: it says `sampling_rate: 10 Hz` and inherits everything else.
- **Two derived booleans per channel, over time** (D8): `controlled` — some command in scope
  asks the channel for a value, so a settings `hold` counts as much as a routine `ramp`; and
  `monitored` — a monitor tag is in effect. They are computed where time lives, not stored on a
  command: rows in the timeline (§4.4), which answers
  "was this channel under control at hour 700?" by looking rather than by reading YAML, and the
  summary's `*_controlled` / `*_monitored` flags are just `any()` over them.
- **Overriding warns (D4b).** A settings value that some step shadows is easy to misread, so
  `normalize()` says so — once per (channel, field), not once per step, because 42 sweeps
  overriding one rate is one fact, not 42:
  *"channel_settings.electrical_load.sampling_rate (1 Hz) is overridden by 42 commands, for 3 h of
  1008 h"*. A setting that is **never** in effect gets the stronger message — it is dead
  configuration, usually a sign the author meant to change the routine instead.
- **It must be documented, not only validated.** The precedence rule belongs in the `description`
  of every overridable field, in the README, and in the example upload (§10) — a user who never
  reads this document must still be told that the routine wins.

**Why a closed vocabulary beats per-device declarations (D4).** Free `key`s were the earlier
design; they were dropped because they de-harmonize an Oasis: `temperature`, `sample_T` and
`T_stage` would all mean the temperature axis, and no cross-upload search could join them. The
fixed set also deletes machinery — key resolution, duplicate-key and did-you-mean checks, the
whole `channels:` section — and makes D7 structural instead of derived. What it costs:

| Cost | Answer |
|---|---|
| **Two devices on one axis** (heated chuck *and* chamber air) cannot both be declared. | Deferred (§12). When it is needed, it is a curated enum member (e.g. `ambient_temperature`), not a free key — so every Oasis gains the same word at the same time. |
| Per-device labels (`temperature`) are gone from the file. | The device belongs in `instrument`; the axis is what the data is about. |
| A lab with an exotic axis must change the plugin. | Deliberate: that change is reviewed once and shared, instead of one spelling per upload. |

**No hardware maxima.** A "fastest the device can sample" field was considered and dropped: the
schema is a read-only record (D1), so nothing is driven and such a field would only ever serve a
sanity check, at the cost of a number somebody has to look up. A standard rate, in contrast, is
consumed — it fills in what the routine leaves unsaid. Instrument limits belong on the
instrument.

**Subclasses — the whole per-channel specificity is this table:**

| Class (enum member = settings slot) | Variables (canonical unit, display) | Control groups | Extra states / named values | Extra fields | Always reported |
|---|---|---|---|---|---|
| `TemperatureChannel` (`temperature`) | `temperature` (K, °C) | {temperature} | — | — | ✅ |
| `IrradiationChannel` (`irradiation`) | `irradiance` (W/m², W/m²) | {irradiance} | `dark` = `0 W/m²` (named value, D8a) | `spectrum` str (`AM1.5G`) | ✅ |
| `AtmosphereChannel` (`atmosphere`) | `humidity` (multi-kind), `oxygen` (multi-kind), `total_pressure` (Pa, mbar) | {humidity}, {oxygen}, {total_pressure} | — | `balance_gas` str (`N2`, `air`, `Ar`) | ✅ |
| `ElectricalLoadChannel` (`electrical_load`) | `voltage` (V), `current` (A), `resistance` (Ω, control only) | {voltage, current, resistance} | `track`, `sweep`; `open_circuit` (named value, no number, D8a) | — | ✅ |
| `MechanicalChannel` (`mechanical`) | `bend_radius` (m, mm), `strain` (dimensionless, %) | {bend_radius, strain} | — | — | ❌ |

All variables are controllable and monitorable unless noted. Generic states
(`hold`, `ramp`, `cycle`, `tabulated`) are accepted by every channel, as is asking nothing.
Named values are the opposite — declared by one class, accepted only there (D8a).

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
    named_setpoints = {}              # D8a; IrradiationChannel: {'dark': '0 W/m²'},
                                      #   ElectricalLoadChannel: {'open_circuit': None}
    always_reported = True
```

**Base-class interface** (implemented once):

```
can_control(variable) / can_monitor(variable) -> bool
group_of(variable)                            -> frozenset
resolve(text)                                 -> a named setpoint, or text unchanged  # D8a
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
- **Across commands, kinds may differ** (the sample moved from chamber to glovebox). The timeline
  target is therefore *(channel, variable, kind)* — one plot row per kind, never a shared axis.

#### Untouched channels, and saying "deliberately not regulated"

Every always-reported channel that **no command acts on** is unregulated from t = 0 — there is
nothing to declare, so nothing to forget (D7). Every protocol plot shows the same four axes,
whatever the file says.

That leaves the question the old `uncontrolled`-vs-`off` split existed to answer: how to tell a
protocol that says "dark" from one that simply never mentions irradiation. **Three distinct
statements now cover it, and no control enum among them:**

| The file says | Means | `controlled` |
|---|---|---|
| nothing about the channel | nobody considered it | false |
| names it, asks nothing — `{channel: irradiation, duration: 1000 h}` | released here, deliberately | false |
| asks a named setpoint — `{channel: irradiation, hold: dark}` | deliberately dark, and that *is* the setpoint | **true** |

The middle form is also how a channel is released mid-run, inside a block that holds it (§4.2).
The last is D8a, and it is the one ISOS-D needs: darkness somebody chose and reported is a
condition, so it counts as controlled — the only thing the old irradiation-only `off` state was
good for, recovered without an enum. *Decided; unbuilt — the irradiation channel is step 6 of the
implementation plan.*

### 4.2 Routine nodes and states — `routine.py`, `states.py`

```
Subroutine(RoutineCommand)                        # a NODE: what it commands, what it contains
    # --- quantities: `name` inherited from RoutineCommand, then
    mode          MEnum(sequential, parallel)  # default sequential; on every node, not just the root
    repetitions   str        # "42" or "forever"; omitted => 1
    stop_when     str        # "pce_relative < 80 %" — a text condition, §4.2.1
    # --- sub-sections
    commands      RoutineCommand[]  # ChannelCommands and blocks in ONE list;
                                    #   resolved by key, not by m_def (D11a)

Routine(Subroutine)                               # the ROOT — a node authored under the
                                                  #   protocol, so `name` is written, not derived

ChannelCommand(RoutineCommand)                    # §4.1 — the acting kind; gains the time-varying
    track         MEnum(mpp, voc, jsc)   # a state, electrical only      states below
    # --- sub-sections
    ramp          Ramp       ┐
    cycle         Cycle      │  section state slots (the time-varying shapes)
    tabulated     Tabulated  │
    sweep         Sweep      ┘
```

> **How one list can hold two classes (D11a).** NOMAD will not do it unaided: a repeating
> sub-section typed to `RoutineCommand` instantiates *`RoutineCommand`* and silently drops
> whatever the subclass added, unless every entry carries `m_def:` (verified, §9) — there is no
> shorter native spelling. `Subroutine.m_update_from_dict` reads the keys — **a `channel`
> names that channel's own class (`temperature` → `TemperatureChannel`, D19a), anything
> else means `Subroutine`** — and writes the matching `m_def` into the entry before handing it to NOMAD's own dict-loading code, which
> does the actual building (and the actual recursing, into a nested block's own `commands`).
> The file stays free of schema boilerplate; the override's whole job is picking a class name,
> nothing more.

`Subroutine`'s `commands` hold `Subroutine`s too, so the tree nests without limit. A block is
named by the `name` that `RoutineCommand` already gives every command; channel commands take
a derived one.

**The command is the settings vocabulary plus time.** `ChannelCommand` (§4.1) is what a
settings block and a node's `channel` entry both are, and it adds what only makes sense for a
span: the time-varying states (`ramp`, `cycle`, `tabulated`, `sweep`, `track`). The node around
it carries `duration` / `repetitions` / `stop_when` / `commands`. One vocabulary, two scopes — a
settings block is the whole run, a node's command is its span, and the node wins where both
speak.

**At most one state slot per node; a `channel` node needs a state, a monitor tag, or both.**
Expose the state slots through one Python property (`node.state`) so the expander sees a single
canonical state object.

**One voice per channel at a time — siblings are never merged (D13a, R4).** Two commands on one
channel in the same `commands` list are legal only when each has its own `duration` and the block
is `sequential`, because only then do they genuinely follow one another:

```yaml
# WRONG — overlapping siblings. Not "hold and log": the second names the channel and
# asks nothing of it, which says *not regulated here* (D8). The two contradict.
commands:
  - {channel: temperature, hold: 85 °C}
  - {channel: temperature, monitor: true}

# RIGHT — one command says both things.
commands:
  - {channel: temperature, hold: 85 °C, monitor: true}

# RIGHT — truly subsequent: each episode has its own turn.
commands:
  - {channel: temperature, hold: 25 °C, duration: 1 h}
  - {channel: temperature, hold: 85 °C, duration: 500 h}
```

The check is a per-block set check, not interval arithmetic: siblings have equal scope, so there
is no precedence rule to apply to them, while *nested* commands differ in scope and D4b decides
those (innermost wins). `normalize()` reports the overlap and leaves the commands as authored.

#### Monitoring — the `monitor` tag (D9)

A measurement is an action, so it is said where the condition is said. In a settings block
`monitor: true` means *log this channel for the whole run*; on a command in a block's
`commands` it means *log it for that block's span* — the same lexical scope rule as states (D13), so monitoring starts and
stops with the node that asks for it.

```yaml
- {channel: temperature, hold: 65 °C, monitor: true, sample_every: 60 s}   # set AND log
- {channel: temperature, monitor: true, sample_every: 10 min}              # log only; `off`
- {channel: electrical_load, track: mpp, duration: 24 h,
   monitor: true, sampling_rate: 1 Hz}
- {channel: electrical_load, variable: voltage, sweep: {...},
   monitor: true, sampling_rate: 10 Hz}
```

- **Orthogonal to the state.** The tag is not a state slot: it sits *next to* one, so "hold and
  log" is one node instead of two parallel branches — and two siblings that split the job
  between them are an error rather than a merge (D13a). A node with a tag and no state logs a
  channel nobody controls — the honest way to record "ambient, but measured".
- **`sample_every` vs. `sampling_rate`** — the same physical thing from two intents: an
  interval means discrete measurements, a frequency means a stream. Exactly one may be given;
  both are unit strings (§6), parsed to seconds and hertz. On a node, omitting both falls back to
  the channel's settings; if those are silent too, the rate stays unspecified rather than guessed.
- **Per run and per step.** The settings carry the rate a protocol mostly logs at; a step
  overrides it where it matters — MPP tracking at 1 Hz and the daily JV sweep at 10 Hz on the
  same channel.
- **Never part of R3.** Monitoring writes nothing, so a monitor tag adds nothing to `W(node)`
  (§5) and two parallel branches may read the same channel. Only *control* is exclusive.
- **`monitored`** names the variables, defaulting to every monitorable variable of the channel
  (`Variable.monitor`, §4.1). It is separate from `variable`, which belongs to the state: a
  node may hold `humidity` while logging both `humidity` and `oxygen`.
- **Precedence, one rule.** For a channel's state *and* for its monitoring: the innermost node
  that speaks about it wins for its span, the settings hold everywhere else. Nothing in the
  settings forbids anything in the routine — the schema records runs, it does not drive them (D1).

**States** (`states.py`, every value a unit string):

| Slot | Fields | Semantics |
|---|---|---|
| *(no state at all)* | — | naming a channel and asking nothing of it releases it (D8); this replaces the former `uncontrolled` and irradiation-only `off` slots |
| *(any value, any slot)* | a word from the channel's own table | **named setpoints** (D8a): `dark` on irradiation, `open_circuit` on electrical load — resolved per channel before `parse()`, so they work in `hold`, `cycle.low/high`, `ramp.from/to` alike |
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

> **Pitfall — `off` is a YAML 1.1 boolean (verified; no longer triggered, kept as a warning).**
> NOMAD reads `.archive.yaml` with `yaml.SafeLoader`, which turns a bare `off` (like `on`,
> `yes`, `no`) into a boolean. While `control` was an enum with an `off` member, `control: off`
> — the natural way to write it — arrived as `control: False` and raised an unhelpful
> `AttributeError: 'bool' object has no attribute 'rsplit'`; it was fixed by mapping the `False`
> value back in `m_update_from_dict`. **D8 removed the field, and the workaround with it.** The
> hazard is not gone, and it has already decided one spelling: the irradiation channel's named
> setpoint is **`dark`, not `off`** (D8a), chosen so that the natural way to write it is not a
> boolean — written `off`, it would arrive as `False` and invert the `controlled` flag it exists
> to set. Keep choosing that way: avoid `off`, `on`, `yes` and `no` as authored values, and map
> the boolean back only where the word cannot be chosen freely.

**The `variable` rule.** `hold`, `ramp`, `cycle`, `tabulated`, `sweep` target one variable;
`variable` is **required when the channel has more than one controllable variable** (on an
atmosphere channel, `hold: 5 mol%` would fit humidity *and* oxygen). `track` acts on the whole
channel and takes no `variable`. A release — a command that asks nothing — acts on the whole
channel too, and may optionally name one `variable` to release just that.)

#### 4.2.1 Stop conditions — `conditions.py`

`stop_when` is authored as **text and parsed**, like every other value. Recorded, not
simulated (§5).

```yaml
- name: aging
  repetitions: forever
  stop_when: pce_relative < 80 %                  # T80
  commands: [...]
- stop_when: temperature >= 84.5 °C               # a state condition
  commands: [{channel: temperature, ramp: {from: 25 °C, to: 85 °C, rate: 2 K/min}}]
```

**Grammar, iteration 1** — one comparison:

```
condition  := observable op value
observable := <channel>.<variable>         # a monitored channel variable, e.g.
                                           #   atmosphere.humidity
            | <channel>                    # short form, only where the channel has exactly
                                           #   one variable: `temperature`, `irradiation`
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
temperature within 1 K of setpoint         # Settled — "wait until stable"
```

A fixed metainfo section (`observable`/`operator`/`value`) would need a schema change and a
data migration for each of these.

Validation: unknown channel / variable / metric; a bare channel that has several variables;
value dimension mismatch; an observable
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
    channel_settings  ChannelSettings   # optional, per channel (D4a)
    routine    Routine             # root node
    timeline   ProtocolTimeline    # DERIVED
    summary    ProtocolSummary     # DERIVED
    figures    PlotlyFigure[]      # inherited from PlotSection, DERIVED
```

```
ProtocolSummary(ArchiveSection)           # DERIVED, flat, scalars only, no a_eln => read-only
    total_duration                  float [h]
    truncated / estimated           bool
    temperature_controlled / _monitored        bool   # any() over the timeline's `controlled`
                                                      #   / `monitored` rows (D8)
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
    channels_used                   str            # 'electrical_load, irradiation, temperature'
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
target — untouched channels as a flat "uncontrolled" band — in each variable's `display` unit;
(2) the first full repetition of the outermost repeating block, in detail. Below the value rows,
a strip per channel for `controlled` and `monitored` (D8): a run is then readable at a glance as
*what was held, when, and where anything was logged* — including the gaps.

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
                                #   no number (nothing asked, track, open_circuit)
    controlled    bool[]        # something asks this channel for a value here (D8) — true for
                                #   a settings `hold` as much as for a routine `ramp`. DERIVED
                                #   here, where time lives; a command stores no control state
    monitored     bool[]        # a monitor tag is in effect here (D9)
    sampling_s    float[] [s]   # the interval in effect, NaN where unspecified
    path_index    int[]         # -> paths, or -1 where the value comes from channel_settings
    # lookup tables
    targets       str[]         # 'atmosphere.humidity[relative]', 'mechanical' (untouched)
    target_units  str[]         # canonical unit per target
    state_labels  str[]
    paths         str[]         # 'light soak/daily cycle[7]/electrical_load: track mpp'
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
    channel_series      ChannelTimeSeries[]   # channel (enum), variable, kind, time[], value[] — HDF5
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
- A bounded parallel child that ends early hands its channel back to the channel's settings
  (its `hold`, or nothing asked by default).
- `duration` on a repeating node is the **time break condition**: `repetitions: forever` +
  `duration: 500 h` repeats until 500 h, cutting the last pass.
- `stop_when` cannot be simulated: the expander assumes it never fires and sets `estimated`.

**Join-all vs. first-to-finish (D12).** The question is only *when a `parallel` block ends*
if its bounded children have different lengths. Unbounded children never "finish", so
blocks like ISOS-L-2 (§8) behave identically under both rules. The difference:

| Heater `hold 65 °C, 500 h` ∥ cycling of 1000 h | **Join-all** (chosen) | First-to-finish |
|---|---|---|
| The block ends at | 1000 h — the longest child | 500 h — the shortest child |
| The heater | falls back to its channel settings at 500 h; the cycling continues | — |
| The cycling | runs to completion | is cut at 500 h, mid-cycle |
| "Stop everything when X" | `duration` / `stop_when` on the parallel node | built in, but only for "when a child ends" |

Join-all never cuts a branch silently; everything first-to-finish offers is still available
explicitly through the break conditions on the node itself.

**Written set `W(node)`** for R3 — bottom-up set of `(channel, control group)`:
a leaf writes the group of its `variable`, or all the channel's groups if it has none;
a container writes the union of its children. For a `parallel` node the children's `W` must be
pairwise disjoint. A leaf with only a monitor tag (D9) writes nothing — reading a channel is
never exclusive.

> **Pitfall — R3 is deliberately static.** Two parallel branches touching the same group at
> *different* times are still rejected. Restructure instead (usually: the channel's commands
> become one sequential branch). That is what keeps the tree readable.

---

## 6. Unit parsing spec — `units.py`

One function, never ad-hoc pint calls. The channel's `parse()` delegates here.

**Where the result goes.** Every number this module returns lands in the declared, unit-ful
quantity the file wrote it into (D19) as well as in the IR the expander works on — parsing is
not a private step that feeds the simulation and leaves the archive holding text. It happens in
`WrittenUnits.m_set`, the setter every assignment passes through, so the field's own `unit=`
states the expected dimension and NOMAD's own code re-checks step 5 for free. Text §6 cannot
read is remembered on the section and reported by `normalize()` (§7) — a mistyped value must
not stop the entry from loading.

```
parse(text, variable) -> (kind, float in the kind's canonical unit)
  0. normalise: U+2212 minus -> '-', µ/μ -> 'u', strip thin/nbsp spaces
  1. split "number unit" ourselves; a bare number -> error (D6)
  2. alias time tokens, as (factor, unit) — the token must match exactly, so 'ms' is
     left alone:  h/hr/hrs -> hour · min -> minute · d/day/days -> (24, hour)
     A day is written as hours on purpose: this registry defines no 'day', 'week' or
     'year' at all (**verified**), and ureg.define() is forbidden (shared registry).
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
parse_frequency(text)      -> hertz      (expected dimension 1/[time]; `sampling_rate`, D9)
parse_rate(text, variable) -> (kind, canonical per second)
       split at the LAST '/': numerator via parse(), denominator via parse_duration()
       -> works for '5 %RH/h' and '2 K/min', where pint alone cannot
resolve(channel, text)     -> a named setpoint's value, or text unchanged      (D8a)
       tried BEFORE parse(), per channel: 'dark' -> '0 W/m²' on irradiation only.
       A name standing for no number at all ('open_circuit') -> None -> NaN in the
       timeline, like `track`. An unresolved word then fails in parse(), loudly.
```

**Verified pint behaviour this spec exists for** (`nomad.units.ureg`):

| Input | Naive `ureg.Quantity(text)` | Handled by step |
|---|---|---|
| `24 h`, `10 K/h` | **silently** Planck's constant | 2 (+ 5 catches it loudly) |
| `1 min` | **milli-inch** | 2 |
| `42 d`, `42 days` | undefined — and so is `day` itself, the obvious alias | 2, as `(24, hour)` |
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

- Run the whole pipeline in **`StabilityProtocol.normalize()`** (it runs last). The exceptions are
  the derivations that depend on **one section alone**, which that section does itself: a node's
  derived `name`, the reciprocal of `sample_every`/`sampling_rate`, and the report of any value
  the file wrote unreadably (D19) — none of them needs tree context, so each happens where it
  lives.
  **Verified:** NOMAD calls `normalize()` on every nested section, so no manual recursion is
  needed to reach them.
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
5. write back        -> derived fields on nodes (name, …), timeline (budgeted),
                        summary, figures
```

Steps 1–4 take the authored protocol content as input and touch no archive, so
`StabilityMeasurement.normalize()` reuses them unchanged to build its own summary (§4.5).

**Validation** (all errors unless marked *warning*):

| Area | Check |
|---|---|
| Structure | unknown key, with did-you-mean (§9 pitfall) · a `ChannelCommand` that names no `channel` (it would have been read as a block — D11a) · a block with no `commands` (*warning*: nothing happens) · a channel command with neither a state nor a monitor tag · more than one state slot · `mode: parallel` with fewer than two blocks (*warning*) |
| References | — the `channel` enum makes unknown, misspelled and duplicate channels impossible (D4); only the settings blocks can name a channel twice, and the schema forbids that too |
| Variables & states | missing / unknown / non-controllable `variable` · state not in `accepted_states` · a named value the channel does not declare, e.g. `dark` on temperature (D8a) · sweep on a variable other than voltage/current · ramp with neither or both of `rate` and `duration` · non-positive `rate` |
| Units | unparseable string · bare number · ambiguous unit (bare `%` on humidity or oxygen) · dimension mismatch (the field's own `unit=` raises it, D19 — check it by assigning, do not re-implement it) · mixed kinds within one state · value outside `limits` (compared only within the same kind) |
| Monitoring (D9) | `monitor` / `monitored` / `sample_every` / `sampling_rate` on a node without `channel` · both `sample_every` and `sampling_rate` in one place · sampling details without `monitor` (*warning*: the tag decides) · unknown or non-monitorable variable in `monitored` · a monitor tag whose rate is unspecified here and in the settings (*warning*) · nothing monitored anywhere (*warning*) |
| Channel settings | more than one state slot in a block · `variable` missing where the channel has several controllable variables · a state the channel does not accept (`off` outside irradiation) · a routine with no commands *and* settings that carry no conditions (*warning*: nothing happens) |
| Precedence (D4b) | a settings field some command overrides (*warning*, once per channel and field, with how long and how many commands) · a settings field **never** in effect (*warning*, dead configuration) · a command that repeats its channel's settings value verbatim (*warning*: redundant) |
| Conditions | unparseable `stop_when` · unknown observable · value dimension mismatch · observable not monitored (*warning*) — §4.2.1 |
| Timing | unbounded child that is not last in a `sequential` node · repeating node (`repetitions` ≠ 1) whose pass is unbounded · unbounded root without `horizon` · `repetitions` not an integer ≥ 1 or `forever` · `duration` cuts a node short of its natural length (*warning*) · `stop_when` present (*warning*: estimated) |
| R3 | overlapping written sets among the children of a `parallel` node |
| R4 | two sibling commands on one channel that overlap — both without a `duration`, one without beside one with, or any pair under `mode: parallel` (D13a); reported per (block, channel), and the commands are left as authored |
| R5 | a sibling the block's `duration` leaves no time for (*warning*): the episodes before it already spend the whole span, so it is authored but never executed |

---

## 8. Worked examples

### ISOS-L-2 — light soak, 65 °C, 1 sun, MPP with a daily JV sweep

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: ISOS-L-2 light soak, 65 C, MPP with daily JV
  isos_specification: ISOS-L-2

  channel_settings:                      # what holds for the whole run (D4a)
    temperature:
      hold: 65 °C                        # constant -> it belongs here, not in the routine
      limits: [20 °C, 90 °C]
      regulation: {kind: pid, kp: 2.0, ki: 0.1}
      monitor: true
      sample_every: 60 s
    irradiation:
      hold: 1 sun
      spectrum: AM1.5G
      monitor: true
      sample_every: 60 s
    electrical_load:
      monitor: true
      sampling_rate: 1 Hz                # the rate the load is logged at unless a command differs
    # atmosphere left out -> `off`, unmonitored, and still a plot row (D7)

  routine:
    name: light soak
    repetitions: 42                      # 42 × (24 h of MPP + one sweep)
    commands:
      - {channel: electrical_load, track: mpp, duration: 24 h}
      - channel: electrical_load
        variable: voltage
        sweep: {from: -0.2 V, to: 1.3 V, rate: 50 mV/s, direction: both}
        sampling_rate: 10 Hz             # this one command logs fast
```

*"Hold 65 °C and 1 sun throughout, logging both every minute; run a daily cycle 42 times, each
24 h of MPP tracking followed by a JV sweep."* Everything constant sits in the settings, so the
routine contains only what changes over time and needs no `parallel` block at all. No `horizon`:
the tree is bounded. Monitoring shows both scopes — a rate per channel, overridden for the one
command that needs 10 Hz.

**Variant — heater ramped down over the last 100 h.** A ramp is time-varying, so the temperature
moves out of the settings and into the routine, which now needs a `parallel` block:

```yaml
  channel_settings:
    temperature: {limits: [20 °C, 90 °C], monitor: true, sample_every: 60 s}   # no `hold`
    # … irradiation and electrical_load unchanged

  routine:
    name: light soak
    mode: parallel
    commands:
      - name: thermal profile
        commands:
          - {channel: temperature, hold: 65 °C, duration: 900 h}
          - {channel: temperature, ramp: {from: 65 °C, to: 25 °C}, duration: 100 h}
      - name: daily cycle
        repetitions: 42
        commands: [...]                  # as above
```

R3 holds: `temperature` and `electrical_load` are disjoint, and inside each branch the commands
are sequential. Equivalently `ramp: {from: 65 °C, to: 25 °C, rate: 0.4 K/h}` — a ramp takes a rate
*or* a duration, never neither (D16). Leaving `hold: 65 °C` in the settings would not be wrong,
only redundant: the thermal profile covers the whole run, so nothing would ever fall back to it.
Each leaf is one command carrying its own `duration` (D13) — no block in between, since a block
that wraps a single command adds nothing a reader can use.

### ISOS-D-3 — damp heat, 85 °C / 85 %RH, dark

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: ISOS-D-3 damp heat
  isos_specification: ISOS-D-3

  channel_settings:
    temperature: {hold: 85 °C, monitor: true, sample_every: 10 min}
    atmosphere:
      variable: humidity                           # the state acts on humidity …
      hold: 85 %RH
      balance_gas: air
      monitor: true
      monitored: [humidity, total_pressure]        # … the log covers more (D9)
    irradiation: {hold: dark}                      # deliberately dark, and counted (D8a)

  routine:
    name: damp heat
    duration: 1000 h                               # nothing changes — the run is just long
```

A steady-state protocol is a settings table plus a duration: every condition is constant, so the
routine has no commands at all. No `horizon` is needed — the root's `duration` bounds it.
Electrical load is never mentioned → not regulated, unmonitored, still a plot row. Irradiation
asks for the named setpoint `dark` (D8a): that is *deliberately dark* — a condition this protocol
chose, so `irradiation_controlled` is true and the timeline plots a flat 0 W/m² — as against the
electrical load, which nobody mentioned at all. Writing it `off` would be the YAML 1.1 trap (§9);
writing `{}` would say "released, nobody's driving it", which is not what ISOS-D means.

---

## 9. YAML ergonomics — why the file looks like §8

**Named slots instead of `m_def` — verified.** For a polymorphic sub-section `state: State`:

| YAML | Result |
|---|---|
| `state: {value: 1}` | **silently** instantiates the base class |
| `state: {m_def: Hold, value: 1}` | `MetainfoReferenceError` — only the ~60-char qualified name works |
| `hold: ...` (named slot) | ✅ |

Same trick for the channel settings via `ChannelSettings`, where the slot is also the
channel's identity (D4). Cost: "exactly one state slot" is a runtime check (§7), not a schema
constraint.

**No string beside the quantity — the setter reads the written unit (D19, D19a).**
`Quantity(type=np.float64, unit='second')` accepts only a bare number *in seconds*: `dur: 24`
is 24 s, while `'24 h'` raises `ValueError` and `{value: 24, unit: hour}` raises too. There is
no escape hatch: `__unit` appears nowhere in NOMAD's source, and a `duration__unit: hour` key
is silently ignored as an unknown key (the §9 pitfall below), leaving 24 **seconds** — the
quiet wrong answer that makes a written unit worth having in the file at all.

An earlier draft answered that with a `Quantity(type=str)` paired with a typed twin
`<name>_value` that `normalize()` kept in sync. The twin bought back everything the string
cost — and itself cost a second field per value, a second name in every ELN, and a standing
rule that the two may never drift. Reading the string one step earlier is cheaper and buys
the same thing: `WrittenUnits.m_set` (§6) parses it into a *pint quantity*, which NOMAD
already knows how to convert and store, leaving one field that is both the authored key and
the stored number.

| | authored string alone | one quantity, its unit read on the way in |
|---|---|---|
| unit switching in the GUI | — (inert text) | ✅ canonical `unit=`, default shown via `display: {unit: …}` |
| numeric search / filtering, plots | — | ✅ archive holds a number |
| dimension check | hand-rolled in `parse()` (§6) | ✅ loud `DimensionalityError` on assignment |
| `65 °C`, `24 h` | our own parsing, and the traps in §6 | ✅ pint converts on assignment: `338.15 K`, `86400 s` |
| what the file writes | `hold: 65 °C` | `hold: 65 °C` — unchanged |
| fields per value | 2 | 1 |

**Verified:** `m_set` is the single gateway — `m_from_dict`, `m_update_from_dict` and
`Section(**kwargs)` all funnel into it — a pint quantity assigned to a unit-ful field converts
and stores correctly, `m_to_dict()` writes a plain number that reloads unchanged, a wrong
dimension raises loudly, and a subclass may declare a quantity its base does not, which is
where a per-channel `hold` lives (D19a). Residual cost: the ELN's numeric widget edits the
value in the unit the field declares, not the one it was authored in, unless a `display`
annotation says otherwise.

**An enum instead of paths or keys.** NOMAD would write `#/data/channels/0` — unreadable and
broken by reordering. A free key (`chuck_T`) would read well but let every lab invent its own
word. `channel: temperature` needs no resolution at all: the ELN shows a drop-down, a typo is a
schema error, and the same word means the same axis in every upload (D4, D20).

**Recursion — verified.** `SubSection(section_def=SectionProxy('Subroutine'), repeats=True)`
on `Routine`, inherited by `Subroutine`, nests without limit; the children load as
`Subroutine` without any `m_def`. It must be a `SubSection` (containment):
`Quantity(type=Subroutine)` is a *reference*, and a nested YAML dict loaded into it silently
becomes an unresolvable proxy. The proxy is needed because `Subroutine` does not exist yet
while `Routine`'s body is executed; it is resolved by name later. Any tree needs it — a
class that contains itself always refers to a name that is not defined yet.
Side effect (**verified**): `m_to_dict()` writes `m_def` on every nested step. Its check
(`sub_section != m_def`) compares the proxy with the resolved definition — two objects,
though both are `Subroutine`. Harmless: the stored archive reloads, and hand-written YAML
needs no `m_def`. Tests that compare against authored dicts strip it.

> **Pitfall — unknown keys are dropped silently (verified).** NOMAD's YAML parser ignores
> keys that are not fields of the section: a typo (`chanel: temperature`, `hodl: 65 °C`) or a
> field on the wrong node (`hold:` on a `Subroutine`, which carries no conditions since D11)
> vanishes without an error, and
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
- deep trees get deeply indented — flow style (`{channel: …, hold: …}`) keeps a command to
  one line;
- **modelling tip:** use a `cycle` state for periodic *stress* (one line, no depth) and
  `repetitions` only for repeating *structure*. Two channels with incommensurate periods are
  simply two branches of a `parallel` node — no LCM flattening.

---

## 10. Module layout and implementation order

```
src/nomad_pv_stability_measurements/
  schema_packages/
    __init__.py       the entry point; it loads `protocol.m_package`, whose imports pull
                      in the modules below (each module carries its own SchemaPackage —
                      a package cannot span modules)
    units.py          parse / parse_duration / parse_rate, kind tables, and the
                      WrittenUnits base that reads a written unit on the way in (§6, D19)
    conditions.py     stop_when tokenizer + parser -> IR                     (§4.2.1)
    routine.py        CHANNELS, Variable, Kind, RoutineCommand, ChannelCommand + 5
                      channel classes, Subroutine, Routine, RegulationLaw
    utils.py          with_m_def and other small cross-module helpers (D11a)
    states.py         Ramp, Cycle, Tabulated, Sweep
    protocol.py       ChannelSettings, StabilityProtocol, ProtocolSummary,
                      normalize pipeline, plot
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
2. **`routine.py`** — variable tables, `parse()` delegation, control groups.
3. **`simulation/`** — IR, expander, validation; test with plain dataclasses, no archive.
4. **`states.py`, `routine.py`, `protocol.py`** — metainfo, IR builder, `normalize()`, summary.
5. **`timeline.py` + plot** — budgeting and the two figures.
6. **End-to-end** — process both §8 examples with NOMAD; check the ELN order and search.
7. **User-facing documentation (D4b)** — the precedence rule in the `description` of every
   overridable field, in the README, and in the example upload: *a routine step overrides the
   channel settings for its span; the settings hold everywhere else.* The schema is also read by
   people who never open this file.
8. **Iteration 2** — `results.py`, parsers, HDF5.

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
- **Monitoring in the timeline and plot** — the `monitor` tags (D9) are expanded only into the
  summary's `*_monitored` flags in iteration 1. Later: one band per monitored target showing
  the logged spans and their rate, which is also what a `logged` timeline must be checked
  against.
- **Richer `stop_when` grammar** — `and` / `or`, `for <duration>`, `within … of setpoint`
  (§4.2.1).
- **More channels** — enclosure, reverse-bias polarity; and a **second device on one axis**
  (heated chuck *and* chamber air) as a curated enum member such as `ambient_temperature`,
  never as a free key (D4).
