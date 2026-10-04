# 608 bearing parts

`standard_parts.py` contains four independent CadQuery solids. All dimensions
are in millimetres, the bearing axis is Z, and the mounting face is Z=0.

| Function | Geometry |
| --- | --- |
| `bearing_carrier_608(seat_clearance=0.15)` | 42 × 42 × 10.15 flange; four Ø3.4 M3 holes at (±15, ±15); Ø19.2 through bore; top bearing seat Ø(22 + clearance), 7.15 deep, leaving a 3 mm shoulder. |
| `bearing_retainer_608()` | 42 × 42 × 3.4 plate; Ø19.2 through bore; same four Ø3.4 holes; a 5.6 × 5.6 × 2.8 square nut pocket opening on the top at each hole. |
| `flanged_hex_sleeve_608(hex_clearance=0.10, outer_clearance=0.05)` | Tube OD (8 − outer clearance), length 6.9; Ø11 flange from Z=6.9 to 8.1; through hex bore with (5 + hex clearance) across flats. |
| `bearing608_reference()` | Nominal 608 annular external envelope: Ø22 OD, Ø8 ID, 7 wide. It does not model races or seals. |

The 608 reference dimensions come from the [NTN 608 bearing specification](https://eshop.ntn-snr.com/en/product/608-NTN/608). The sleeve's 5 mm hex to 8 mm bearing interface is a **prototype radial interface**, not a rated bearing fit. Print a fit coupon and check the actual bearing, shaft, silicone/process material, and printer before relying on any clearance. Adjust only the two exposed clearance parameters after measurement.

Copy `standard_parts.py` into the project design **before** creating a CADLoop revision, so that the revision seals the exact source used for that design. Do not import this live repository copy from a revisioned design.
