# v0.1.1 recorded results

The expanded suite passed **214 tests**, with **1 optional build123d test skipped**.
The original v0.1.0 suite was rerun first: 74 passed, 1 skipped. Raw JUnit XML,
commands, failed-before/fixed-after logs, a seeded shuffled repeat, and summary
metadata are retained under `evidence/audit/`. Read `AUDIT.md` for exact scope.

## A genuine false pass reproduced

A valid solid bar crossing the lower plate bore was previously accepted as a
through-hole. The new continuous inset cylindrical probe measures material inside
the intended passage, and rejects this case. See `evidence/audit/demo/rejected/`.
Removing the bar and freshly rebuilding/verifying the assembly produces the
26-check accepted result under `evidence/audit/demo/accepted/`. It is synthetic
nominal geometry, not fabrication or strength approval.

## Efficiency evidence

The saved parameter-only context shrank from 9,187 to 4,892 canonical JSON bytes
(46.75%). Required dimensions, units and limits remain, and named references were
added. These are bytes, not billed tokens, and no model-quality/cost test was run.

Identical hardened checks used 3 cylindrical-face traversals instead of 7. Twelve
paired repetitions measured approximately 105.4 ms versus 105.7 ms median: no
meaningful end-to-end speedup is established. These warm in-process checks exclude
CAD creation, interpreter startup, export, views and model calls.

View-only cache updates launch no geometry workers, duplicate parameter-search
candidates are removed after validation, and improving numerical repairs no
longer trigger premature escalation merely because the blocker count is unchanged.

## Reading evidence

Old delivery evidence is separately labeled `evidence/baseline_v0.1.0/`. Stored
absolute paths document this container, not the installation path on your machine.
Run the included audit scripts to generate new local paths and revisions.
All demonstrations and replays used zero live LLM/API calls.
