# Static planner compatibility fixture

`static_frozen_v1.zip` was generated using the unmodified planner at commit
`fa8118f5cca45c080078f5fab4b47e6864d08541`, with `PlanningProject.initialize`
and that commit's `tests/planning_helpers.py:frozen`. The synthetic brief is
“Compatibility fixture for static concept sketches.” It contains no CAD source
or external account information. The archive preserves the original revisions,
render hashes, frozen contract and handoff so future tests can check pre-variant
workspace compatibility without recomputing old expected values with new code.
