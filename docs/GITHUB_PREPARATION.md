# GitHub preparation

Prepared: 2026-09-18. Target repository name: `cadloop`; intended visibility: private.
No remote repository has been created or pushed by this preparation step.

## Inputs

- `CADLoop_v0.1.1.zip`: audited CAD harness, regression tests, and historical evidence.
- `CADLoop_Codex_Account_Addon.zip`: account launcher, guide, benchmark protocol,
  launcher tests, and historical evidence.

All input files were retained. The archives had no overlapping file paths. Their
Python source files, tests, CAD templates, and checkers were not modified.
README.md and AGENTS.md now point to the already-merged account workflow, and
.gitignore includes additional local credential and cache exclusions.

## Manifest correction

The base archive's SOURCE_MANIFEST.json was stale: 24 referenced files matched,
26 had different hashes, and 52 referenced paths were absent. This was detected
before repository preparation, not caused by merging the disjoint add-on files.
The original is retained as evidence/github_preparation/original_source_manifest.json
for provenance; it must not be used to verify this combined tree.

SOURCE_MANIFEST.json is regenerated for this combined tree, excluding itself.
The original ADDON_MANIFEST.json is retained; all nine listed add-on files match.
Neither manifest is a cryptographic signature or proof of security or correctness.

## Checks and limitations

Archive paths and file types were checked before extraction. A narrow scan for
private-key markers, common GitHub/OpenAI token patterns, and credential filenames
found no matches. This is not a complete secrets audit or a security guarantee.
Historical CAD and launcher evidence is retained unchanged. Any current packaging
smoke-test output is stored separately under evidence/github_preparation/.
No live Codex login, model request, CADGenBench run, or GitHub publication is implied.
