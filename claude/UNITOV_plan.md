# Plan: reading UNITOV's runs, and what it takes to add the next institution

Status: **proposed, not built.** Edit freely. Decisions you have already taken are
marked **(decided)**. Open points are in the last section.

---

## 1. What UNITOV's files contain

`example_uploads/institutes/UNITOV/example_batch/<device>/<device>_<pixel>/<HH.MM.SS>/`

- **One timestamp folder is one run of one pixel.** There are 18 runs over 6 pixels:
  AI14-1A/1B/1C and AI22-1A/1B/1C. The folders `1D` are empty. Pixels of one device start
  at the same second, each on its own SMU channel (`Note: SMU 1A`).
- A run folder holds these files:

  | File | Header | Data |
  |---|---|---|
  | `0000_…_Stability (Tracking)_<dev>.txt` | `Algorithm` (here `Fixed Voltage`), `dV track`, `track delay`, `JV interval (min)`, `Test duration (min)`, `Start-up Time` | time in hours, V, J (mA/cm²), P (mW/cm²) |
  | `0000_…_Stability (Parameters)_<dev>.txt` | J–V settings | one row per J–V scan: hours since the start, and each figure of merit for FW and RV |
  | `000N_…_Stability (JV)_<dev>.txt` (0–2 per run) | J–V settings, its own `Time` | a figures-of-merit table, then the curve with FW and RV side by side |

- **Format:** tab-separated, CRLF line endings, **Latin-1** (the `²` in `mA/cm²` is the byte
  0xB2). There is a `## Header ##` part with `[Section]` blocks of `key<TAB>value` lines, then
  a `## Data ##` part.
- The FOM table of a J–V file has its **units on a separate row**. `FF` and `Eff` are in %.
  `Rs` and `R//` are labelled `Ohm` but are **Ω·cm²** **(decided)**.
- In the curve, FW runs from −0.1 V to about V_oc (Voc is auto-detected) and RV runs back
  down. The two columns can differ in length. J is positive where the cell delivers
  power, the same convention as the schema.
- **Parameters has a row for a J–V scan whose file is missing** in 3 runs:
  `AI14_1C/17.23.47`, `AI22_1C/17.33.33` and `AI22_1C/21.18.55`.
- **The fixed voltage is not in any header.** The data holds it at 1.40 V, which is the
  intended set point **(decided)**. That is forward bias beyond V_oc ≈ 0.73 V, so J and P
  are negative.
- **Temperature, irradiance and humidity are neither recorded nor stated.**

## 2. Mapping onto the schema

| UNITOV | Goes to |
|---|---|
| one run folder | one `StabilityMeasurement` entry. Its **anchor** (mainfile) is the Tracking file |
| `User` | `operator` |
| `Device` (`AI14-1A`) | `samples: [{name: 'AI14-1A'}]` |
| `Note` (`SMU 1A`) | `instruments: [{name: 'SMU 1A'}]` |
| `Start-up Time` (dd/mm/yyyy, Europe/Rome) | `datetime` |
| `Cell area`, `Tipology` | -> create these as new fields in a boiler blade sample dataschema Reference it in the activity. Comment this will later be replaced. |
| Tracking data | `StabilitySeriesStep`: `time`, `voltage`, `current_density`, `power_density`, `controlled: [voltage]` |
| Tracking settings | the new tracker fields of the series step (§5.2) |
| each J–V file | `JVSweepStep`: FW/RV turned into long form with `direction`, FOM rows into `figures_of_merit`, J–V settings into the new sweep fields (§5.2) |
| a Parameters row with no J–V file | `JVSweepStep` with `figures_of_merit` only, and `start_time` = start + hours |
| J–V header `Date` + `Time` | step `start_time` |
| settings of the Tracking header | the embedded protocol (§6) |

The steps are ordered by `start_time`. The J–V scans fall inside the tracking series,
because the tracking pauses for them. The overview figure already places each step by its
own time.

## 3. Extensibility: what the next institution has to do

Today, adding an institution means writing its module, listing it in `INSTITUTIONS`, and
**widening the entry point's regex**. UNITOV also breaks the assumption that a run file
lists its steps. The changes:

1. **Matching.** Set the entry point's `mainfile_name_re=r'.*'` and let `is_protocol_file`
   decide, which the template already requires. After that, adding an institution means
   writing its module and adding one line to `INSTITUTIONS`.
   *To check:* that NOMAD applies the entry point's regex nowhere else, and that a `.*`
   match costs nothing for uploads with thousands of files. `is_protocol_file` looks at
   the name before the content.
2. **A run without a run file.** Reword the template: the "run file" is **the one file per
   run that stands for it**, and `read_protocol` may collect the step files around it
   (a folder, a shared prefix, …). The interface does not change.
3. **Steps without a file.** A step in `read_protocol` may carry `figures_of_merit`
   inline instead of, or beside, `file`. `read_files` changes by a few lines. This covers
   any lab that logs only FOMs over time, which many stability set-ups do.
4. **Assumed conditions.** Each module gets an optional `ASSUMED_CONDITIONS` (see §6). It
   is empty in the template and SIM, and `{'temperature': 'RT', 'irradiance': '1000 W/m^2'}`
   in UNITOV **(decided)**.
5. **Collections.** A new interface function, `read_collection(path)`, returns `None`
   where an institution has no collections (§7).
6. **Shared helpers in `file_reading_utils.py`.** Only formats that are not specific to
   UNITOV go here:
   - `rename_columns(table, {'Voc': 'open_circuit_voltage', ...}, units={...})`: a lab
     mostly writes one mapping from its column names (and units) to the schema's quantity
     names;
   - `jv_from_side_by_side(v_fw, j_fw, v_rv, j_rv)`: FW/RV in parallel columns of unequal
     length, a common J–V station layout;
   - `files_beside(anchor, is_series, is_jv)`: the step files of a run that is a folder;
   - `encoding` as a parameter of the existing readers.

   UNITOV's `## Header ##` / `[Section]` reader stays in `file_reading_UNITOV.py` until a
   second lab with the same station software needs it.

## 4. The two kinds of entries: runs and collections  **(decided)**

**The physical model.** A cell's life is a **degradation series**: J–V scans taken at
different times, with conditions between them that nobody specified (shelf, glovebox,
transport). It is rarely standardized. Standardized stability runs happen *within* that
life. So data taken outside any planned run is neither lost nor presented as following a
plan it never had. There are two kinds of entry, both of class `StabilityMeasurement`:

| Entry | `plan` | Holds |
|---|---|---|
| **run** (one per run folder) | the protocol it followed | its own steps, as in §2 |
| **collection** (one per **pixel**, the physical device) **(decided)** | the general protocol *Storage and irregular measurements* (below) | `sub_activities` → every run of the pixel, and the **loose J–V scans as its own steps** |

- `StabilityActivity` gets `sub_activities = Quantity(type=Reference(StabilityActivity),
  shape=['*'])`. It is to be replaced by the subactivities of Activity v2 once those
  exist.
- **The general protocol *Storage and irregular measurements*:** no instructions, no
  conditions, no holds, and an **open-ended** duration. It states only that nothing
  between the measurements was specified. A shared helper, `irregular_protocol()` in
  `file_reading_utils.py`, returns it in the authored form, so every institution's
  collections use the same one. *Verified:* `{'data': {'name': …, 'duration':
  'open-ended'}}` translates without problems and normalizes without errors, warnings or
  figure.
- **Which scans are loose** is decided by the institution's reader, never by comparing
  data with the plan. For UNITOV **(decided)**: everything inside a run folder with a
  Tracking file belongs to that run, **including the rows found only in Parameters**.
  Everything else under the pixel's folder is loose, for example a J–V file or a
  Parameters file in a folder without a Tracking file.
- **Later:** the collection links the Device and Substrate it measured, once those exist
  as results of processing entries.
- **The cumulative plot:** the collection draws one figure over time from all its
  sub_activities' steps and its own steps, each placed by its `start_time`. The
  measurement's current overview figure becomes a function over a list of step lists, so
  runs and collections share it.
  *Risk:* resolving references to other entries of the same upload in `normalize` depends
  on the order NOMAD processes them in. *Proposed:* the parser has the files anyway, so it
  reads the sample's runs with the same reader functions, in memory, draws the figure
  there, and stores only the references. This needs verifying before step 6.

## 5. Schema changes

### 5.1 `P_MPP` (decided)
- Add `JVFiguresOfMerit.power_density_at_maximum_power_point` (W/m²), taken as reported.
- In the overview over time, draw each scan's P_MPP as markers on the **power density**
  row. It shares its unit with the tracking series, so tracked and scanned power can be
  compared directly. The efficiency row on top stays as it is.

### 5.2 Settings of the steps (decided)
- `JVSweepStep`: `voltage_start`, `voltage_stop` (the planned range; the data may stop
  earlier because V_oc is auto-detected), `voltage_step`, `scan_rate`, and `scan_order`
  (`forward then reverse`, …).
- `StabilitySeriesStep`, as **flat fields on the step** **(decided)**: `tracking_algorithm`
  (text: `fixed voltage`, `perturb and observe`, …), `tracking_step` (V, `dV track`) and
  `tracking_delay` (s, `track delay`).
- `read_files` fills these through the step dict, as it does `controlled`. A setting a
  step class has no place for is reported, not dropped.

### 5.3 Periodic J–V scan in the protocol (decided: add it)
Design.md deferred this item ("periodic J–V characterization as a step"). UNITOV is the
first real case: `JV interval 0.55 min`.
- A new `JVScan(SingleInstruction)` with `voltage_start`, `voltage_stop`, `voltage_step`,
  `scan_rate`, `scan_order`, and the light it is measured under (`irradiance`).
- How "every 0.55 min" is written. The options:
  a. `JVScan.interval`: one instruction, with duration `whole block`, that scans every
     `interval`. It is simple to author (`jv_scan: {every: 0.55 min, …}`) and drawn as
     ticks on the timeline.
  b. A `TimedRepeatingBlock` of `[JVScan, pause]`. This needs a new `Pause` instruction
     that exists nowhere yet, and it states the scan's own duration, which a protocol
     rarely knows.

  **Recommended: a.** It is what ISOS and the labs write ("J–V every x"), and a
  combination that makes no sense cannot be written.
- The translator gets a `jv_scan` word, the timeline draws the scans, and the ISOS files
  that mention periodic J–V only in their `notes` stay unchanged for now.
- This is the largest change, so it is built last (step 7).

## 6. The embedded protocol of a UNITOV run

Every run file describes its test, so each run also makes a `'protocol'` child entry
(through `read_embedded_protocol` and `protocol_from_phases`):

- **one phase**, lasting `Test duration` (1 min), in which:
  - the electrical load follows `Algorithm`. `Fixed Voltage` holds the voltage (`hold`);
    other algorithms map to `mpp`, `open_circuit`, … as they turn up;
  - the **set voltage** is taken from the header where a key states it. Otherwise it is
    **the mean of the recorded voltage, rounded to 1 mV** (1.400 V) **(decided)**;
  - `temperature` and `irradiance` come from `ASSUMED_CONDITIONS` (RT, 1000 W/m²) where the
    files do not state them **(decided)**;
- a `jv_scan` every `JV interval`, with the header's J–V settings. This depends on §5.3;
  until that is built, the scan goes in `notes`.
- **`notes` names every value that was assumed or worked out rather than read**: "The
  voltage is the mean of the recorded voltage; temperature and light are UNITOV's standard
  conditions, not stated in the files." This is an **exception** to "the protocol is what
  the file says was planned, never inferred from the data". It is allowed per
  institution, and always said. Design.md §34.4a gets amended to match.
- `ASSUMED_CONDITIONS` is generic. `protocol_from_phases` fills in only what a phase
  leaves out, so any institution can declare its own, or none.

The 18 protocol entries are identical. Keeping one entry per protocol is Design.md §35,
which is still open.

## 7. Parser: which entries one anchor file makes

- A run's anchor (the Tracking file) makes the run entry and its `'protocol'` child.
- A pixel's collection needs a mainfile of its own: **the anchor of the pixel's earliest
  run** also makes the children `'collection'` and `'collection protocol'` (the general
  protocol of §4). That is deterministic from the folder listing, so it needs no second
  pass.
  - `read_collection(anchor)` returns `None`, or
    `{'name', 'samples', 'runs': [anchor paths], 'steps': [loose steps]}` where this anchor
    is the pixel's first run.
  - `sub_activities` are filled with
    `../upload/archive/{generate_entry_id(upload_id, run_anchor)}#/data`. Entry ids are
    deterministic, so it does not matter which entry is processed first.
  - `is_mainfile` returns `['protocol', 'collection', 'collection protocol']`,
    `['protocol']`, or `True`.
- A pixel with loose scans but **no** run still gets a collection, because no data is lost
  **(decided)**. Its anchor is the first loose file (sorted by path). That file makes the
  main entry, which is the collection itself, and its `'collection protocol'` child.
- With one general protocol per collection, the 6 collections make 6 identical protocol
  entries. Keeping one entry per protocol is Design.md §35, which is still open.

## 8. Steps (each one reviewed before the next)

0. Remove the `.DS_Store` files from `institutes/` and add them to `.gitignore`.
1. **Matching:** entry point `.*`, the reworded template, and `ASSUMED_CONDITIONS` and
   `read_collection` in the template and in SIM. SIM must behave exactly as before.
2. **UNITOV readers:**
   - the Latin-1 header/table reader, `read_stability_series` and `read_jv_file`;
   - the helpers `rename_columns` and `jv_from_side_by_side`;
   - Rs and R// read as Ω·cm², FF and Eff from %;
   - `tests/file_reading/test_file_reading_UNITOV.py` on one real folder.
3. **Schema §5.1 and §5.2:** the P_MPP field and its markers in the overview, and the
   settings of the J–V sweep and the tracker, each with a test.
4. **Runs:** `read_protocol` for UNITOV (the folder as the run, Parameters rows without a
   file as FOM-only scans), and inline `figures_of_merit` in `read_files`.
   *Test:* the run with a missing J–V file still has two scans.
5. **Embedded protocol:** `ASSUMED_CONDITIONS`, the mean voltage, and `notes`.
   *Test:* the protocol entry, and the run's `plan` pointing to it.
6. **Collections:** `sub_activities`, `irregular_protocol()`, the `'collection'` and
   `'collection protocol'` children, loose steps, a collection anchored at a loose file,
   and the cumulative figure. Verify the reference and ordering question of §4 first.
   The example batch has no loose scans, so a test adds a folder of loose files.
7. **§5.3 `JVScan`:** schema, translator word, timeline, and use in the UNITOV protocol.
8. **Example upload and docs:**
   - an entry point for `institutes/UNITOV/*`;
   - an upload test like `test_simulated_runs.py`: every run and collection through NOMAD's
     `parse` and `normalize_all` with no errors, and each `plan` and `sub_activities`
     pointing to entries in the upload;
   - Design.md gets a new §37 (and amendments to §34.4a and §20.8); CLAUDE.md is updated.

## 9. Open points

- **The HZB folder** is empty; waiting for its files. HZB is the test of §3: it should
  need only its module and one line in `INSTITUTIONS`.

Decided (2026-09-23): a collection per pixel (§4); Parameters-only scans belong to the run
(§4); a collection even without a run (§7); tracker settings as flat fields (§5.2); the
general protocol *Storage and irregular measurements* (§4).
