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
| D4c | *Superseded by §14: `ControlGroup` and `control_groups` are gone. Which variables are alternatives for one degree of freedom is `VariableSet` data (`variable_sets.py`), and each variable is its own small section with its unit-ful `setpoint`.* *Amended by §13: `Variable.field` / `setpoint_field` are gone. Every variable's quantity carries the variable's own name, and `hold` is a word only the translator reads. Amended again after §13: every method about variables lives on `ControlGroup`, and `ChannelCommand` only declares `control_groups`. `ControlGroup.variables_of(groups)` and `ControlGroup.numberless_of(groups)` flatten a channel's groups. `group_of`, `names` and `__contains__` are gone, since nothing but tests called them. `Variable` is gone too. Once `unit`, `display` and `name` had nothing reading them, it held only two flags that defaulted to `True`, and only `resistance` ever differed. `ControlGroup` is now a frozen dataclass of static data: `variables` (names, in ELN order), `unmonitored` (set, never read back), `numberless` and `tied_by`. Every variable is controllable. A variable that is monitored but never commanded would return as one more tuple (`uncontrolled`), not as a class. The instances stay on each channel class, beside the quantities they name, and not in `schema_packages/__init__.py`: that module is NOMAD's entry point, which must not import metainfo at configuration time, and moving them there would split the table from its quantities.* **A channel declares one table, and the control group is it.** `control_groups` is the whole of a channel's capability (§4.1 role 2): each `ControlGroup` **owns** its variables, so the grouping cannot name a variable that does not exist and `variables` is derived by flattening the groups in declaration order rather than written a second time — **on demand, by a classmethod that reads `control_groups`**. Not cached onto the class by an `__init_subclass__` hook, and not built in `normalize()`: D19b's `hold` rewriting runs while the entry loads, *before* any normalize, so a table built there would be built too late, and would have an instance writing state that belongs to the class. A channel has three variables at most; walking them costs nothing, and `control_groups` stays the only place the capability is either written or read. Group-level facts live on the group — which variables are tied, why (`tied_by`), and the words that stand for no number at all (`open_circuit` releases every variable the group ties, not one of them, D8a). Variable-level facts stay on the `Variable`, and are **asked of it**: `resistance` is settable but not readable *inside* the same group where `voltage` is both, so `control` / `monitor` cannot move up — and neither can they be re-exported as base-class predicates, since the channel's own part of the answer is just whether `variables` holds the name. The group stamps each variable with its own name when it takes it, which is what lets a `Variable` answer `setpoint_field` for itself (D19b). *Supersedes three parallel class tables (`variables`, `control_groups` as name-sets, `numberless`), which said one thing three times and could disagree.* |
| D5 | **Variables have physical names** (`humidity`, `oxygen`, `temperature` …); **the unit selects the quantity kind** (relative, molar ratio, dew point …). Values stay in the kind they were given — no cross-kind conversion. *Amended by §15.7: the atmosphere has one kind only — an absolute volume ratio — so no unit selects a kind there, and `humidity` is retired as an authoring word.* |
| D6 | **Every value is a unit string** (`65 °C`, `85 %RH`, `1 sun`), parsed and dimension-checked against its variable. **Ambiguity is an error:** bare numbers, and bare `%` on humidity/oxygen. The one documented convention: `ppm`/`ppb` are molar (ppmv) — the glovebox standard. The string is the *authored* form only: it is read into the field's own unit-ful quantity on the way in (D19). A bare number **written as text** stays an error; a plain YAML number is read in the quantity's declared unit — which is what NOMAD itself writes back when it serializes. *Amended by §15.7: with one kind on the atmosphere axis a bare `%` is no longer ambiguous there, and `%RH`, `wt%`, `ppmw`, `ppbw` are refused with what to write instead.* |
| D7 | **The four ISOS stress axes are always reported.** Since the vocabulary is fixed (D4), this is structural: a channel no routine touches appears in the derived layers as *uncontrolled and unmonitored*. UV content is a property of the irradiation spectrum, not a channel; encapsulation belongs to the sample. |
| D8 | *Amended after §13: `setpoints` and `asks_for_anything` are removed from `ChannelCommand`. Nothing outside tests called them, and §3 puts the expander on plain dataclasses. Deriving "asks for anything" (a setpoint, or a word standing for no number such as `open_circuit`) moves to the IR builder in step 3. The meaning below is unchanged.* **A command says what is *asked* of a channel; the control *state* is derived, never authored.** A `ChannelCommand` carries a setpoint (`hold`) or a time-varying shape (`ramp`, `cycle`, `tabulated`, `sweep`, `track`) and nothing that names a control mode. **Asking nothing is the neutral element**: a channel no command in scope touches is not regulated, which is also what it is wherever nothing says otherwise, so every channel still has a defined state at every instant (D7). Two booleans follow per channel, **computed over time when commands are expanded into a time series, not stored on a command**: **`controlled`** (some command in scope asks for a value) and **`monitored`** (a monitor tag is in effect) — timeline rows, plottable next to the values (§4.4). On a command itself, `controlled` is only "does this ask for anything" — and it is **spelled `asks_for_anything` there**, for two reasons. The same class also carries the derived `is_controlled` (§4.1), and two names one letter apart for two different questions is a misreading waiting to happen. And the question is an `any`, not an `all`: one setpoint out of a channel's three makes it true — asking for *more* than one is a contradiction (§4.2), not a fuller answer — while `open_circuit` makes it true with no setpoint at all, since a word standing for no number is still something somebody asked for (D8a). `has_setpoint` would have been wrong on both counts. *Supersedes `control = MEnum('off', 'hold', 'active')` (and, before that, the `uncontrolled`/`off` split): `hold` already said `hold`, and `active` was a label for time-varying behaviour that a single static command cannot know — a command is one clause, and what a channel is doing at hour 700 follows from all the clauses in scope. **Explicitly released** is still writable, structurally: a command that **names a channel and asks nothing of it** says "not regulated here" out loud, as against a channel nobody mentions (§4.1, "Untouched channels").* |
| D8a | *Superseded in mechanism by §13: the words (`dark`, `hold: open_circuit`) are resolved by the translator (`parsers/channels.py`), not by the field's type. What they mean is unchanged, and `open_circuit` stays a boolean quantity of the schema.* **Named setpoints: a field may declare words that stand for values.** Irradiation's `hold` declares `dark` (= `0 W/m²`); the electrical load's declares `open_circuit`. They are written wherever a value is written — `hold: dark`, `cycle: {low: dark, high: 1 sun}`, `ramp: {from: dark, to: 1 sun}` — and the table is declared **on the field's own type**, `StabilityUnitAwareFloat(named={'dark': '0 W/m²'})`, which resolves the word **before** parsing it (D19, §6). *Resolution moved twice: out of `normalize()` when D19 made a word have to become a value before the field is set, and then off the section onto the field — a word belongs to the quantity it can be written into, not to every unit-ful field the section happens to declare, which is what kept `duration: dark` from reading as an irradiance.* Per field, never global: `dark` is meaningless on the temperature axis and is rejected there. Where a state section takes endpoints of the same dimension (`ramp: {from: dark}`, states.py), that section's own endpoint fields declare the same table. A name that stands for a number becomes one, so the timeline plots `dark` as 0 instead of a NaN hole; a name that stands for no number at all (`open_circuit` is neither 0 V nor 0 A) stays NaN, like `track`. **Asking for a named setpoint is asking for something**, so `controlled` is true — that is how "deliberately dark" is said out loud *and counted*, the one thing the old irradiation-only `off` state did that D8 alone does not (§4.1). **Spelled `dark`, never `off`:** a bare `off` is a YAML 1.1 boolean (§9), so that spelling arrives as `False` and would silently invert the very flag it exists to set — and `dark` is ISOS's own word. **There is no `on`:** `dark` has a defined value and an illuminated state does not, and the irradiance is exactly what ISOS reporting needs, so it is written as a number (`hold: 1 sun`). |
| D9 | **Monitoring is a tag, not a state.** Acquiring data is an action, so it is said where the condition is said: `monitor: true` with an optional `sample_every: 60 s` or `sampling_rate: 10 Hz` — in a channel's settings (the whole run) or on a node (its span, D13). It is orthogonal to the setpoint, so the same place may set a state *and* monitor, and monitoring alone logs a channel nobody controls. |
| D10 | **The regulation law (PID, on/off …) is a channel setting**, orthogonal to the setpoint shape. |

**Routine** (§4.2, §5)

| # | Decision |
|---|---|
| D11 | *Amended again by §14: the two kinds are `PlannedMonitorControlStep` and `PlannedSubroutineStep`, both under `PlannedProcessStep`. There is no `Routine`: the protocol's own `steps` are the root list, and an authored `routine:` becomes a subroutine step.* *Amended by §13.6 step 8: `RoutineCommand` → `PlannedActivityStep` (now deriving from NOMAD's own `ActivityStep`, §2), `ChannelCommand` → `MeasurementStep`, `Subroutine` → `SubroutineStep`. `Routine` keeps its name. The chain and its meaning below are unchanged.* **One base, two kinds of command, single inheritance throughout: `RoutineCommand` → `ChannelCommand` \| `Subroutine` → `Routine`.** A `ChannelCommand` *acts* on one axis; a `Subroutine` is a *block* that contains commands of its own. **Both live in one authored list, `commands:`** — a channel command holds for its block's whole span, a block runs where `mode` puts it. `Routine` is the root: a block authored under the protocol. **Three keywords carry the whole tree: `commands`, `channel`, `name`.** A node needs no `subroutine:` tag — a block is simply a command that names no `channel`, and it labels itself with the `name` every command already has. |
| D11a | *Superseded by §13: the translator writes each entry's `m_def`, and the schema loads a bare archive with no override.* **The mixed list decides its `m_def` by key, then lets NOMAD load it natively.** Verified: a repeating sub-section typed to a common base instantiates *the base* and silently drops whatever the subclass added, unless every entry carries the ~70-char qualified `m_def:` — schema boilerplate in every file, and the only native discriminator NOMAD has (no short form: a bare class name fails to resolve, verified). `Subroutine.m_update_from_dict` reads the keys — **a `channel` names that channel's own class, `channel: temperature` → `m_def: …TemperatureChannelCommand` (D19a); anything else means `m_def: …Subroutine`** — writes that one field into each entry, then calls NOMAD's own, unmodified `m_update_from_dict` to do the actual building. No hand-built sections, no round-trip asymmetry (`m_to_dict` already wrote `m_def`; loading now agrees), and a nested block's own `commands` get their `m_def` too, since NOMAD calls back into this same method when it builds that block. An entry that already carries `m_def` is left alone — the sniff only fills a gap. |
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
| D19 | *Superseded by §13: `StabilityUnitAwareFloat` is gone. Every value is a plain `np.float64` quantity, and the translator reads the written unit into a number in the declared unit. One field per value still holds.* **One field per value: the quantity itself, with the written unit read by its own type.** Every authored value is a real `Quantity(type=StabilityUnitAwareFloat(), unit=…)` — no `type=str` beside it, no twin. NOMAD's stock float refuses `duration: 500 h` (**verified**: it rejects `'24 h'` outright, reads a bare number as its declared unit, and honours no `__unit:` escape hatch anywhere in its source), so the plugin declares **its own `Datatype`** (§6) — the extension point NOMAD itself uses for this, exactly as its stock `Datetime` type accepts a written-out date and stores a canonical one. `StabilityUnitAwareFloat.normalize` parses the string against the field's own `unit=` and hands `super()` a pint quantity, which NOMAD's own number type already knows how to convert and store (`500 h` → `1800000.0 s`, `65 °C` → `338.15 K`, **verified**). Because `Quantity.__set__` calls `self.type.normalize` unconditionally, **every** way of setting the field is covered — `m_from_dict`, `m_update_from_dict`, `Section(**kwargs)`, an ELN edit *and* a plain `section.hold = '65 °C'` (**verified**). The file keeps the unit it was written with, the archive keeps a number, and unit switching, numeric search, plots and a loud `DimensionalityError` all come free from the declaration. The schema still serializes as a plain float quantity, so nothing downstream needs to know (**verified**). *Supersedes two earlier drafts: the string-plus-twin pair (the twin existed only to buy back what the string cost), and then a section-wide `m_set` override — which worked, but intercepted every field of every section to serve the few that declare a unit, and still missed plain attribute assignment.* |
| D19a | *Amended by §13: the per-channel class stays, but choosing it from `channel:` and reporting unreadable text move to the translator.* **Where the dimension depends on the channel, the field is declared on the channel class.** `hold` cannot sit on `ChannelCommand`: it is kelvin for temperature and W/m² for irradiation. So `ChannelCommand` does not declare it at all and each channel class declares its own — `TemperatureChannelCommand.hold` in `K` — which is also how a channel whose setpoint is not a number at all declares an `MEnum` instead (`dark`, `open_circuit`, D8a). **Verified:** a subclass may declare what its base does not, and NOMAD then **silently drops** an authored `hold` when the same dict is loaded as the base class. That makes D11a's per-entry dispatch load-bearing rather than a convenience: it must resolve the `channel:` *value* to that channel's class (`channel: temperature` → `TemperatureChannelCommand`), or the setpoint disappears without a word. Text the file writes that §6 cannot read is remembered where it was written and reported by `normalize()` (§7), never raised — a typo must not stop an entry from loading; an empty or blank string leaves the field unset, since asking nothing is the neutral element (D8). |
| D19b | *Amended by §13: one quantity per variable stays, now named after the variable on every channel (`temperature`, `irradiance`). Both spellings, `variable:` + `hold:` and the variable as the key, are read by the translator.* **Where the dimension depends on the *variable*, the field is declared per variable — and `variable:` + `hold:` stays the authored spelling.** D19a's argument does not stop at the channel: the electrical load holds volts, amps *or* ohms, and the mechanical channel metres *or* a dimensionless strain, so one `hold` quantity cannot carry them either — a NOMAD `Quantity` has exactly one unit, and `shape=['*']` gives a list of *volts*, not a list of one of each. So a channel with several variables declares **one unit-ful quantity per variable, named after it** (`voltage` in `V`, `strain` in `dimensionless`), and the `variable` a command names says which. A channel with a single variable keeps `hold` — there is no variable to name — which the variable's table entry records as `field='hold'`. **The two spellings are one field:** `{variable: strain, hold: 2 %}` (§8) and `{strain: 2 %}` both land in `strain`, because `ChannelCommand.m_update_from_dict` moves an authored `hold` into the named variable's own quantity before NOMAD loads it — the same per-entry rewriting D11a already does for `m_def`. A `hold` with no variable to go to (several controllable, none named) is remembered and reported like an unreadable value (D19a, §7), never dropped in silence. *Considered and rejected: a repeating `hold` ordered by a `variables` list. It does not solve the dimension problem (the list is still all one unit), it makes `hold[i]` meaningful only through `variables[i]` — so adding a variable to a class silently re-targets stored values — and §4.1 already decided one command sets at most one variable, which is the only thing the list would buy.* |
| D20 | *Superseded in part by §14: `channel:` now resolves to a `variable_set`, which the schema stores again as an enum; `channel: mechanical` names two sets and is resolved by the variable written.* *Amended by §13: `channel:` is an authored word only, resolved by the translator to the channel's class. The bare schema has no `channel` quantity, because the class is the axis.* **References by enum value** (`channel: temperature`) — never `#/data/...` paths, and never a free string that each lab spells differently. |

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
| `ActivityStep` | `nomad.datamodel.metainfo.basesections.v2` | base of `PlannedActivityStep` (§13.6 step 8): `name`, `start_time`, `description`, `to_task()` |

**Deliberately not used:**
- **`Activity` as protocol base** — its `normalize()` appends to `results.eln.methods` and
  *overwrites* `workflow2.tasks`. A protocol is a plan, not something that happened.
- **`ProcessStep`** — `ActivityStep` (below) already covers the tree's node base; `ProcessStep`
  adds nothing this schema needs.
- **`SolarCellJV`** (core ELN) — reusable for JV snapshots later, but heavy for iteration 1.

**Reconsidered (§13.6 step 8):** `ActivityStep` as the node base was rejected above for its
absolute `start_time`. The tree's own base (`RoutineCommand`, now `PlannedActivityStep`) never
sets it, so an unused optional field is the whole cost, and deriving from it gains NOMAD's own
step vocabulary — `name`, `description`, and `to_task()` for workflow visualization — for free.
Protocol time stays relative to t₀, carried entirely by `duration`, which `ActivityStep` does not
declare and `PlannedActivityStep` adds itself.

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
    variable      str   (opt)      # which variable this applies to (the "variable rule", §4.2);
                                   #   derived from the setpoint that is set, where only one can be
    available_variables str[]      # DERIVED from the class table — what this axis can be asked
                                   #   for, shown in the ELN beside `variable`
    # NO setpoint here — its dimension is the axis's, and on a multi-variable axis the
    #   variable's, so each channel class declares its own: `hold` where there is one
    #   variable, one quantity named after each variable where there are several
    #   (D19a, D19b). None set = nothing asked of the channel: the neutral element (D8).
    #   No control mode is stored either; it is derived over time (§4.4)
    monitor       bool             # acquire data here (D9)
    monitored     str[] (opt)      # which variables; default: every monitorable one.
                                   #   A QUANTITY — so no python property may take this
                                   #   name: `bool(monitor)` is already the boolean
    sample_every  float [s]  ┐     # "60 s"  -> discrete measurements  } author at most
    sampling_rate float [Hz] ┘     # "10 Hz" -> a stream               } one; the other is
                                   #   derived as its reciprocal (neither: unspecified)

TemperatureChannelCommand(ChannelCommand)         # one per CHANNELS member: the axis's own class,
                                           #   carrying its variable table and, as a
                                           #   `channel_settings` block, the run-wide extras
    # --- quantities
    hold           float [K]       # authored as "65 °C" — the setpoint, in the unit only
                                   #   this class knows (D19a). One variable, so it is
                                   #   spelled `hold`; a multi-variable channel names each
                                   #   variable instead — ElectricalLoadChannelCommand
                                   #   declares voltage [V], current [A], resistance [Ω],
                                   #   and reads `{variable: voltage, hold: 0.8 V}` into
                                   #   the first of them (D19b)
    limits         Any    (opt)    # {variable: [min, max]} as unit strings;
                                   #   plain [min, max] allowed for single-variable channels
    is_controlled  bool            # DERIVED: here or some step asks this channel for a
                                   #   value (D8)
    is_monitored   bool            # DERIVED: here or some step carries a monitor tag (D9)
    # --- sub-sections
    regulation     RegulationLaw (opt)
    instrument     InstrumentReference (opt)

ChannelSettings(ArchiveSection)     # authored as `channel_settings:`
    temperature      TemperatureChannelCommand      ┐  one NON-repeating slot per member of
    irradiation      IrradiationChannelCommand      │  CHANNELS; each optional, and omitting one
    atmosphere       AtmosphereChannelCommand       │  means "all defaults" (D7 stays structural)
    electrical_load  ElectricalLoadChannelCommand   │
    mechanical       MechanicalChannelCommand       ┘

RegulationLaw(ArchiveSection)                    # metadata only
    kind enum{open_loop, pid, on_off, external};  kp, ki, kd, hysteresis
```

One block sets at most **one variable** of its channel, since it has one state and one
`variable`. Holding humidity *and* oxygen constant therefore takes two routine commands — rare
enough to leave to the tree, where parallel branches already say it.

No `key`, no `name`: the slot *is* the identity. The class stays `TemperatureChannelCommand` — it
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
| `TemperatureChannelCommand` (`temperature`) | `temperature` (K, °C) | {temperature} | — | — | ✅ |
| `IrradiationChannelCommand` (`irradiation`) | `irradiance` (W/m², W/m²) | {irradiance} | `dark` = `0 W/m²` (named value, D8a) | `spectrum` str (`AM1.5G`) | ✅ |
| `AtmosphereChannelCommand` (`atmosphere`) | `humidity` (multi-kind), `oxygen` (multi-kind), `total_pressure` (Pa, mbar) | {humidity}, {oxygen}, {total_pressure} | — | `balance_gas` str (`N2`, `air`, `Ar`) | ✅ |
| `ElectricalLoadChannelCommand` (`electrical_load`) | `voltage` (V), `current` (A), `resistance` (Ω, control only) | {voltage, current, resistance} | `track`, `sweep`; `open_circuit` (named value, no number, D8a) | — | ✅ |
| `MechanicalChannelCommand` (`mechanical`) | `bend_radius` (m, mm), `strain` (dimensionless, %) | {bend_radius, strain} | — | — | ❌ |

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
                                      #   — built as `unit: str`, the only form step 2b
                                      #   needs; step 2c widens it to the kind table
    display: str | None = None        # plot unit, e.g. 'degC'
    control: bool = True
    monitor: bool = True
    field: str | None = None          # the quantity carrying this variable's setpoint;
                                      #   None = the variable's own name (D19b). Only a
                                      #   single-variable channel sets it, to 'hold'
    name: str | None = None           # stamped by the group that owns it, never written

    @property
    def setpoint_field(self) -> str:  # D19b — asked of the variable, which knows both
        return self.field or self.name

class ControlGroup:                   # variables one device cannot set independently
    def __init__(self, *, numberless=(), tied_by=None, **variables: Variable):
        # the keywords ARE the variables, in ELN order — so `numberless` and `tied_by`
        # are the two names a variable may not have. The keyword IS the name, so the
        # group stamps it on and a Variable can answer for itself; `replace` copies,
        # so nothing the caller wrote is mutated and equality stays sane.
        self.variables = {n: replace(v, name=n) for n, v in variables.items()}

class AtmosphereChannelCommand(ChannelCommand):
    control_groups = (           # ONE authored table per channel (D4c): the group owns
        ControlGroup(humidity=Variable(HUMIDITY_KINDS)),          # its variables, so
        ControlGroup(oxygen=Variable(OXYGEN_KINDS)),              # there is no second
        ControlGroup(total_pressure=Variable('Pa', display='mbar')),   # table to desync
    )
    accepted_states = GENERIC_STATES
    always_reported = True
    # Named setpoints (D8a) are NOT here: a word belongs to the field it can be
    # written into, so it is declared on that quantity's own type —
    #   hold = Quantity(type=StabilityUnitAwareFloat(named={'dark': '0 W/m²'}), unit='W/m²')
    # — except a word standing for no number at all (`open_circuit`), which no unit-ful
    # quantity can hold. That one is a boolean field of its own, and it is the GROUP
    # that lists it: it releases every variable the group ties, not one of them (D8a).

class ElectricalLoadChannelCommand(ChannelCommand):
    control_groups = (
        ControlGroup(
            voltage=Variable('V'), current=Variable('A'),
            resistance=Variable('ohm', monitor=False),   # set, never read back
            numberless=('open_circuit',),
            tied_by='the cell I-V curve: commanding one leaves the others measured',
        ),
    )
```

**Base-class interface** (implemented once):

```
variables()            -> {name: Variable}   # DERIVED on demand: the groups flattened,
                                            #   in order. The lookup IS the channel's answer:
                                            #   `.get(name) is None` means "not on this
                                            #   channel", and the Variable answers the rest
                                            #   — `.control`, `.monitor`, `.setpoint_field`
group_of(variable)     -> ControlGroup | None   # `.names` is the set tied to it. The one
                                            #   question no Variable can answer alone: a
                                            #   search, not a lookup — and §5's written set
                                            #   W(node) is defined over what it returns
parse(variable, text)  -> (kind, canonical float)   # §6
# resolving a named setpoint is NOT here: it belongs to the field's type (D8a, §6)
```

**No `can_control` / `can_monitor` / `setpoint_field` on the base class.** Each was a `.get()`
welded to an attribute the `Variable` already carries, and the weld bought only the `None` case
— which `variables.get(name) is None` states directly, and more precisely: a caller can then
tell *this channel has no such variable* from *it has it, but monitor-only*, which one boolean
cannot. Nothing is lost by asking the object that knows.

**What a control group encodes is *actuation*, not physics** — which variables one device
cannot set independently of one another. Humidity and oxygen are separate groups because a gas
mixer sets them independently, even though their partial pressures do sum to the total; a cell's
voltage and current are one group because its I–V curve ties them, so commanding `voltage`
leaves `current` measured-only for that span. `tied_by` says why **in words, never as an
equation**. Two relations sit behind that one case and only one of them is writable: `V = I·R`
is the *load's* definition (a resistive load obeys it by construction; on a sourcemeter `R` is
just the ratio), while what the run measures — and what actually decides where on that load
line it sits — is the cell's own I–V curve, which is data, not a constant the schema could
carry (D1). Carrying the first without the second buys nothing: a protocol holds **exactly
one** of the three, which is what a control group *is*, so there is never a second value for a
formula to consume. A formula nothing evaluates is also what the "no hardware maxima" argument
above already rejected. *An evaluable `law=lambda …` on the group was proposed and is parked as
**O12**, with the case for and against; the place it would pay is §4.4's timeline, over measured
arrays.*

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
> names that channel's own class (`temperature` → `TemperatureChannelCommand`, D19a), anything
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

The rule is about the **authored** `hold`, and D19b is what makes it enforceable rather than
guesswork: the value has to be moved into one variable's own quantity to be stored at all, so a
`hold` with nowhere to go is reported (§7) instead of read as a guess. Writing the variable as
the key — `{channel: electrical_load, voltage: 0.8 V}` — says the same thing and needs no rule.
Where the channel has one controllable variable, `variable` is optional in both directions:
`hold` needs no name, and `normalize()` fills `variable` in from whichever setpoint is set.

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
`StabilityUnitAwareFloat.normalize`, the quantity's own type, which `Quantity.__set__` calls on every
assignment whatever its origin, so the field's own `unit=` states the expected dimension and
NOMAD's own number type re-checks step 5 for free. Text §6 cannot
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
  4. 'sun' -> 1000 W/m^2 — the same (factor, unit) alias table as step 2, never ureg.define
  5. check the dimension; convert to canonical; any mismatch fails LOUDLY
parse_duration(text)       -> seconds    (expected dimension [time])
parse_frequency(text)      -> hertz      (expected dimension 1/[time]; `sampling_rate`, D9)
parse_rate(text, variable) -> (kind, canonical per second)
       split at the LAST '/': numerator via parse(), denominator via parse_duration()
       -> works for '5 %RH/h' and '2 K/min', where pint alone cannot
StabilityUnitAwareFloat(named={...}) -> the datatype a unit-ful quantity declares   (D19)
       normalize() resolves a named setpoint BEFORE parse(), from the table that
       field declares: 'dark' -> '0 W/m²' on irradiation's `hold` only, never on a
       `duration` beside it (D8a). A name standing for no number at all
       ('open_circuit') -> NaN in the timeline, like `track`. An unresolved word
       then fails in parse(), and is reported rather than raised (§7).
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

> **Since §13, this is the translator's concern, not the schema's.** The file still looks like
> §8, but `.stability.yaml` is read by `parsers/translate.py` into a bare archive. The loading
> tricks below (`m_def` sniffing, the unit-reading datatype, `hold` rewriting) no longer run
> inside the schema. The NOMAD facts stay true and explain why the translator exists. The
> unknown-key pitfall is now closed by the translator.

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
the same thing: `StabilityUnitAwareFloat.normalize` (§6), the field's own type, parses it into a *pint
quantity*, which NOMAD already knows how to convert and store, leaving one field that is both
the authored key and the stored number.

| | authored string alone | one quantity, its unit read on the way in |
|---|---|---|
| unit switching in the GUI | — (inert text) | ✅ canonical `unit=`, default shown via `display: {unit: …}` |
| numeric search / filtering, plots | — | ✅ archive holds a number |
| dimension check | hand-rolled in `parse()` (§6) | ✅ loud `DimensionalityError` on assignment |
| `65 °C`, `24 h` | our own parsing, and the traps in §6 | ✅ pint converts on assignment: `338.15 K`, `86400 s` |
| what the file writes | `hold: 65 °C` | `hold: 65 °C` — unchanged |
| fields per value | 2 | 1 |

**Verified:** `Quantity.__set__` calls the field's own `type.normalize` on every assignment
whatever its origin — `m_from_dict`, `m_update_from_dict`, `Section(**kwargs)`, an ELN edit and
a plain `section.hold = '65 °C'` all reach it, so there is no path that stores text unread. The
type is handed the section as a keyword argument, which is how an unreadable value is remembered
where it was written. A pint quantity converts and stores correctly, `m_to_dict()` writes a plain
number that reloads unchanged, a wrong dimension raises loudly, the schema still serializes as a
plain float quantity so nothing downstream needs to know, and a subclass may declare a quantity
its base does not, which is where a per-channel `hold` lives (D19a). Residual cost: blank text
(`hold: ''`) leaves the field unset but *writes* it back as an explicit `null` rather than
omitting the key — the type may choose what a value becomes, not whether it is stored at all. The
two read identically (`__get__` answers `None` either way) and a `null` reloads as unset, so this
is verbosity, not a semantic difference; omitting the key is still the way to ask nothing (D8).
Second residual cost: the ELN's numeric widget edits the
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
  schema_packages/    the bare schema: plain NOMAD, no loading hooks, never imports
                      parsers/ (§13)
    __init__.py       the entry point; it loads `protocol.m_package`, whose imports pull
                      in the modules below (each module carries its own SchemaPackage —
                      a package cannot span modules)
    general.py        PlannedProcess, PlannedProcessStep: extensions of NOMAD's own
                      Process / ProcessStep with the plan/record split (was_executed,
                      the estimated_* fields), specific to no PV concept (§15.5)
    routine.py        PlannedMonitorControlStep (monitor, control, the sampling pair),
                      its three kinds HoldStep (set_point, set_point_tolerance), HoldBelowStep
                      (upper_bound, §17.5) and RampStep (start_point,
                      end_point, ramp_rate, end_of_ramp_behavior — whose
                      repeating members are the cycles, §21.2) (§15.11), and PlannedSubroutineStep
                      (execution_mode, steps, and repeat / repeat_n /
                      estimated_duration_one_iteration, §15.8); the checks that
                      hold for any archive (R4, R5, the sampling pair) (§15.1)
    hold_steps.py     one HoldStep per quantity, each fixing the unit of its set_point
                      and set_point_tolerance (§17.4)
                      (HoldTemperature, HoldIrradiance, ..., the atmosphere pair and
                      HoldPressure), plus BalanceGas (a gas name), which holds no
                      number at all (§15.1, §15.7, §15.10, §15.11)
    ramp_steps.py     one RampStep per quantity, each fixing the unit of both ends and
                      of the rate (RampTemperature, ...) (§15.11)
    hold_below_steps.py  one HoldBelowStep per quantity a standard bounds, fixing the
                      unit of its upper_bound — HoldBelowWaterVaporFraction only (§17.5)
    standard_values.py  StandardValue (name, value, tolerance) and the values a
                      standard names: RoomTemperature (23 ± 4 °C), Dark. Never stored;
                      the parser resolves `RT` / `dark` into a step's fields (§17.2)
    mpp_steps.py      the electrical load driven to a point it finds rather than to a
                      number: MPPTracking (with the perturbation settings an operator
                      sets) and VOCTracking; the file a JV sweep would go in
                      (D17, §15.10, §15.13)
    utils.py          the checks a block and the protocol share: R4 (grouping by class
                      name minus KIND_PREFIXES, §17.5), R5, and R6, which
                      fits steps to their block's duration (§15.4); check_steps runs the
                      three over one iteration of a repeating block (§15.8)
    states.py         Ramp, Cycle, Tabulated, Sweep — superseded: the ramp is a step's
                      final_setpoint (§15.10) and the cycle a repeat block (§15.8)
    protocol.py       StabilityProtocol (its steps, and what the run itself records:
                      standard, environment, notes, and geo_location beside NOMAD's own
                      location) and GeoLocation (§15.12); ProtocolSummary, normalize
                      pipeline, plot
    timeline.py       ProtocolTimeline
    results.py        StabilityMeasurement, StabilityResult, …                (iteration 2)
  parsers/            everything that reads an authored `.stability.yaml` (§13)
    __init__.py       the parser entry point (`*.stability.yaml`)
    parser.py         StabilityYamlParser: translate -> archive.data
    translate.py      translate / translate_section -> Translation(archive, problems)
    channels.py       authoring words: variable keys (`bend_radius` -> BendRadius),
                      channel words (`mechanical` -> two sets), §13's old class names
    units.py          parse / parse_duration / parse_frequency, the alias tables (§6)
    conditions.py     stop_when tokenizer + parser -> IR     (§4.2.1; see O13)
  simulation/
    ir.py             plain dataclasses the expander works on
    expander.py       §5 — pure Python, no metainfo
    validate.py       §7
tests/
  data/               each example as `.stability.yaml` (authored) and `.archive.yaml` (bare)
  schema_packages/    the schema's meaning, tested on bare dicts
  parsers/            the translator, the units, the old-format compatibility suite
                      (§13.1a), and the end-to-end path through StabilityYamlParser
```

Suggested order — each step is testable on its own:

1. **`units.py` + tests** — table-driven from §6; the highest bug density lives here.
   `conditions.py` follows naturally — it reuses `parse()` for its values.
2. **`routine.py`** — the channel classes (D4). Four substeps, each one idea and testable
   on its own:
   - **2a — named setpoints, and the irradiation channel (D8a).** `sun` (§6 step 4), and a
     per-channel table of words that stand for values, resolved by the same setter that reads
     the written unit (D19). `IrradiationChannelCommand` carries `dark` and `spectrum`.
   - **2b — variables and control groups.** The `Variable` table, `variable` on a command,
     the derived `variables` view and `group_of`. `MechanicalChannelCommand` (two variables) and
     `ElectricalLoadChannelCommand` (three in one group, plus the numberless `open_circuit`) are what
     exercise them.
   - **2c — quantity kinds (§6 step 3).** The dimensionless token table, bare `%` ambiguity,
     `ppm` = molar. `AtmosphereChannelCommand` and its `balance_gas` are what need them.
   - **2d — envelope and provenance.** `limits`, `RegulationLaw`, `instrument`, `monitored`.
     `is_controlled` / `is_monitored` are derived over the whole tree, so they land with step 4.
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
| O11 | **Bare number on offset unit** — `hold: 65` on temperature reads as 65 K = −208 °C, because D6-as-amended requires a plain YAML number to read in the declared unit to preserve round-trip. Unfixable without breaking `m_to_dict` and reload. Worth recording in §9 as a second residual cost, alongside the `display` annotation? | decision: document, do not fix |
| O12 | **An evaluable law on a control group** — `ControlGroup(..., law=lambda …)`, a general hook on the class overridden per group, so that `V = I·R` is carried as arithmetic rather than as `tied_by` prose. *Against:* the relation is true but near tautological (it is the load's definition — a resistive load obeys it by construction, and on a sourcemeter `R` is simply the ratio), and it is inapplicable where the schema lives: it relates three quantities of which a protocol holds **exactly one**, which is what a control group *is*. Commanding `resistance` fixes the load line; where the run sits on it is the intersection with the cell's own I–V curve, which the experiment measures — so the lambda could never fire at authoring time, and the only document carrying two of the three is one §4.2 already rejects. A lambda also does not serialize (invisible to the archive, the ELN, search and every non-Python reader of the schema — D1), it is a *relation* rather than a function (`R = U/I` is one of three rearrangements, so one lambda is a third of one), and it would be a general mechanism with exactly one possible user: of the 5 control groups today and 8 once atmosphere lands (2c), only the electrical load has more than one variable — humidity, oxygen and total pressure are separate groups precisely *because* nothing ties them. *Where it would pay:* §4.4's timeline, over measured arrays, where two of the three do exist — a resistance row derived from logged `V` and `I`. That is the measurement layer, over data, not the protocol's class table. *Cheap half-step meanwhile:* put the formula into `tied_by`, which already reaches the ELN and the validation messages, stating the physics without pretending the schema evaluates it. | open; not built — revisit with §4.4 (step 5), where the data the law needs first exists |
| O13 | **Where does `stop_when` get parsed, after §13?** D15 stores the readable text and parses it in `normalize()`, but the value parser it reuses (`units.parse`) now lives in `parsers/`, which the schema must not import. Either the translator parses it and the schema stores the structured form beside the text, or the parser moves to a module both sides may import. | open; decide when `conditions.py` is built |

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

---

## 13. Proposed — a bare schema, and a translator from `.stability.yaml`

**Status: implemented (steps 1–5 of 13.6). It supersedes the parts of D4c, D8a, D11a, D19,
D19a, D19b, D20 and §9 that it names.**

**Goal: a clear separation between the schema and the parsing.** The schema describes the
data and nothing else. Every convenience of the authored file lives in the parser, and the
file format written today stays readable through the parser (13.1a).

### 13.1 The idea

Today one set of metainfo classes does two jobs: it *is* the data model, and it *reads a
human-written file*. The second job is where most of the code lives, and all of it runs
inside NOMAD's loading hooks (`m_update_from_dict`, `Datatype.normalize`, `m_cache`), which is
why every rule needs a NOMAD fact **verified** before it can be written down.

Split the jobs:

```
  tests/data/soak.stability.yaml      pretty: units, `hold`, `dark`, no m_def
            │
            ▼   translate(doc) -> (archive_dict, problems)     pure Python, no metainfo
  tests/data/soak.archive.yaml        bare: explicit m_def, numbers in the declared unit
            │
            ▼   StabilityProtocol.m_from_dict(...)             plain NOMAD, no overrides
  archive.data                        normalize() checks meaning only
```

**The dividing test:** a rule belongs to the translator if it only exists because a person
writes the file. It belongs to the schema if it would still be needed for an archive that
came from anywhere else, such as an ELN edit, an API upload or a future instrument log.

**The dependency runs one way.** `parsers/` may import `schema_packages/`, for class paths and
`control_groups`. `schema_packages/` never imports `parsers/`. A test checks this, so the
separation cannot erode in silence. Both are ordinary NOMAD plugin entry-point packages;
there is no third package.

### 13.1a Compatibility — the old format stays readable

Every file the schema accepts today must still load, now through the translator, and mean
the same thing. Concretely, the translator accepts all of the following:

- `channel: temperature` with no `m_def`, and entries that already carry a qualified `m_def`;
- values with units (`65 °C`, `500 h`, `1 sun`, `2 %`) and plain YAML numbers in the
  declared unit;
- `hold:` on a single-variable channel; `variable: voltage` with `hold: 0.8 V`; `voltage: 0.8 V`;
- the named words `hold: dark` and `hold: open_circuit` (also `open_circuit: true`);
- `sample_every` or `sampling_rate`;
- nested blocks, `mode`, `duration`, `name`, and `channel_settings` slots.

The translator also accepts **the bare format itself**: `translate(bare) == bare`. The new
format is then a subset of what the parser reads, and an `archive.yaml` written out by hand or
by NOMAD is a valid `.stability.yaml` as well.

**How this is checked:** every YAML input in today's tests
(`channels.archive.yaml`, `tree.archive.yaml`, and the inline dicts in `test_routine.py` and
`test_protocol.py`) becomes a translator fixture before the schema is stripped (step 2). Each
fixture keeps its expected meaning, now asserted on the translated and loaded archive.

**The one thing that cannot stay:** the file *name*. NOMAD's own archive parser claims
`*.archive.yaml` and loads it straight into the schema, which no longer understands the pretty
form. Old files are renamed to `*.stability.yaml`.

**Verified in step 5, not built:** a plugin parser *could* claim pretty `*.archive.yaml` files.
`nomad.parsing.parsers` appends every plugin parser before `TabularDataParser` and
`ArchiveParser`, and `match_parser` returns the first match. A name pattern alone would take
every other plugin's archive files too, so it would need a content pattern as well, for
example `mainfile_contents_re` matching `StabilityProtocol`. Bare files would then also pass
through the translator, which is harmless because `translate(bare) == bare`. This is left for
review, since it changes which files the plugin claims.

### 13.2 What moves out of the schema

| Today (file) | Only there so the YAML reads well? | Goes to |
|---|---|---|
| `Subroutine.m_update_from_dict`, `utils.with_m_def` (D11a): `channel:` fills in `m_def` | yes. `archive.yaml` carries `m_def`, because it is generated. | translator |
| `ChannelCommand.m_update_from_dict`, `_route_hold` (D19b): `hold` goes to `voltage` | yes | translator |
| `hold: open_circuit` becomes `open_circuit: true` | yes | translator. `numberless()` itself stays in the schema (13.4). |
| `StabilityUnitAwareFloat(named={'dark': …})` (D8a): `dark` becomes `0 W/m^2` | yes | translator |
| `StabilityUnitAwareFloat`, `UNREADABLE_VALUES`, `StabilityUnitAwareSection` (D19): `'65 °C'` becomes `338.15` | yes | translator. `units.py` keeps the pure parser and loses the datatype. |
| `variable` quantity, inferred from the setpoint | yes. Which field is set already says it. | translator (dropped from the schema) |
| `channel` quantity, `CHANNELS` enum (D20) | yes. `m_def` names the class, and the class is the axis. | translator: `channel:` stays an authored word, resolved to a class. Dropped from the schema (13.5 b). |
| `CHANNEL_CLASSES` (word → class) | yes | translator |
| `Variable.field` / `setpoint_field`, the `hold` quantity | yes. Each variable's field carries its own name (13.5 d). | translator: `hold` is an authored word only |
| `available_variables` | largely: the ELN shows it | dropped (13.5 c) |
| unknown-key detection (§9 pitfall, planned) | yes | translator, where it is a plain set difference |

**Not moved:** the `sample_every` / `sampling_rate` pair. Both are stored (13.5 a). Deriving
one from the other holds for any archive, including an ELN edit that sets only one, so it stays
in the schema's `normalize()`. The translator only reads the units of whichever was written.

### 13.3 What stays in the schema

- **The tree:** `StabilityProtocol`, `ChannelSettings`, `PlannedActivityStep`
  (deriving from NOMAD's own `ActivityStep`, §2, §13.6 step 8), `MeasurementStep` → the
  per-channel classes, `SubroutineStep` / `Routine`, `commands`
  (`SubSection`, `repeats=True`), `mode`, `duration`, `name`.
- **One plain quantity per variable, named after the variable:**
  `temperature = Quantity(type=np.float64, unit='K')`,
  `irradiance` (`W/m^2`), `voltage` / `current` / `resistance`, `bend_radius`, `strain`. Plus
  `open_circuit: bool`, `spectrum: str`, `monitor: bool`, and **both** `sample_every` (`s`) and
  `sampling_rate` (`Hz`).
- **Derivations that hold for any archive, in `normalize()`:** whichever of `sample_every` and
  `sampling_rate` is missing is computed from the other. The same method is kept as today.
- **Semantic checks in `normalize()`**, because they hold for any archive:
  - R4, overlapping commands. It groups by the command's class instead of by `channel`.
  - R5, commands that never run.
  - A command loaded as the base `MeasurementStep`, which names no axis. This replaces the
    "command without a `channel`" check.
  - One setpoint per control group (§4.2, not yet built).
- **The capability tables** (`ControlGroup`, a frozen dataclass, and `control_groups` on each
  channel class, D4c). The semantic checks read them, and so does the translator, which imports them
  (13.5 c). Every question about variables is asked of `ControlGroup`
  (`variables_of`, `numberless_of`), never of the channel command.

**What this deletes from the schema:** both `m_update_from_dict` overrides, `utils.py`, the
`StabilityUnitAwareFloat` datatype and its `m_cache` bookkeeping, `StabilityUnitAwareSection`,
`CHANNELS` and the `channel` quantity, `CHANNEL_CLASSES` (moved), `units.py` (moved),
`variable`, `available_variables`, and `Variable.field` / `setpoint_field`. Of
`ChannelCommand.normalize` only the sampling derivation is left. `routine.py` shrinks from 438
lines to roughly 200. Every remaining schema line is ordinary NOMAD, so the **verified** caveats
in D11a, D19 and §9 stop being load-bearing for the schema.

### 13.4 The translator

The translator lives in the plugin's own `parsers/` package, next to the parser that is its
only user. It works on plain dicts and never builds sections. It reads the schema's
*definitions* only: class paths for `m_def`, each quantity's declared `unit` (the only source
of units), and `control_groups`.

```
parsers/
  parser.py      StabilityYamlParser, the thin NOMAD wrapper below
  translate.py   translate(doc) / translate_section(dct, cls) -> Translation(archive, problems):
                 the tree walk, m_def dispatch, hold routing, units, unknown keys
  channels.py    CHANNEL_CLASSES (`temperature` -> TemperatureChannelCommand), and the named
                 words per field: `dark` -> irradiance 0 W/m^2
  units.py       moved from schema_packages/, minus the datatype
```

`numberless` (the words that stand for no number, such as `open_circuit`) stays on
`ControlGroup` in the schema. It is a fact about the device. Only the spelling
`hold: open_circuit` belongs to the translator.

- **Errors are collected, never raised.** `Problem(path='routine.commands[3].hold', message=…)`
  replaces `m_cache[UNREADABLE_VALUES]`. Each message says where in the file it happened,
  which today's section-local complaints cannot.
- **It is strict where NOMAD is silent.** An unknown key is a problem with a did-you-mean,
  not a dropped key.
- **It is testable without NOMAD.** A test gives it a dict and gets back a dict and a list.

**Naming: this is a *parser*, not a normalizer.** In NOMAD a `Normalizer` runs on an archive
that already exists. Turning a raw upload file into an archive is a `MatchingParser`'s job.
The plugin already has a parser template (`parsers/parser.py`). The wrapper is thin:

```python
class StabilityYamlParser(MatchingParser):          # mainfile_name_re=r'.*\.stability\.ya?ml$'
    def parse(self, mainfile, archive, logger, child_archives=None):
        translation = translate(yaml.safe_load(open(mainfile)))
        for problem in translation.problems:
            logger.error(problem.message, path=problem.path)
        archive.data = StabilityProtocol.m_from_dict(translation.archive['data'])
```

`archive.yaml` as a *file* is then the translator's output, dumped. It is used as the golden
file in tests. There is no command line: the plugin is only what NOMAD loads. The upload
itself needs only the `.stability.yaml` (see 13.5 f).

### 13.5 Decisions — settled in review

| | Question | Decision |
|---|---|---|
| a | Which sampling field does the bare schema store? | **Both**, `sample_every` (`s`) and `sampling_rate` (`Hz`). Whichever is missing is calculated from the other, in the schema's `normalize()`, because that holds for any archive (13.2). |
| b | Keep the `channel` enum in the bare schema, now that `m_def` names the class? | **No.** The class is the axis. `channel:` survives only as an authored word, which the translator resolves to a class. D20's point, no free strings and no paths, still holds in the file. |
| c | Where do `control_groups` live? | **On each channel class** (D4c unchanged). The translator imports them. `available_variables` is dropped. |
| d | Single-variable channels: field named `hold`, or after the variable? | **After the variable** (`temperature`, `irradiance`). Every channel is uniform, `Variable.field` goes away, and `hold` is a translator-only word. |
| e | ELN edits lose `'65 °C'` text input. | **Accepted.** NOMAD's numeric widget with unit switching takes its place. |
| f | Should the parser fill `archive.data` directly, or write an `.archive.yaml` into the upload? | **Directly.** Writing a file would create a second entry for the same protocol. |

### 13.6 Order, each step reviewed on its own

The order is chosen so the compatibility check (13.1a) exists **before** anything is deleted,
and no step leaves the old format unreadable for longer than one review.

1. **Design.md only.** Mark D4c (`Variable.field`), D8a, D11a, D19, D19a, D19b, D20 and §9 as
   superseded where 13.2 says so, and update §10's layout.
2. **Freeze the old format.** Move the pretty files to `tests/data/*.stability.yaml`. Collect
   every authored input from today's tests as fixtures, each with the meaning it must keep.
   Add the test that `schema_packages/` does not import `authoring/`. For now the fixtures
   are still loaded by the current schema, so everything stays green.
3. **Translator, pure Python, written against the current schema.** Four substeps, each with
   its own tests:
   - 3a: `m_def` dispatch and the tree walk, with `translate(bare) == bare`;
   - 3b: units, through `units.parse`;
   - 3c: `hold` routing and named words;
   - 3d: unknown keys with did-you-mean.
   Each fixture from step 2 must translate without problems.
4. **Bare schema.** Delete what 13.2 lists and rename the single-variable fields (13.5 d).
   Write the golden `*.archive.yaml` files in the bare form. The fixture tests now go
   file → translator → schema and must keep every meaning from step 2. Schema tests load only
   bare dicts. `test_units.py` keeps the parser tests and drops the datatype tests.
5. **Parser and entry point.** Replace the `NewParser` template. Add an end-to-end test that
   parses a `.stability.yaml`, runs normalize, and checks that problems are logged with their
   path. **Verified:** `ArchiveParser` matches only `.*(archive|metainfo)\.(json|yaml|yml)$`, so
   `.stability.yaml` reaches this parser through NOMAD's own matching (tested). Whether
   pretty `*.archive.yaml` files can be claimed is answered in 13.1a.
6. **Back to §10's roadmap.** States, the expander and the timeline build on the bare schema,
   and each new authoring convenience lands in the translator.
7. **Kept strictly a plugin (after review).** The separate `authoring/` package of steps 2–5
   was folded into `parsers/`, since it only serves the parser, and its `__main__.py`
   command line was dropped. The one-way dependency is now `parsers/` → `schema_packages/`.
8. **The tree's base now derives from NOMAD's own `ActivityStep` (after review).**
   `RoutineCommand` → `PlannedActivityStep(ActivityStep)` (`basesections.v2`, §2), gaining
   `name`, `start_time` (left unset — protocol time stays relative to t₀, carried by
   `duration`) and `description` for free, and declaring `duration` itself, since
   `ActivityStep` does not. `ChannelCommand` → `MeasurementStep`, `Subroutine` →
   `SubroutineStep`; `Routine` keeps its name (D11). Nothing about the tree's shape,
   `commands`, or the checks in `normalize()` changes — only the names and the base.

---

## 14. One `PlannedMonitorControlStep`, variables as sections, the protocol as steps

**Status: settled in review (14.4), built in the order of 14.5.** It supersedes 13.5 b (the class
is the axis), the per-channel classes of D19a, `ControlGroup` / `control_groups` (D4c), D8a's
separate list of words standing for no number, the `channel` amendment of D20, and
`channel_settings` / `routine` as parts of the schema. The bare-schema/parser split of §13 is
unchanged.

### 14.1 The idea

Today an axis is a class. Adding one touches four places: a `*ChannelCommand` class, a
`ChannelSettings` slot, `CHANNEL_CLASSES` and `NAMED_VALUES` in `parsers/channels.py`.

Instead:

- **one step class, `PlannedMonitorControlStep`.** It names its axis in `variable_set` and holds
  what it commands in a single `variable` sub-section;
- **one small section class per variable** (`schema_packages/variables.py`). Each declares its one
  unit-ful `setpoint` in NOMAD's unit system, exactly as the channel commands' quantities do today,
  plus the physical properties that belong to it (`Irradiance.spectrum`);
- **the variable sets as data** (`schema_packages/variable_sets.py`). A new variable is one small
  class and one registry line; a new axis is one registry entry;
- **the protocol is only `steps`.** `channel_settings` and `routine` stay words of the authored
  YAML, and the parser turns them into steps.

A **`VariableSet`** is one physical degree of freedom. Its variables are alternative ways to
command it, not independent settings: voltage, current, resistance and open circuit are tied by
the cell's I–V curve. A step commands at most one of them, which the single `variable` sub-section
makes structural.

A **`Variable`** knows its unit (on its `setpoint`), whether an instrument reads it back
(`monitored`), and its **alternative setpoints**: words that stand for a value (`dark` → 0 W/m²).
A variable without a `setpoint` stands for no number at all (`OpenCircuit`); it is commanded by
being there (D8a).

```python
# schema_packages/variables.py — NOMAD sections
class Variable(ArchiveSection):
    alternative_setpoints: Mapping[str, float] = {}  # class data, in the setpoint's unit
    monitored: bool = True                           # False: set, never read back
    def is_commanded(self) -> bool                   # has a setpoint, or needs none

class Temperature(Variable):   setpoint = Quantity(type=np.float64, unit='K')
class Irradiance(Variable):    setpoint [W/m^2], spectrum: str; alternative_setpoints = {'dark': 0}
class Voltage [V], Current [A], Resistance [ohm] (monitored = False), OpenCircuit (no setpoint)
class BendRadius [m], Strain [dimensionless]

# schema_packages/variable_sets.py — plain data
@dataclass(frozen=True)
class VariableSet:
    name: str
    variables: tuple[type[Variable], ...]
    tied_by: str | None = None

VARIABLE_SETS = {temperature: (Temperature,), irradiation: (Irradiance,),
                 electrical_load: (Voltage, Current, Resistance, OpenCircuit),
                 bending: (BendRadius,), stretching: (Strain,)}
```

### 14.2 The schema

```python
class PlannedMonitorControlStep(PlannedProcessStep):
    variable_set   MEnum(*VARIABLE_SETS)   # the axis
    variable       SubSection(Variable)    # what is commanded, if anything; m_def picks the class
    monitor, sample_every, sampling_rate   # unchanged

class PlannedSubroutineStep(PlannedProcessStep)     # unchanged: mode, commands
class StabilityProtocol(PlannedProcess, EntryData)  # steps only (PlannedProcess.steps)
```

`Routine`, `ChannelSettings`, `channel_commands.py` and `ControlGroup` are deleted.

**Verified** (scratch test): a non-repeating `SubSection(section_def=Variable)` loads whichever
subclass the entry's `m_def` names, keeps its unit, and writes the `m_def` back, so it
round-trips. An empty `OpenCircuit` round-trips as `{m_def: …}`. A protocol's own `normalize()`
needs an `EntryArchive` with `metadata`, not `None`.

**Checks in `normalize()`**, because they hold for any archive:

- A missing `variable_set` is derived from the `variable`'s class, like the sampling pair. A
  `variable` of another set, or a bare `Variable` of no set, is an error, and so is a step with no
  `variable_set` at all. This replaces "a command built as the base class names no axis".
- R4 groups sibling steps by `variable_set`: in a block's `commands`, and now also in the
  protocol's `steps`, which run in sequence.
- R5 (never runs) and the sampling derivation are unchanged.

### 14.3 The parser

- `channel_settings: {temperature: {...}}` becomes one step per slot, **first in `steps`, without a
  `duration`**: a condition that holds for the whole protocol (D13). Authored `steps:` follow, then
  `routine:` as a `PlannedSubroutineStep`. The routine's commands sit one block deeper, so they win
  for their span: D4b's precedence, now by lexical scope. R4 compares siblings only, so it does
  not fire.
- `channel: temperature` → `variable_set: temperature`. `channel: mechanical` becomes `bending` or
  `stretching`, chosen by the variable written.
- `hold`, `variable: voltage`, and the variable as its own key (`voltage: 0.8 V`,
  `open_circuit: true`) become the `variable` sub-section; `spectrum` moves into its `Irradiance`.
  Alternative setpoints are read from `Variable.alternative_setpoints`. `hold: open_circuit` names
  the variable that needs no number.
- An entry whose `m_def` names one of the four deleted channel classes is read as that channel, so
  §13's bare archives still translate. NOMAD's own `ArchiveParser` cannot load those old files any
  more (13.1a's caveat); the golden files are regenerated.
- `parsers/channels.py` keeps only authoring words: the variable keys (`bend_radius` →
  `BendRadius`), the channel words (`mechanical` → two sets), and the old class names.

### 14.4 Decisions — settled in review

| | Question | Decision |
|---|---|---|
| a | Where does a setpoint's value live? | One unit-ful field per variable, in NOMAD's unit system: a small `Variable` subclass per variable, each with its `setpoint`. |
| b | `channel_settings` | Not part of the schema any more; an authored word only. The parser turns it into leading steps, and the protocol is only `steps`. `routine` goes the same way. |
| c | `spectrum` | A property field of its variable (`Irradiance.spectrum`), like any other physical property. |
| d | Mechanical | Split into `bending` and `stretching`. |
| e | `control: str` | Dropped: whether a set is controlled is derived from whether its variable is commanded (D8). |
| f | Class name | `PlannedMonitorControlStep`. |

### 14.5 Order

Tests and ruff run after every step, against a stated expectation.

1. **Design.md** (this section).
2. **`variables.py` and `variable_sets.py`**, with tests on them alone. Nothing else changes.
3. **The switch**, in one step, because the protocol's shape changes under every test at once.
   `PlannedMonitorControlStep` takes `variable_set` / `variable`; `Routine`, `ChannelSettings`,
   `channel_commands.py` and `ControlGroup` go; the parser emits the new form; the golden files are
   regenerated. Every test moves to the new shape, and the compatibility suite (13.1a) keeps every
   meaning.
4. **§10's layout**, and the superseded decisions marked.

---

## 15. Plain monitor/control steps, no physics in the schema

**Status: settled in review, built.** It supersedes §14's `variables.py`, `variable_sets.py`,
`variable_set` / `variable`, the alternative setpoints, `OpenCircuit`, `monitored` and
`tied_by`. §14's protocol-as-steps and the parser's `channel_settings` / `routine` stay.

### 15.1 The idea

The schema describes data only. Physics is logic: which quantities are tied, what `dark` means,
which of a load's quantities an instrument reads. It belongs in a `normalize()` once it is
needed, or in the parser, not in the shape of the data model.

- **`PlannedMonitorControlStep`** (`routine.py`) carries two tags, `monitor` and `control`, a
  `setpoint` with no unit on the base, and `sample_every` / `sampling_rate`.
- **`hold_steps.py` and `ramp_steps.py`** hold one subclass per quantity each, under the two
  kinds `HoldStep` / `RampStep` (§15.11). A hold fixes the unit of its `setpoint`, a ramp of its
  `start_point`, `end_point` and `ramp_rate`: `…Temperature` (K), `…Irradiance` (W/m², plus
  `spectrum`), `…Voltage` (V), `…Current` (A), `…Resistance` (Ω), `…BendRadius` (m), `…Strain`
  (dimensionless), the atmosphere pair `…WaterVaporFraction` / `…OxygenFraction`
  (dimensionless, §15.7) and `…Pressure` (Pa). `BalanceGas` (a gas name) and `OperatingPoint`
  (a point of the JV curve, in `mpp_steps.py`) hold something that is no number, so they take
  neither (§15.10).
  **Verified** (scratch test): a subclass may redeclare `setpoint` with a unit, the base's stays
  unit-less, and the step round-trips.
- **The class is the axis again.** R4 groups sibling steps by class; a bare
  `PlannedMonitorControlStep` names no quantity and is reported.
- **`estimated_duration` replaces `duration`** for planning: R4, R5 and D13's episodes read it.
  `ProcessStep.duration` is left for what actually happened.
- **A block's list is `steps`**, like the protocol's.

### 15.2 The parser

- `channel` and a variable (`variable:` or its key) choose the step class; `hold` or the key
  becomes `setpoint`, and a written setpoint sets `control: true`.
- `duration` → `estimated_duration` and `commands` → `steps`, on every step.
- A channel with several variables and no setpoint (`electrical_load: {monitor: true}`) becomes
  one step per variable, each with the same tags.
- `dark` stays an authoring word of the parser (`Irradiance`, setpoint 0).
- `open_circuit` has no place in the schema: it is reported, and its step left out. The example
  file keeps it, so its translation carries exactly that one problem.

### 15.3 Calls made while building, for review

| | Call | Why |
|---|---|---|
| a | The base stays in `routine.py`; the subclasses live in `steps.py`, which imports it | The block's checks need the base; the other direction would be an import cycle. |
| b | Class names `TemperatureStep`, `IrradianceStep`, … *Renamed since to the bare quantity — `Temperature`, `Irradiance`, … — and `steps.py` to `activity_steps.py`: the class is the quantity, and the suffix only repeated what the base class already says.* | One class per quantity, named as the step it is. |
| c | The parser sets `control: true` with a setpoint; `normalize()` checks nothing about the tags | Logic is added later, when needed (15.1). |
| d | A channel logged without a setpoint becomes one step per variable | The schema no longer knows which of a load's quantities are read back. |
| e | `open_circuit` is reported and its step left out | It is a pre-defined setpoint with no field to go to. |
| f | `dark` is kept, in the parser | It is an authoring word only; the schema stores `0`. |

### 15.4 Steps fitted to their block, and the shared checks

**R6 — a step that would outlast its block is shortened.** When a block has an
`estimated_duration`, its `normalize()` fits the steps into it:

- in a `sequential` block, the step during which the time runs out is shortened to the time left;
- in a `parallel` block, every step longer than the block is shortened to the block's length;
- a step with no time left at all is not touched: R5 already warns that it never runs;
- a step without a duration is not touched either. It is a condition and already lasts exactly
  as long as the block (D13); giving it a duration would make it an episode that takes a turn.

This is a repair, where R4 and R5 only report (D13a). Each shortening is therefore logged as a
warning that names the step, both lengths and the block.

**The checks live in `schema_packages/utils.py`** — R4 (`report_overlapping_steps`), R5
(`report_steps_that_never_run`) and R6 (`fit_steps_to_duration`) — because a block
(`routine.py`) and the protocol (`protocol.py`) run them the same way. They are plain functions
over steps. `utils.py` imports no schema module, since `routine.py` imports it; it recognises a
monitor/control step by its `setpoint` field instead of by its class.

**The protocol does the same with its own `steps`**, which run in sequence: R4, R5 and R6
against its `estimated_duration`.

**A missing `estimated_duration` is derived from the steps**, for a block and for the protocol,
as D13 already says a block without one lasts as long as what it contains: the sum of the steps'
durations in a sequential list, the longest in a parallel block. Steps without a duration are
conditions and add nothing; with no duration among the steps it stays empty. NOMAD normalizes
nested sections first (verified), so a nested block's derived duration is in place before its
parent adds it up. It is a derivation, like the sampling pair, so it is not logged.
`normalize_steps(section, mode, logger)` in `utils.py` runs all four for both.

Because they are plain functions over steps, they are tested as such, in
`tests/schema_packages/test_utils.py`: each called directly on a list of steps, without a
`normalize()` pass around it. That suite is where the boundaries live — what counts as an
overlap, what "never runs" means against what R6 only shortens, what a condition is exempt
from, and that R4 and R5 leave the steps exactly as authored while R6 alone writes to them.
`test_routine.py` and `test_protocol.py` keep only the check that a block and the protocol
do run them.

### 15.5 `PlannedProcess` and `PlannedProcessStep` moved to `general.py`

Both are extensions of NOMAD's own base classes only — `was_executed` and the `estimated_*`
fields the plan/record split needs (§14.1) — and name no PV concept, unlike everything else in
`routine.py` and `protocol.py`. Moved out to say so: `general.py` imports only NOMAD and
`nomad.common`, and both `PlannedMonitorControlStep` (`routine.py`) and `StabilityProtocol`
(`protocol.py`) import from it, the same class either way. `PlannedProcessStep` is defined first
in the file, so `PlannedProcess.steps` (`SubSection(section_def=PlannedProcessStep, ...)`) can
reference it directly, without a `SectionProxy` string reference.

### 15.6 `mode` renamed to `execution_mode`

`PlannedSubroutineStep.mode` is now `execution_mode`, to say plainly that it is *how the block
runs its steps*, not a mode of the block itself. `mode` stays a readable authoring word: `RENAMED`
in the translator (§15.2) maps it to `execution_mode`, the same as `duration` /
`estimated_duration` and `commands` / `steps`, so old files keep loading and the bare archive
always shows the current name.

### 15.7 The atmosphere, as an absolute volume ratio

**`WaterVaporFraction` and `OxygenFraction`** (`activity_steps.py`) are the atmosphere's two
steps, monitored, controlled or both like every other. Each declares its `setpoint` as
`unit='dimensionless'`: the volume ratio itself, the plain fraction.

**Why a ratio, and not relative humidity.** `%RH` is no property of the atmosphere alone — the
same water content is 85 %RH at 25 °C and something else at 85 °C. A step holding `85 %RH`
would therefore mean a different amount of water beside every temperature step, two protocols
run at different temperatures could not be compared on the number they wrote, and R4's check
that two steps do not contradict each other would be comparing figures that are not the same
kind of thing. An absolute ratio is also what the sensor in a glovebox actually reports. So
relative humidity is not a setpoint; it can be derived in a `normalize()` from the water
fraction and the temperature if anything ever needs it, which is where logic belongs (§15.1).

**Why dimensionless, and not a unit per spelling.** `nomad.units.ureg` knows `ppm` (1e-6) and
`%` (1e-2), both dimensionless (**verified**), so one field takes either and stores one number:
`500 ppm` is 5e-4, `2 %` is 0.02, and a glovebox figure compares with a vol-% figure with no
conversion table and no "kind" to record. For an ideal gas the volume fraction and the mole
fraction are the same number, so D6's glovebox convention (`ppm` is by volume) needs no second
axis. This replaces §6's multi-kind treatment of humidity and oxygen (relative / molar / mass,
and the ambiguity error on a bare `%`): with one kind on the axis, a bare `%` is unambiguous.

**The parser fills the registry's gaps the way §6 step 2 does for time** — through the
`(factor, unit)` alias table, never `ureg.define()`, since the registry is shared: `ppb`,
`ppmv`, `ppbv` → `ppm`, and `vol%`, `mol%` → `percent`. Spellings this schema does not record
are refused loudly, each naming what to write instead: `%RH` and `RH`, and the mass ratios
`wt%`, `ppmw`, `ppbw`, which are not volume ratios and are not silently converted into one.

**`humidity` is a retired authoring word**, like `open_circuit` (§15.2). Written as a key or as
`variable:`, it is reported with `water_vapor` as what to write, and its step left out rather
than half-translated. `_Words.take` now recognises a retired word in all three places a word can
stand: as a key, as `hold:`, and as `variable:`.

**The channel** `atmosphere` groups `water_vapor` and `oxygen`, so `channel: atmosphere` with no
setpoint becomes one monitored step per variable, exactly as every other channel does.

**Left out, for review:** `balance_gas` (`N2`, `air`, `Ar`), which describes the atmosphere as a
whole rather than either fraction and so belongs to neither step; and `total_pressure`, a third
quantity of another dimension. Neither is needed to write a soak, and both are one class or one
field away.

### 15.8 A block that repeats

**`repeat` on `PlannedSubroutineStep`** says how often the block runs its steps. Only a block
carries it: a monitor/control step is one episode on one quantity, and running it again is the
job of the block around it.

| `repeat` | What it means |
|---|---|
| `until_end_of_duration` (default) | The steps run for as long as the block's `estimated_duration` lasts. Nothing repeats explicitly, so a block that says nothing is the block §15.4 already described. |
| `n_times` | The steps are **one iteration**, run `repeat_n` times, each `estimated_duration_one_iteration` long. |

**With `n_times` the block's own length is derived, not authored:** `estimated_duration` becomes
`repeat_n` × `estimated_duration_one_iteration`. `estimated_duration_one_iteration` may itself be left empty, and is
then derived from the steps exactly as a block's duration always was (§15.4) — so a thermal cycle
is written as its steps and a count, and nothing else.

**The steps are checked against one iteration.** R4, R5 and R6 run against
`estimated_duration_one_iteration`, never against all the iterations together: a 2 h step inside a 1 h
iteration is shortened, where measured against 10 × 1 h it would have looked as if it fitted.
That is what `check_steps` in `utils.py` is — the three checks over one run of the steps —
with `normalize_steps` left as what the protocol and a non-repeating block call.

**Reported, never repaired** (D13a): `n_times` with no `repeat_n`; a `repeat_n` below 1; and an
authored `estimated_duration` that contradicts `repeat_n` × `estimated_duration_one_iteration`, where the
authored value stands and the disagreement is named with both figures. `repeat_n` or
`estimated_duration_one_iteration` written *without* `n_times` is dead configuration rather than a
contradiction, so it is a warning and the field is ignored.

**Why this and not a `Cycle` state class** (§10's `states.py`, §4.1's `cycle`): a cycle is a block
of ordinary steps run n times, and saying so needs one enum and two fields rather than a class
with `waveform`, `period` and `duty_cycle` — a shape the schema would then have to evaluate,
which is the physics §15.1 keeps out. What stays genuinely irreducible is the **ramp**, where the
value varies *within* one step. That is still open.

### 15.9 ISOS Table 1 coverage — what's still missing

`tests/data/ISOS_protocols_table1.xlsx` (Khenkin et al., *Nat Energy* 2020) is the reference: one
row per ISOS protocol, meant to become one example `.stability.yaml` each. Checked against §15 as
it stands, most of the table is already expressible — fixed temperature/irradiance setpoints,
`dark` for "Light source: None", a bare monitored condition for "Ambient", and the ISOS-LC-1
dark/light duty cycle (a `repeat` block alternating two `Irradiance` steps, §15.8). Four gaps
remained, in the order worth closing them. **All four are built** (§15.10–§15.16), schema and
authored words alike, so every row of the table can now be written as a `.stability.yaml`:

| | Gap | Blocks | Why |
|---|---|---|---|
| T1 ✅ | **MPP tracking** — no schema representation | ISOS-L (all 3), ISOS-O (all 3), ISOS-LC (all 3), ISOS-LT (all 3), half of ISOS-V-1 | `Voltage` / `Current` / `Resistance` (`activity_steps.py`) only take a fixed `setpoint`. `track: mpp` existed pre-§15 (§4.1) but was dropped with everything else in that rewrite, and nothing in §15 replaces it. Roughly half the table's rows use MPP as the load condition. |
| T2 ✅ | **Open circuit as an explicit, nameable step** | ISOS-D (all 3), ISOS-T (all 3), negative branch of ISOS-V-1 | `open_circuit` is a **retired word** (`RETIRED_WORDS`, `channels.py`): writing it is reported and the step is left out. A protocol that deliberately holds OC is indistinguishable, on disk, from one that never mentions electrical load at all — there is no way to say "OC, on purpose." |
| T3 ✅ | **Ramping / continuously varying setpoints** | ISOS-T-1/2/3 ("RT to 65/85 °C"), ISOS-LT-1/2/3 ("linear ramping between X and 65 °C") | Already named above as the one thing §15.8's `repeat` cannot reach: a value that varies *within* one step, not across repeated iterations. |
| T4 ✅ | **Relative humidity as an authored quantity** | ISOS-D-3, V-3, L-3, T-3, LC-3, LT-1/2/3 | Collides on purpose with §15.7: `%RH`/`RH` are in `_REJECTED_UNITS` and hard-refused. None of these rows' humidity figures (`85 %`, `~50 %`, `< 55 %`) can be transcribed as the table states them today. Needs a decision, not just code: keep absolute-ratio-only and expect the figure converted before authoring, or accept `%RH` as a spelling the parser converts using a sibling temperature step — the second reopens part of §15.7. *Settled in review: the second, but **only as a compound value carrying its own temperature** — written `water_vapor: {rh: 85 %, at: 65 °C}` — converted to the absolute ratio in the parser, before the schema sees it. §15.7's schema decision is then untouched (`HoldWaterVaporFraction.setpoint` stays the plain fraction), and nothing reaches across sibling steps to resolve one value: the temperature stays explicit and local, which is exactly what §15.7 objected a bare `%RH` had not. It also matches the table, where every RH figure is already written beside its own temperature. Built in §15.16 (`units.py`, `translate.py`).* |

Smaller, and not worth a schema change on its own: ISOS-LT-2/3's "controlled at 50 % beyond
40 °C" is a control law conditioned on another channel's value — even with T3 and T4 solved, that
clause stays unreachable without conditional logic. Footnote it in the example rather than model
it exactly, the same way the xlsx's setup and characterization-light-source columns are out of
scope (tooling, not the protocol).

### 15.10 The operating point, the ramp, and the ambient quantities

Closes T1, T2 and T3 of §15.9. T4 (relative humidity) follows in §15.16, which is the decision
its row records.

**`OperatingPoint`** (`mpp_steps.py`, §15.11) is the electrical load's other axis: *where on the JV
curve the load sits*, when the point is found by the instrument instead of written as a number.
`point` is `MEnum('mpp', 'voc')` — maximum power point tracking, and the open-circuit condition.

**One class with an enum, not `MaximumPowerPoint` + `OpenCircuit`.** *Superseded by §15.13:
`MPPTracking` and `VOCTracking` are two classes, named for what they do. The argument below is
right that R4 then stops seeing the contradiction — the declared axis that was to have bridged
them was removed in review, so the report is a known gap (§15.13).* A load sits at
exactly one
point at a time, so the two are values on one axis, and R4 then reports "MPP and Voc at once" as
the contradiction it is — which two separate classes could never catch, since R4 groups siblings
*by class* (§15.4). It is also the one step that names **no number**: `setpoint` and
`final_setpoint` stay empty, because the volts and amps at the maximum power point are what the
cell answers, not what the protocol instructs, and writing them would be authoring a measurement.

**`voc` is what `open_circuit` was.** §15.2 retired the word for having no field to go to; it has
one now, so T2's real complaint — that a protocol deliberately holding OC was indistinguishable
from one that never mentioned the load — is answered. The translator still retires the word: it
is a `RENAMED`-style mapping away (`open_circuit` → `OperatingPoint(point='voc')`), and belongs
with the rest of the parser work, not here.

**The ramp is `final_setpoint`.** *Superseded by §15.11: a ramp is its own kind of step —
`RampStep`, with `start_point`, `end_point` and `ramp_rate` — and `setpoint` moves off the base
onto `HoldStep`. What the rest of this section argues (linear only, the rate derived rather than
a third authored field, declared per class in its own unit) stands, and is what §15.11 builds.*
A step with one goes from `setpoint` to it, **linearly**, over
its `estimated_duration` — or over its block's whole span, if it has none, since that is what a
step without a duration already means (D13). The presence of the field *is* the shape, so there
is no `shape` enum to keep in step with it, and no second way to say "hold".

- **No `rate`.** D16 allowed a ramp a `rate` *or* a duration; every step already has
  `estimated_duration`, so the rate is `(final_setpoint − setpoint) / estimated_duration` —
  derivable by whatever needs it, and a third unit-ful quantity on every class if authored.
- **No curve but the straight one.** Anything else is a shape the schema would have to evaluate,
  which is the physics §15.1 keeps out. A staircase is not a curve at all: it is a `repeat` block
  of ordinary holds (§15.8), which is how ISOS-T-1's "step ramping" is written.
- **Declared per class, like `setpoint`.** Each numeric step redeclares `final_setpoint` in its
  own unit. A ramp's end must carry the same dimension as its start, and a bare number beside a
  kelvin one is exactly the trap O11 records. `OperatingPoint` and `BalanceGas` redeclare
  neither: a tracked point does not ramp, and neither does a gas name.

**Reported, never repaired** (D13a): a `final_setpoint` with no `setpoint` (a ramp needs the
value it starts from — and unlike a missing end, it cannot be read as a hold), and an
`OperatingPoint` naming no `point`, the same way a bare `PlannedMonitorControlStep` naming no
quantity is reported.

**The ambient quantities** are §15.7's "left out, for review" pair, added now: **`Pressure`**
*(`HoldPressure` / `RampPressure` since §15.11)*
(Pa — the atmosphere as a whole, so a glovebox overpressure, an altitude or a vacuum soak has
somewhere to go) and **`BalanceGas`** (`gas`, free text like `Irradiance.spectrum`: `N2`, `air`,
`Ar` — a name, not a number, so it declares no setpoint either). Note what did *not* need a
class: "Ambient" as ISOS Table 1 writes it is a monitor-only step with no setpoint — a condition
that lasts as long as its block (D13) — and that was already expressible on every axis.

### 15.11 Holding and ramping are two kinds of step

**Status: settled in review, built.** Supersedes §15.10's `final_setpoint`.

`PlannedMonitorControlStep` keeps only what every monitor/control step has — `monitor`,
`control` and the sampling pair. *What the step does with its quantity* is the kind below it,
and the quantity itself is the class below that:

| Kind (`routine.py`) | Declares | One class per quantity |
|---|---|---|
| `HoldStep` | `setpoint` | `hold_steps.py`: `HoldTemperature`, `HoldIrradiance`, … |
| `RampStep` | `start_point`, `end_point`, `ramp_rate` | `ramp_steps.py`: `RampTemperature`, … |

**Why two kinds rather than one class with both.** A step either holds or moves; it is never
half of each. With `setpoint` and `final_setpoint` on one class, every hold carried a field it
never filled, and *which kind a step is* was a question you answered by looking at which fields
were empty — a shape the schema states nowhere and every reader has to infer. As two kinds the
answer is the class, which is what the rest of the design already reads. It also pays twice
over: `OperatingPoint` and `BalanceGas` hold something that is no number, and with `setpoint`
moved down to `HoldStep` they subclass the plain step directly and inherit no numeric field at
all — the wart §15.10 had to document is simply gone.

**R4 groups by axis, not by class.** This is what the split costs, and it is worth naming:
`HoldTemperature` and `RampTemperature` are two classes and *one quantity*, and two steps
commanding the temperature at once contradict each other whichever kind they are. So
`report_overlapping_steps` groups siblings by the **axis** — the class name without its `Hold` /
`Ramp` prefix — where §15.1 could say "the class is the axis". `utils.py` deliberately imports
no schema module (§15.4), so it cannot ask `isinstance`; it reads the name, as it already reads
fields. That makes the naming convention load-bearing, which is the one thing to remember when
adding a quantity: a class is `Hold<Quantity>` or `Ramp<Quantity>`, and the rest of the name is
the axis. `_is_monitor_control` moves with it, from sniffing `setpoint` (which a ramp has not)
to sniffing `monitor` (which both kinds have and no block does).

**The rate and the duration are one fact** (D16): `ramp_rate` is a positive magnitude — the
direction is `start_point` → `end_point` — and whichever of the two was written, both are
stored, exactly as the sampling pair is (D9). A ramp with neither is a condition like any other
step without a duration: it lasts as long as its block, and its rate is not known until that is
(D13).

**Reported, never repaired** (D13a): a ramp missing `start_point` or `end_point` — unlike a
missing rate, there is nothing to derive it from; and a `ramp_rate` that contradicts the ends
over the authored `estimated_duration`, where both stand and the disagreement is named with both
figures. A bare `PlannedMonitorControlStep`, `HoldStep` or `RampStep` names no quantity and is
reported as before, now saying which of the three it was.

**Still authored nowhere.** The parser maps every variable key to its `Hold…` class; a ramp has
no authoring spelling yet, and neither have `OperatingPoint` and `BalanceGas` (§15.10). That,
and T4's `rh` with its own temperature, is what stands between this schema and the ISOS example
files of §15.9.

### 15.12 What the run itself records — `standard`, `environment`, `notes`, `location`

Facts about the whole protocol rather than about any one quantity, so they sit on
`StabilityProtocol` and not on a step.

**`environment`** is `MEnum('indoor', 'outdoor', 'other')`, **defaulting to `indoor`** — unlike
most defaults in this schema, a positive claim rather than a neutral element (D8). Deliberate:
nearly every one of these tests is run in a laboratory, so the default is right far more often
than it is wrong, and an outdoor test is exactly the one whose author is thinking about where it
ran. *Spelled `MEnum`, like every other enum here* (`execution_mode`, `repeat`, `point`):
`nomad.metainfo.metainfo.Enum` resolves, but one spelling per concept.

**`notes`** is free text, and exists because `environment`'s own description already pointed at
it. NOMAD's inherited text fields are `description`, `lab_id` and `name`, none of which means
"anything else worth saying about this run".

**The place's name is NOMAD's own `location`; only the coordinates are ours.** Every NOMAD
activity already declares `location` — a string, *"the location associated with this activity"* —
so `Denver, U.S.` goes there, where it searches beside every other activity in the Oasis, and
this schema adds only what NOMAD has no field for. **Verified, the hard way:** declaring a
`location` sub-section of our own instead raises `MetainfoError: Cannot inherit from different
property types` — the collision saying out loud that the field already exists.

- **`GeoLocation` (`geo_location`)** is `latitude` / `longitude` in degrees and `altitude` in
  metres: what a search can compare, and what joins two uploads of one site where two spellings
  of a name would not. Altitude is not decoration — it sets the air mass, and so the spectrum an
  outdoor test actually sees. A plain number reads in the declared unit (D6), so `39.74 °` and
  `5280 ft` both read; a bare `5280` on `altitude` reads as metres, which is O11's residual cost
  turning up on the one field where feet are a common spelling, and is why the description says
  so.
- A section of its own rather than two flat fields, so the pair travels together — while either
  half still stands alone: a named site nobody surveyed, or coordinates off an instrument log
  that no one has a name for.
- No `name` inside it. That would be a second place to write what `location` already holds,
  which is the same "one fact, one place" that keeps `balance_gas` off the two fraction steps.

**Reported, never repaired** (D13a): a latitude beyond ±90° or a longitude beyond ±180°, whose
usual cause is the pair written the wrong way round — which a latitude of `-104.99` catches and
nothing else would.

**Left out of §15.12:** any check tying `geo_location` to `environment`, since an indoor lab has a place on
Earth too; and any bound on `altitude`. Latitude and longitude have hard mathematical ones, so
breaking them is always a mistake and worth reporting; an altitude's plausible range is a
judgement about where experiments happen rather than a fact about the number, and a rule
guessing *"that looks like feet"* is exactly the physics §15.1 keeps out of the schema.

### 15.13 The load's found points, as two classes

**Status: settled in review, built.** Supersedes §15.10's single `OperatingPoint` with a `point`
enum.

*Amended in review: the declared `axis` attribute described below was **removed** — it encoded
physics in the schema, which is the one thing §15.1 exists to keep out. What survives is the two
classes and their names; what is lost is R4's report of "MPP and Voc at once". See "The axis was
declared — and then removed" below.*

**`MPPTracking` and `VOCTracking`** (`mpp_steps.py`), named for what they do. `OperatingPoint`
asked a reader to know an enum before the class said anything at all: the class named a
*category*, and the fact lived in a value. Two classes put the fact in the name, which is what
every other step here does — `HoldTemperature` does not carry a `quantity: temperature`.

**The axis was declared — and then removed.** §15.10 argued that one class was *forced*, because
R4 groups by axis and the axis was the class name minus its kind prefix — so two classes would be
two axes and "MPP and Voc at once" would go unreported. The remedy tried was a class attribute
naming the axis outright, `axis = 'OperatingPoint'`, which `_axis_of` read ahead of the derived
name. It worked (a plain class attribute survives NOMAD's metaclass and is *not* registered as a
metainfo property), and it was **rejected in review as too physics-encoded**: "these two classes
are one physical degree of freedom" is a fact about solar cells, and §15.1's whole line is that
such facts live in the parser or in a `normalize()`, never as schema furniture. One tag for one
pair is also a general mechanism with a single user — the argument O12 lost on.

So `_quantity_of` (renamed from `_axis_of`, since "axis" was the physics word) is now just the
class name minus its `Hold`/`Ramp` prefix, and that name is the whole rule.

**The gap this leaves, stated plainly:** `MPPTracking` and `VOCTracking` group under their own
names, so a block asking for both is **not** reported. A load does sit at one point at a time, so
this is a real contradiction going unseen — recorded here, and asserted as current behaviour in
`test_mpp_and_open_circuit_go_unreported`, so that it is a known gap rather than a silent
regression. It is the same limit R4 already has between voltage, current and resistance
(see the paragraph below): the cell ties them, and the schema does not know the cell. If it ever
needs closing, the honest route is a check that knows about the load — in the parser, where the
channel vocabulary already lives — not a tag on the class.

**A constant external bias is `HoldVoltage`** — settled in review, and no class of its own here.
Reverse bias included: `-1.2 V` is a number the protocol names, which is precisely what
distinguishes it from the two points above, where the *cell* decides. *Known gap, unchanged from
before:* `HoldVoltage` stays on the `Voltage` axis, so "hold 0.8 V while tracking MPP" is not
reported. That is the same limit R4 already has between voltage, current and resistance — the
cell ties them, and §15.1 keeps the cell's physics out of the schema.

**The MPP parameters, and the plan/record split.** They come from `MPPTrackingProperties` in
[nomad-baseclasses](https://github.com/nomad-hzb/nomad-baseclasses/blob/main/src/baseclasses/solar_energy/mpp_tracking.py),
filtered by one question: *does an operator set this before the run, or does the run report it
back?* Only the first kind is a protocol.

| From the reference | Here | Why |
|---|---|---|
| `perturbation_voltage` (V) | kept | How far the tracker steps looking for the peak. |
| `perturbation_delay` (s) | kept | How long it waits before reading back. |
| `perturbation_frequency` (s) | **renamed** `perturbation_every` | It is a *period* in seconds despite the name, and this schema already spells that `sample_every` (D9). A field called a frequency and measured in seconds is the trap §6 exists to avoid. |
| `start_voltage_manually` (bool) | kept, **plus `start_voltage` (V)** | The reference has the flag with nowhere to put the voltage it turns on, which is dead configuration; the companion field is the smallest thing that makes it mean something. |
| `sampling`, `time` | left out | Every step already has `sample_every` / `sampling_rate` and `estimated_duration`. A second way to say either is a second thing to keep in step. |
| `status`, `last_pce`, `last_vmpp` | left out | What the run reports back. A protocol cannot plan its own last PCE. |
| `MPPTracking`'s arrays, `StabilityFiguresOfMerit`, `FitParameter` | left out | The measurement layer — measured series, and T80 / T95 / lifetime yield fitted from them. They belong with §4.5's `results.py`, over data that does not exist at authoring time. |

**The authored words.** `TRACKED_POINTS` (`channels.py`) maps `mpp` to `MPPTracking`, and both
`voc` and `open_circuit` to `VOCTracking` — ISOS Table 1 writes `OC` in every one of its eighteen
rows, so the word it uses had to reach a step. **`open_circuit` therefore leaves
`RETIRED_WORDS`**, which it entered in §15.2 for having no field to go to: it has a class now.
Both spellings the old format allowed still read, `hold: open_circuit` and `open_circuit: true`
(§13.1a), so no file that loaded before stops loading.

Asking for a point **sets `control`**, exactly as a written setpoint does — the load is being
regulated; there is simply no number to store beside it. Reported, never repaired: the word on
another channel (per channel, never global, as `dark` is refused off irradiance, D8a); a
setpoint written beside it; two points in one step; and `open_circuit: false`, which asks for
nothing and is more likely a typo than an intention.

One consequence worth recording, because it is not obvious: **the translator's setpoint path is
now guarded by whether the chosen class declares a `setpoint` at all.** A bare archive naming
`VOCTracking` in its `m_def` is read back through the very same code (§13.1a's round trip), and
before the guard it asked a class with no `setpoint` for its unit. `BalanceGas` would have hit
it next.

### 15.14 The ramp, as an authored file writes it

**Status: settled in review, built.** The schema half is §15.11; this is how a file reaches it.

```yaml
- {channel: temperature, ramp: {from: 25 °C, to: 85 °C, rate: 2 K/min}, duration: 1 h}
```

§8 wrote exactly this before §15 rebuilt the schema underneath it, so the form is kept rather
than invented: `from` / `to` / `rate` become `start_point` / `end_point` / `ramp_rate`, each read
in its own class's unit (§6). **`rate` is optional** — D16 gives a ramp a rate *or* a duration,
and §15.11's `normalize()` derives whichever is missing, so a file writes the one it knows and
the archive ends up with both.

**`ramp:` is what chooses the kind.** `RAMP_STEPS` (`channels.py`) is `VARIABLE_STEPS` again, one
entry per variable, pointing at the `Ramp…` class instead of the `Hold…` one. The variable is
named exactly as it always was — a channel with a single variable, a `variable:`, or the key
itself — so `temperature` names two classes and the presence of `ramp:` picks between them. That
is the hold-or-ramp dispatch §15.11 predicted everything later would reuse.

Asking for a ramp **sets `control`**, as a setpoint does. Reported, never repaired: `ramp:`
beside a `hold:` or a variable's own value (two answers to one question); a ramp on a channel
logged as a whole, where no one variable was named; and a key inside `ramp:` that is none of
`from`, `to`, `rate`.

**The round trip needs both tables.** A bare archive names `RampTemperature` in its `m_def` and
writes `start_point` / `end_point` as plain fields, with no `ramp:` key anywhere — so
`VARIABLE_KEYS` maps *both* kinds back to their variable, and the class the `m_def` names picks
the ramp table on its own. Without that, storing a ramp and reading it back would quietly hand
back a hold.

### 15.15 The atmosphere's last two keys — `pressure` and `balance_gas`

**Status: settled in review, built.** The classes are §15.10's; these are their authored words.

`pressure` is an ordinary variable: it holds a number in a unit, so it joins `VARIABLE_STEPS`
and `RAMP_STEPS` like every other, and `{channel: atmosphere, pressure: 1013.25 mbar}` reads.

**`balance_gas` is the first variable whose value is not a number.** `BalanceGas` keeps a gas's
name in `gas`, not in a `setpoint` it does not have (§15.10), so the translator learns that a
class may put its value elsewhere:

```python
VALUE_FIELDS = {BalanceGas: 'gas'}   # channels.py; everything else means `setpoint`
```

`_value_field(cls)` answers `setpoint` unless the table says otherwise, and `_setpoint` and
`_monitor_control` both ask it instead of naming `setpoint` outright. That is a smaller change
than a third branch beside `hold` and `ramp`, and it leaves one path through the translator: a
variable is named, its value is read, and it lands where the class keeps it.

**A gas does not ramp.** `RAMP_STEPS` has no `balance_gas` entry — there is no `RampBalanceGas`,
because a name does not move linearly between two ends. Writing `ramp:` on it is reported rather
than crashing on a missing table entry, and the same guard covers any variable that gains a hold
but no ramp later.

**One judgement worth flagging:** `{channel: atmosphere, monitor: true}` now becomes **four**
steps, not two — water, oxygen, pressure and the balance gas — because a channel logged as a
whole expands to one step per variable (§15.2) and the channel now has four. Logging which gas
is present is a slightly odd thing to ask for, but the alternative is a variable that cannot be
written as its own key, since `_allowed` reads the same table; one list per channel is what
keeps the authored words and the expansion from disagreeing.

### 15.16 Relative humidity, with the temperature it was read at — T4 built

**Status: settled in review, built.** This is §15.9's T4, and the decision its row records.

```yaml
- {channel: atmosphere, water_vapor: {rh: 85 %, at: 65 °C}}
```

**The schema does not change.** `HoldWaterVaporFraction.setpoint` is still the plain volume
ratio it has been since §15.7 — `85 %RH at 65 °C` reaches the archive as `0.211`, and two
protocols run at different temperatures still compare on the number they stored. What is new is
only that an author may *write* the figure the way ISOS Table 1 prints it.

**Why the temperature must be written beside it, and not looked up.** §15.7 refused a bare `%RH`
because it says nothing on its own: the same reading is a different amount of water at every
temperature. The obvious repair — read the sibling temperature step in the same block — was
rejected on purpose. Which sibling, when a block holds several? What of a block whose
temperature *ramps*, where there is no single value to read? A conversion that silently depends
on a neighbour is one an author cannot check by looking at the line they wrote. A compound value
carries its own answer, is local, and reads the same wherever it appears.

**The conversion** is `volume_ratio_of_relative_humidity` (`units.py`), the Magnus form for the
saturation vapour pressure — good to a few tenths of a percent from −40 °C to 100 °C, which
covers every row of ISOS Table 1 — over a **standard atmosphere**. That last part is an
assumption, and the honest name for it: the ratio depends on the total pressure, and a compound
value carrying its own temperature does not carry a pressure. It is the right assumption for the
ovens and chambers these protocols describe, and `pressure` is a variable of the same channel
(§15.15) if a protocol ever needs to say otherwise. Flagged here rather than buried.

**`humidity` stays a retired word** (§15.7), now pointing at this form instead of saying the
figure cannot be translated at all. `%RH` as a *unit* stays refused by `_REJECTED_UNITS` — the
message names the compound form — because `85 %RH` in a bare setpoint is still a number without
its temperature. The compound is the one place the schema will read a relative humidity, which
is what keeps "absolute on purpose" true of everything stored.

---

## 16. ISOS Table 1 as example uploads

**Status: in progress.** §15.9 asked for one `.stability.yaml` per row of ISOS Table 1, and
§15.10–§15.16 closed the four gaps that blocked it. This section is how those files are written,
and what authoring the real protocols exposed that §15.9 did not predict.

### 16.1 Where they live, and why not in `tests/data/`

```
src/nomad_pv_stability_measurements/example_uploads/isos/
  README.md                what the set is, and how to read one file
  ISOS-D-1.stability.yaml  … one per row, twenty-one in all
```

They ship **with the plugin**, through the `example_upload_entry_point` the package already
declares, because an example upload is what a new Oasis user opens first — these files are the
user-facing documentation §10 step 7 asks for, written in the format they will write themselves.
The tests read them from that path rather than keeping a second copy in `tests/data/`: two copies
of twenty-one files is twenty-one chances for the shipped one to rot while the tested one passes.
`tests/data/` keeps what exists only to exercise the parser (`channels`, `tree`).

The cookiecutter's placeholder `example_uploads/getting_started/` (one file, reading
`EXAMPLE DATA`) is replaced rather than kept beside them.

### 16.2 Two rules that govern every file

**Settled in review, and the correction that produced them.** The first draft of the ISOS-D files
broke both: it invented a test duration, a sampling interval, and a routine block with a name, to
hold a protocol that has no moving parts at all.

**Rule 1 — write only what the standard fixes, with certainty.** An example upload is read as a
*template*. Anything written in one is taken by the next author as something the protocol
requires, so a plausible-looking figure the standard never states is worse than an empty field:
it manufactures a requirement. ISOS Table 1 fixes conditions — light, temperature, humidity,
load. It fixes **no test duration, no sampling interval, no measurement schedule, and no cycle
count** (with one exception, ISOS-LC-1's "cycle period 2, 8 or 24 h; duty cycle 1:1 or 1:2",
which the table does state). None of those appear in a file. Where the table offers levels
("65, 85 °C"), the file takes one and names the other in `notes`; that is a choice among stated
values, not an invention.

The same rule retires `monitor: true` from most files. The table writes "Monitored" in exactly
one place — ISOS-LT's humidity — so that is the only place a file asserts logging. Elsewhere
"Ambient" means **not controlled**, and the file says exactly that and nothing more:

```yaml
temperature: {control: false}      # ambient: not regulated. Not "logged every 600 s".
```

*Amended by §18.7, after reading the consensus statement's text rather than Table 1 alone: the
paper does ask for every uncontrolled condition to be monitored ("even if a parameter is not
controlled … it is still important to monitor and report", p.43), so an ambient quantity is
`{control: false, monitor: true}`. Rule 1 itself stands — it was applied to too narrow a source.
Monitoring asserts that a quantity is logged, still not how often.*

**Rule 2 — `channel_settings` is everything constant; `routine` is only what cannot be a
constant.** The two parts of a file are a statement about the protocol, not a house style: a
setting has no duration and therefore holds for the whole run (D13), which is precisely what a
constant condition is. If a protocol holds one temperature, one irradiance and one load from
beginning to end, **it has no routine**, and writing an empty block around it to look complete is
a lie about the protocol's shape.

This splits ISOS Table 1 cleanly in two:

| Families | Shape |
|---|---|
| **ISOS-D, -V, -L, -O** | every condition constant → `channel_settings` only, no `routine` |
| **ISOS-T, -LC, -LT** | something varies within the run — a thermal cycle, a light/dark duty cycle, a ramping temperature → the varying part, and only that, goes in `routine` |

*Amended: a channel of several variables lists one setting per variable in its slot,
`atmosphere: [{variable: relative_humidity, …}, {variable: oxygen, reference_point: ambient
air}]`. The ambient air of every ISOS file used to be a protocol-level `instructions:` entry,
only because the `atmosphere` slot already held the humidity; it read as if it were something
that happens during the test. Each item is read like a slot of its own and reported at its index
(`channel_settings.atmosphere[1]`). The settings are still in file order, so the air now comes
right after the humidity. Status: built.*

**No invented names.** A block or protocol is named only where the standard names it. The
protocol's own `name` is the designation from the table (`ISOS-D-1`) and nothing more;
descriptive titles like "dark storage, ambient" are the author's prose, and a block that the
standard does not name is left unnamed.

**The rest of the transcription**, unchanged from the first draft:

| The table says | The file writes | Why |
|---|---|---|
| "None" (light source) | `hold: dark` | Deliberately dark, and counted (D8a) — not the absence of an irradiance step. |
| "OC" | `hold: open_circuit` | §15.13; ISOS's own word reaches `VOCTracking`. |
| "MPP or OC" | `hold: mpp` | The table's "or" is a choice the operator makes. MPP is written because it is the case the tracker settings exist for; `notes` records that OC is equally within the protocol. |
| "Linear ramping between X and 65 °C" (ISOS-LT) | one `ramp:` step with `end_of_ramp_behavior: triangle` | §15.14. A triangle *is* the solar-thermal cycle: up at the rate, down at the rate, repeat. Two ramp steps in a repeat block would say the same thing at twice the length. |
| "Outdoor" (ISOS-O) | `environment: outdoor` + `geo_location` | §15.12. The site is part of an outdoor result. |

A consequence of Rule 1 worth seeing coming: a ramp whose rate the table does not state is
written with `from` and `to` and **no** `rate` and no `duration`. §15.11's `normalize()` derives
one from the other when either is present and reports nothing when neither is — so an
under-specified ramp is a legal, honest archive rather than an error.

### 16.3 What twenty-one real protocols exposed

Three things, none of them predicted by §15.9's four-row table:

1. **ISOS-V's load column is device-derived, and the schema cannot say so.** The row reads
   "Positive: V_MPP; V_oc; E_g/q; J_SC — Negative: −V_oc, J_MPP": every one of them is a number
   *taken from a JV curve measured on a fresh device*, not a number an author knows when writing
   the protocol. `HoldVoltage` takes a number, so the files write a representative one and say in
   `notes` what it must be set from. **The gap is real and is not a parser gap:** the schema has
   no way to express "this setpoint is derived from a measurement of this sample". It would be a
   quantity whose value is a reference plus a rule, which is a bigger idea than a step — closest
   to §4.5's `results.py`, where the measured JV curve will actually exist. Recorded, not built.
2. **ISOS-O-1 and ISOS-O-2 become the same file.** They differ in the table *only* by the
   characterization light source (solar simulator vs sunlight), which §15.9 put out of scope. The
   two files are therefore identical but for `standard` and `notes`. That is the honest outcome
   of the scope decision rather than a fault — and it is the clearest argument yet that
   characterization belongs in the measurement layer, where it will distinguish them.
3. **"Monitored, uncontrolled" is one word away from "monitored, controlled".** ISOS-LT-1's
   humidity is monitored and not controlled; LT-2/3's is controlled at 50 %. In the file that is
   the presence or absence of a setpoint beside the same `monitor: true` — which reads well, and
   is worth noting as a case where the schema's central distinction lines up exactly with the
   standard's own prose.

ISOS-LT-2/3's "controlled at 50 % beyond 40 °C" stays footnoted in `notes`, as §15.9 settled: a
control law conditioned on another quantity's value is not reachable without conditional logic,
and one clause in two rows does not buy it.

### 16.4 The tests

`tests/example_uploads/test_isos_protocols.py`, one test per protocol, each asserting **every
field of every step** — not a smoke test that the file parses. Each one:

1. translates the shipped file with **zero problems** (a typo in an example upload is a bug in
   the documentation, so the bar is zero, not "no exception");
2. loads the bare archive into `StabilityProtocol` and normalizes it, with **no errors logged** —
   which is what runs R4/R5/R6 over the real protocol and catches an overlap a hand-written
   example would otherwise ship with;
3. asserts each step's class, its setpoint or ramp ends in their own units, its duration, its
   sampling, and the protocol's own `standard` / `environment` / `notes` / `geo_location`;
4. round-trips: translating the bare archive again returns it unchanged (§13.1a).

A shared parametrized test covers 1, 2 and 4 for all twenty-one; the per-protocol tests carry 3,
which is the part that has to be written out by hand for each row.

---

## 17. Standard values, tolerances, and bounds

**Status: steps 1–5 built (§17.6); step 6, the ISOS files, waits on review.** Where the build
departed from the proposal, the text below is marked *Amended while building*. Asked for in review, to close two gaps §16.3 recorded: "RT to
65 °C" gives no number for room temperature, and "< 55 %" is a bound the schema can only store as
an equality. A third thing falls out for free — `23 ± 4 °C` currently loses its `± 4`.

### 17.1 The three pieces

| Piece | Where | What it is |
|---|---|---|
| `StandardValue`, `RoomTemperature` | `schema_packages/standard_values.py` | A named value with a tolerance, published as a section so the number has one home and a description |
| `set_point`, `set_point_tolerance` | `routine.py`, `hold_steps.py` | `HoldStep.setpoint` renamed and given its tolerance; authored `hold:` / `hold_tolerance:` |
| `HoldBelowStep` + `HoldBelow…` | `schema_packages/hold_below_steps.py` | "Keep this under X", authored `hold_below:` |

### 17.2 `standard_values.py`

```python
class StandardValue(ArchiveSection):
    """A value a standard names rather than each protocol restating it."""
    name      = Quantity(type=str)                 # 'room temperature'
    value     = Quantity(type=np.float64)          # no unit on the base
    tolerance = Quantity(type=np.float64)          # symmetric: value ± tolerance

class RoomTemperature(StandardValue):
    name      = Quantity(type=str, default='room temperature')
    value     = Quantity(type=np.float64, unit='K', default=296.15)   # 23 °C
    tolerance = Quantity(type=np.float64, unit='K', default=4.0)      # ± 4 K
```

The base names no unit and each subclass declares one, exactly as `HoldStep.set_point` and its
ten subclasses do (§15.11) — so the pattern is the one already in the file, not a new one.

**The figures are ISOS Table 1's own.** The table writes "Ambient (23 ± 4 °C)" in the rows that
state a number, and "RT" in the rows that do not; taking the first as the definition of the
second is a cross-reference *within one table*, which is the only reading that does not invent a
figure (§16.2, Rule 1). The `description` says so, and `name` is what carries it into the ELN.

**Verify before building** (the `location` collision in §15.12 was found this way): that
`ArchiveSection` declares no `name` of its own, and that a `default` on a unit-ful `Quantity`
reads back in the declared unit. *Verified while building: `ArchiveSection` declares no
properties at all, and the default reads back as `296.15 kelvin`. Defaults do not appear in
`m_to_dict()` — harmless, since a standard value is never stored and the parser reads attributes.*

**Why a section at all, when the parser inlines the numbers (§17.3)?** Because the alternative is
a dict literal in `channels.py`, and this way the definition is *published*: it appears in the
metainfo and the schema browser, carries a description and a citation, and is one `EntryData`
away from being a referenceable entry in an Oasis if these ever need to be curated centrally.

### 17.3 How `RT` reaches a step — resolved by the parser, numbers in the archive

`temperature: RT` and `hold: RT` both fill `set_point` **and** `set_point_tolerance` from
`RoomTemperature`, in the translator, before the schema sees anything. The archive holds
`set_point: 296.15, set_point_tolerance: 4.0` and no trace of the word.

This is D8a's rule and §13's whole architecture: authoring words never reach the archive, so no
consumer has to resolve one. It also means a file that pins its own figure and a file that writes
`RT` are the same archive, and compare without a lookup.

`NAMED_SETPOINTS` (`channels.py`) therefore stops mapping a word to a bare float and maps it to a
`StandardValue` subclass:

```python
NAMED_VALUES = {
    HoldTemperature: {'RT': RoomTemperature},
    HoldIrradiance:  {'dark': Dark},          # value 0 W/m², no tolerance
}
```

**`dark` moves over too.** It is the same idea — a word standing for a value — and it is
currently a magic `0.0` in a parser dict. As a `StandardValue` it gains a description and a unit
and stops being a special case, and the translator keeps **one** path instead of a float branch
beside a section branch. Separable from the rest of this section if it is not wanted.

**A named word must resolve in a ramp, which today it does not.** `_value` gates the table on
`key == 'setpoint'`, so `ramp: {from: dark, to: 1 sun}` — written out in D8a as a thing that
works — silently does not resolve. The gate becomes `key in ('set_point', 'start_point',
'end_point')`. This is not polish: `ramp: {from: RT, to: 65 °C}` **is** ISOS-T-1 and ISOS-LT-1,
so `RT` is needed at a ramp endpoint on day one. A tolerance has nowhere to go on a ramp
endpoint, and is dropped there with a reported problem rather than silently. *Amended while
building: dropped **without** a problem. Reporting it would make `ramp: {from: RT, to: 65 °C}` —
ISOS-T-1's own spelling, and the reason this paragraph exists — impossible to write cleanly, when
every shipped file must translate with zero problems (§16.4). The value lands exactly; only the
± 4 K has no field, and no standard here states a tolerance on a ramp's end.*

*Also amended while building: `NAMED_VALUES` is keyed by **variable** (`'temperature'`), not by
class, so one entry serves the hold, the ramp and the bound of that variable alike. The
relative-humidity compound reads through the same path, so `{rh: 50 %, at: RT}` works too.*

### 17.4 `set_point` and `set_point_tolerance`

`HoldStep.setpoint` → **`set_point`**, and a new `set_point_tolerance` beside it. The rename is
worth its churn for one reason: `RampStep` already spells its fields `start_point` and
`end_point`, so `setpoint` was the odd one out.

```yaml
temperature: {hold: 65 °C, hold_tolerance: 2 K}
temperature: {hold: RT}                 # both fields, from the standard value
```

- **The tolerance is symmetric** — `value ± tolerance`, one field, because that is how every
  standard states it. An asymmetric window is `HoldBelow` plus `HoldAbove` (§17.5).
- **An explicit `hold_tolerance` overrides the one a named value brought.** Not a contradiction
  to report: a lab whose oven holds tighter than the standard demands is stating a fact about its
  own run.
- **A tolerance is a *difference*, so its unit is a difference unit.** `hold_tolerance: 4 °C`
  reads as 277.15 K through `parse()` — the O11 trap, and silent. The plan is to **refuse an
  offset unit on a tolerance** with a message naming `4 K`, which is a small, targeted check of
  exactly the kind §6 exists for. *Built as `parse_difference` (`units.py`): converting **zero**
  exposes an offset through pint's public API (0 °C → 273.15 K ≠ 0), and any field whose name ends
  in `_tolerance` is read through it. A tolerance on a tracked point, a ramp, a gas or a whole
  channel is reported — there is no single held value for it to belong to.*

**Compatibility is the risk in this section, not the rename itself.** §13.1a promises that no
file which loaded before stops loading, and `setpoint` appears in every bare archive ever written
by this plugin, including `tests/data/channels.archive.yaml`. So the translator gains a bare-field
rename (`setpoint` → `set_point`) for monitor/control steps, tested with a golden archive in the
old spelling. `VALUE_FIELDS`, `_value_field` and `_setpoint` all follow the rename.

### 17.5 `HoldBelow`

```yaml
atmosphere: {variable: water_vapor, hold_below: 55 %}
```

```python
class HoldBelowStep(PlannedMonitorControlStep):
    upper_bound = Quantity(type=np.float64)   # unit declared per subclass
```

A sibling kind of `HoldStep`, not a subclass of it: "keep under 55 %" is not "hold at 55 %", and
reusing `set_point` for both would be one field with two meanings. `upper_bound` rather than
`maximum` leaves `lower_bound` free for the symmetric `HoldAbove`, which is three lines whenever
a standard states one — not built now, because none of these do.

**Only the quantities that need one.** ISOS states a bound for water vapour alone (`< 55 %` in
T-3, `< 50 %` in LC-3), so `HoldBelowWaterVaporFraction` is the whole family at first. The
translator already reports against a partial table — `balance_gas` "does not ramp" (§15.15) —
and the same guard gives "`voltage` has no below-bound form" for free. Adding one later is one
class and one table line, which is cheaper than ten classes nobody writes.

**R4 has to keep grouping by quantity.** `_quantity_of` strips `Hold` then `Ramp`, so
`HoldBelowWaterVaporFraction` would become `BelowWaterVaporFraction` and stop colliding with the
plain hold — two steps commanding one quantity, unreported. The prefixes become data, longest
first:

```python
KIND_PREFIXES = ('HoldBelow', 'Hold', 'Ramp')   # utils.py; HoldAbove joins when it exists
```

Asking for a bound **sets `control`**, as a setpoint and a ramp do (§15.13, §15.14).

*Found while building — a hole the partial table opened.* `{channel: atmosphere, hold_below: 55 %}`
with **no variable named** fell into the "channel logged as a whole" expansion (§15.2), which
yields one step per variable *that has a class in the kind's table*. With water vapour the only
boundable variable, that was exactly one class, so the bound **silently landed on the water
vapour** without the author ever naming it. Ramps escaped only by luck: three atmosphere
variables ramp, so the old `len(classes) != 1` check fired. The check now lives where the kind
is chosen — **a ramp or a bound names one variable, never a channel's worth** — so it no longer
depends on how many classes a table happens to hold, and the two `len(classes)` checks it
replaced were unreachable and are gone. `hold_below` also takes the relative-humidity compound,
read through the water vapour's own hold, since a bound has no `set_point` to read it by.

### 17.6 Order of work, each step reviewable on its own

1. **`standard_values.py` + tests.** Section only, no parser, no rename — verifies the two
   NOMAD assumptions in §17.2 before anything depends on them.
2. **`set_point` rename + `set_point_tolerance`**, with the bare-field compatibility rename and a
   golden archive in the old spelling. The biggest diff and the one with a migration, so it
   travels alone.
3. **`hold_tolerance`, and named values resolving at ramp endpoints.** Includes the offset-unit
   refusal, and fixes `dark` in a ramp along the way.
4. **`RT` end to end** — `NAMED_VALUES`, `RoomTemperature`, and `{channel: temperature, hold: RT}`
   and `ramp: {from: RT}` both landing the value and the tolerance.
5. **`HoldBelowStep` + `HoldBelowWaterVaporFraction` + `hold_below:`**, with the `_quantity_of`
   prefix fix and an R4 test that a hold and a below-bound on one quantity still collide.
6. **The ISOS files that were waiting on this** — T-1/-2 and LT-1 (`RT`), T-3 and LC-3
   (`hold_below`), and `± 4 K` wherever the table states a tolerance.

### 17.7 Decisions for review

- **`StandardValue`, not `standardValue`** — every section in this package is PascalCase, and so
  is every section in NOMAD.
- **Scope of the standard values.** `RoomTemperature` is asked for. `Dark` is proposed (§17.3) to
  remove the float special case. Nothing else: `1 sun` is already a *unit* alias (§6), not a
  named value, and should stay one.
- **What a tolerance means is not checked.** The schema stores `± 4 K`; nothing verifies a run
  stayed inside it, because that is measured data (§4.5). It is a statement of the plan.
- **Still unreachable, and not addressed here:** ISOS-LT-2/3's "controlled at 50 % beyond 40 °C"
  is a bound *conditioned on another quantity* — `HoldBelow` is unconditional. Footnoted in
  `notes`, as §15.9 and §16.2 settled.

---

## 18. One protocol per option — `standard_variant`, and the transcription settled

**Status: settled in review; D, V, L, O and LT built (55 files, after §18.7), T and LC blocked (§18.5).**
*Amended by §20.9: T, LC-1/-2 and LT-1's step option built since — 117 files.*

### 18.1 An option is a protocol

Where ISOS Table 1 offers options — "65, 85 °C", "MPP or OC", six biases — each combination is a
**separate `StabilityProtocol` instance**: a different run is a different protocol, and in NOMAD
a different entry. One file per combination, with the options in the file name, in the table's
column order (light, temperature, humidity, load):

```
isos/ISOS-D-1/ISOS-D-1.stability.yaml                   no options: the designation alone
isos/ISOS-D-2/ISOS-D-2_65degC.stability.yaml
isos/ISOS-L-2/ISOS-L-2_85degC_MPP.stability.yaml
isos/ISOS-V-2/ISOS-V-2_65degC_minus-Jmpp.stability.yaml
```

*Amended in review:* **one folder per standard**, named by its designation, so the variants of a
row sit together instead of 48 files in one directory. The parser matches
`.*\.stability\.ya?ml$` on the whole path, so nesting changes nothing for NOMAD.

`StabilityProtocol.standard_variant` (str, free text) names the option taken — `65 °C, MPP` — and
stays empty where the standard offers none. `standard` stays the bare designation, so every
variant of ISOS-L-2 is still found by searching `ISOS-L-2`. `name` is both together,
`ISOS-L-2 (85 °C, MPP)`, so two entries of one upload are told apart in the ELN.

The merged cells of the workbook decide what an option applies to: **the biases span
ISOS-V-1 to -3** (`G8:G10`), and **the light/dark cycle spans ISOS-LC-1 to -3** (`B24:B26`).

### 18.2 The transcription, row by row

| The table says | The file writes |
|---|---|
| Temperature "Ambient (23 ± 4 °C)" | `temperature: {hold: RT, control: false, monitor: true}` — an assumed value and tolerance, not regulated (*amended by §18.7*) |
| Temperature or humidity "Ambient" | `{control: false, monitor: true}` (*amended by §18.7*) |
| Light "None" | `irradiation: {hold: dark}` |
| Light "Solar simulator" | `irradiation: {control: true}` — regulated, at no stated irradiance |
| Light "Sunlight" | `irradiation: {control: false, monitor: true}`, with `environment: outdoor` (*amended by §18.7*) |
| "65, 85 °C" | one file each, `temperature: {hold: 65 °C}` |
| Humidity "85%", "~ 50%" at a held temperature | `water_vapor: {rh: 85 %, at: 65 °C}` |
| Humidity "Monitored, uncontrolled" | `{monitor: true, control: false}` |
| Humidity "Monitored, controlled at 50% beyond 40 °C" | `{monitor: true}` — the conditional control stays in `notes` (§15.9) |
| Load "OC" / "MPP" | `hold: open_circuit` / `hold: mpp`; at levels 1–2 under light also a fixed voltage near the MPP, `{variable: voltage, control: true}` (*§18.7*) |
| Bias V_MPP, V_oc, −V_oc | `{variable: voltage, control: true}` — no set point, since each is measured on the device. E_g/q is no option (§18.6) |
| Bias J_SC, −J_MPP | `{variable: current, control: true}` |
| "Linear ramping between 5 °C and 65 °C" | `routine` with `ramp: {from: 5 °C, to: 65 °C}`, `end_of_ramp_behavior: triangle` |

The distinction in the first two rows is the table's own: "Ambient (23 ± 4 °C)" states a figure
and a tolerance, bare "Ambient" states none.

**No `geo_location` for ISOS-O.** The standard names no site. **No sign on a bias**: `−V_oc` and
`V_oc` are the same step without a set point, and the sign lives in `notes` and the file name.

### 18.3 `notes` say what the standard says — nothing about the schema

Very short, and only the standard's content: the set-up column, and what a bias is determined
from. How a row became fields is a design decision and lives here, never in an upload:

```yaml
notes: Dark storage in an oven in ambient air.
notes: Dark. Bias at −J_MPP, from a light J–V curve of the fresh device, in ambient air.
```

### 18.4 The tests compare whole archives

`tests/example_uploads/test_isos_protocols.py` holds one expected archive per file, built from
the figures in SI units, and compares it to the **whole** `m_to_dict()` of the loaded,
normalized protocol. Equality of the whole dict is what "every individual field" means: a field
written wrongly fails, and so does a field written that should not be there (a sampling interval,
a duration, a set point on a bias). The set of files and the set of expectations must be equal,
so no file ships untested. `notes` are checked to be present and short, not word for word.

### 18.5 Blocked: two things the current schema cannot say without inventing

*Both built since: A as the repeat condition `until_end_of_protocol` (§20.1), B as `CycleStep`
(§20.2). ISOS-LC-1/-2, ISOS-T and ISOS-LT-1's step option are written; ISOS-LC-3 waits on its
humidity (§20.9).*

**A — a cycle that repeats for as long as the test runs (all of ISOS-LC, 48 files).** The table
states the cycle — period 2, 8 or 24 h, light:dark 1:1 or 1:2 — but not how many cycles or how
long the test runs. A block without a written `estimated_duration` derives one from its steps
(§15.4), so a light/dark block **lasts exactly one period**, and the protocol with it: the file
would claim a 2 h test. `repeat: n_times` needs a `repeat_n` the table does not give. What is
missing is a repeat that is *indefinite* — e.g. `n_times` with `repeat_n` optional, meaning
"until the test ends", with the block's duration then not derived.

**B — a cycle between two temperatures whose shape the table does not state (ISOS-T, 6 files;
the "step ramping" option of ISOS-LT-1, 2 files).** "RT to 65 °C" says the endpoints, not linear
ramps (`triangle`), a jump (`sawtooth`), or dwells at each end — and a dwell needs a duration the
table does not give. ISOS-LT is buildable only because it says **"linear"**. What is missing is a
cycle between two values with the shape left unstated, or a decision that "thermal cycling"
means linear ramps.

Also found: ISOS-T-3's "< 55 %" is a *relative* humidity bound during a temperature cycle, so it
has no single temperature to be converted at — `hold_below: {rh: 55 %, at: …}` has nothing to put
after `at`. It would go into `notes` with the conditional control of LT-2/3.

### 18.6 Every option checked against the text, not the table's punctuation

Asked for in review. Table 1 writes "or" in some cells ("MPP or OC", "Linear or step") and only
commas or semicolons in others ("65, 85 °C", the bias list), which on their own could as well
mean *both*. Each was checked against the consensus statement's text (Khenkin et al., *Nature
Energy* 5, 35–49, 2020, CC BY):

| Option | Verdict | The text |
|---|---|---|
| 65 / 85 °C | option | "controlled elevated temperatures of 65 **or** 85 °C" (D-2); "(65 **or** 85 °C)" (D-3); "a fixed set point temperature of 65 **or** 85 °C" (LC-2) |
| MPP / OC, levels 1–2 | option | "For lower levels of sophistication, we give options of exposure under open-circuit condition or using a fixed voltage bias near the MPP" |
| **OC at ISOS-LT-3** | **no option** — removed | "we indicate MPP tracking as **mandatory** only at the third, most advanced level". The table's "MPP or OC" for LT-3 contradicts it; L-3, O-3 and LC-3 already say MPP alone. |
| V_MPP / V_oc | option | "applying a voltage equal to VMPP **or** VOC … as a positive bias condition" |
| J_SC | option | "constant-current stress … such stability tests might also be useful" |
| **E_g/q** | **no option** — removed | "we recommend voltages **below** the bandgap energy divided by the charge of the electron": an upper limit on the two voltages above, and so written into their `notes` |
| −V_oc / −J_MPP | option, and the sign is the text's | "a constant negative bias applied (for example, −VOC) … and with the current enforced up to **−JMPP**". The table omits the minus on J_MPP; the text has it. |
| 2 / 8 / 24 h; 1:1 / 1:2 (LC) | option, **light:dark** | "cycle periods of 2, 8, **or** 24 h and duty cycles (light:dark) of 1:1 **or** 1:2" |
| Linear / step (LT-1) | option | explicit "or" in the cell |

**Removed: 6 files** (five E_g/q variants and ISOS-LT-3's OC), leaving 48.

Four further findings, recorded and not acted on:

- **A load option the table does not list.** The same sentence offers "a fixed voltage bias near
  the MPP (instead of active MPP tracking)" at levels 1–2. The table writes only "MPP or OC", and
  gives no voltage, so no file is written for it.
- **ISOS-LC-3's humidity disagrees with itself**: the table says "< 50%", the text "RH is held at
  50%". To settle before LC is built.
- **"−VOC" is "for example"** in the text, where the table lists it as the negative voltage. It is
  kept as the table's value.
- **The cycle shape is the author's to report, not the standard's to fix.** The reporting
  checklist (Table 3) asks for "Cycling procedure: Dwell and period times" — confirming §18.5 B:
  ISOS-T states no shape, so a file cannot either.

### 18.7 The files read against the paper's text

**Status: corrected and built.** Read in review against the full consensus statement (Khenkin et
al., *Nature Energy* 5, 35–49, 2020), not only Table 1. Page numbers are the journal's.

| # | Was | Is now | The text |
|---|---|---|---|
| 1 | "Ambient (23 ± 4 °C)" as `hold: RT` — which sets `control: true` | `{hold: RT, control: false, monitor: true}` (D-1, V-1, L-1; LT-1's `RT` ramp end is unchanged) | "ISOS-D-1 tests, where the cell environment is **monitored but not explicitly controlled** (room temperature in the laboratory is **assumed** to be 23±4 °C)" — p.36 |
| 2 | Ambient temperature and humidity `{control: false}` | `{control: false, monitor: true}` (every ambient quantity) | "even if a parameter is not controlled during the ageing experiment (for example, temperature or RH …), it is still important to **monitor and report** the parameters listed in Table 3" — p.43; also p.36 for RH in D-1/D-2, p.39 for LC-1 |
| 3 | Outdoor sunlight `{control: false}` | `{control: false, monitor: true}` (O-1, -2, -3) | Table 3, *Outdoor stability*: "Weather conditions throughout the exposure period — Temperature, humidity, **sunlight irradiance**" — p.40 |
| 4 | Load "MPP or OC" as two files | three: MPP, OC, and a **fixed voltage near the MPP** (L-1, L-2, O-1, O-2, LT-1, LT-2) | "For lower levels of sophistication, we give options of exposure under open-circuit condition **or using a fixed voltage bias near the MPP** (instead of active MPP tracking)" — p.37 |
| 5 | ISOS-O-1, -2, -3 with one shared note | notes state how each measures J–V curves, the one thing that tells them apart | "Under the ISOS-O-1 protocol, periodic measurements of J–V curves are done under illumination by a solar simulator. In ISOS-O-2, … by natural sunlight. ISOS-O-3 requires both in situ MPP tracking under natural sunlight and periodic performance measurements under a solar simulator." — p.37 |
| 6 | D-3 note "Dark storage in an environmental chamber." | "Damp heat, dark storage in an environmental chamber." | "The ISOS-D-3 damp heat test" — p.36 |

The fixed-voltage option is written in the V-family's form: a controlled voltage with no set
point, since "near the MPP" names no number. **Net: +7 files, 55 in all.** The correction of #1
leans on a translator behaviour worth naming: `hold:` sets `control` only by `setdefault`, so an
explicit `control: false` beside it is kept.

Confirmed by the text, and unchanged: 65 **or** 85 °C (pp.36, 39); 85 % RH at those temperatures
(p.37); VMPP **or** VOC as positive bias, measured on a fresh device under AM1.5G one sun, with
voltages **below** E_g/q (p.39); constant-current stress (J_SC, p.39); −VOC "for example" and
"current enforced up to −JMPP" (pp.39–40); MPP tracking mandatory at level 3 (pp.37, 43); the LC
cycle options and their light:dark reading, "12 h light and 12 h dark or 8 h light and 16 h dark"
(p.39); RT as 23 ± 4 °C (p.36).

**Found, not acted on:**

- **Is the light cycled in ISOS-LT?** Table 1 writes "Solar simulator" (where LC writes "Solar
  simulator/Dark"), but Fig. 3 places LT-1, -2 and -3 in the column *Light: cycled*. The files
  follow the table and hold the light as a controlled condition. If Fig. 3 is right, LT's light is
  a cycle with no stated shape — the §18.5 B gap — and LT joins T among the blocked families.
- **The ageing irradiance.** "Ideally, light sources with an irradiance of 800–1000 W m⁻²
  (1 sun = 1000 W m⁻²) should be applied" (p.43). *Ideally* makes it a recommendation, not a
  condition, so no file writes it; §19 item 5 is what would let a file say so.
- **The cycle shape is referred elsewhere.** "temperature cycling varies from simple turning on
  and off a hotplate … to complex temperature and humidity cycles in an environmental chamber.
  Examples of such cycles are available elsewhere¹¹,⁷⁸" (p.38); "The advanced, level 3 protocols
  differ from LC-1,2 and T-1,2 in the temperature cycle and some technicalities that are reported
  elsewhere¹¹" (p.42). ISOS-T needs Reese et al. 2011 (ref. 11) before it can be written.
- **ISOS-LC-3's humidity** is "< 50%" in Table 1 and "RH is held at 50%" on p.39.
- **ISOS-I** (Table 2, p.39): twelve further protocols, "inert atmosphere (nitrogen, argon, and so
  on) … with the other parameters kept the same" (p.42). Not in Table 1, so not in scope so far;
  §19 item 7 is what they need.

---

## 19. Schema shortcomings the paper exposes — implementation list

**Status: proposed, not built.** Each item names the gap, the evidence, a sketch that fits the
schema as it stands, and what it unblocks. Ordered by what it unblocks, then by size.

### 19.1 Unblocks whole families

**1. A repeat that lasts as long as the test does.** *(§18.5 A — ISOS-LC, 48 files)*
A block without a written `estimated_duration` derives it from one pass of its steps, so a
light/dark cycle claims a test one period long. The standard fixes the period, never the count.
- `routine.py`: `repeat: n_times` with `repeat_n` optional — empty means "until the test ends".
  With `repeat_n` empty the block derives `estimated_duration_one_iteration` but **not**
  `estimated_duration`, and neither does anything above it.
- Alternative: a third `repeat` member, `indefinitely`. Clearer to read; one more enum value.
- Tests: an LC-shaped block keeps `estimated_duration` empty through the protocol's normalize.

**2. A cycle between two values whose shape is not stated.** *(§18.5 B — ISOS-T, 6 files; LT-1
step ramping, 2 files; LT's light if Fig. 3 is right)*
- `routine.py`: `end_of_ramp_behavior` gains `unspecified` — the ramp cycles between its ends by
  a path the protocol does not fix — so "RT to 65 °C, cycled" is one step with no invented shape.
- Or a `CycleStep` kind (`low_point`, `high_point`, optional `dwell_low`, `dwell_high`,
  `period`), which is also what Table 3's "Dwell and period times" reports.
- Needs Reese et al. 2011 read first: if it does fix shapes for T-1…T-3, only the per-file
  values are missing, not a schema feature.

**3. Conditional control.** *(LT-2, LT-3: "controlled at 50% beyond 40 °C"; T-3 footnote b)*
- A `control_condition` sub-section on a step: `quantity` (a step class name), `above` and/or
  `below`, in that quantity's unit. Stored, not evaluated — the schema says *when* control
  applies; a timeline or simulator evaluates it (§15.1 keeps the physics out).
- Translator word: `control_when: {temperature: {above: 40 °C}}`.

**4. Relative humidity during a temperature cycle.** *(T-3 "< 55%", LT-2/-3 "50%")*
The compound `{rh, at}` needs one temperature; a cycling chamber has none, so no absolute ratio
exists to store.
- A `HoldRelativeHumidity` / `HoldBelowRelativeHumidity` pair storing RH itself, used **only**
  where the temperature is not constant. This reopens §15.7 for exactly the case §15.7 could
  not foresee, and leaves the absolute ratio the default everywhere else.

### 19.2 Lets a file say what the standard says

**5. Required versus recommended.** *("Ideally … 800–1000 W m⁻²", p.43; "we recommend voltages
below E_g/q", p.39; "we stress that monitoring … is of critical importance", p.36)*
Today a file can only assert a condition or stay silent, so a recommendation is lost.
- A `requirement` MEnum (`required`, `recommended`) on `PlannedMonitorControlStep`, default
  `required`. The 800–1000 W m⁻² band becomes `{hold: 900 W/m^2, hold_tolerance: 100 W/m^2,
  requirement: recommended}` — which also exercises the symmetric tolerance of §17.4.

**6. A value taken from the device.** *(V_MPP, V_oc, J_SC, J_MPP, E_g/q; "fixed voltage near the
MPP"; footnote a of Table 1)*
Every bias file stores a controlled voltage or current with no set point, and the *which* lives
only in `notes` and the file name — unsearchable.
- `set_point_reference` MEnum on `HoldVoltage` / `HoldCurrent`: `V_MPP`, `V_oc`, `E_g/q`,
  `J_SC`, `J_MPP`; plus `set_point_sign` (+1 / −1) and `near` (bool, for "near the MPP").
- The E_g/q ceiling as `HoldBelowVoltage` with `upper_bound_reference: E_g/q` and
  `requirement: recommended` (item 5).
- The reference is resolved against the fresh device's J–V curve in the measurement layer
  (§4.5), never in the protocol.

**7. An inert atmosphere.** *(ISOS-I, Table 2 — 12 protocols; "in the absence of humidity" for
LC-3I, T-3I, p.42)*
- `BalanceGas.gas` stays free text, and a `StandardValue` `InertAtmosphere` (§17.2) gives the
  word `inert` a published definition: no oxygen and no water vapour stated as a fraction, gas
  "nitrogen, argon, and so on". Translator word: `atmosphere: {balance_gas: inert}`.
- Then ISOS-I is the same generator with the atmosphere swapped and `standard: ISOS-D-1I`, … .

**8. Structured options.** *(§18.1)*
`standard_variant` is free text, so "every ISOS-L-2 run at 85 °C" is a substring search.
- A repeating `StandardOption` sub-section (`name`, `value`: `temperature` / `65 °C`), kept
  beside `standard_variant`, which stays as the human label.

### 19.3 Checks the standard implies

**9. The level-3 rule.** "MPP tracking as mandatory only at the third, most advanced level" (p.37).
- `standard_level` (int, 1–3), or derived from the designation's last digit for ISOS names. A
  `normalize()` check: at level 3 under light, a load other than `MPPTracking` is reported.
  This is the rule that removed LT-3's OC, made executable.

**10. What the standard obliges a run to report.** Table 3 lists items that are *required to be
reported* but not fixed by the protocol: location and dates for ISOS-O, MPPT hardware and
algorithm, dwell and period times, number of samples, encapsulation.
- Belongs to the measurement layer (§4.5): a `StabilityMeasurement` referencing its
  `StabilityProtocol`, whose normalize reports what the protocol's `standard` requires and the
  measurement lacks. `geo_location` (§15.12) is the first such field already in place.

**11. Stop conditions.** "we suggest ageing the sample for at least 1000 h and using the PCE after
1000 h" when T80 is not reached (p.44); T80 as "an optimal minimum ageing test time".
- The `stop_when` of D15 / §4.2.1 (`conditions.py`), still unbuilt: `T80 or 1000 h`. A
  recommendation, so it pairs with item 5.

**12. Periodic characterization as a step.** ISOS-O-1 and -O-2 differ only in the light the J–V
curves are measured under (p.37), which the schema cannot hold, so the difference lives in
`notes` (§18.7 #5).
- The J–V sweep `mpp_steps.py` was reserved for (D17): a `JVMeasurement` step with its light
  source and repeat interval, where the standard fixes the light source and leaves the interval
  to the author.

### 19.4 Order

1 and 2 first — they unblock 56 files and are small. Then 6 and 5, which change what the 25
ISOS-V files and every "ideally" can say. 7 opens ISOS-I. 3 and 4 finish LT-2/-3 and T-3. 9 is a
one-rule check once `standard_level` exists. 8, 10, 11, 12 wait for the measurement layer.

---

## 20. §19 settled — what is built

**Status: settled in review, built.** The decisions on §19's list, item by item, as they were
answered. §19's numbering is kept.

### 20.1 A repeat until the protocol ends (§19 #1)

**A repeat condition, not an optional `repeat_n`.** `PlannedSubroutineStep.repeat` gains a third
member, **`until_end_of_protocol`**: the block runs its steps again and again for as long as the
protocol runs. It derives `estimated_duration_one_iteration` from its steps, checks R4–R6 against
that one iteration (as `n_times` does, §15.8), and **never derives its own
`estimated_duration`** — so nothing above it derives one either, and an ISOS-LC file no longer
claims a test one cycle long. A written `repeat_n` or `estimated_duration` has no effect there and
is reported as a warning (dead configuration), never repaired.

### 20.2 A cycle whose path is not stated (§19 #2)

*Superseded in review by §21.2: a ramp that repeats is a cycle too, so the cycle is a
behaviour of `RampStep`, not its parent. Kept as the record of what was built first.*

**`CycleStep`, the parent of `RampStep`**, used directly where the path is open:

```
PlannedMonitorControlStep
├── HoldStep            set_point …
├── HoldBelowStep       upper_bound …
└── CycleStep           start_point, end_point      the path between them not stated
    └── RampStep        + ramp_rate, end_of_ramp_behavior   the path is linear
```

`start_point` / `end_point` move up from `RampStep`, and so does the "missing an end" report.
`CycleTemperature` (`cycle_steps.py`) is the concrete class — only temperature, because only
temperature is cycled without a stated path (ISOS-T, the step option of ISOS-LT-1), the rule
§17.5 set for `HoldBelow`. Authored as `cycle: {from: RT, to: 65 °C}`; `rate` is no part of a
cycle. R4 strips `Cycle` too, so a cycle and a hold of one temperature still collide.

### 20.3 A point on the device's own characteristic (§19 #3)

**`reference_point` on `PlannedMonitorControlStep`**, a free string there and narrowed to an
`MEnum` by the children that have one. **Verified:** a child may redeclare a base `str` quantity as
an `MEnum`; a value outside it is refused, and it round-trips.

| Class | `reference_point` |
|---|---|
| `HoldVoltage` | `V_MPP`, `near V_MPP`, `V_oc`, `-V_oc` |
| `HoldCurrent` | `J_SC`, `-J_MPP` |

The sign is part of the value, so one field is searchable on its own. The reference is resolved
against a measured J–V curve in the measurement layer (§4.5), never in the protocol. E_g/q is not
a member: the standard recommends voltages *below* it, which no bias step can hold beside its
own reference without a second step on the same quantity (R4). It stays in `notes`.

### 20.4 Required and recommended, side by side (§19 #5)

*Superseded in review by §21.1: a misreading. No `recommended_*` field exists; a protocol
with the recommendation and one without are two variants. Kept as the record.*

**Read in review as: both values on one step**, because a recommendation is usually *stricter*
than the requirement it sits beside, so a step needs to carry both at once. Two parallel classes
would put two steps on one quantity, which R4 reports.

| Kind | Required | Recommended |
|---|---|---|
| `HoldStep` | `set_point`, `set_point_tolerance` | `recommended_set_point`, `recommended_set_point_tolerance` |
| `HoldBelowStep` | `upper_bound` | `recommended_upper_bound` |

Each concrete class declares the recommended pair in its own unit, exactly as the required pair.
Authored as `recommended_hold`, `recommended_hold_tolerance`, `recommended_hold_below`, read like
their required twins (named values such as `RT` included; a tolerance is a difference, §17.4).
A recommendation **does not set `control`** — only a requirement asserts regulation. Ramps and
cycles have none yet: nothing the standard says is a recommended ramp.

### 20.5 An inert atmosphere (§19 #7)

**Stated by thresholds and the gas, not by a word.** An inert atmosphere is oxygen and water each
kept below a ppm threshold, in a named balance gas:

```yaml
atmosphere: {variable: oxygen, hold_below: 1 ppm}
atmosphere: {variable: absolute_humidity, hold_below: 1 ppm}
atmosphere: {balance_gas: N2}
```

This needs one class more, `HoldBelowOxygenFraction`. **ISOS-I is not written yet:** the paper
names the gas ("nitrogen, argon, and so on") but no threshold, so there is no number to write —
recorded as an open question in `example_uploads/isos/OPEN_QUESTIONS.md`.

### 20.6 Relative and absolute humidity, as two variables (§19 #4)

**Relative humidity becomes a variable of its own, semantically distinct, with no temperature
required.** This reopens §15.7 on purpose: the standard states humidity as RH throughout, including
where the temperature cycles (T-3, LT-2/-3) and no single temperature exists to convert it at.

| Before | After |
|---|---|
| `HoldWaterVaporFraction`, `RampWaterVaporFraction`, `HoldBelowWaterVaporFraction` | `HoldAbsoluteHumidity`, `RampAbsoluteHumidity`, `HoldBelowAbsoluteHumidity` |
| — | `HoldRelativeHumidity`, `RampRelativeHumidity`, `HoldBelowRelativeHumidity` |
| key `water_vapor` | `absolute_humidity` — `water_vapor` still read as its old spelling |

**"Absolute" here keeps §15.7's meaning: a volume ratio (`500 ppm`, `2 %`), not g/m³** — the
glovebox sense of the word, said so in every description. Relative humidity is the fraction
itself (`85 %` → 0.85) and also reads `85 %RH`. The two never convert into each other in the
schema. `{rh: 85 %, at: 65 °C}` (§15.16) stays, as a way of writing an *absolute* humidity.

**Compatibility (§13.1a):** bare archives name `HoldWaterVaporFraction` and friends in their
`m_def`; the translator maps the three old class names to the renamed classes, as it maps §13's
channel classes (`OLD_CLASSES`, `channels.py`).

### 20.7 The level-3 rule (§19 #9)

"MPP tracking as mandatory only at the third, most advanced level of ISOS protocols" (p.37).
`StabilityProtocol.standard_level` (int, 1–3) is derived from an ISOS designation when left
empty (`ISOS-L-3` → 3, `ISOS-LC-3I` → 3). At level 3, a protocol under light — any irradiance
step that is not a hold at zero — whose electrical load is anything but `MPPTracking` is reported,
never repaired. Dark level-3 protocols (D-3, V-3, T-3) are untouched.

### 20.8 Later (§19 #8)

**Deferred in review, to be worked on later:** structured options (`StandardOption`, name and
value, beside the free-text `standard_variant`), the reporting obligations of Table 3 (location,
MPPT hardware, dwell times, number of samples), stop conditions ("at least 1000 h"), and periodic
J–V characterization as a step. All four belong with the measurement layer (§4.5).

**Also still open:** conditional control ("controlled at 50 % beyond 40 °C", §19 #3) was not
decided; those clauses stay in `notes`.

### 20.9 The files, after §20

*Amended by §21: the recommended irradiance is now a variant of its own (192 files), and every
`cycle:` a ramp with `end_of_ramp_behavior: cycle`.*

**Status: built.** 117 files, each equal as a whole to its expected archive
(`tests/example_uploads/test_isos_protocols.py`), 605 tests in all.

| What changed | Files |
|---|---|
| Humidity stated as **relative humidity**, as the paper does, with no temperature beside it (D-3, V-3 at 85 %; L-3 at 50 %; every ambient humidity) | all with a humidity |
| Every bias names its `reference_point` (`V_MPP`, `V_oc`, `J_SC`, `-V_oc`, `-J_MPP`); the fixed voltage option is `near V_MPP` | ISOS-V; the `Vfixed` variants |
| The solar simulator carries the **recommended** 800–1000 W m⁻² as `recommended_hold: 900 W/m^2 ± 100` (p.43) | ISOS-L, -LC, -LT |
| **ISOS-T** written: the temperature a `cycle:` from RT to 65 / 85 °C, or −40 to 85 °C; T-3's humidity monitored, its condition in `notes` | +5 |
| **ISOS-LT-1 step ramping** written as a `cycle:`, beside the linear `ramp:` | +3 |
| **ISOS-LC-1, -2** written: settings for what is constant, a `routine` that `repeat`s `until_end_of_protocol` with a light and a dark step of the stated lengths | +54 |
| `standard_level` derived in every file, and the level-3 MPP rule passing for L-3, O-3, LT-3 | all |

**Not written: ISOS-LC-3** (Table 1 "< 50%" against p.39 "held at 50%") **and ISOS-I** (no ppm
threshold for an inert atmosphere). Every question the standard leaves open, and what the files do
meanwhile, is in `example_uploads/isos/OPEN_QUESTIONS.md` — a document for the reader of the
standard, where this section is for the reader of the schema.

---

## 21. Review of §20 — recommendations as variants, the cycle as a ramp

**Status: settled in review, built.** Two of §20's decisions were read wrongly and are replaced.

### 21.1 A recommendation is a variant, not a field (replaces §20.4)

**No `recommended_set_point`, `recommended_set_point_tolerance` or `recommended_upper_bound`.**
The schema describes one protocol, and a protocol either holds a value or does not. Where the
standard recommends something it does not require, **the standard has two protocols**: one
without the recommendation, one with it written as an ordinary requirement. They are separate
files, as every other option is (§18.1), and the recommendation's value is in the file name.

| | Without | With the recommendation |
|---|---|---|
| Solar simulator (ISOS-L, -LC, -LT; "Ideally … 800–1000 W m⁻²", p.43) | `irradiation: {control: true}` | `irradiation: {hold: 900 W/m^2, hold_tolerance: 100 W/m^2}` |
| File name | `ISOS-L-1_MPP` | `ISOS-L-1_MPP_800-1000Wm2` |
| `standard_variant` | `MPP` | `MPP, recommended 800–1000 W/m²` |

The token comes last, after the standard's own options. Every solar-simulator file therefore has
a twin: ISOS-L 11 → 22, ISOS-LC 54 → 108, ISOS-LT 10 → 20, **117 → 192 files**.

"Voltages below E_g/q" (p.39) is a recommendation too, but has no number a protocol can hold
beside its own bias (§20.3). It stays in `notes` and gets no variant.

The authoring words `recommended_hold`, `recommended_hold_tolerance`, `recommended_hold_below`
go with the fields. Nothing stored ever used them outside this package's uncommitted work, so no
compatibility mapping is kept.

### 21.2 A cycle is a ramp that repeats (replaces §20.2)

§20.2 made `CycleStep` the parent of `RampStep`, reading "cycle" as "two ends, no path". But a ramp
that runs back and forth continuously — `triangle`, `sawtooth` — *is* a cycle, and a ramp that runs
once is not, so the parent was named after what only some of its children do. **Whether a ramp
cycles is its `end_of_ramp_behavior`**, and the cycle without a stated path is one more member:

```
PlannedMonitorControlStep
├── HoldStep            set_point, set_point_tolerance
├── HoldBelowStep       upper_bound
└── RampStep            start_point, end_point, ramp_rate, end_of_ramp_behavior
```

| `end_of_ramp_behavior` | Cycles | Path | `ramp_rate` |
|---|---|---|---|
| `hold` (default) | no — runs once, then holds `end_point` | linear | read |
| `sawtooth` | yes — jumps back to `start_point` | linear | read |
| `triangle` | yes — ramps back at the same rate | linear | read |
| **`cycle`** | yes — returns to `start_point` | **not stated** | **reported if written** |

A `cycle` writes no rate: a rate along a path the protocol does not state says something the
protocol does not, so it is an error (D13a), and no `estimated_duration` is derived from one.

- **Removed:** `CycleStep`, `CycleTemperature`, `cycle_steps.py`, the `Cycle` kind prefix of R4,
  and the authoring word `cycle:` with its translator table.
- **Authored as** `ramp: {from: RT, to: 65 °C}` with `end_of_ramp_behavior: cycle`, on
  `RampTemperature` — the class ISOS-LT's linear ramps already use, so a thermal cycle and a
  thermal ramp are one kind on one quantity, and R4 needs no special case.
- Every quantity with a ramp class can now cycle by an unstated path. No class is added for it.

| Files | Before | After |
|---|---|---|
| ISOS-T-1, -2, -3; ISOS-LT-1 step ramping | `cycle: {from, to}` | `ramp: {from, to}`, `end_of_ramp_behavior: cycle` |
| ISOS-LT-1 linear, -2, -3 | `ramp:`, `triangle` | unchanged |

**Status after §21: built.** 192 files, 798 tests, ruff clean.

---

## 22. A range is a kind of its own — `hold_between`

**Status: settled in review, built.** Replaces how §21.1 *writes* the recommended irradiance; the
variants themselves stay.

### 22.1 Why

§21.1 wrote "800–1000 W m⁻²" as `hold: 900 W/m^2` with `hold_tolerance: 100 W/m^2`. The two
describe the same interval, but not the same instruction: a hold names a target to regulate *to*,
and a tolerance how far from it still counts. The standard names no target — any irradiance in the
range will do. Writing 900 invents a set point the standard never states (§16.2, Rule 1).

### 22.2 The kind

```
PlannedMonitorControlStep
├── HoldStep            set_point, set_point_tolerance
├── HoldBelowStep       upper_bound
│   └── HoldBetweenStep + lower_bound
└── RampStep            start_point, end_point, ramp_rate, end_of_ramp_behavior
```

**A subclass of `HoldBelowStep`**: a value kept between two bounds *is* kept below the upper one,
so everything true of a bound stays true of a range, and `upper_bound` keeps one meaning. It adds
`lower_bound`. `normalize` reports, never repairs (D13a), a range missing either bound or whose
`lower_bound` exceeds its `upper_bound`.

- **One class, `HoldBetweenIrradiance`**, in `hold_below_steps.py` beside the other bounded
  steps — only what a standard states a range for has a class (§17.5).
- **R4:** `HoldBetween` is stripped before `HoldBelow` and `Hold`, so a range and a hold of the
  irradiance still collide.
- **The level-3 rule (§20.7)** counts a range as light unless its `upper_bound` is zero.

### 22.3 Authoring

```yaml
irradiation:
  hold_between: {lower: 800 W/m^2, upper: 1000 W/m^2}
```

Both keys are required, and read like any value (named values such as `dark` included). Like
`hold_below:`, it sets `control: true` unless written otherwise, and cannot be combined with
`hold`, `hold_tolerance`, `hold_below`, `ramp` or a variable key.

### 22.4 The files

The 75 `800-1000Wm2` variants write `hold_between: {lower: 800 W/m^2, upper: 1000 W/m^2}`, stored
as `HoldBetweenIrradiance` with `lower_bound` 800 and `upper_bound` 1000. Names, tokens and
counts (192 files) are unchanged.

**Status: built.** 192 files, 812 tests, ruff clean.

## 23. Plans and instructions — the protocol is no activity

Replaces §15.4's fitting, §15.5, §15.6 and §15.8. A protocol is a **plan**: it says what is to be
done, and never claims that anything ran. `Plan.execute()` is where a plan becomes a NOMAD
`Activity`; this plugin never calls it, as it has no concrete measurements yet. "Step" is kept
for what an activity records (`ActivityStep`) and nowhere else: everything a plan holds is an
**instruction**.

### 23.1 `general.py` — no PV concept

```
Instruction                     name, description, estimated_duration, sub_instructions
├── SingleInstruction           no sub-instructions
│   └── MonitorControlInstruction (base_instructions.py) → Hold…, HoldBelow…, HoldBetween…, Ramp…, MPP/VOC
└── InstructionBlock            sub_instruction_execution_mode — runs once
    ├── CountingRepeatingBlock  repeat_n
    └── TimedRepeatingBlock     repeat_duration
Plan (EntryData)                name, description, estimated_duration, instructions, execute()
└── ScheduledPlan               scheduled_datetime, scheduled_end_time
    StabilityProtocol (protocol.py) is a Plan
```

- **An instruction is completed after its `estimated_duration`. Empty means it never finishes.**
  There is no "condition lasting as long as its block" any more: a setting without a duration
  simply never ends. *(Superseded by §32: in a parallel block, it does last as long as its
  block. Superseded by §33: an empty duration no longer carries a meaning; a `Duration`
  section says what kind of duration it is.)*
- **Instructions are consistent on their own.** A block's `estimated_duration` is always derived,
  never authored. `InstructionBlock`, the parent of both repeating blocks, runs its
  sub-instructions once (`sequential` sum, `parallel` maximum); a `CountingRepeatingBlock` lasts
  that times `repeat_n`. Empty if it repeats indefinitely or anything inside never finishes —
  which passes up to every parent and to the plan.
- **`repeat_n` has no default; empty means indefinitely.** A default would come back on every
  read, since NOMAD stores no empty value (verified), and an indefinite block would load as one
  pass.
- **`TimedRepeatingBlock`** repeats its sub-instructions until `repeat_duration`, then stops
  them wherever they are; that is its `estimated_duration`. Each repeating block has only its own
  way of ending: no `repeat_n` on the timed one, no `repeat_duration` on the counting one.
- **Only a plan stops instructions early.** A written `Plan.estimated_duration` is where every
  instruction still running is stopped; left empty it is derived, and empty if one never ends.
  `ScheduledPlan.scheduled_end_time` is empty then too.
- **`execute()` takes everything the activity is as keyword arguments** — never the plan's own
  `name` or `description` — and a subclass overrides it to turn instructions into steps.

### 23.2 The protocol runs all its instructions in parallel

`StabilityProtocol.instruction_execution_mode = 'parallel'`: the settings, which never finish,
and the routine start together, so the routine is not left waiting behind them. With settings in
every file, a protocol claims no length unless it writes `duration`. *(Since §32: or its routine
finishes.)*

**No cross-instruction checks.** R4 (two instructions on one quantity at once), R5 (an
instruction that never runs) and the level-3 MPP rule are dropped, with `utils.py`. They
recovered from class names what the structure does not say, which is a modelling gap, not a
check to keep. A contradiction or a dead instruction now loads silently; if it matters, a
higher specialization can rule it out structurally — e.g. one non-repeating slot per quantity in
a parallel block, which would also close the MPP/open-circuit gap. What stays is what one section
can check of itself: both ends of a ramp, the order of two bounds, a positive duration, a block
with contents, `repeat_n` ≥ 1, a latitude within ±90°.

**Tests encode the specification, not the implementation**: one test per rule a reader of the
schema or of `.stability.yaml` relies on, tables as parametrized cases, messages matched by their
telling fragment only. The ISOS table (§16, §18) stays whole.

### 23.3 Authoring

```yaml
duration: 1000 h            # on the protocol only: where everything stops
routine:
  repeat: indefinitely      # a CountingRepeatingBlock; or `repeat: 5`; left out, indefinitely too
  mode: parallel            # optional, `sequential` otherwise
  commands: [...]
routine:
  repeat_for: 12 h          # a TimedRepeatingBlock
  commands: [...]
```

`commands` becomes `instructions` on a protocol and `sub_instructions` on a block; `mode` becomes
`sub_instruction_execution_mode`, `repeat_for` becomes `repeat_duration`. The former words are
reported with what to write instead: `until_end_of_protocol` (`repeat: indefinitely`),
`until_end_of_duration` (`repeat_for`), `n_times` (the number). `duration` on a block is
reported: its length follows from its commands. A block without `m_def` is a
`CountingRepeatingBlock`, or a `TimedRepeatingBlock` with `repeat_for`; a plain `InstructionBlock`
is only reached by naming it, and takes no `repeat`.

### 23.4 Renamed, and not kept readable

`PlannedProcess` → `Plan`; `PlannedProcessStep` → `Instruction`; `PlannedSubroutineStep` deleted
for `InstructionBlock` and its two repeating children; `PlannedMonitorControlStep`, `HoldStep`, `HoldBelowStep`,
`HoldBetweenStep`, `RampStep` → `…Instruction`; `hold_steps.py`, `hold_below_steps.py`,
`ramp_steps.py`, `mpp_steps.py` → `…_instructions.py`; `steps` → `instructions` /
`sub_instructions`. `was_executed` and the `estimated_*` plan/record fields are gone with
`PlannedProcess`; `location` is the protocol's own quantity now. No alias maps the old class
paths — nothing was published in them. The 109 ISOS files write `repeat: indefinitely`.

**Status: built.** 192 files, 52 tests (320 cases, 192 of them the ISOS table), ruff clean.

## 24. Options — one file, every variant

The ISOS table offers options (two temperatures, three loads, five biases, six light–dark cycles,
the recommended irradiance range), and §18/§21.1 wrote every combination as a file of its own:
192 files in 20 folders, most differing in one or two lines. A reviewer had to diff files to see
what a variant is. Now each option is written once, where it differs, and the parser expands
them.

### 24.1 The notation

```yaml
electrical_load:
  control: true
  options:                     # in any section: its alternatives
    - label: V_MPP             # optional; a single value is its own label, none otherwise
      variable: voltage        # the keys written into the section for this alternative
      reference_point: V_MPP
    - {label: J_SC, variable: current, reference_point: J_SC}
```

- One rule: an alternative's keys are written into the section that lists the `options`. A key is
  written beside the options or in an alternative, never both (reported). Nothing is merged
  deeper than that.
- Every combination of one alternative per `options` is a variant. An alternative may list
  `options` of its own, which multiply only with it (the light–dark cycle holds the irradiance
  range inside its light command).
- `{}` is an alternative that adds nothing, and no label.
- A variant's `name` gets its labels in parentheses, in the order the file writes them; they are
  its `standard_variant` unless the file writes one. Two variants of one name are reported.
- No references and no arithmetic. What repeats is repeated with plain YAML anchors
  (`&light`, `<<: *light`), which `yaml.safe_load` resolves before the parser sees the file.
- A coupled value that lives in another section cannot vary with an alternative. The notes that
  named each bias (and "Fixed voltage bias near the MPP.") became one note per file; the label
  says which bias.

`parsers/options.py` does only this, on plain dicts, before the translator, which never sees
`options`.

### 24.2 In NOMAD

The parser has `creates_children = True`. `is_mainfile` returns the variants' names for a file
with options, so NOMAD makes one child entry per variant (`mainfile_key` and `entry_name` are the
name); the file's own entry keeps no protocol and carries the problems of `options`. A file
without options is one entry, as before.

### 24.3 The files

`example_uploads/isos/` holds 20 files, `ISOS-<designation>.stability.yaml`, and no folders. They
expand to the same 192 protocols, which the ISOS table test checks field by field; it keys its
expectations by name.

**Status: built.** 20 ISOS files (192 variants), 58 tests (328 cases), ruff clean.

## 25. `commands` → `instructions` in the authored format

The authored word for a protocol's or a block's list is `instructions`, the schema's own word
(§23). On a block it becomes `sub_instructions`, on the protocol `instructions`. `commands` is
reported (`write instructions`) and still read, so one old word does not drop a routine. This
replaces `commands` in §23.3 and in every example above. The ISOS files, `tests/data` and the
ISOS README write `instructions`.

## 26. Monitoring is written where the standard requires it

`control` and `monitor` stay independent: Khenkin et al. name them separately ("monitored, controlled
at 50% beyond 40 °C", Table 1; "RH (controlled or monitored)", Table 3), so neither is derived
from the other. The ISOS files write `monitor: true` wherever the paper requires a reading:

- uncontrolled ambient conditions (p.36, p.43) — as before;
- a held or ramped temperature — Table 3 asks for the temperature sensor type;
- a solar simulator and the light phase of a light–dark cycle — "the exact irradiance … should be
  reported" (p.43), checked periodically with a reference cell (p.44);
- a controlled relative humidity — Table 3's parameters are monitored "even if … not controlled"
  (p.43), so controlled ones are too;
- MPP tracking — it "holds the device at its normal operating voltage and measures the output"
  (p.43).

Not monitored: darkness, open circuit and fixed biases, which Table 3 lists only as conditions.
ISOS-V's in situ dark current is "informative" (p.40), not required, and is not written. The ISOS
table test expects each of these.

## 27. Repeating blocks say whether they finish

§23 made an empty `repeat_n` mean "indefinitely" on a `CountingRepeatingBlock` — a counting block
that does not count. The kind now says it:

```
InstructionBlock                  runs once
└── RepeatingBlock                may or may not finish; on its own, not known to (no duration)
    ├── TimedRepeatingBlock       always finishes: after `repeat_duration` (missing: error)
    ├── IndefiniteRepeatingBlock  never finishes: no duration, ever
    └── CountingRepeatingBlock    should finish: `repeat_n` × one iteration
```

A counting block that does not finish after all — no `repeat_n`, or a sub-instruction that never
finishes — is a **warning**, not an error, and its duration is empty. `repeat_n < 1` stays an
error.

Authoring: `repeat: 5` is a counting block, `repeat_for: 12 h` a timed one, and `repeat:
indefinitely` — or no `repeat` at all — an indefinite one. With an `m_def`, a count on an
indefinite block and `indefinitely` on a counting block are reported. The ISOS routines are
`IndefiniteRepeatingBlock`s; `tests/data/tree.archive.yaml` follows.

## 28. Instructions are listed by what they do

NOMAD's GUIs list a repeating sub-section's items by the section's `label_quantity`, else by a
`label`, `name`, `type` or `id` quantity (GUI v2; the legacy GUI skips `label`), else by index. No
GUI draws a sub-section tree; items are navigated one level at a time.

`Instruction` has a derived `label`, and `Section(label_quantity='label')`: its `name` where one is
written, else `describe()` — `Hold temperature 65 °C`, `Monitor relative humidity`,
`Hold irradiance 0 W/m² for 80 min`, `Ramp temperature 23 °C → 65 °C (cycle)`, `MPP tracking`,
`Repeat indefinitely (2 instructions)`. Values are shown in °C, %, and the largest of h/min/s that
counts a time whole.

A label reads only what is written, never what `normalize` derives (a ramp's duration), so a second
normalize gives the same label. The ISOS table ignores labels; `test_general` and
`test_instructions` pin them.

`IndefiniteRepeatingBlock` is now an alias of `RepeatingBlock` (edited in `general.py`): the
translator writes `m_def: …general.RepeatingBlock` for an indefinite block, compares the class
exactly when a count is written, and `tests/data/tree.archive.yaml` follows.

## 29. The protocol draws its timeline

A `StabilityProtocol` shows a reader of the standard what it asks for over time. It is a picture
of the plan, not a simulated run: no start date, no device, no environment. Simulating a run, or
reading measured data, is a separate design, started once there is real data.

**Where.** Each instruction draws itself: `Instruction.time_series_for_plotting(start, stop)` returns a
`TimePlotSeries` — plain data, no Plotly: times, values or text per quantity, and the axis breaks.
A single instruction gives its own points, from `set_values_for_plotting(length)` — the corners, `None` where the
protocol states no value — or `annotation_for_plotting()` for the text instead (`MonitorControlInstruction`,
`base_instructions.py`). A block combines its sub-instructions' series one after another or side by side,
up to 3 iterations, and adds its break. `plan_timeline.py` only turns the series into Plotly
figures; `StabilityProtocol` becomes a `PlotSection` and adds them in `normalize`. No parser
change, no new entry.

**What.** One row per quantity, on one time axis in hours since the start:

| Instruction | Drawn as |
|---|---|
| Hold with `set_point` (dark: 0 W/m²) | line at the value |
| Ramp with a stated path (`hold`, `sawtooth`, `triangle`) | line through its corners, exact |
| `HoldBetween` / `HoldBelow` (from 0) | translucent band, two sharp edges, bounds as text |
| Ramp whose path (`cycle`) or pace (no rate, no duration) is not stated | band between its ends: `…, rate not stated` |
| Reference point, MPP, open circuit | bar with text: `MPP`, `near V_MPP` |
| Monitor only | thin bar: `monitored` |
| Option left open (light, no value) | bar: `irradiance not specified` |

**Time stays accurate.** A repeating block is drawn for at most 3 iterations, then the axis breaks
(`//`) to the block's end, labelled below: `n=300 repetitions`, `until t+300 h`, or `indefinitely`.
An instruction that never finishes runs to the right edge; where the whole plan never ends, the
axis closes with `…`. Every tick shows true time; a break is made of axis segments side by side,
never of dates.

**Figures.** An overview (open), and one per repeating block whose iteration ends, showing a single
iteration (`one_iteration_for_plotting`). Plotting-only methods end in `_for_plotting`.

*Amended:* the protocol shows **only its timeline**. The one-iteration figure belongs to the
block: `RepeatingBlock` is a `PlotSection` and sets it in its own `normalize`
(`figures_for_plotting`), so it appears where a reader opens that instruction, not beside the
timeline. Verified to be the same figure as before for all 120 shipped variants. A block whose
pass never ends has none.

*Amended:* **the timeline tells everything, on hover.** Time stays true, so a short step in a long
protocol is too narrow for its text, which is then left out. Every piece now also lies under an
all-but-transparent area as high as its row (`HOVER_FILL`, `hoveron: 'fills'`) that shows, where
hovered, the piece's full `label`, when it starts and how long it runs (`from 1000 h for 1 min`:
start and length, not start and end, which rounding at 1000 h would make equal), and the red
notes. Nothing changes to the eye. The areas are placed after each row is drawn, once its range is
known (`_Drawing.hover_areas`). *Not verified in a browser* here; Plotly finds a fill only where
one is drawn, hence the 1 % opacity rather than none.

**Colour** says what the protocol states (`role_for_plotting`), in the words of the ISOS consensus
(Khenkin et al. 2020): `controlled` to a value, bounds, path or named point ("controlled elevated
temperatures of 65 or 85 °C", MPP tracking, a V_MPP bias); `specified` but not controlled ("Ambient
(23 ± 4 °C)", open circuit — "disconnected" —, dark — light source "None"); only `monitored`
("monitored but not explicitly controlled"); or `unspecified`: regulated to what is not stated. A
protocol that never ends carries its time axis, and what never ends, a little past the drawing, to `⋯`. An axis whose values
cannot be negative starts at 0. A `set_point_tolerance` is a translucent area around the value's
line. The time axis is a black line below the rows; the row labels stand at one place on the left;
the text in a row is as large as its narrowest bar allows (`text_size`); text too long for its bar
at any size is left out — the colour stays, and the block's own figure has the room. Break labels
stand above the axis, the ticks below it; a narrow axis section gets few ticks.

**Tests.** A hold is drawn at its value for its duration; a device-dependent instruction is text,
not a value; a block of 300 repetitions draws 3 and a break labelled `n=300 repetitions`; all ISOS
examples normalize within a time budget.

**Steps.** 1 `set_values_for_plotting`/`annotation` on single instructions · 1b `TimePlotSeries` ·
2 `time_series_for_plotting` on blocks (repeats, breaks) · 3 overview figure · 4 block figures ·
5 all-ISOS check.

## 30. A solar simulator is held between 800 and 1000 W/m²

Reverses the twin variants of §21.1 for the light. p.43's "Ideally, light sources with an irradiance
of 800–1000 W m–² … should be applied" is read as the standard's light: every solar-simulator
protocol (ISOS-L, -LC, -LT) holds `hold_between: {lower: 800 W/m^2, upper: 1000 W/m^2}` as its
only light, controlled and monitored. The variant without an irradiance is gone — it said nothing
a reader of the timeline (§29) could use. ISOS-L 22 → 11, ISOS-LC 108 → 54, ISOS-LT 20 → 10:
**192 → 117 variants**. Sunlight (ISOS-O) stays only monitored. OPEN_QUESTIONS.md #10 records it.

## 31. Timeline adjustments

- **Title** bold. **A plan that never ends** closes its axis with `⋯` only: no `//` and no
  "indefinitely", which the `⋯` already says. A label stays where a break is followed by more.
- **Subscripts** as Plotly's `<sub>`: `V_MPP` → V<sub>MPP</sub>. Not LaTeX: Plotly renders `$…$`
  only where the page loads MathJax (the classic GUI does, the v2 GUI is unverified, a PNG export
  doesn't), and only for a text that is LaTeX as a whole.
- **Value axes** run from a little below their least value (0 at most) to a little above their
  greatest (`VALUE_MARGIN`), so a line at 0 is as thick as any other.
- **Rows** top to bottom: irradiance, temperature, humidity, oxygen, other quantities, then the
  electrical load last (`TOP_ROWS`, `BOTTOM_ROWS`).
- **Oxygen:** every ISOS file states `oxygen: reference_point: ambient air` (specified, purple).
  Only the "I" protocols run inert (p.42), so the others run in air.
- **A temperature ramp without a pace** (ISOS-T, ISOS-LT: no rate, no duration, or a `cycle`
  without a path) is drawn at **100 K/h**, IEC 61215-2 MQT 11's fastest thermal cycling. A
  `cycle` is drawn linear. The line is dashed, and a red note says what is assumed:
  `path and rate not specified: drawn linear at 100 K/h`. Endless, it is drawn for three
  cycles. Quantities with no plausible pace keep the band between their ends (§29). The
  assumption is only for the plot; the stored ramp stays as the standard states it.
- **Light and dark mode:** nothing is drawn in black or white. The time axis and its marks are
  a mid grey (`AXIS_COLOR`). The page shows through (`paper_bgcolor` transparent), and the rows
  sit on a translucent grey with a translucent grid. The role colours are of middle lightness.
  Text colour is left to the GUI's theme.

## 32. A condition lasts as long as its parallel block

*Superseded by §33: the context-dependent meaning of an empty duration is replaced by an
explicit duration kind. The behaviour of conditions in parallel blocks is kept, as `whole_block`.*

Supersedes the first bullet of §23.1 for parallel blocks. Under §23.1 a single instruction
without a `duration` never finished, and that passed up to every parent. A phase could therefore
not hold a condition: *hold 65 °C while cycling light and dark five times, then recover at
25 °C* made the phase endless, and the recovery never ran — silently, since R5 is gone. The
workarounds wrote one fact twice: the phase length again on the hold (and a hold shorter or
longer than the phase is not reported), or a `TimedRepeatingBlock` whose "repeat" never
completes a pass.

**The rule.**

- In a **parallel** block, or a plan run in parallel, a **single instruction** without a
  `duration` is a *condition*: it lasts as long as the block. The block lasts as long as its
  longest other sub-instruction; with nothing else there, it never finishes.
- A **block** without a duration still never finishes, and keeps its parent going: *keep going
  forever* is said by a block (`IndefiniteRepeatingBlock`), *for as long as this phase* by a
  bare instruction. The class says which (`Instruction.lasts_as_long_as_its_block`).
- In a **sequential** block nothing changes: an instruction without a duration never finishes,
  and what follows it never runs. "Until the end of the block" would contradict *one after
  another*.
- In a repeating parallel block, a condition lasts one pass, and is drawn once per iteration.
- A condition's `duration` stays empty: it is not derived, only drawn to its block's end.

**What it costs.** An instruction's extent now depends on its siblings — but only on those of
one parallel block, never on the tree, so no second pass and no interval arithmetic.

**The protocol** runs in parallel (§23.2), so its settings last as long as its routine: a
protocol with a routine that finishes has that length without writing `duration`
(`tests/data/channels.stability.yaml`: 725 h, formerly none). Every ISOS routine is indefinite,
so all 117 variants are unchanged — durations, messages and figures compared before and after.

The meaning is written into `sub_instruction_execution_mode`'s and `instruction_execution_mode`'s
descriptions, where an author choosing the mode reads it.

## 33. Durations say what kind they are

**Status: settled in review; steps 1–4 of §33.8 built.** Supersedes §32 and the first bullet
of §23.1.

### 33.1 Why

An empty `duration` stood for three different things, and which one depended on where the
instruction sat:

| Meant | Example | Read as, before §33 |
|---|---|---|
| finite, but not known when the protocol is written | a JV scan, a ramp whose pace is not stated | never finishes |
| as long as its block | a condition, a channel setting | as long as the block, but only in a parallel block (§32) |
| until something outside the plan stops it | a test run to T80, a thermal cycle | never finishes |

The first had no honest spelling at all: an author wrote a made-up exact duration, or none, and
none made everything after it never run. A proposal to read every empty duration as an
instantaneous setting was rejected: it gave the T/LT cycling ramps zero length inside an
indefinite repeat, and settings issued within one sequence overlapped, which only
cross-instruction logic could resolve. Making the kind explicit removes the context-dependent
rule instead of adding another.

### 33.2 The `Duration` section

Every `Instruction`, and `TimePlan`, has a `duration` sub-section (a sub-section rather than two
quantities, so it can grow, e.g. a range for a typical value):

| Field | |
|---|---|
| `kind` | `fixed` \| `typical` \| `whole_block` \| `open_ended` \| `derived` |
| `value` (s) | required for `fixed` and `typical`; forbidden for `whole_block` and `open_ended`; written by normalize for `derived` |
| `includes_typical` | on a `derived` duration only, written by normalize: some part of it is `typical` |

| Kind | Meaning |
|---|---|
| `fixed` | lasts exactly `value` |
| `typical` | takes time the protocol does not fix; `value` is a typical one, used for sums and drawing |
| `whole_block` | lasts as long as the block (or plan) it is in; does not count toward that block's duration |
| `open_ended` | goes on until something outside the plan stops it: an objective such as T80, the operator, or the plan's written duration |
| `derived` | worked out from the instruction's own content |

`typical` requires a number, so that a sum is never "finite but unknown": that would be a fourth
outcome every consumer had to handle. `instantaneous` is left out: a setting that persists is
`whole_block`, and an action takes time, so it is `typical`. It can be added if a true
zero-time event turns up.

### 33.3 Who has which kind — each rule has one owner

| Rule | Owner |
|---|---|
| `fixed`/`typical` need a positive `value`; `whole_block`/`open_ended` take none | the `Duration` itself (`Duration.normalize`) |
| `whole_block` only where its container runs in parallel; not in a sequence, not on a plan (no block around it) | the `Duration`, from its place: owner → container → execution mode |
| whether, and how, a duration is worked out | the owner's class: `derive_duration()` |
| `derived` only where something works it out | `settle_duration` |

One template, `settle_duration`, runs in `Instruction.normalize` and `TimePlan.normalize`: a
duration `derive_duration()` returns replaces any stated one; else one must be stated, and not
as `derived`. No class lists the kinds it may state: what was excluded that way was either a
fact about the kind (`derived` is never written by hand) or about the place (`whole_block`).

| Class | `derive_duration()` |
|---|---|
| `SingleInstruction` | none: it states its own |
| `RampInstruction` | from `ramp_rate` and its ends, where nothing is stated and the path is |
| `InstructionBlock`, `CountingRepeatingBlock` | from the sub-instructions (`derived`, or `open_ended`; a counting block without `repeat_n` also warns) |
| `TimedRepeatingBlock` | `fixed` at `repeat_duration`, whatever it contains |
| `IndefiniteRepeatingBlock` | `open_ended` |
| `TimePlan` | from the instructions, where nothing is stated |

A plan may state `fixed` (every instruction still running stops there), `typical`, or
`open_ended` ("until T80", said explicitly). A `derived` duration always has a value; what has
no end is `open_ended`. `ScheduledPlan.scheduled_end_time` follows from the plan's length, and is
empty where it is open-ended.

**Subtypes.** The role of a monitor/control instruction — setting or timed step — is its
duration kind, not its class: the same `HoldIrradiance` is a setting in `channel_settings` and a
timed step in the LC routine, and a class per role would double every concrete class. Where a
class really does restrict its kinds, it checks that itself: the first such case will be a
discrete action (a JV scan, a photograph), which completes by itself and so is `fixed` or
`typical` only — one class, `ActionInstruction`, added when actions are modelled.

### 33.4 How a derived duration is worked out

- **Sequential**: the sum. Anything `open_ended` makes the result `open_ended`. `whole_block` is
  an error: "until the end of the block" contradicts *one after another*. The `whole_block`
  duration reports it from its own place (§33.3), so no instruction checks another; in the sum
  it counts as open-ended.
- **Parallel**: the longest, `whole_block` left out. Anything `open_ended` makes the result
  `open_ended`; so does holding nothing but `whole_block`.
- `includes_typical` passes up: any `typical` part, or a derived part that includes one.
- In a repeating parallel block a `whole_block` instruction lasts one pass, and is drawn once per
  iteration (kept from §32).

### 33.5 Drawing

A `typical` piece is drawn at its typical length, with its line solid — its values are stated,
only its length is not — and `typically 10 min` in red above it, once per piece drawn (so once
per iteration shown). An `open_ended` one is drawn to the edge, as a never-ending one was. A
`whole_block` one is drawn to its block's end, as a condition was.

A figure's title gives the length where there is one: `soak · 725 h`, `soak · ≈ 1217 h` where
some of it is only typical, nothing where it is open-ended (every ISOS timeline). The separator
is ` · ` because a variant's name already ends in its choices in brackets. The iteration figures
say their pass's length the same way (`… · 2 h`). Lengths are written in the largest of h, min
and s that counts them whole in under five digits, else rounded in the largest unit they reach
(`1217 h`, never `7.3e+04 min`). An approximate length is only ever rounded: `≈ 12.02 h`, not
`≈ 721 min`.

### 33.6 Authoring

The YAML changes as little as possible, using the split between settings and routine:

```yaml
duration: 1 h               # fixed, as before
duration: typical 1 min     # typical
duration: open-ended        # open_ended
duration: whole block       # whole_block
```

- A missing duration in `channel_settings` or in protocol-level `instructions` is `whole_block`:
  these are the protocol's settings, and the protocol runs in parallel (§23.2).
- Inside any block — the `routine` and whatever it contains — a single instruction must write
  its duration; a missing one is reported, at the instruction's path, with the four spellings
  above. A ramp written with a `rate` is the exception: it works its duration out. (The schema
  reports the missing duration too; the translator's message is the one that names the file's
  spellings.) The rule is structural — the protocol's own instructions against those in a
  block — rather than tied to the word `routine`.
- `derived` is never written. Blocks still take no `duration` (§23.3); `repeat_for` stays.

The ISOS files need one line each where a routine instruction had none: `duration: open-ended`
on the cycling temperature ramps of ISOS-T-1/2/3 and ISOS-LT-1/2/3. Every other routine
instruction already states a fixed duration. `tests/data/tree.stability.yaml` gets its tags.

### 33.7 What it costs

- One more sub-section per instruction: more nested sections in each archive. The Elasticsearch
  limit of 10 000 nested documents was hit once before (uploads of the simulated LC variants of an earlier design),
  so a server upload of all ISOS variants is part of building this.
- Every consumer of `duration` reads `duration.value` and the kind; a helper gives the length in
  seconds (`inf` where open-ended), so plotting code does not unpack the section.

### 33.8 Order of building

1. This section.
2. The rules in `general.py` and `utils.py`, with the translator mapping mechanically: a written
   duration is `fixed`; a missing one is what it meant before (`whole_block` in the settings and
   in parallel blocks, `open_ended` in sequential ones). The expected ISOS archives may change
   only in the shape of `duration`. *Built: all 117 variants and `channels` draw the same
   figures and labels as before, compared figure by figure.*
3. Instruction classes and drawing: a ramp with a rate is `derived`, typical pieces marked, "≈".
   *Built: only the titles of the ISOS figures changed — the 54 LC iteration figures now end in
   their pass's length.*
4. The YAML words, the rule for the routine, and the tags in the six T/LT files. The expected
   archives must not change. *Built: they did not; `duration: open-ended` on the six cycling
   ramps, the README says how durations are written.*
5. A server upload of all ISOS variants, and CLAUDE.md's rules brought up to date. *Checked
   without the server: every variant has 28–70 searchable quantities (the nested documents
   Elasticsearch counts against its limit of 10 000); the `Duration` sub-sections add about two
   each. CLAUDE.md updated. The server upload itself waits for a restart of the running
   services, which still hold the code from before §33.*
6. Later, separately: one `RepeatingBlock` instead of three, now that timed is `fixed` and
   indefinite `open_ended`. *Evaluated, not done.* One class would carry `repeat_n` and
   `repeat_duration` both optional: "both" becomes a new cross-field rule, "neither" an empty
   field meaning *indefinitely* — what §27 removed — and the four overridden methods become
   branches on which field is set. Letting a timed block state `duration: fixed` instead of
   `repeat_duration` breaks "a block's duration is always derived". The kinds confirm the split:
   each class's `derive_duration()` is one line naming its kind.
   *Done instead:* `IndefiniteRepeatingBlock` is its own subclass rather than an alias of the
   base, which says not how it ends and is reported where written (`tree.archive.yaml` follows).

## 34. Stability runs — what a test recorded, read from an institution's files

**Status: built, steps 1–11 of §34.7.** The first measured side of the plugin: until now only
`StabilityActivity` bridged plan and activity (§23). Nothing here changes the protocol schema.

### 34.1 What a run is

A run is **one file that says how the test went** and **one file per step** holding the step's
data. The run file names the protocol it followed (file and variant), the standard, who ran it,
when, where, on which samples and instruments, and its steps in the order they ran. A step is
either a **stability series** — every quantity recorded over time in one table, as many channels
as there are — or a **J–V sweep**, whose shape does not fit that table. Several phases give
several series; a J–V sweep between them is its own step.

### 34.2 Schema — `schema_packages/measurement.py`

| Class | |
|---|---|
| `StabilitySeriesStep(ActivityStep)` | `time` (from the step's `start_time`), `temperature`, `irradiance`, `relative_humidity`, `voltage`, `current_density`, `power_density`, each `shape=['*']`; only what was recorded is filled in |
| `JVSweepStep(ActivityStep)` | `voltage`, `current_density`, `direction` (`MEnum('forward', 'reverse')` per point); a reverse and a forward sweep listed together; `figures_of_merit`, one `JVFiguresOfMerit` per scan (§34.9) |
| `StabilityMeasurement(StabilityActivity)` | `operator`, and `read_files(path, read_protocol, read_stability_series, read_jv_file)` |

- Each step checks only itself (the dividing test, §13): arrays as long as `time`, `time` never
  going backwards, a sweep's three arrays equally long. Reported, never raised.
- Current density is positive where the cell delivers power, as solar-cell data is written.
- `read_files` is **handed the functions that read files** and never opens one: the schema stays
  independent of any format, and `test_separation.py` still holds. It maps the run file onto
  existing fields (`start` → `datetime`, `standard` → `method`, `notes` → `description`, samples
  and instruments as references), builds one step per listed step by its `kind`, and puts each
  column into the quantity of its name. What has no place — an unknown kind, a column no
  quantity takes — is **returned as a message**, the rest still read, like the translator's
  problems (§13).
- *Verified:* an `MEnum` array takes a list, not a numpy array of strings (shape error), so
  `read_files` passes text columns as lists. Steps of these subclasses survive `m_to_dict` /
  `m_from_dict` inside `StabilityActivity.steps` as what they are.
- The module is its own `SchemaPackage`; the schema entry point imports it in `load()`. Importing
  it from `protocol.py` would be circular.
- `plan` is set by the parser, never by `read_files`: which entry is the protocol is a question of
  the upload, not of the files.

### 34.3 Reading — one module per institution

Institutions write runs in formats of their own. Each gets `file_reading/file_reading_<INSTITUTION>.py`
with the same interface, written out in `file_reading/file_reading_TEMPLATE.py`. The folder
`file_reading/` sits beside `parsers/` and `schema_packages/`: an institution works only there.

| Name | |
|---|---|
| `INSTITUTION` | the short name in the module's name |
| `is_protocol_file(path, content)` | is this the institution's run file — from its name, its content, or both |
| `is_stability_series_file(path)`, `is_jv_file(path)` | which kind of step file |
| `read_protocol(path)` | `{'run': {...}, 'steps': [{name, kind, file, start}, ...]}`, dates as datetimes, each `file` a path that opens as it is |
| `read_stability_series(path)` | one quantity array per column, by the name of the quantity it fills |
| `read_jv_file(path)` | `voltage`, `current_density`, `direction`, and `figures_of_merit` (a table, one row per scan) where the file holds them (§34.9) |
| `read_embedded_protocol(path)` | the protocol the run file describes itself, as a `*.stability.yaml` holds it (`{'data': {...}}`), or `None` where it names a protocol file (§34.4a) |

- Plain functions, plain data (dicts, datetimes, pint quantities): an institution only fills in
  one file. `tests/file_reading/test_file_reading_interface.py` holds every `file_reading_<X>.py` to the
  template's names and parameters and to `INSTITUTION == '<X>'`.
- What more than one format shares is in `file_reading/file_reading_utils.py`:
  `read_csv_with_units_in_header` (a header `temperature (°C)` gives a quantity column, one
  without a unit a text column; unit strings through `units.split_match_convert`, so `h` is an
  hour), `as_datetime`, and `protocol_from_phases(name, phases, repeat=1, **fields)`: for a run
  file that only lists phases and what each holds, the protocol file it amounts to — the phases
  as parallel blocks in a routine repeated `repeat` times, the first quantity of a phase stating
  its duration and the others `whole block`, every quantity held and monitored except the light
  in the dark. A quantity it does not know, or a phase without a duration, raises `ValueError`.
- "Protocol" in `read_protocol` is the run's record of the protocol it followed, not a
  `StabilityProtocol`: the name the institutions' side uses.

**SIM**, the simulated examples, writes a run as a folder: `<name>.run.yaml` (saying
`institution: SIM`), `01_jv_initial.csv`, `02_stability_series.csv` (or one per phase,
`02_stability_series_burn_in.csv`, with `03_jv_after_burn_in.csv` between), `…_jv_final.csv`.
Every CSV names each column's unit in its header. A J–V file starts with the figures of merit
the station reported, one row per scan, then an empty line, then the curve
(`read_csv_tables_with_units_in_header`).

### 34.4 Parsing — one parser for every institution

`parsers/measurement_parser.py`, `StabilityMeasurementParser(MatchingParser)`, entry point
`measurement_parser_entry_point`, `mainfile_name_re=r'.*\.run\.ya?ml$'`:

- `is_mainfile` asks each module in `INSTITUTIONS` whether the file is its run file
  (`is_protocol_file`), and takes it if one does. An institution is added by writing its module
  and listing it; the name pattern is widened if its run files are named otherwise.
- `parse` creates a `StabilityMeasurement`, calls `read_files` with that institution's three
  readers, logs every returned message as an error, and sets `plan`.
- `plan` refers to the protocol entry in the same upload: `../upload/archive/<entry id>#/data`,
  the id from `generate_entry_id(upload_id, protocol, key)`, where `key` is the variant for a
  file with options and none for a file without (its variant is the file's stem, §24).
- The sample's `lab_id` is left out of the simulated runs: `EntityReference.normalize` searches
  Elasticsearch by it, which a run needs no part of.

### 34.4a A protocol described in the run file

Some institutions keep no protocol files; their run file says what the test was. Such a file
makes **two entries**, through NOMAD's child entries (as options do, §24): the run is the main
entry, and the protocol a child keyed `PROTOCOL_KEY = 'protocol'`.

- `creates_children = True`. `is_mainfile` returns `['protocol']` where the institution's
  `read_embedded_protocol` gives a protocol, `True` otherwise (**verified**: the main entry is
  always made, children beside it). `is_mainfile` is handed the file's full path, so it reads
  the whole file, as the protocol parser does for options.
- The protocol is read as a protocol file is (`parser.load_protocol`: `translate` →
  `StabilityProtocol`), so an institution only rewrites its words into the authored form, and
  the translator's units, defaults and messages apply unchanged.
- `plan` refers to the child: `generate_entry_id(upload_id, metadata.mainfile, 'protocol')`.
- An institution's reader failing is logged, not raised; the run is still read, with no `plan`.
- Rejected: writing a `.stability.yaml` into the upload from the parser — files the lab never
  wrote, dependent on processing order, and a second copy that can drift from the run file.
- The protocol is what the file says was **planned**, never inferred from the recorded data,
  which would merge the plan into what happened and leave no deviation to find.

### 34.5 Example uploads

| Entry point | `resources` | |
|---|---|---|
| `example_upload_entry_point` | `isos` | the protocols (§16), unchanged |
| `simulated_runs_example_upload_entry_point` | `isos`, `simulated_data/*` | a run of the first variant of every ISOS file, beside a copy of the protocols |
| `custom_protocols_example_upload_entry_point` | `custom_protocols/*` | three protocols that follow no standard, each beside its run |
| `protocols_in_run_files_example_upload_entry_point` | `protocols_in_run_files/*` | two runs whose run files describe their test under `test conditions` (damp heat at open circuit; seven days and nights at 45 °C), each making a run and a protocol entry (§34.4a) |

The ISOS protocols are copied into the upload by `resources`, not duplicated in the repository.
The custom protocols show what the schema holds beyond ISOS Table 1:

| Protocol | Shows |
|---|---|
| Stepped stress | phases one after another (run once), a counted repetition (3 cycles), a condition held beside a nested sequence (light `whole block` beside a temperature profile), ramps with a rate; recorded as one series per phase with a J–V sweep between |
| Diurnal emulation | a timed repetition (`repeat_for: 120 h`) of a parallel block of two sequences, light and temperature ramped over fixed durations |
| Damp heat with light soaks | a counted repetition whose phases hold different electrical loads: MPP only while lit, open circuit in the dark |

### 34.6 Simulating — `example_uploads/simulate_runs.py`

Not shipped in any upload; writes `simulated_data/`, the run folders in `custom_protocols/`,
and `protocols_in_run_files/` from its `TEST_CONDITIONS` through `protocol_from_phases`.
Seeded per run, so the files are reproduced exactly.

- It loads the first variant through the plugin's own path (`expand` → `translate` →
  `StabilityProtocol`, normalized so blocks know their durations) and **walks the instruction
  tree**: sequential sums, parallel starts together, blocks repeated by count, by time or
  indefinitely, `whole_block` bounded by its pass, later instructions overriding earlier ones.
  Each single instruction becomes a stretch of time in which it holds.
- Columns are what the protocol monitors; the electrical columns where MPP tracking is monitored.
- Conditions: holds with noise, the 800–1000 W/m² band drifting inside it, ramps by rate or over
  their duration, cycling ramps (`triangle`, `cycle`, `sawtooth`), an ambient room, an outdoor
  day. A ramp that cycles without a rate is assumed to take 6 h per cycle, and says so in the
  run's `notes`.
- The cell: 20 % at one sun, losing efficiency faster when hotter (0.3 eV), lit and humid. MPP
  tracking reads its output; a lit cell not tracked sits at open circuit; the dark reads nothing.
  J–V sweeps at one sun and 25 °C, the forward one slightly lower (hysteresis).
- A run lasts one week, or the protocol's length if shorter; one sample every 10 min.

### 34.7 Order of building

1. The generator and the SIM format, the 20 ISOS runs. *Built.*
2. The file reading: `file_reading_SIM.py`, `file_reading_utils.py`. *Built.*
3. `StabilitySeriesStep`, `JVSweepStep`. *Built.*
4. `StabilityMeasurement.read_files`, the schema entry point importing the module. *Built.*
5. `file_reading_TEMPLATE.py` and the interface test; `StabilityMeasurementParser` recognizing
   SIM, left for further institutions. *Built.*
6. The two example uploads, the custom protocols, the generator walking any instruction tree.
   *Built.*
7. The regression over every run of both uploads through NOMAD's own `parse` and `normalize_all`
   (each loads without an error and follows a protocol entry that exists in its upload), this
   section, CLAUDE.md, READMEs. *Built.*
8. A protocol described in the run file (§34.4a): `read_embedded_protocol` in the interface,
   `protocol_from_phases`, the child entry, the third run upload. *Built.*

9. The figures of the steps (§34.8). *Built.*
10. The figures of merit of the J–V scans, as reported, and the efficiency in the overview
    (§34.9). *Built.*
11. What a series controlled, and the colours of the roles in its figures (§34.10). *Built.*

Not done, on purpose: the J–V sweeps of a run overlaid in one figure, T80 and other figures of
the whole run, the efficiency in NOMAD's `results` (searchable), J–V scans as instructions of a
protocol, and `deviations_from_plan` worked out from a run. Each is a step of
its own.

### 34.8 Figures of the steps

**Status: built.** Each step draws itself, as the protocol does: `JVSweepStep` and
`StabilitySeriesStep` are `PlotSection`s and set `figures` in `normalize`. The Plotly JSON is in
`schema_packages/step_figures.py`, written directly as in `plan_timeline.py`, sharing its font,
grid and background so both read on a light and a dark page.

- **J–V sweep:** one figure, `J–V`, current density (mA/cm²) against voltage (V), one curve per
  `direction` in the order swept, a legend naming them. A sweep without `direction` is one curve.
- **Series:** one figure, `Electrical output`, one row per electrical quantity recorded
  (power density, current density, voltage, top to bottom, power first as what a stability test
  follows), on one shared time axis in hours since the step started. It serves MPP tracking and a
  held voltage alike: the figure shows what was recorded and **never infers which load was
  applied** — that is the plan's to say, not the data's. A series without electrical quantities
  (a test in the dark, not tracked) has no figure; the conditions (temperature, irradiance,
  humidity) are not drawn yet.
- A figure is drawn only from arrays that pass the step's own checks: a sweep whose arrays
  differ in length has none, and a series draws only quantities with one value per sample.
- **The whole run:** `StabilityMeasurement` is a `PlotSection` too, with one figure, `Over time`:
  on top the efficiency of each J–V scan (§34.9), then every quantity any series recorded but
  its power density, one row each (current density, voltage, irradiance, temperature, humidity), on one axis in hours since the run's `datetime` (else its earliest
  step). Each series is drawn where its `start_time` puts it, as a line of its own, so nothing is
  drawn across the time between two. Each J–V sweep is a dashed line at its `start_time`, marked
  `J–V`. A step without `start_time` has no place on the axis: it is left out, with a warning.
  The step's `Electrical output` figure and this one are drawn by the same function
  (`over_time_figure_for_plotting`).
- Every recorded value goes into the figure, without thinning. A long, densely sampled run would
  store its data a second time, in the figures; thinning is left until such a run exists.
- *Not verified:* how GUI v2 shows figures of a subsection (the steps sit in
  `StabilityMeasurement.steps`); the archive holds them either way.

### 34.9 Figures of merit of the J–V scans

**Status: built.** Amends §34.8: the overview draws the efficiency of the J–V scans on top. A
stability test is judged by the efficiency its J–V scans report. (For a while the overview left
the series' power density out; *amended by §34.10*: it is back, as what MPP tracking records.)

- **Reported, not worked out.** A J–V station works its figures of merit out of the curve and
  writes them with it; they are **read from the file**, never computed again in the schema. A
  file without them gives a sweep without them. (The simulator, standing in for the station,
  works them out of the curve it writes.)
- `JVFiguresOfMerit(ArchiveSection)`, repeating as `JVSweepStep.figures_of_merit`, one per scan:
  `direction`, `irradiance`, `open_circuit_voltage`, `short_circuit_current_density`,
  `fill_factor`, `efficiency`, `potential_at_maximum_power_point`,
  `current_density_at_maximum_power_point`, `series_resistance`, `shunt_resistance`. Names from
  `SolarCellJV` in nomad-hzb's `nomad-baseclasses` (`jvmeasurement.py`), so a mapping from it is
  one to one; `light_intensity` is `irradiance` here as everywhere in this plugin, and the typo
  `maximun` is not taken over. SI units as the rest of the plugin; fill factor and efficiency
  as fractions (0.2 is 20 %), as relative humidity.
- The blueprint keeps each scan as a section of its own with its curve; here the curve stays in
  the sweep's arrays, told apart by `direction` (§34.2), and only the reported figures are one
  section per scan.
- **Reading:** `read_jv_file` may hand back `figures_of_merit`, a table of one row per scan by
  quantity name. `read_files` fills one `JVFiguresOfMerit` per row; a column it has no place for
  is reported like any other. SIM writes the table first in the J–V file, an empty line after
  it.
- **Overview:** the top row, `PCE (%)`, one line of dots per direction (reverse, forward in the
  sweep's colours) at each sweep's `start_time`, where its dashed `J–V` mark is.

### 34.10 Controlled or monitored — the colours of what was recorded

**Status: built.** Amends §34.8 and §34.9: the over-time figures colour what was recorded by its
**role**, in `ROLE_COLORS` of the protocol's timeline (§29, §36): `controlled` blue, `monitored`
green. `specified` and `unspecified` do not occur: what was recorded was either regulated or only
logged. Every row is in the colour of its role, no longer a colour of its own; the rows' labels
say which quantity each is.

- **What was controlled is a fact of the run**, so it is recorded with the run:
  `StabilitySeriesStep.controlled`, an `MEnum` array of the recorded quantities that were
  controlled during the step. **Every other recorded quantity was only monitored**, so an
  institution that says nothing gets everything green, which is what a logger alone gives.
- It is **not taken from the plan** at normalization: the plan says what should have been
  controlled, the run what was (§34.4a keeps the two apart), and the protocol is another entry,
  which need not be processed first.
- The power density cannot be named: nothing controls it, the operating point sets it. Under MPP
  tracking the voltage is controlled and current and power are monitored (§36.2); at a held
  voltage the same; at open circuit (`VOCTracking`) the current is controlled, and a recorded
  current density is shown so.
- **Reading:** a step of the run file may say `controlled: [temperature, voltage]`; `read_files`
  puts it into a series and reports it on any other step. The template shows it.
- **SIM:** the simulator writes it per phase: the columns an instruction with `control: true`
  controls (`controlled_quantities()`) at any time in that phase.
- **Scan directions** move off the roles' colours: reverse orange, forward magenta, in the J–V
  figure and the PCE row alike.
- **One legend, as in the timeline:** a line of text above the rows on the right, a square per
  role drawn, a dot per scan direction. Plotly's own legend is off.
- **Hover:** each line is named `<step> · <quantity> · <role>`.
- The **power density is back in the overview**, under the PCE row: it is what MPP tracking
  records, and a run without tracking has no such row.

## 35. Open question — one entry per protocol

**Status:** open. Planned, not built. Parked because NOMAD offers no way to re-check entries that
already exist when something is uploaded or published (§35.2).

Every upload that copies the ISOS files, and every run file that describes its own test (§34.4a),
makes protocol entries again. The aim is one entry per protocol: a run's `plan` refers to an
existing protocol wherever one is equal, and the duplicate is not stored.

### 35.1 Decisions taken

- **Equal** means every field equal **except name and metadata**. Ignored: `name`,
  `description`, `notes`, `datetime`, `lab_id`, `location`, `geo_location`, `standard`,
  `standard_variant`, `standard_level`, the figures, and the names of blocks and instructions
  (the last two still to be confirmed). Compared: the whole instruction tree (every value,
  duration, repetition, mode, ramp), `environment`, `objectives`, the protocol's duration; values
  in SI, so `65 °C` equals `338.15 K`. Held as `StabilityProtocol.fingerprint`, a hash computed in
  `normalize`, searchable once published.
- **Compared against** published protocols only (`owner='public'`): they cannot be deleted, so a
  reference to one stays valid. Within an upload, identical protocols make only one entry.
- **Who wins:** the oldest published protocol with the fingerprint; else the first in the upload,
  protocol files before protocols in run files, each by path and variant key.
- **A duplicate is deleted:** no entry at all. `is_mainfile` returns `False` for a protocol file,
  or only the variants that are not duplicates, and a run file makes no `'protocol'` child. On
  reprocessing, NOMAD deletes an existing entry whose file no longer matches (**verified**,
  `Upload` processing, "remove existing entries if unmatched"). The raw file stays.
- **The run is told:** it refers to the winner, logs a warning that its protocol was not stored,
  and keeps the name its own protocol had in a new `StabilityActivity.plan_name_alias`.
- **By name:** a run naming a protocol its upload does not contain is matched to published
  protocols by variant, else standard; of several, the oldest published; its differing name goes
  into `plan_name_alias`.

### 35.2 What NOMAD offers (verified in `nomad-FAIR`)

- `is_mainfile` receives the raw file's real path, `<fs.staging>/<prefix>/<upload_id>/raw/<mainfile>`,
  so the upload's other files can be read to find duplicates within it (relies on the internal
  layout). Parsers run by `level`: every entry of a level finishes before the next starts.
- **No trigger:** no plugin entry point runs when something is uploaded or published. The kinds
  are app, schema package, normalizer, parser, example upload, API, dashboard, action and NORTH
  tool; parsers and normalizers run only on the entry being processed. Publishing is a Temporal
  workflow that packs the entries as they are, without parsing or normalizing.
- **Staged uploads** can be reprocessed by their owners (GUI, API). An `ActionEntryPoint` or an
  `APIEntryPoint` could offer "re-check my staged uploads", but a user starts it, not an event.
- **Published uploads** are immutable to users; only an admin reprocesses them
  (`nomad admin uploads process`). By default `reprocess.delete_unmatched_published_entries` is
  `False`, so a published duplicate would stay even when no longer matched; switching it on deletes
  entries others may already refer to.
- A periodic admin job (outside the plugin), or a publish hook proposed upstream to NOMAD, are the
  only ways to re-check old entries automatically.
- **Actions** (`nomad/actions/`) could do the re-checking: a Temporal workflow in a worker, with
  access to MongoDB, Elasticsearch and the files, allowed to `users`/`groups` named on the entry
  point. But one starts only by a logged-in user (`POST /actions`) or by code calling
  `start_action(action_id, data)` with a `user_id`: no schedule, no event. Options, if taken up:
  (a) an action "check my uploads for duplicate protocols" that reprocesses the user's own staged
  uploads, so `is_mainfile` drops duplicates — within NOMAD's rules, preferred; (b) an admin-only
  action run by a Temporal schedule set up outside the plugin, also over published uploads —
  bypasses their immutability, needs the operators' consent; (c) event triggers for actions
  (on publish) proposed upstream. Not: a parser calling `start_action`, which fires on
  processing, not publishing, and loops through reprocessing. Actions are new in the development
  build; their API may change.

### 35.2a Intended route — an admin action "harmonize published results"

Parsing decides which protocol wins and drops the rest (§35.1); the action only finds the
published uploads concerned and reprocesses them, so the rules live in one place.

1. Aggregate published protocols by `fingerprint`; groups of more than one; the oldest published
   wins.
2. The uploads concerned: those holding a losing protocol, and those holding runs that refer to
   one (`metadata.entry_references.target_entry_id` is indexed, **verified**).
3. A dry run first: which entries are deleted, which runs get another `plan`, which aliases are
   kept. An admin approves.
4. `upload.process_upload(reprocess_settings={'rematch_published': True,
   'delete_unmatched_published_entries': True})` (**verified**: what `nomad admin uploads process`
   calls). Losing protocols no longer match and are deleted; runs refer to the winner and keep
   their old name in `plan_name_alias`.
5. Startable by an admin group only (`groups` on the `ActionEntryPoint`).

What parsing needs for it: a protocol is dropped only for one published **before** it (reprocessing
a published upload finds its own protocols); an entry in a dataset with a DOI stays, as NOMAD
refuses to remove it (**verified**), and could refer to the winner instead.

### 35.3 What remains open

- Owners are not told that their published entries changed; whether a plugin can send NOMAD's
  notifications is unchecked.
- A deleted entry's URL stops working outside NOMAD; only NOMAD's own references are repaired by
  the reprocessing.

- A duplicate protocol file no run refers to is deleted silently: without an entry there is no
  place to warn.
- Between matching and parsing (seconds), a protocol published elsewhere can make a run refer to
  an entry that was never made; reprocessing fixes it.
- An upload processed before an identical protocol is published elsewhere publishes its duplicate
  unless reprocessed first; nothing re-checks it afterwards (§35.2).

### 35.4 Order of building, once taken up

Checked against the code as built (§34): nothing blocks it. Translating and normalizing a variant
takes ~9 ms and is deterministic (all 117 ISOS variants), so matching computes the fingerprint on a
normalized copy exactly as the schema will; `normalize` adds only `duration` (compared) and
`standard_level` (ignored). Every variant's `data.name` is its entry key, so the search by name
works as is. Two edits come with it: `fingerprint` joins `DISPLAY` in `test_isos_protocols.py`,
and the run parser gets `level=1` (step 3), since nothing reads a run's protocol entry today.

1. `fingerprint`, and tests of what it ignores and what it compares.
2. The winner, found once for matching and parsing alike; a cache of fingerprints per file so
   matching stays linear; duplicates within an upload made no entry.
3. Runs refer to the winner; `plan_name_alias`; the warning.
4. Published protocols by fingerprint, and by name.
5. Example uploads with a duplicate; docs; the regression.
6. A check against a running NOMAD: the derived upload root, the search syntax for the plugin's
   own quantity, references across uploads, deletion on reprocessing.
7. The admin action "harmonize published results" (§35.2a), dry run first.

## 36. The electrical load is one port — dependent quantities

**Status: built, steps 1–3 of §36.4.** Amends §29's "one row per quantity" for the electrical load.

### 36.1 Why

Humidity and oxygen were split (§20.6) because they are independent: two partial pressures, both
settable at once. Voltage, current and resistance are not: the cell's terminals are one port with
one degree of freedom. A protocol sets one of them, or a point on the J–V curve (MPP, open
circuit), and the device answers with the rest. The answer is always worth logging and every
source-measure unit logs it, so a protocol rarely says so.

Splitting the electrical channel into one channel per quantity would make "control voltage and
control current at once" writable. That is physically impossible, and we don't check across
instructions (§23.2). So the model keeps one electrical instruction at a time. The class states
the pair, as physics and not as data.

### 36.2 Schema — a mixin, not new fields

`DependentMonitorControl(MSection)` in `base_instructions.py` is mixed in **before** the kind:
`class HoldVoltage(ElectricalLoad, HoldInstruction)`. The mixin cuts across the kinds (hold, ramp,
tracking), which is why it can't be one more level in the hierarchy. Each concrete class states two
class attributes. They are **not Quantities**: they are not authored and don't vary per instance,
so nothing new reaches the archive.

- `controlled`: what `control: true` regulates.
- `dependent`: what follows it, and what `monitor: true` logs, **all** of them.

`MonitorControlInstruction` gets two readouts that every instruction answers:
`controlled_quantities()` and `monitored_quantities()`. For an ordinary instruction both are its
own quantity. The mixin answers from the class attributes.

`ElectricalLoad(DependentMonitorControl)` names the port.

| Class | `controlled` | `dependent` |
|---|---|---|
| `HoldVoltage`, `RampVoltage` | voltage | current |
| `HoldCurrent`, `RampCurrent` | current | voltage |
| `HoldResistance`, `RampResistance` | resistance | voltage, current |
| `MPPTracking` | voltage (the tracker perturbs it: `perturbation_voltage`) | current |
| `VOCTracking` | current (zero: the terminals are disconnected) | voltage |

**The rule behind the table:** `controlled` names what the hardware sets, and `dependent` names
what the instrument measures. At the port only voltage and current are measured, so `dependent`
only ever holds those two. Resistance is a setting of a passive load: a resistor fixes the operating
point where its load line meets the J–V curve, as MPP or open circuit do. So it appears only as
`controlled`, never as `dependent`. Values computed from what is measured, such as the cell's
resistance V/I or the power V·I, are never listed as dependents.

`role_for_plotting` is unchanged: open circuit stays `specified`.

**Verified in `nomad-FAIR`:**
- Every base of a section class must itself be a section (`metainfo.py`: "Section defining
  classes must have MSection or a descendant of base classes"). So the mixin is an `MSection`
  even though it has no fields. Plain class attributes and methods then work through the MRO,
  and archives round-trip unchanged.
- A Quantity redefined in a mixin does **not** override the kind's own definition (the kind's
  description wins). A concrete class can override it. Rather than repeat `monitor` in 8
  classes, the shared descriptions of `monitor` and `control` on `MonitorControlInstruction`
  point to the readouts.

### 36.3 Plotting

- **One row, `electrical load`,** for every `ElectricalLoad` instruction (`row_for_plotting`).
  `BOTTOM_ROWS` loses `voltage`, `current` and `resistance`. The variants of one ISOS file
  (open circuit / MPP / fixed V) then share their row label, and a protocol that switches from
  open circuit to a fixed voltage draws one continuous row instead of two rows with gaps.
- **Controlled side** as today: a line at the value, or a bar with `V_MPP`, `MPP`,
  `open circuit`. The row's unit (V, A, Ω) says which quantity a line is. Where pieces of one
  row carry **different units**, their values can't share an axis, so each piece with a value
  is drawn as a bar with its label instead (`Hold current 0.02 A for 1 h`). Pieces without a value
  keep their own text (`open circuit`). This rule is generic (`_one_unit_per_row`), but only the
  electrical row can mix units today.
- **Monitored side:** where `monitor: true`, a thin row (`MONITORED_ROW_HEIGHT`, 0.4 of a row)
  right under the electrical row, with a green bar `monitored: current` (or
  `monitored: voltage, current`) from `monitored_quantities()`. The mixin adds this piece in
  `time_series_for_plotting`; it is derived from the one instruction, never authored as a
  second one. The row is keyed `electrical load, monitored` and has no label of its own: its bars
  say what they are. A sub-row rather than a strip inside the bar, so it never overlaps a value
  line.
- **Bars side by side stay apart** (`BAR_GAP`, 3 px), so that `Hold voltage` followed by
  `Hold current` reads as two bars, not one long one. This applies to every row.
- **A row and its monitored row write their text at one size**, the size that fits the
  narrowest bar of either.

### 36.4 Order of building

1. The mixin, `ElectricalLoad`, the readouts on `MonitorControlInstruction`, the eight
   electrical classes; one parametrized test over the table in §36.2.
2. Plotting per §36.3; a test that open circuit followed by a fixed voltage draws one row; the
   monitored sub-row.
3. The gap between bars side by side; one text size for a row and its monitored row.
