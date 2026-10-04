# Sources and interpretation

Checked September 29, 2026. Downloaded reference files and SHA256 hashes are listed in the delivery evidence. These sources define nominal interfaces; physical tolerances and use conditions still require checks.

| Source | Used for |
|---|---|
| [FIRST BIOBUZZ competition manual TU02](https://ftc-resources.firstinspires.org/ftc/archive/2027/game/cm-html/BIOBUZZ%20Competition%20Manual%20-%20TU02.htm) / [PDF](https://ftc-resources.firstinspires.org/ftc/archive/2027/game/manual) | HIVE upward opening geometry, launch restrictions, 457.2 mm starting cube, field tolerances, four-element control limit |
| [FIRST game resources](https://ftc-resources.firstinspires.org/ftc/archive/2027/game) | Official field CAD v26-27.2; interpret upward CELL plane rather than a vertical target |
| [AndyMark POLLEN drawing](https://s3.amazonaws.com/docusync-files/bc64addc5b9b6e528cb96de4e498ffd2134eb656232d4f0e3c7f5c1ebd057b58/am-5851_yellow%20Pollen.pdf) / [product](https://andymark.com/products/biobuzz-scoring-elements?variant=47194281148588) | Nominal 2.8 in (71.12 mm), drawing ±0.1 in: maximum 73.66 mm; approximately 25 g, polyethylene |
| [REV Starter Kit V3 BOM](https://www.revrobotics.com/content/docs/FTC_Starter_Kit_V3-BOM.pdf) | Stock availability, 5 mm hex shafts, chain, sprockets, collars and UltraPlanetary |
| [REV Starter Kit V3.1 BOM](https://www.revrobotics.com/content/docs/REV-45-3529_FTC_Starter_Kit_V3.1-Visual_BOM.pdf) | Common inventory for this provisional build; actual user kit is unknown |
| [REV UltraPlanetary assembly](https://docs.revrobotics.com/rev-crossover-products/ultraplanetary/assembly-instructions) | Zero-stage assembly is permitted; no reduction cartridges required |
| [REV-41-1600 drawing](https://www.revrobotics.com/content/docs/REV-41-1600-DR.pdf) | Motor/output envelope and static mounting geometry; reference cylinder uses maximum 43.74 mm width |
| [REV-41-1621 bracket drawing](https://www.revrobotics.com/content/docs/REV-41-1621-DR.pdf) | Static case six-hole M3 pattern on 32 mm PCD; three alternating holes used |
| [REV #25 sprockets drawing](https://www.revrobotics.com/content/docs/Sprockets-25-Plastic-DR.pdf) | 10T REV-41-1338, 15 mm overall axial width, 2.8 mm tooth plate, 24.1 mm tooth-clearance envelope |
| [REV shaft collar drawing](https://www.revrobotics.com/content/docs/REV-41-1327-DR.pdf) | 8 mm axial width, 13 mm OD; actual bearing-inner-ring contact requires measurement |
| [Limelight 3A specification](https://docs.limelightvision.io/docs/docs-limelight/getting-started/limelight-3a) / [CAD downloads](https://docs.limelightvision.io/docs/resources/downloads) | 72.11 × 48.11 × 16.80 mm enclosure; rear M3 holes on 64 × 8 mm pattern |
| [NTN 608](https://eshop.ntn-snr.com/en/product/608-NTN/608) | 8 mm bore, 22 mm OD, 7 mm width; actual user bearing seal/race geometry unspecified |

## Field model

The HIVE lower mouth lip is 1359 mm above the tiles, with top at approximately 1666 mm. The gable opening is 508 mm wide and 355.6 mm tall measured on its tilted plane, with 193.294 mm straight sides. Its plane is 60° to horizontal: upper edge farther from the shooter. The basket's interior axis slopes 30° downward away from the shooter, with nominal 304.8 mm depth. The trajectory code checks the full maximum-size sphere crossing the thin opening plane, not the complete basket interior. This is why the report does not equate aperture clearance with a scored shot.

Calculated launch speeds, chain centers, compression, print clearances, shaft cuts, turret pattern and material/process suggestions are engineering assumptions or derivations, not manufacturer-certified values. Mold shrink compensation is zero until measured. A 25A hardness target alone does not select a silicone product.
