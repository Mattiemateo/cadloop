# CADGenBench evaluation protocol for Codex + CADLoop

Status: NOT RUN. No submitted candidates, private-ground-truth evaluation,
leaderboard score, live Codex request, or measured model-quality improvement.
This is a preregistration template, not an implemented benchmark adapter.

## What must be measured

The v0.1.1 regression suite measures supported checker and controller behavior.
CADGenBench measures engineering-drawing reconstruction and STEP editing. It
accepts STEP/BREP output independently of the authoring tool. Its API-key-based
reference generator is optional; Codex account login can be our generator.
The official score compares with private ground truth on the benchmark Space.
A local valid solid or passing CADLoop report is not a CADGenBench score.

## Paired arms

A: Codex + the selected CAD runtime and basic execution/rendering feedback.
B: the same Codex model/reasoning/runtime + CADLoop's compact feedback,
   measurements, scoped repairs and approved parameter search.

Hold the task input, CAD backend, model/version, reasoning setting, wall-time cap,
CAD-execution cap, reference access, and number of repetitions constant. Both arms
see the same drawing images at adequate resolution. They get separate fresh
workspaces and sessions; no shared transcripts, candidates or caches of task
answers. Label A as a custom Codex baseline, not CADGenBench's official baseline.

Start with a clearly labelled 10-task development smoke subset, selected before
seeing outcomes and including generation and editing if available. Three attempts
per task/arm is a proposed setting: 10 x 2 x 3 = 60 model sessions, not necessarily
cheap in subscription quota. Start serially and pause at limits. This sample is
not a full benchmark result; freeze code/settings, then use a separate evaluation
set or full required dataset for a reportable run. No selective removal of hard
samples. Missing/invalid outputs remain failures in the denominator. No best-of-N
submission unless that protocol and all retries are reported explicitly.

## Missing engineering work before automated benchmarking

The present harness does not yet implement a general CADGenBench task importer,
a drawing-image input pipeline, or a benchmark-compatible generic project profile.
Its checked demo has reviewed requirements, while new drawings do not arrive as
CADLoop requirements JSON. Generation from an empty source tree and editing an
imported STEP require additional tested integration. Do not describe the launcher
as having implemented those features.

For the first benchmark profile, trusted acceptance checks should cover objective
artifact/solid validity and fixed input requirements. Measurements and
model-derived design intent may guide repair, but inferred requirements must not
be treated as independent proof of correctness. Do not manually encode hidden
answers into CADLoop-only requirements. Any human specification must be supplied
equally to both arms and reported as assistance, or excluded from the standard run.
Unsupported local checks must not silently make a task disappear. Record coverage
and submit the final candidate under the predeclared benchmark protocol even when
some local engineering claims cannot be established.

## Isolation and leakage controls

Mount only the sample's public inputs into the agent workspace. Keep official
scoring, hidden models, solution code, public submissions, and answer-bearing
repositories inaccessible during generation. Freeze the checker and record its
hash outside agent write access. Use external OS/network controls for benchmark
isolation; merely telling Codex not to read a file is not sufficient.
Do not run a benchmark with unrestricted root-repository write access and call
requirements protected. No auth cache enters the generated-code worker.
Ground truth is never part of the iterative model feedback.

## Evidence per attempt

Record public dataset commit, benchmark code commit, task ID/type, arm, attempt,
CADLoop source digest, CAD/kernel versions, Codex CLI version, actual model and
reasoning configuration, prompt and allowed tools, session ID, elapsed time,
CAD evaluations, tool calls, retries, interruptions, and output STEP SHA256.
Record Codex-reported input/cached/output/reasoning tokens without double counting;
unknown usage is null, not zero. An API-equivalent dollar estimate is not an actual
subscription charge. Report account credits separately if actually observable.

Capture stdout JSONL from `codex exec --json` for controlled future runs. Keep raw
logs local, redact secrets, and do not assume every CLI event version has identical
usage fields. CADLoop's separate HTTP-provider budget ledger does not meter this.

## Scoring and reporting

Write one `<task_id>/output.step` per final candidate. Use the benchmark's official
local validity helper as a preflight, then the official hidden-ground-truth grader
for CAD Score, validity, shape, interface and topology metrics where applicable.
Report generation and editing separately. Keep repair/checker-mutation evaluations
as a third, separate report; keep native Onshape feature editability separate too.

Publish paired per-task outcomes plus aggregates, failures, time and usage; avoid
claims of broad superiority from the development subset. Include unassisted and
human-assisted runs separately. Do not compare one new Codex run against an old
leaderboard row and attribute the difference entirely to CADLoop.

The README currently describes ZIP uploads with root meta.json, while the detailed
submission document describes local per-task STEP layout. Recheck the actual
Space/package command contract at the pinned revision rather than guessing the
metadata schema. Public leaderboard submission may publish a row and report:
obtain explicit user approval before uploading. No upload is authorized by this
protocol alone, and the add-on performs none.

## Primary sources inspected September 18, 2026

- https://github.com/huggingface/cadgenbench
- https://raw.githubusercontent.com/huggingface/cadgenbench/main/README.md
- https://raw.githubusercontent.com/huggingface/cadgenbench/main/docs/benchmark/submission.md
- https://raw.githubusercontent.com/huggingface/cadgenbench/main/docs/metrics.md
- https://raw.githubusercontent.com/huggingface/cadgenbench/main/docs/benchmark/validation.md
- https://developers.openai.com/codex/noninteractive

Pin actual retrieved revisions before running; this document does not invent
revision hashes or claim the private ground truth is locally available.
