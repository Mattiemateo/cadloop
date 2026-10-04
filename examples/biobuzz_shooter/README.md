# BIOBUZZ shooter prototype — 608 bearing edition

A real CADLoop task: a compact hooded shooter, a cast-tire mold, and reusable 608 bearing parts. **Geometry accepted; engineering approval remains false.** This is a fabrication prototype, not a demonstrated scored shot or an inspection certificate.

Generated STEP/STL, cut files and the delivery ZIP are local outputs under ignored `work/` or `artifacts/`; this repository versions their design sources and export scripts.

## Delivered geometry

| Item | Specification |
|---|---|
| Assembly envelope | 303.014 × 143.55 × 264 mm (X × Y × Z), measured from exported solids |
| Structure | Three laser-cut 3 mm plywood panels; printed fastened components |
| Flywheel | 100 mm OD × 40 mm tire width; printed keyed core; cast 25A silicone |
| Bearings | Two supplied 608 bearings, 8 × 22 × 7 mm, printed 5 mm hex sleeves |
| Hood | 65° outlet above horizontal; separately checked 70° replacement included |
| Hood clearance | 118.12 mm inside radius: nominal POLLEN compression 3 mm; drawing-maximum sphere compression 5.54 mm |
| Drive | REV UltraPlanetary zero-stage 1:1; 10T:10T #25 chain; nominal centers 76.2 mm |
| Camera | Front Limelight 3A, 20° upward; rear M3 pattern 64 × 8 mm |
| Turret adapter | Replaceable 88 mm square; 60 mm shooter pattern and provisional 76 mm turret pattern |
| Square nut pockets | 5.6 × 5.6 × 2.8 mm throughout the fabricated interfaces |

Coordinates: +X shoots forward, +Z up, shafts parallel Y. The turret mounting plane is Z=0. The starting-height calculation assumes that plane is **180 mm above the tiles**, giving a 444 mm total height. The fixed assembly needs a deck **no higher than 193.2 mm** to fit the 457.2 mm starting-height limit; the rest of the robot must also fit. Actual turret pattern, deck height, and REV kit version await confirmation. Compactness was pursued by packaging the motor above the wheel; no global size optimum is claimed.

## Files and fabrication

The delivery ZIP contains untouched CADLoop `shooter/` and `mold/` finish exports (STEP, BREP, checks, previews and hash manifests), `manufacturing/`, sources, and test evidence. `manufacturing/manufacturing_manifest.json` identifies each printable file, orientation, quantity and its verified source. Print the core once: the mold's core insert represents the same part. The silicone-tire STL is a casting reference, **not a filament-print part**.

DXF files are in millimetres at 1:1, with no kerf compensation. The combined sheet is 600 × 400 mm. Confirm the base-panel outline is 284 × 96 mm in the laser software, measure the actual plywood, and cut a hole/nut-fit coupon before cutting the complete sheet. Apply measured kerf compensation in CAM. Inspect for char, delamination and cracks around small fastener holes.

Use the manifest's print orientations. The hood needs approximately 243.05 × 124.52 mm of bed area at 65° (248.13 × 124.52 mm at 70°), plus brim/clearance. A 220 mm bed does not fit that orientation. The wheel core's raised hub/flanges and the inclined camera plate need supports. Both mold halves print with their broad exterior faces on the bed and their cavities upward; the upper half has a flat exterior with a recessed funnel. Choose print material and wall/infill settings through physical testing; no strength is established by CAD.

The two plywood side panels are common to both hood variants; the forward hood fastener uses an arc slot. Angles 55–72° fit the intended slot, but only 65° and 70° have completed geometry checks. Only the nominal 76.2 mm motor spacing is delivered: the horizontal mounting slots provide physical chain-tension adjustment, and are not a validated parametric redesign of the drivetrain.

## Assembly

1. Fit-test one carrier, retainer and sleeve with an actual bearing, REV shaft and your square nuts. Seat diameter is 22.15 mm, seat depth 7.15 mm; sleeve OD is 7.95 mm, hex bore 5.10 mm across flats. These are provisional printer clearances. Bearings must seat squarely, the shaft must run concentrically, and retainers must not clamp rotating races or seals.
2. Insert captured nuts before closing interfaces. Fit the turret adapter to the base, feet to the base and panels, then hood and chute between panels. Install the bearing carriers and retainers with their nut pockets facing outward. Verify fastener access before tightening.
3. Make the cast flywheel as below. Install the 140 mm main shaft through the two sleeves and wheel. Use kit collars to retain the wheel and shaft, allowing rotation without axial preload. Nominal axial positions and stock-cut allowances are in BOM.md.
4. Assemble the UltraPlanetary with **no reduction cartridges**, following REV's zero-stage instructions. Fit its static output-case mounting holes to the printed motor plate. Fit the nominal 45 mm driver shaft only after confirming socket engagement and set-screw access on the actual gearbox.
5. Fit two 10T sprockets, align their **tooth planes**, then fit the 34-pitch closed chain loop. Adjust tension using the mounting slots. Check the master link, shaft collars and guard clear the moving chain through a complete rotation. Chain and most individual fasteners/collars are specified but not simulated as complete detailed solids.
6. Install the Limelight using its rear M3 threads; verify screw engagement rather than bottoming screws in the camera. Attach the front mount and route camera/motor wiring outside the ball and chain paths, with slack appropriate to turret motion.
7. At low unpowered speed, turn the wheel so a ball on its left moves down, passes underneath, then leaves toward **+X and +Z**. In an X-right/Z-up side view this is counterclockwise. The exit tangent is 65° upward, not the radial angle of the hood end.

The current gravity chute is for a separate robot feeder to supply one ball at a time. A complete intake, indexing system, turret, wiring harness and control program are outside this assembly.

## Casting the 25A tire

Print one keyed core and the two mold halves. Smooth/seal the cavity as required by the chosen silicone and release system; print surface finish transfers to the tire. Confirm a cure coupon with all printed/sealant/release materials. Shore 25A alone does not specify chemistry, shrinkage, density, adhesion or allowed rotation speed.

Place the core on a released/masked 50 mm stock 5 mm hex mandrel, seat it between the mold hub recesses, and close the alignment pins and four M3 clamp screws. Seal the split and mandrel interfaces after a leak test. The upper half has a Ø6 mm pour passage with a recessed funnel and three Ø1.5 mm vents. Fill slowly, allow air to escape, and follow the silicone maker's mixing and cure instructions. Trim sprues/flash after demolding; remove the mandrel. Inspect voids and mechanically locked keys. Measure final diameter, width, concentricity, tire/core retention, and balance before powered testing. The finished tire BREP volume is 141.864 mL; allow extra for the sprue, vents and mixing loss according to the chosen process. This volume is not a validated mix mass.

## Launch calculations and physical validation

The model uses the official upward HIVE opening and a worst-drawing-size 73.66 mm sphere. At the provisional deck height, the 65° ball release center is 285.645 mm above the floor. The trajectory is upward at release and descending at the target opening.

| Wheel-axis to lower-lip range | Vacuum speed | Cd=1 assumed speed | Ideal wheel RPM, vacuum–Cd=1 |
|---|---:|---:|---:|
| 1.5 m | 5.583 m/s | 6.178 m/s | 2133–2360 |
| 2.0 m | 6.003 m/s | 6.854 m/s | 2293–2618 |
| 2.5 m | 6.456 m/s | 7.620 m/s | 2466–2910 |

Each drag case is aimed separately. Cd=0, 0.5 and 1 are sensitivity assumptions, **not measured limits for POLLEN**. RPM above assumes ideal wheel/ball speed transfer; divide by measured efficiency (e.g. 0.8 means 25% higher RPM). The motor's 6000 RPM free speed is not a loaded operating-speed guarantee. ±5% launch-speed and ±25 mm lip-height sweeps include misses. The thin opening is checked; basket interior, roof, rim thickness, rebounds, spin/Magnus, lateral errors and wind remain unvalidated. Fixed 65° is a plausible starting point across 1.5–2.5 m; a near-normal downward approach benefits from a lower hood angle at longer range.

Before installation, test actual ball passage with the largest/most distorted POLLEN samples available. The independent sphere audit finds only **0.90 mm minimum non-hood clearance at the feed chute**; this is a real jam-risk tolerance, not a generous fit. Other measured minima include side panels 4.17 mm, core 4.46 mm and motor case 16.06 mm (65°) / 9.54 mm (70°). Tire deformation is intentional but untested.

Use an enclosed bench fixture for progressive speed, balance, retention and loaded-RPM tests. Then record at least 30 shots per intended distance/RPM/hood setting with real POLLEN, measuring exit speed or deriving it from video, shot dispersion, entry point, recovery time, jams and successful scores. Record actual target dimensions and repeat after warm-up and wear. Tune RPM from measurements; rebuild/recheck geometry for any fit, compression or hood change. Verify the complete robot against the current game manual, including starting envelope, four-element control limit and launch restrictions. FLOWER scoring is not optimized here.

## CADLoop evidence and reusable parts

The full repository suite passed 431 tests in 133.35 s; see RESULTS.md. Fresh `finish` builds accepted 471 shooter checks (including a separate 70° rebuild with 470 checks) and 23 mold checks. Independent BREP audits check dimensions, the outlet tangent and sampled maximum-ball passage, with negative probes for wrong outlet angle and excessive deck height. STL validation checks manifold edges, positive signed volume and volume agreement with the source BREP; DXF inspection checks units and cut geometry. These checks do not establish material strength or scored-shot probability.

`parts/standard_parts.py` is the reusable library: carrier, retainer, 5 mm hex sleeve and 608 reference. Use named functions, then copy that small module into a new CADLoop design before creating its revision so source hashes seal the exact version. No registry or mutable runtime dependency is needed. Library tests measure real solids and interfaces.

Run the trajectory model with ordinary Python:

```sh
python examples/biobuzz_shooter/trajectory.py --deck-mm 180 --output trajectory.json
```

Use CADLoop's CLI/Python API for project changes and fresh `finish`; retain the exact base revision and all engineering blockers. Execute generated CAD in the validated Docker profile. See SOURCES.md, BOM.md, and the delivered test evidence.
