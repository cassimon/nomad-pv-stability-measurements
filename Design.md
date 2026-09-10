# Design — `nomad-pv-stability-measurements`

Status: **design draft, iteration 0**. Nothing implemented yet.
Goal of this document: agree on the smallest set of general classes that can
describe a PV stability measurement, before writing any metainfo.

---

## 0. Decisions already taken

| # | Question | Decision |
|---|----------|----------|
| 1 | PID vs ramp vs alternating | **Split axes.** *What the setpoint does over time* is the `ChannelState` subclass (`Hold` / `Ramp` / `Cycle` / `Tabulated` / `Track` / `Sweep`); *how the hardware regulates* is a separate `RegulationLaw` field (open loop / PID / on-off). A PID-regulated ramp is one object, not a `PIDRamp` class. |
| 2 | Must every controller be stopped? | **Moot — nothing is stopped.** A channel state ends when its protocol's scope ends. `Off` remains available for ending a state without a scope boundary. *(Superseded by #9.)* |
| 3 | `WaitUntil` / conditional waits | **Dropped.** Termination lives on the `Protocol`: `repetitions`, `duration`, or `stop_when`. |
| 4 | JV sweep during MPP tracking | **Explicit, and now unavoidable.** The sweep is its own subprotocol setting `bias -> Sweep`. Running both at once is no longer expressible at all. |
| 5 | Does this drive hardware? | **No.** Read-only data schema, describing the output of instruments that already ran. |
| 6 | External schema packages | **Later.** `nomad-measurements` and `perovskite-solar-cell-database` are declared in the distro's `[tool.uv.sources]` but are **not** in `[project].dependencies` and are **not installed**. Iteration 1 depends on `nomad-lab` only. |
| 7 | One device per channel | **Yes — and now structural rather than validated.** A channel has exactly one `ChannelState` at any instant because states are scoped to protocols. The validator rule this used to need is gone. *(Strengthened by #9.)* |
| 8 | `Observer` as a startable device | **Dropped.** Observation is a plain field on the channel, not something you `Start`/`Stop`. (This closes former open point (e).) |
| 9 | `Instruction` tree (Start/Stop/Wait/Repeat) | **Deleted.** Lifetime is expressed by protocol *nesting*, not by start/stop pairs. `Repeat` becomes a repeating subprotocol; `Wait` becomes a subprotocol `duration`. |
| 21 | `subprotocols` -> `steps`, and a visible block marker | **Adopted.** A node's children are its `steps`. A step that acts on a channel opens with `channel: <key>`; a step that is a nested block opens with `subprotocol: <name>`. Exactly one, same position, so the two kinds are told apart on their first line — with no extra indentation. |
| 19 | "Simultaneous to *what*?" | **A `mode` tag on the node, not a flag on the element.** `mode: sequential \| parallel` says how *that node's children* run. Carried by every node including the root. Supersedes the per-element `execution` flag and its implicit grouping rule from #11. |
| 20 | `Command` in the core model | **Yes — and it is a `Protocol` node, not a separate class.** One `Protocol` class with an optional `channel` + state slot. A node that names a channel acts on it; a node with children runs them per its `mode`. Kills R1. |
| 15 | Polymorphic sub-sections in YAML | **Avoided via named slots.** `m_def` is never written by hand. Verified: the short form `m_def: Hold` does *not* resolve, and omitting `m_def` silently instantiates the **base** class. See §10.1. |
| 16 | Durations and rates in YAML | **Human strings** (`"24 h"`, `"50 mV/s"`) parsed in `normalize()`. Verified: NOMAD accepts only a bare number in the quantity's declared unit — `"24 hour"` and `{value: 24, unit: hour}` both raise. See §10.2. |
| 17 | Cross-references in YAML | **By `key` string**, resolved in `normalize()` — never `#/data/channels/0`. See §10.3. |
| 18 | `RegulationLaw` placement | **Moved from the state to the channel.** PID gains belong to the hardware loop, not to each setpoint — and it lets `hold: 65` collapse to a scalar. |
| 12 | Timeline storage | **Column arrays, plus a fixed sparse point budget for simulated timelines.** Expansion is exact in memory; only a downsampled view is persisted. *(Resolves §9.1.)* |
| 13 | Protocol findability | **A non-editable `ProtocolSummary`**, populated from the tree in `normalize()` and pushed to `archive.results.properties`. *(Resolves §9.2.)* |
| 14 | Units | **Option (i): generic states carry unitless numbers; the channel declares the unit.** Refined — *time* fields stay unit-ful everywhere, and channel-specific states are fully unit-ful. *(Resolves §9.3.)* |
| 11 | Concurrent execution | **Adopted.** Restores overlapping spans, and — with the disjointness rule R3 — keeps the tree readable. Supersedes the "cost" I described for #9. *(Mechanism revised by #19: a `mode` tag on the node, not a flag on each element.)* |
| 10 | Channel capability | **The channel subclass declares which `ChannelState`s it accepts.** "What the channel can do" is fixed by extending the channel, not by wiring up controllers. |

---

## 1. What NOMAD core already gives us

Survey of `nomad.datamodel.metainfo.basesections` and `nomad.datamodel.metainfo.eln`
(both ship with `nomad-lab`, no plugin needed).

### Use these

| Class | Gives us | Use for |
|---|---|---|
| `BaseSection` | `name`, `datetime`, `lab_id`, `description` + registers them into `archive.results.eln` for search | base of `StabilityProtocol` |
| `EntryData` | makes a section a standalone, referencable entry | `StabilityProtocol`, `StabilityMeasurement` |
| `Measurement` (← `Activity` ← `BaseSection`) | `samples: CompositeSystemReference[]`, `instruments: InstrumentReference[]`, `results: MeasurementResult[]`, `steps`, `method`, `location`, and wires `archive.workflow2` inputs/outputs | base of `StabilityMeasurement` |
| `MeasurementResult` | trivial (`name`), but is what `Measurement.results` expects | base of `StabilityResult` |
| `CompositeSystemReference` | a typed reference to a sample entry | **this is the "link to the solar cell sample"** — no separate reference schema needed |
| `InstrumentReference` | typed reference to an instrument entry | channel → instrument provenance |
| `PlotSection` | `figures: PlotlyFigure[]` | protocol simulation plot, results plots |

### Do *not* use these (and why)

- **`Activity` as the base of `StabilityProtocol`.** `Activity.normalize()` appends to
  `archive.results.eln.methods` and **overwrites** `archive.workflow2.tasks` from `self.steps`.
  A protocol is a *plan*, not something that happened — it should not claim the entry's
  workflow or method. Use `BaseSection` + `EntryData`.

- **`ActivityStep` / `ProcessStep` as the base of `Protocol`.** `ActivityStep` is
  `name` + `start_time` (**absolute `Datetime`**) + `comment` + `to_task()`. Protocol time is
  purely *relative* to t₀, so `start_time` is actively wrong here. And `to_task()` is only
  invoked by `Activity.normalize()` over `self.steps` — which we decided not to use.
  Iteration 1: plain `ArchiveSection`. Worth revisiting *later than before*, though: a tree of
  nested `Protocol`s maps onto NOMAD's nested `TaskReference` workflow tree far more
  naturally than a flat instruction list did.

### Noted for later

- `nomad.datamodel.metainfo.eln.SolarCellJV` / `SolarCellJVCurve` already exist in core and
  carry `voltage`, `current_density`, efficiency, FF, Voc, Jsc. Reusable for JV snapshots,
  but heavy (certification institute, data_file, …). Iteration 1 uses a minimal own class;
  swap later if the weight is acceptable.
- There is **no** `Protocol` / `Recipe` / `Plan` base section anywhere in NOMAD core.
  We are defining new ground.

---

## 2. The three layers

The single most important structural point: keep these apart.

```
  AUTHORED                  DERIVED                      OBSERVED
  ────────                  ───────                      ────────
  StabilityProtocol   ──►   ProtocolTimeline      vs     StabilityMeasurement
  a tree of Protocol        a flat list of               what the instrument
  nodes                     setpoint events              actually logged
  (hand-written)            (normalizer output)          (parsed from files)
```

`ProtocolTimeline` is never hand-authored. It is produced by a **pure Python expander**
(no metainfo) that walks the protocol tree. That expander is unit-testable without an
archive, and it is the only place where loop semantics live.

Nice consequence: the *same* `ProtocolTimeline` class can also be filled by **parsing an
instrument's command log**. So it carries a `source = simulated | logged` flag, and the
headline plot becomes *intended vs. actual*.

---

## 3. Core model — four concepts

```
1. StressChannel   a physical variable + the set of states it accepts
2. Protocol        ONE node type. Names a channel -> it commands that channel.
                   Has children -> its `mode` says whether they run in order or at once.
3. ProtocolTimeline the expanded/parsed setpoint events (derived)
4. StabilityMeasurement + StabilityResult   the observed data (an entry)
```

`Instruction`, `Start`, `Stop`, `Wait`, `Repeat`, `Controller` and `ProtocolDevice` are all
gone. So is `Command` as a separate class — **a command is a `Protocol` node that names a
channel** (decision #20). Three rules remain:

> **R1 — a node that names a channel puts it in a state.** `{channel: chuck_T, hold: 65}` is
> a leaf. That is the whole of "Command".
>
> **R2 — a node's `mode` says how its `steps` run.** `sequential` (default) runs them in
> order; `parallel` runs them all at once. Every node carries the tag, root included.
>
> **R3 — the children of a `parallel` node must write disjoint channels.** Checked
> statically, by set intersection.

Lifetime falls out of **lexical scope**: a node's state holds for that node's span. A child
with no `duration` spans its parent's whole scope. Scope exit *is* the stop — nothing to
pair up.

### Why a `mode` tag and not a per-element `execution` flag

Your objection was right: `execution: DoSimultaneously` never says *simultaneous to what*.
The old answer — "to the preceding sibling, and to any run of `DoSimultaneously` siblings
after it" — makes grouping **implicit and order-dependent**. Reordering a list in the ELN,
which the GUI actively invites, would silently change the meaning. That is a bad property in
a schema whose entire job is recording what happened.

The tag moves the question to the node, where it has an unambiguous answer: **simultaneous
with the other children of this node.** Reordering the children of a `parallel` node is
meaningless and therefore safe; reordering the children of a `sequential` node is meaningful
and visible. Mixed sequencing composes by nesting:

```
A, then B ∥ C, then D:

mode: sequential
steps:
  - A
  - {subprotocol: fork, mode: parallel, steps: [B, C]}
  - D
```

You raised a list-of-lists as the alternative — same instinct, and it is what the nested
`parallel` node above *is*, except it only appears where parallelism is actually used
instead of wrapping every stage. R3 also becomes trivial to state and to check: intersect the
channel sets of one node's children.

### Why `Command` is a `Protocol` node rather than a subclass

Elevating it into the core model is right — it is the only node that *does* anything. But a
literal subclass would put `Protocol` and `Command` instances in the same list, which is a
**polymorphic sub-section**, which decision #15 forbids: it would demand a 60-character
`m_def` on every command line, or silently instantiate the base class.

So it is one class with an optional `channel` + state slot. Mechanically a discriminating
field; conceptually exactly what you described. This costs one more "exactly one of" runtime
check and buys:

- **R1 disappears.** Commands are no longer a special parallel list bolted onto each node;
  they are children like any other.
- **A command can carry a `duration`.** `{channel: chuck_T, hold: 65, duration: 500 h}` is
  the "heater for the first 500 h" case in one line — the case that motivated decision #11.
- **One child list, one ordering.** The `commands` key is gone, so a node no longer has two
  child collections whose interleaving was undefined.

### Why this is better, not just smaller

**The one-state-per-channel invariant becomes structural.** Decision #7 previously needed a
validator to catch "two controllers writing the same channel at once". Now a channel simply
*has one state at a time* by construction — the illegal case cannot be expressed. That is
the strongest argument for this shape: a rule enforced by the type system beats a rule
enforced by a normalizer that a user can ignore.

Three instructions collapse into one node:

```
  before:  Start mppt ; Wait 24 h ; Stop mppt
  after:   {channel: bias, track: mpp, duration: 24 h}
```

### What `mode: parallel` costs — less than I previously said

The old cost was: state boundaries had to line up with protocol boundaries, so "heater on for
the first 500 h of a 1000 h run" needed splitting or an explicit `Off`. Now it is one line:

```yaml
mode: parallel
steps:
  - {channel: chuck_T, hold: 65, duration: 500 h}
  - {subprotocol: cycle, repetitions: 42, steps: [...]}
```

**The structural guarantee weakens, but only slightly.** "Two states on one channel" becomes
expressible again, so decision #7 needs a validator once more. But it comes back in a far
cheaper form than the state-`duration` alternative would have brought it:

| | Detecting a double-write |
|---|---|
| state `duration` | needs **time-interval arithmetic** over every scope — a simulation |
| `mode: parallel` + R3 | needs a **set intersection** over one node's children — no time involved |

R3 is the natural rule anyway: parallel branches control different pieces of hardware. And
critically, **R3 preserves the readability property**. "What is channel X doing at time t?"
is still answered by walking the tree, because at most one child of a `parallel` node can
write X. That is the property worth protecting, and it survives intact.

So this is a better trade than the `parallel` flag I dismissed earlier — I was comparing
against a version without R3.

**Residual costs:**
- one enum field, one static check, and a merge-sort of concurrent event streams in the
  expander (~60 lines instead of ~40);
- **join semantics must be pinned down** (see §4.2): what is a parallel group's duration when
  its branches differ?
- `Off` / `Idle` remains useful for ending a state without a scope boundary, so keep it.

This is structured *concurrency* — fork/join, single entry and exit per branch — not `goto`.
The well-behaved kind.

### Can a better `StressChannel` subclass absorb this cost? No.

Tempting, but it gives back the win. The obvious move is to put a `duration` on
`ChannelState`, so a state can end before its scope does — `Hold(65 C, duration=500 h)`
inside a 1000 h protocol. That immediately breaks both rules:

- a channel's state is no longer readable by walking up the tree; you must also track elapsed
  time inside every scope;
- two states on one channel can now overlap (parent sets `Hold(65 C, 500 h)`, a child at
  t = 200 h sets `Hold(80 C)` — what holds at t = 500 h?). The structural one-state-per-channel
  guarantee is gone and the validator rule from decision #7 comes straight back.

The clean division is:

> **Channels own *what*. The protocol tree owns *when*.**
> Subclassing extends *what*. The cost lives entirely in *when*, so no subclass can touch it.

The one legal exception, which is not a violation: a state may **determine** its leaf
protocol's duration (a `Sweep`'s duration is intrinsic — scan range ÷ scan rate). Derived
*from* the state, still exactly 1:1 with the scope. A state may not outlive or under-live its
scope.

What subclasses *should* absorb: capability sets (decision #10), physics-specific fields,
derived durations, and per-channel idle semantics (open point (f)).

**The `mode` tag confirms this division rather than contradicting it.** `sequential` /
`parallel` is a fix applied to the *tree*, which is where "when" lives — the correct layer. Had the same expressiveness been bought via a `ChannelState.duration`, it would have
been the wrong layer, and it would have cost time-interval arithmetic instead of a set
intersection.

---

## 4. Class tree (iteration 1, minimal)

### 4.0 How to read these sketches — field order

**Checked against this distro's `nomad-lab`**, because my earlier sketches got this wrong:

1. **Inherited quantities come first**, in base-class definition order. `Demo(BaseSection)`
   with its own `version` serializes as `name, datetime, lab_id, description, version` — so
   `name` really is first, always, and it is not an afterthought.
2. **All quantities serialize before all sub-sections, regardless of declaration order.**
   A `horizon` quantity declared *after* a `channels` sub-section still comes out
   `['name', 'horizon', 'channels']`. This is what made the old `StabilityProtocol` sketch
   confusing: it listed a scalar sandwiched between sub-sections, which cannot happen.
3. Within each group, declaration order is preserved.

So the sketches below are written in **true serialization order**: identity first, then the
rest of the quantities, then the sub-sections, then derived members last within their group.

Two things this does *not* constrain:

- **Hand-written YAML may use any key order** — mappings are unordered on input. Rule 2 only
  affects how NOMAD renders the ELN and how it re-serializes a file.
- **The ELN display order is overridable**, via
  `a_eln=ELNAnnotation(properties=SectionProperties(order=[...]))`. Worth using here, because
  rule 2 would otherwise split the "exactly one of" state slots (§10.1) across the
  quantity/sub-section boundary — `hold` and `track` are quantities while `ramp` and `sweep`
  are sub-sections, so they would render far apart despite being alternatives. An explicit
  `order` keeps them together.

### 4.1 Channels and their states — `channels.py`

The channel subclass declares **what the channel can do**. This is the single extension point
of the whole schema: a new kind of stress = one new `StressChannel` subclass plus the
`ChannelState`s it accepts.

```
StressChannel(ArchiveSection)                    # abstract

    # --- quantities
    name          str                            # 'chuck_temperature' — human, renameable
    key           str                            # stable, immutable — §9.7
    unit          str                            # decision #14: the unit for THIS channel's
                                                 #   state values and limits
    limits        float[2]                       # in `unit`
    observe_every str                            # "60 s" — decision #16
    idle          str                            # enum, per subclass; what it does when
                                                 #   no command applies
    role          enum{controlled, observed, declared}   # DERIVED

    # --- sub-sections
    regulation    RegulationLaw (opt)            # decision #18 — belongs to the hardware loop
    instrument    InstrumentReference (opt)
│
├── TemperatureChannel      unit K
├── IrradiationChannel      unit W/m2 | suns;  spectrum: SpectrumDefinition
├── AtmosphereChannel       relative_humidity, total_pressure; components: GasComponent[]
├── ElectricalLoadChannel   the "JV channel"
└── MechanicalChannel       bend_radius / strain

```

Channels live in a `Channels` container with one repeating slot per type, so no `m_def` is
ever written — decision #15, §10.1:

```
Channels(ArchiveSection)
    temperature      TemperatureChannel[]
    irradiation      IrradiationChannel[]
    atmosphere       AtmosphereChannel[]
    electrical_load  ElectricalLoadChannel[]
    mechanical       MechanicalChannel[]
```

```
ChannelState(ArchiveSection)                     # abstract — what a channel is doing

GENERIC — accepted by any channel; value axis is UNITLESS (decision #14),
          time written as a human string (decision #16)
│
├── off        bool                              # a scalar slot
├── hold       float                             # a scalar slot -> `hold: 65`
├── ramp       Ramp      ( from:float, to:float, duration:str? )
├── cycle      Cycle     ( waveform{square,triangle,sine},
│                          low:float, high:float, period:str, duty_cycle:float )
└── tabulated  Tabulated ( time:str[], value:float[] )

CHANNEL-SPECIFIC — accepted only by ElectricalLoadChannel, so the unit IS known
│
├── track      enum{mpp, voc, jsc}               # a scalar slot -> `track: mpp`
└── sweep      Sweep     ( from:[V], to:[V], rate:str, direction, repeats:int )
```

These are **named slots on the `Protocol` node**, not a polymorphic `ChannelState`
sub-section — decision #15. Exactly one may be set, checked in `normalize()`. A single Python
property returns whichever is set, so the expander still works against one canonical state
object; the slots exist purely so nobody ever types an `m_def`.

Which slots a channel accepts is declared per subclass (`accepted_states`) and checked in
`normalize()` — cheap, and it makes the ELN self-documenting.

**Two refinements to decision #14, both free:**

1. **Time is unit-ful everywhere.** Time is the one dimension that is identical for every
   channel, so `duration`, `period` and `dwell_time` are proper `Quantity(unit='s')`. This is
   why `Ramp` is specified by `start / end / duration` rather than by a *rate* — a rate would
   have been K/min here and suns/min there, dragging the unit problem into the time axis for
   no benefit. Rate is derived.
2. **Channel-specific states keep their units.** `Track` and `Sweep` are only ever accepted by
   `ElectricalLoadChannel`, whose unit is always volts, so `scan_rate` really can be
   `Quantity(unit='V/s')`. The unitless compromise applies *only* to states that must work
   across channels.

So the compromise is narrower than plain option (i): it costs unit checking on the value axis
of five generic states, and nothing else.

```
RegulationLaw(ArchiveSection)                    # optional, metadata only
    kind enum{open_loop, pid, on_off, external};  kp, ki, kd, hysteresis
```
Hangs off the **channel**, not the state — decision #18. PID gains describe the hardware
control loop, which does not change from setpoint to setpoint; and putting it here is what
lets `hold` collapse to a bare scalar. Still orthogonal to the state type (decision #1): a
channel with `kind: pid` regulates a `hold` and a `ramp` alike.

### 4.2 Protocol — `protocol.py`

```
Protocol(ArchiveSection)             # ONE node type — decision #20

    # --- quantities. EXACTLY ONE of `channel` / `subprotocol` opens the node — #21
    channel       str              # a channel KEY  => this step acts        (a command)
    subprotocol   str              # a block name   => this step contains    (a container)
    name          str              # DERIVED from whichever of the two is set
    mode          enum{sequential, parallel}   # how MY steps run; default sequential
    duration      str              # "24 h"; omitted => spans the parent's scope
    repetitions   int              # None/0 = infinite
    off           bool     \
    hold          float      >     scalar state slots — §10.1
    track         enum       /
    duration_s    [s]              # DERIVED from `duration` — decision #16
    channel_ref   -> StressChannel # DERIVED from `channel` — decision #17

    # --- sub-sections
    ramp          Ramp       \
    cycle         Cycle        >   section state slots — §10.1
    tabulated     Tabulated    /
    sweep         Sweep      /
    stop_when     StopCondition (opt)
    steps         Protocol[]       # SectionProxy, recursive — #21

Exactly one state slot may be set, but they straddle the quantity/sub-section split — give
this section an explicit `a_eln` `order` so the ELN shows the seven together (§4.0).

**Why `subprotocol: <name>` rather than a wrapper key.** The obvious alternative is to nest
each block under its own key:

```yaml
steps:
  - subprotocol:                 # <- a wrapper section
      name: daily cycle
      steps: [...]
```

It reads well, but it costs **an extra indent level and an extra empty section object per
nesting level** — and §9.5 already lists depth as this design's main usability problem. Using
`subprotocol` as the block's *name* field puts the word in the same position as `channel`,
so the two kinds of step announce themselves identically on their first line, at zero cost:

```yaml
steps:
  - {channel: bias, track: mpp, duration: 24 h}     # acts
  - subprotocol: daily cycle                        # contains
    repetitions: 42
    steps: [...]
```

The **root** keeps plain `name` — it is not a step of anything, and the entry's `protocol:`
key already announces it. So `subprotocol` appears exactly where a reader needs it: on the
blocks nested inside a list, which are the ones that are otherwise hard to pick out.
```

```
StopCondition(ArchiveSection)
    observable str                 # see open point (b)
    operator   enum{<, <=, >, >=}
    value      float
```

**Join semantics for a `parallel` node** — see open point (g):
- a child's state ends when **that child** ends, not when the parent ends. Otherwise
  parallelism would be pointless. Scoping is unchanged; concurrent scopes simply overlap.
- the parent's duration = **max over its finite children** (join-all).
- a child with **no `duration` spans the parent's whole span**, i.e. it is truncated to that
  max rather than being an error. This is the most useful idiom in the design: "hold 65 °C
  for as long as the cycling runs, whatever that turns out to be" is an unbounded hold
  alongside a finite cycling child, with no duration duplicated anywhere.
- a `parallel` node whose children are *all* unbounded falls back to `horizon`.

**Infinite repetition** (`repetitions = None`) is allowed. Two consequences:
- the expander needs `horizon` to truncate — it was optional before, it is now mandatory;
- inside a `sequential` node, an infinite child makes every later sibling unreachable →
  validator error. Inside a `parallel` node it is fine — that is the idiom above.

`stop_when` depends on measured data the expander does not have, so when it is set the
timeline is marked `estimated = True` and expansion falls back to `repetitions`/`horizon`.

### 4.3 Protocol entry — `protocol.py`

```
StabilityProtocol(BaseSection, EntryData, PlotSection)

    # --- quantities, inherited first (§4.0 rule 1)
    name               str          # from BaseSection
    datetime           Datetime     # from BaseSection
    lab_id             str          # from BaseSection
    description        str          # from BaseSection
    version            str
    isos_specification str          # e.g. 'ISOS-L-2'  (free enum for now)
    isos_deviations    str
    horizon            str          # "1000 h" — expansion cut-off

    # --- sub-sections, always after every quantity (§4.0 rule 2)
    channels      Channels          # declared ONCE, here
    protocol      Protocol          # the root of the recursion
    timeline      ProtocolTimeline  # DERIVED
    summary       ProtocolSummary   # DERIVED — decision #13
```

Channels are declared only at the entry level; every node's `channel` must resolve to one of
them. The recursive `Protocol` is a separate class from the entry so that the entry is not
itself repeatable and does not carry `repetitions`.

```
ProtocolSummary(ArchiveSection)          # DERIVED, flat, indexable, NON-EDITABLE
    total_duration              [h]
    temperature_min/max/mean    [K]      # unit-ful — see below
    irradiance_mean             [W/m^2]
    relative_humidity_mean      [%]
    atmosphere_label            str      # 'N2', 'ambient', 'dry air'
    load_condition_label        str      # 'MPP', 'open circuit', 'MPP + JV every 24 h'
    channels_used               str[]    # channel keys
    states_used                 str[]
    is_cyclic                   bool
    n_jv_sweeps                 int
```

**Non-editable** is achieved the idiomatic NOMAD way: derived quantities simply get **no
`a_eln` edit component**, so the GUI renders them read-only. Populated in `normalize()` by
walking the expanded timeline, then copied into `archive.results.properties` so it is
searchable across the Oasis.

**Where unit safety comes back.** `ProtocolSummary` is per-physical-quantity, so unlike the
authored states it *can* be fully unit-ful. `normalize()` knows each channel's declared
`unit`, converts, and writes real `Quantity(unit='K')` fields. So decision #14's compromise
never reaches the layer that search and cross-protocol comparison actually use — which is
the layer where a unit error would do real damage.

**Validation the expander performs** (note how much shorter this list is than before):
- command referencing an undeclared channel
- a state the channel does not accept (`accepted_states`)
- leaf protocol with no `duration`
- **R3: children of a `parallel` node writing the same channel** — set intersection over the
  channel sets of that node's children, computed bottom-up. The one check `mode` adds.
- inside a `sequential` node, an infinite child followed by further siblings
- a `parallel` node with no finite child and no `horizon`
- state value outside the channel's `limits`
- **more than one state slot set on a node** — the runtime cost of decision #15
- **a node setting both `channel` and `subprotocol`**, or neither — the #21 discriminator.
  The **root node is exempt**: it is reached through the entry's `protocol:` key rather than
  being a step of anything, so it uses plain `name`.
- **a node with `subprotocol` but no `steps`**, or with `channel` but no state slot
- **`mode: parallel` on a node with no children** — a no-op worth flagging
- **unparseable duration/rate string** — the runtime cost of decision #16
- **unknown channel key**, with a did-you-mean — decision #17

### 4.4 Timeline — `timeline.py`

Column arrays, not repeating sub-sections (decision #12).

```
ProtocolTimeline(ArchiveSection)
    source          enum{simulated, logged}
    estimated       bool
    total_duration  [h];   truncated bool
    n_points        int                   # actual, after budgeting
    messages        str[]

    # column arrays — one section, not 10^5
    time            [s][]
    channel_index   int[]                 # -> channel_keys
    state_index     int[]                 # -> state_labels
    value           float[]               # UNITLESS; the unit is channel_units[i]
    path_index      int[]                 # -> paths

    # small lookup tables
    channel_keys    str[];  channel_units str[]
    state_labels    str[];  paths         str[]   # 'root/cycle[7]/track'
```

`value` stays unitless here because one array carries every channel — the per-row unit lives
in `channel_units`. This is the one place decision #14 propagates into a derived section; it
does not reach `ProtocolSummary`, which is per-quantity and therefore unit-ful.

**Exact in memory, sparse on disk.** The expander computes the *complete, exact* event list in
plain Python — validation (R3, limits, reachability) runs against that, so nothing is missed.
Only a downsampled view is persisted:

```
budget:  n_points ≈ 2000–5000, configurable on the entry point
keep:    (1) every discrete state transition, up to the budget
         (2) the first full repetition of each repeating block at full detail
         (3) remaining budget spent densifying Ramp / Cycle spans
mark:    downsampled = True, and record what was dropped in `messages`
```

Rationale for (2): a 1000-cycle overview plot is unreadable anyway; what people actually want
is the whole run coarsely plus one cycle in detail. That is two figures from one budget.

**The simulated timeline is a visualization artifact, not data.** Nothing downstream should
compute from it — measured values live in `StabilityResult`, and searchable scalars live in
`ProtocolSummary`. That is what makes a fixed budget safe. A `source = logged` timeline parsed
from a real instrument log is different: it *is* data, so it should be HDF5-backed by the same
argument as §4.5 rather than budgeted.

### 4.5 Results — `results.py`

```
StabilityMeasurement(Measurement, EntryData, PlotSection)
    # inherited: samples (CompositeSystemReference[]), instruments, results, datetime, ...
    protocol        -> StabilityProtocol
    t_zero          Datetime
    aging_time      [h]                   # clock that pauses during interruptions
    wall_clock_time [h]
    interruptions   Interruption[]
    actual_timeline ProtocolTimeline      # source = logged, if the instrument logged commands

StabilityResult(MeasurementResult)
    channel_series      ChannelTimeSeries[]    # ACTUAL T(t), irradiance(t), RH(t)
    performance_series  PerformanceTimeSeries  # PCE(t), Voc(t), Jsc(t), FF(t), Pmpp(t)
    jv_snapshots        JVSnapshot[]
    metrics             StabilityMetrics

ChannelTimeSeries(ArchiveSection)
    channel -> StressChannel; time[]; value[]; uncertainty[] (opt)

StabilityMetrics(ArchiveSection)
    t80, ts80, tT80, te80, t90 [h]
    initial_efficiency, degradation_rate, extrapolated_lifetime
```

- **Array quantities need HDF5 backing.** `nomad.datamodel.hdf5` (`HDF5Dataset`,
  `HDF5Reference`) is available in this distro. A 1000 h MPPT log at 1 Hz will not survive as
  a plain metainfo list. Decide before the first real upload, not after.
- **`StabilityMetrics` scalars should be pushed into `archive.results.properties`** in
  `normalize()` so they are searchable across the Oasis.

---

## 5. Module layout

```
src/nomad_pv_stability_measurements/
  schema_packages/
    channels.py       Channels container, StressChannel + subclasses,
                      SpectrumDefinition, RegulationLaw
    states.py         Ramp, Cycle, Tabulated, Sweep (the non-scalar command slots)
    units.py          human duration/rate string parsing — decision #16
    protocol.py       Protocol (the single node type), StopCondition,
                      StabilityProtocol (+ plotting)
    timeline.py       ProtocolTimeline (column arrays + lookup tables)
    results.py        StabilityMeasurement, StabilityResult, metrics
  simulation/
    expander.py       pure python, dataclasses only, no metainfo
    validate.py       the checks listed in 4.3
tests/
```

One `SchemaPackage` / one entry point, all modules imported into it.

---

## 6. Worked example — a real `.archive.yaml`

ISOS-L-2: 65 °C, 1 sun, MPP tracking, JV sweep every 24 h, for 1000 h.
This is the actual file a user would write, not pseudo-notation. Every readability decision
in §10 is visible here.

```yaml
data:
  m_def: nomad_pv_stability_measurements.schema_packages.protocol.StabilityProtocol
  name: ISOS-L-2 light soak, 65 C, MPP with daily JV
  isos_specification: ISOS-L-2
  horizon: 1000 h

  channels:
    temperature:
      - key: chuck_T
        unit: celsius
        limits: [20, 90]
        regulation: {kind: pid, kp: 2.0, ki: 0.1}
        observe_every: 60 s
    irradiation:
      - key: sun
        unit: suns
        spectrum: AM1.5G
        observe_every: 60 s
    electrical_load:
      - key: bias
        unit: volt
        idle: open_circuit
        observe_every: 60 s

  protocol:
    name: light soak
    mode: parallel                     # the three steps below all run at once
    steps:
      - {channel: chuck_T, hold: 65}   # unbounded -> spans the whole protocol
      - {channel: sun, hold: 1}        # unbounded -> spans the whole protocol
      - subprotocol: daily cycle
        repetitions: 42
        mode: sequential               # ... while these two alternate inside it
        steps:
          - {channel: bias, track: mpp, duration: 24 h}
          - channel: bias
            sweep: {from: -0.2, to: 1.3, rate: 50 mV/s, direction: both}
```

Read it as: *"light soak runs three things at once — hold the chuck at 65 °C, hold 1 sun, and
run the daily cycle 42 times; the daily cycle is 24 h of MPP tracking followed by a JV sweep."*
That is the protocol in one English sentence, and the YAML has the same shape.

R3 holds: the three parallel children write `chuck_T`, `sun` and `bias` — disjoint. Inside
`daily cycle` both children write `bias`, which is fine because that node is `sequential`.

### The variant that motivated parallelism

Heater ramped down over the last 100 h. Only the `chuck_T` line changes — it becomes a
`sequential` node of its own, still running in parallel with everything else:

```yaml
  protocol:
    name: light soak
    mode: parallel
    steps:
      - subprotocol: thermal profile
        mode: sequential
        steps:
          - {channel: chuck_T, hold: 65, duration: 900 h}
          - {channel: chuck_T, ramp: {from: 65, to: 25}, duration: 100 h}
      - {channel: sun, hold: 1}
      - subprotocol: daily cycle
        repetitions: 42
        mode: sequential
        steps:
          - {channel: bias, track: mpp, duration: 24 h}
          - channel: bias
            sweep: {from: -0.2, to: 1.3, rate: 50 mV/s, direction: both}
```

Neither branch has to know the other's duration.

### What it would have looked like without §10

The first two commands, using plain polymorphic sub-sections, SI-only numbers and path
references:

```yaml
  channels:
    - m_def: nomad_pv_stability_measurements.schema_packages.channels.TemperatureChannel
      key: chuck_T
  protocol:
    subprotocols:
      - channel: '#/data/channels/0'
        state:
          m_def: nomad_pv_stability_measurements.schema_packages.states.Hold
          value: 65
      - name: daily cycle
        repetitions: 42
        subprotocols:
          - name: track
            duration: 86400        # and 'steps' was 'subprotocols'
```

Two lines became eleven, `24 h` became `86400`, and `chuck_T` became `#/data/channels/0`.
That is what the schema produces by default, which is why §10 is a set of deliberate
decisions rather than formatting advice.

---

## 7. Deliberately deferred

Kept out of iteration 1 on purpose. Each is additive — none requires reworking the core.

- **ISOS conformance checking.** For now `isos_specification` is a string and
  `isos_deviations` free text. Later: ship the ISOS envelopes as YAML data in the package and
  validate the expanded timeline against them. Deliberately *not* a class hierarchy —
  `ISOSL2Protocol(StabilityProtocol)` would not survive an ISOS revision.
- **`to_task()` / workflow integration.** Now a better fit than before — see §1.
- **Reuse of `SolarCellJV`**, `nomad-measurements`, `perovskite-solar-cell-database`.
- **Parsers.** Nothing about file formats yet.
- **Extra channels** ISOS eventually wants: UV content/filter, encapsulation & enclosure,
  reverse-bias polarity.

---

## 8. Open points for you

**(a) Recursion depth.** `SectionProxy` self-reference works in NOMAD metainfo, but the ELN
editor gets unpleasant past ~3 levels — and this design now uses nesting for *everything*,
so real protocols will be deeper than before. This is the main cost of the new shape. Cap
depth with a warning, or leave unbounded?

**(b) What can `StopCondition` reference?** A channel only, or also a performance metric
("repeat until PCE < 80 % of initial")? The latter is the scientifically interesting case but
crosses the protocol/results boundary. Suggestion: a free-text/enum `observable` field rather
than a hard reference, keeping the layers separate.

**(c) Naming.** Recursive unit = `Protocol`, entry = `StabilityProtocol`, field =
`steps`, block marker = `subprotocol`. Reads well, slightly odd that a "Protocol" is nested
in a "StabilityProtocol". Alternatives for the recursive unit: `ProtocolBlock`, `Stage`,
`Segment`. Also `StressChannel` vs plain `Channel` / `Variable`. Fix now — renaming metainfo
after data exists is painful.

**(d) ~~Does `Command` earn its own class?~~ — settled by decision #15.** It does: `Command`
is now the section that carries the named state slots, so it is doing real work rather than
just pairing a channel with a state. `{channel: bias, track: mpp}` is also the most readable
line in §6.

**(e) Where does `duration` live on non-leaf protocols?** Derived from children (sum ×
repetitions, or max over a parallel group), or allowed to be set explicitly as a cross-check?
I lean **derived, with an optional `expected_duration` for validation**.

**(j) Sparse-budget policy.** §4.4 proposes: keep every discrete transition, plus the first
full repetition of each repeating block at full detail, then spend what is left densifying
ramps and cycles. Confirm the budget (~2000–5000 points) and whether the "first full
repetition at full detail" rule is worth the extra code — it exists so the overview plot and
a readable single-cycle plot come out of one budget.

**(k) `unit` as enum or free text?** §9.3 argues for a per-subclass enum with suggestions, so
decision #14 loses unit *conversion* without also losing controlled vocabulary.

**(l) ~~`execution: DoSimultaneously` vs `parallel: true`~~ — settled by decision #19.**
Neither: `mode: sequential | parallel` on the node whose children it governs.

**(m) How far to take the scalar-slot shorthand?** `hold: 65` and `track: mpp` are scalars
because those states have a single meaningful field. `ramp: {from: 65, to: 25}` could also
accept `ramp: [65, 25]`. Terser, but list-positional arguments are a readability trap once
there are three of them. I lean **stop where §6 stops**.

**(f) Is `Off` really universal?** For `AtmosphereChannel`, "off" is ambiguous — is that
vacuum, ambient, or "stop regulating"? May need `Uncontrolled` as a distinct state from
`Off`, which would also be the honest state for ISOS-O outdoor channels.

**(g) Join semantics for a `parallel` node.** §4.2 proposes: a child's state ends with that
child; the parent's duration = max over *finite* children; a child with no duration is
truncated to that max rather than erroring. That last one is what makes "heater runs as long
as the cycling does" work without duplicating a duration. Confirm, or pick first-to-finish
instead of join-all.

**(h) ~~Naming of the execution enum~~ — settled by decision #19.** `mode: sequential |
parallel`, defaulting to `sequential`. Remaining nit: the field could be `mode`, `run`, or
`children_run`. `mode` is short and sits next to `steps`, which reads well.

**(i) ~~Should `commands` be sugar for a parallel leaf?~~ — settled by decision #20.** Yes,
and more than sugar: `commands` is gone entirely. A command is a node that names a channel,
so there is now exactly one child list and one ordering rule.

---

## 9. Scalability issues

Ranked by how likely they are to actually bite. The first three should be settled before
writing code; they change the schema, not just the implementation.

### 9.1 Timeline storage — **RESOLVED (decision #12)**

Repeating sub-sections are `MSection` objects that land in the archive one by one, and a
densified ISOS-LC protocol is 10⁵–10⁶ events. Resolved two ways at once, see §4.4:

- **column arrays** instead of `SetpointEvent[]` — one section rather than 10⁵, and the
  per-event `protocol_path` string becomes an index into a small path table;
- **a fixed sparse point budget** (~2000–5000) for `source = simulated`, since a simulated
  timeline is a *visualization artifact*, not data. Expansion stays exact in memory so
  validation is unaffected; only the persisted view is downsampled.

Open residual: a `source = logged` timeline parsed from a real instrument command log **is**
data, so it should be HDF5-backed rather than budgeted. Same argument as the result arrays.

### 9.2 Protocol findability — **RESOLVED (decision #13)**

`ProtocolSummary` (§4.3): flat, derived, non-editable, populated in `normalize()` from the
expanded tree and copied into `archive.results.properties`. Non-editability comes free by
giving derived quantities no `a_eln` component.

This is also where unit safety returns after decision #14 — see §9.3.

### 9.3 Units — **RESOLVED (decision #14, option (i) refined)**

Generic states carry plain unitless numbers; the **channel** declares the unit once. Avoids
the N × M class explosion that per-channel state subclasses would have caused, and keeps the
"one new subclass per new stress" promise intact.

Two refinements make the compromise much narrower than plain option (i):

1. **Time stays unit-ful everywhere** — it is the one dimension shared by all channels. This
   is why `Ramp` is specified as `start / end / duration` rather than by a rate: a rate would
   be K/min on one channel and suns/min on another, dragging the problem into the time axis
   for nothing. Rate is derived.
2. **Channel-specific states stay unit-ful** — `Track` and `Sweep` are only accepted by
   `ElectricalLoadChannel`, so `scan_rate` really is `Quantity(unit='V/s')`.

So the loss is unit checking on the value axis of five generic states, and nothing else.

**What compensates:**
- `ProtocolSummary` is per-quantity and therefore fully unit-ful — search and cross-protocol
  comparison, the places a unit error would actually do damage, are unaffected.
- `StressChannel.limits` is in the channel's own unit, so an out-of-range value is still
  caught even without dimensional analysis.
- Make `unit` an **enum with per-subclass suggestions** (`K` / `°C` for temperature, `suns` /
  `W/m^2` for irradiance) rather than free text, so it is at least controlled vocabulary.
  Without that, decision #14 degrades into ambiguity rather than merely losing conversion.

Residual risk to accept knowingly: nothing stops someone typing `65` into a channel declared
in `K`. The `limits` check catches the plausible cases; a per-subclass sanity range in
`normalize()` would catch the rest, if it proves necessary.

### 9.4 Incommensurate periods — **resolved by decision #11**

Two channels cycling at different periods (ISOS-LT: thermal cycling on one period, light
cycling on another) do not nest, and a pure tree would have forced flattening to the least
common multiple.

Two independent escapes now exist:

1. **Periodicity is a state, not a structure.** `Cycle(period=12 h)` set at the root runs for
   the whole root scope regardless of what steps below it do at 24 h. Different
   periods on different channels cost nothing.
2. **`mode: parallel` handles the residual case** — two channels needing structurally
   different repeating *sequences* at incommensurate periods are simply two children of a
   `parallel` node, each with its own `repetitions`. R3 is satisfied automatically because
   they drive different channels. No LCM anywhere.

**Rule still worth writing down:** prefer `Cycle` for periodic *stress* and `repetitions`
only for repeating *structure*. It keeps the tree shallow (§9.5), which is now the only
reason to prefer it.

### 9.5 Tree depth in the ELN — usability, not correctness

A realistic ISOS-LC protocol nests root → phase → day cycle → light period → track/sweep.
Five levels of NOMAD sub-section editor is unpleasant, and this design uses nesting for
*everything*, so it will be deeper than the flat instruction list was.

Mitigated by decision #5: this schema *describes* runs rather than authoring them, so
protocols mostly arrive from parsers. The browse experience still matters, so the protocol
plot and `ProtocolSummary` (§9.2) carry more weight than they otherwise would — they are what
people will actually look at instead of the tree.

### 9.6 Protocol edit drift

The protocol is a shared, referenced entry. Editing one that 200 measurements already point at
silently changes what those measurements claim. `version` exists but there is no policy.
Options: treat published protocols as immutable and copy-on-edit, or snapshot the resolved
timeline into each measurement. Process problem, but it scales with adoption, so decide early.

### 9.7 Stable channel keys — **folded in**

`Protocol.channel` and `ChannelTimeSeries.channel` resolve by object reference, and a parser
matching a data column to a declared channel needs a stable handle; `name` is human-editable
and will be renamed. `StressChannel.key` is now in §4.1 — decision #12 forced the issue
anyway, since the timeline's `channel_keys` lookup table needs exactly such a handle.

Still open: 9.4 is resolved by decision #11, 9.5 is usability only, and **9.6 (protocol edit
drift) remains genuinely unresolved** — it is the only scalability item still needing a call,
and it is a policy question rather than a schema one.

---

## 10. YAML ergonomics

The four decisions (#15–#18) that make §6 readable. The first two are backed by behaviour I
checked against this distro's `nomad-lab`, not assumed.

### 10.1 Never write `m_def` by hand — use named slots

**Checked.** For a sub-section declared as an abstract base `State` with subclass `Hold`:

| YAML | Result |
|---|---|
| `state: {value: 1}` | silently instantiates **`State`**, the base class — no error |
| `state: {m_def: Hold, value: 1}` | `MetainfoReferenceError: Could not resolve Hold` |
| `hold: {value: 1}` | ✅ `Hold` |

So the polymorphic form is both *unreadable* (it needs the fully-qualified
`nomad_pv_stability_measurements.schema_packages.states.Hold`, ~60 characters, once per
state) and *unsafe* (omitting it fails silently into the base class).

**Pattern:** replace one polymorphic slot with one named slot per subclass, exactly one of
which may be set — validated in `normalize()`.

```
Protocol(ArchiveSection)             # a node that names a channel is a command — #20
    channel  str                     # a channel key — §10.3
    # exactly one of:
    off      bool
    hold     float                   # scalar! -> `hold: 65`
    ramp     Ramp     ( from, to, duration? )
    cycle    Cycle    ( waveform, low, high, period, duty_cycle )
    tabulated Tabulated ( time[], value[] )
    track    enum{mpp, voc, jsc}     # scalar! -> `track: mpp`
    sweep    Sweep    ( from, to, rate, direction, repeats )
```

`hold` and `track` collapse to plain scalars because decision #18 moved `RegulationLaw` off
the state and onto the channel. Two of the seven states now cost one line each — and since
decision #20 folded `Command` into `Protocol`, a whole command is one line:
`{channel: bias, track: mpp, duration: 24 h}`.

**Apply the same to channels.** A `Channels` container with one repeating slot per channel
type turns a 60-character `m_def` line into the word `temperature:`. The cost is honest and
should be recorded: **adding a channel type is now a new subclass *plus* one line in the
container**, slightly weakening the "one new subclass" promise from decision #10. Worth it —
channels sit at the top of every file and set the tone.

**Cost:** `ChannelState` is no longer a single polymorphic slot, so generic code must check
several fields. Hide that behind one Python property on `Protocol` returning whichever slot
is set; the expander and timeline keep working on a single canonical state object.

### 10.2 Durations and rates as human strings

**Checked.** For `Quantity(type=float, unit='second')`:

| YAML | Result |
|---|---|
| `dur: 24` | ✅ 24 **seconds** — the declared unit, not what the author meant |
| `dur: "24 hour"` | `ValueError: Cannot convert 24 hour to float` |
| `dur: {value: 24, unit: hour}` | `ValueError` |

So NOMAD accepts *only* a bare number in the quantity's declared unit. A protocol mixing
1000 h soaks with 50 ms sweep steps would be written entirely in seconds — `86400`,
`3600000` — which is unreadable and silently wrong if someone assumes hours.

**Pattern:** author these as `Quantity(type=str)` and parse in `normalize()` into a real
unit-ful derived quantity.

```
duration      str      # authored: "24 h", "50 ms", "1000 hours"
duration_s    [s]      # DERIVED, unit-ful, what everything downstream reads
```

Parse with `pint` (already a NOMAD dependency) and raise a clear error on failure. This is
the one place a plain string beats a typed quantity, and it applies to every duration,
period, `observe_every`, and rate in the schema.

Note this interacts well with decision #14: rates like `50 mV/s` are channel-specific
(`Sweep` is `ElectricalLoadChannel`-only), so they are unit-ful anyway and the string simply
carries the unit the author already thinks in.

### 10.3 References by key, never by path

NOMAD serializes a section reference as `#/data/channels/0`. That is unreadable, breaks when
the list is reordered, and is impossible to write by hand correctly.

**Pattern:** `Protocol.channel` is a plain `str` holding `StressChannel.key`, resolved to a
real reference in `normalize()` and stored in a derived `channel_ref`. Validation reports
`unknown channel key 'chuck_t' (did you mean 'chuck_T'?)` — a far better error than a
dangling path.

This is why `key` (§9.7) had to be required and immutable. It now carries three jobs: YAML
references, the timeline's `channel_keys` lookup table, and parser column matching.

### 10.4 What is left that is still ugly

Honest residue, not solved by the above:

- **The root `m_def`** — unavoidable; every NOMAD archive file needs one, and it is one line.
- **Depth.** The parallel example reaches four levels of indentation. Flow style
  (`{name: track, duration: 24 h, ...}`) keeps leaf protocols to one line, which helps a lot,
  but a deeply structured protocol will still be a deeply indented file. §9.5.
- **`mode: parallel` / `mode: sequential`** is the one piece of vocabulary a reader has to
  learn. It is one word, it sits on the node it governs, and it is guessable — which is more
  than could be said for the `execution: DoSimultaneously` flag it replaced (decision #19).
  Writing `mode` on every node is optional; `sequential` is the default.
- **`exactly one of` is a runtime check, not a schema constraint.** Setting both `hold` and
  `ramp` is expressible and must be caught in `normalize()`. This is the cost of trading the
  polymorphic slot for readability, and it is the right trade only because the failure is
  loud and immediate.
