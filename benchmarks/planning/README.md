# Planning evaluation protocol

These fixtures test deterministic planning infrastructure. They are not evidence
of model quality, manufacturing strength, or a completed live-model benchmark.
No model API or network access is needed to replay the motor-mount fixture.

For a future matched evaluation, use the same CAD agent, authoring budget, kernel,
verification requirements, and execution profile in all three arms:

* **A:** `lazy_brief.txt` goes directly to the CAD agent.
* **B:** `expert_prompt.md` goes directly to the same CAD agent.
* **C:** `lazy_brief.txt` passes through CADLoop planning; the same CAD agent then
  receives the frozen contract and compiled modeling context.

Keep the gold contract and question oracle outside the agent's context. Record
the exact model/host version, prompts, contract revisions, decisions, timestamps,
CAD source revisions, verifier reports, and retained engineering blockers. Measure
human clarification time separately from model and kernel execution time. Failed
or unsupported checks cannot count as verified successes.

The future target is `verified_success(C) / verified_success(B) >= 0.95`, with
human clarification time no greater than 30 seconds and no more than three
questions. Also report open-ended question count (ideally zero), critical
requirement recall, invented hard requirements, and first-proposal acceptance.
The ratio is undefined when arm B has no successes; do not report a favorable
ratio in that case. Use multiple tasks and repeated, matched runs before claiming
improvement.

`fixtures/motor_mount` uses supplied synthetic dimensions, not inferred or
external motor specifications. It deliberately leaves motor orientation open.
The fixture exercises one question, deterministic answers, sketches, freeze,
handoff, and explicit limits of requirement translation. It does not validate
the strength of a motor mount.

`proposal.json` is a replay packet: bind its `base_revision`, contract `revision`
and `task_id` to the initialized workspace before submission. Its original brief
and `src_user_1` record must match that workspace exactly. `gold_contract.json`
is the expected reviewed reference, including an explicitly synthetic oracle
decision and fixed fixture timestamp. It is not a frozen controller receipt.
Actual replays create their own immutable revisions, answer records and freeze
manifests. Unsupported bore/pitch verification remains explicit in the handoff;
the fixture never claims that concept dimensions prove the fabricated geometry.
