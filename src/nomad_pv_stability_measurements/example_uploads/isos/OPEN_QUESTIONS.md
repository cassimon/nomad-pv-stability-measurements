# Open questions about the ISOS protocols

Where Khenkin et al., *Nature Energy* **5**, 35–49 (2020) is silent, ambiguous, or disagrees with
itself, and what the files in this folder do meanwhile. Page numbers are the journal's; "Table 1"
and "Fig. 3" are the paper's. Settling a question may add, change or remove files.

## Blocking — no file is written

### 1. ISOS-LC-3: is the relative humidity *held at* 50 % or kept *below* it?

- Table 1: "< 50%".
- Text, p.39: "At the ISOS-LC-3 level, RH is held at 50% and high temperatures."
- Fig. 3 files LC-3 in the row "Controlled RH = 85 or 50%".

The two readings are different instructions — a bound or a held value — so no file is written.
**Blocks 12 files** (6 light–dark cycles × 65 / 85 °C, MPP).

### 2. ISOS-I: what makes an atmosphere inert?

- p.42: "intrinsic stability of solar cells in inert atmospheres (nitrogen, argon, and so on) …
  with the other parameters kept the same"; Table 2 lists twelve protocols.
- p.42: ISOS-LC-3I and ISOS-T-3I are to be performed "in the absence of humidity".

An inert atmosphere would be written as oxygen and water each kept below a threshold, in a named
gas. **The paper states no threshold** (in ppm) and names the gas only by example.
Which threshold, and is "nitrogen, argon, and so on" one option per gas?
**Blocks the 12 ISOS-I protocols** and their variants.

## Written with a reading — worth confirming

### 3. Is the light cycled in ISOS-LT?

Table 1 writes the light source as "Solar simulator" (where ISOS-LC writes "Solar simulator/
Dark"), but Fig. 3 places LT-1, -2 and -3 in the column "Light: cycled". **The files follow
Table 1**: the light is held under control for the whole test. If Fig. 3 is right, the light
belongs in the routine, cycled by a path the paper does not state.

### 4. How does a thermal cycle move between its two temperatures?

ISOS-T gives "RT to 65, 85 °C" and "−40 to +85 °C"; ISOS-LT-1 offers "Linear or step ramping".
The paper defers the path: "Examples of such cycles are available elsewhere" (p.38) and "the
temperature cycle and some technicalities … are reported elsewhere" (p.42), both pointing to Reese
et al., *Sol. Energy Mater. Sol. Cells* **95**, 1253–1267 (2011). Table 3 asks authors to *report*
"Dwell and period times". **The files write a ramp from one end to the other that cycles by
a path not stated** (`end_of_ramp_behavior: cycle`); the step option of LT-1 the same way. Reese et al. 2011 may fix the path, rates or dwells.

### 5. Humidity controlled only above 40 °C

ISOS-T-3 "< 55%" with footnote b ("controlled at temperatures above 40 °C and is not controlled
for the remainder of the cycle"); ISOS-LT-2/-3 "Monitored, controlled at 50% beyond 40 °C".
Control that depends on another quantity cannot be written yet, so **the files state the value
(`{below: 55 %}`, `50 %`) and monitor it, without `control`, and state the condition in
`notes`**.

### 6. E_g/q — a bias or a ceiling?

Table 1 lists "Eg/q" among the positive biases. The text (p.39): "we recommend voltages below the
bandgap energy divided by the charge of the electron to avoid unnatural overstressing". **The
files follow the text**: no E_g/q bias; the ceiling is named in the `notes` of the V_MPP and V_oc
biases.

### 7. Open circuit at ISOS-LT-3

Table 1 offers "MPP or OC"; the text (p.37): "we indicate MPP tracking as mandatory only at the
third, most advanced level of ISOS protocols". **The files follow the text**: ISOS-LT-3 tracks
the MPP only.

### 8. The negative biases

- "−VOC" is "for example" in the text (p.39: "a constant negative bias applied (for example,
  −VOC)"). **Written as the only negative voltage**, as Table 1 lists it — are others meant?
- Table 1 writes "JMPP" under "Negative"; the text writes "−JMPP" ("the current enforced up to
  −JMPP"). **The files follow the text.**

### 9. Room temperature where the table writes "RT"

p.36 defines it for ISOS-D-1: "room temperature in the laboratory is assumed to be 23±4 °C".
**The files read every "RT"** (ISOS-T-1/-2, ISOS-LT-1) and every "Ambient (23 ± 4 °C)" **by it**.

### 10. The recommended irradiance — for which protocols?

p.43: "Ideally, light sources with an irradiance of 800–1000 W m–² (1 sun = 1000 W m–²) should be
applied". **Every solar-simulator protocol (ISOS-L, -LC, -LT) holds the irradiance between 800 and
1000 W m⁻²**, as its only light: the recommendation is read as the standard's light, since a solar
simulator at no stated irradiance says nothing a reader can use. Sunlight (ISOS-O) is only
monitored. (Until 2026-09: a variant without an irradiance beside one with the range.)

### 11. Smaller readings

- ISOS-L-3's "~ 50%" is written as a relative humidity of 50 %, with no tolerance for the "~".
- ISOS-O-1 and -O-2 differ only in the light the J–V curves are measured under (p.37), which the
  protocol files do not describe; they are identical but for `standard` and `notes`.
- MPP tracking is "encouraged … whenever possible" (p.37) at the levels where it is not mandatory.
  That is a preference among load options, which the files keep as separate variants.
- The minimum ageing time, "at least 1000 h" when T80 is not reached (p.44), is a stop condition
  and not written yet.

### 12. What is logged

The paper asks for monitoring outright only where a condition is not controlled: the ambient
temperature and humidity ("monitored but not explicitly controlled", p.36; "the temperature and
RH are monitored, but not controlled", p.39; "even if a parameter is not controlled … it is still
important to monitor and report", p.43), the outdoor weather ("preferably in tabulated format",
Table 3), and ISOS-LT's humidity ("Monitored", Table 1). For what it controls, it asks for things
to report: the temperature "sensor type", "RH (controlled or monitored)" (Table 3), the exact
irradiance and a periodic check "with a reference cell" (p.43–44). **The files log only the
first group**, and MPP tracking, which "measures the output" (p.43). ISOS-T-3's humidity is
logged too: it goes uncontrolled below 40 °C. Is a controlled temperature meant to be logged
after all?
