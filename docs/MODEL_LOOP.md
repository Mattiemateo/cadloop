# Managed model loop and cost experiment

The local CLI is the main integration. An existing coding agent can call it and
read images using its own tools. That host's inference spending is outside CADLoop's
budget ledger.

The included managed loop is intentionally narrower: a text-only worker receives a
bounded context packet and returns `propose`, `finish` or `stop` as validated JSON.
The controller reevaluates every patch, stops after configured step or no-progress
limits, and forces a fresh final gate. Progress compares artifact/validity failures,
blocking-check count, and normalized numerical violations. It recognizes an
improving gap even when the same checks still fail. This scheduling heuristic is
not acceptance: every required check must still pass. Strong-model escalation is
reported as needed, not silently performed.

The context includes the last two bounded attempts. Parameter-only packets omit
uneditable source and repeated schema labels; named geometric references, measured
failures, units and numeric requirements are retained. Set
`include_source_in_context: true` to include source during parameter repair. Source
editing remains Docker-only and Docker itself requires local validation.

The budget ledger serializes reservations and blocks further requests while a
reservation is pending or usage is uncertain. Invalid structured actions stop with
a typed error rather than silently triggering repeated paid requests.

## Run with a provider

```sh
.venv/bin/python -m pip install -e '.[llm]'
cp scripts/provider.example.json provider.local.json
# Edit endpoint, model, supported token-limit field and current prices.
# Confirm pricing explicitly. Use a localhost zero-cost tariff only for a local service.
.venv/bin/cadloop init work/model-trial
.venv/bin/cadloop loop work/model-trial --provider-config provider.local.json --trusted-native
```

For an external HTTPS endpoint set `api_key_env` to an environment-variable name and
set that variable outside the project. The base URL is the API root ending in `/v1`
when applicable; the adapter appends `/chat/completions`. Providers must support a
JSON-object response, the configured output-token limit, and reliable integer prompt
and completion token usage. There are no automatic network retries. Provider
compatibility is not inferred from marketing terminology; test the actual endpoint.

An existing managed session is not resumed automatically. Archive `.cadloop/sessions`
and, only after reconciling any outstanding charges, its budget ledger before a new
session. This avoids silent duplicate inference after an interruption. It is not a
complete resumable-job implementation.
Invalid execution options are rejected before creating a session. Once started,
initial evaluation errors and handled interruptions are recorded as terminal
states instead of leaving a misleading `RUNNING` marker. A hard process kill
cannot guarantee finalization.

## What the delivered tests establish

Scripted replay proves that validated actions can drive real geometry builds and
checks. Mock HTTP tests prove that the adapter constructs the expected request,
validates the response, accounts for usage, retains uncertain reservations, and
blocks further calls where required. Neither establishes live-provider reliability
or the CAD ability of a cheap model. No such benchmark is claimed.

## Next benchmark

Use mechanically different held-out tasks, fixed protected checkers and equal budget
rules. Record accepted task count, failures, total spend including retries, latency,
patch size and number of full builds. Compare normal concise prompting with
reuse-first prompting and optional terse wording. Do not remove units or required
checks to save tokens. Cost per accepted task is total spend divided by independent
acceptances; with no accepted tasks, it is undefined rather than zero.
