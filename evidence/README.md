# Evidence index

`audit/` contains the v0.1.1 runs, failed-before regressions, repeated shuffled suite,
context/microbenchmark data, and blocked-bore demonstration.

`baseline_v0.1.0/` is the original delivered evidence, retained separately. The
v0.1.0 suite was also rerun at the start of this audit (see `audit/baseline.*`).

Top-level pytest files are convenience copies of the new expanded run.
The installed-wheel smoke reused this runtime's existing dependency packages
through an explicit virtual-environment path; it does not validate a clean install.
No live-model inference requests were made.
