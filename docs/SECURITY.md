# Execution and trust boundaries

## Native mode is not a sandbox

The tested mode starts separate build and verification interpreters, strips API
secrets from the build environment, sets core/file-size limits inside the fresh
worker, kills process groups on timeout, and checks input/artifact digests. These
are useful controls, but generated Python still runs as your user and can access
your filesystem or network. Use `--trusted-native` only for source you have reviewed.
The included fixture and tests are reviewed source, not a sandbox-escape test suite.

Do not give a hostile agent unrestricted shell access and expect a CLI permission
layer to constrain it. A user-level process can modify its own controller files and
receipts. Hashes identify changes; they are not signatures from an external trust root.

## Docker profile (not executed in the delivery environment)

The runner declares no network, read-only root/input, a non-root UID, dropped
capabilities, no new privileges, PID/CPU/memory limits, and a bounded scratch tmpfs.
Only the current output directory is writable. Verification uses a second container
with read-only geometry. Provider credentials remain in the controller.

```sh
docker build -t cadloop-worker:0.1.1 .
.venv/bin/cadloop demo --directory ./work/docker-demo --docker
```

Validate this profile on your installation before accepting untrusted model source.
The Dockerfile requires network access during image construction. Native CAD parsers
also have an attack surface. This is not a security audit, and macOS Docker Desktop
resource behavior has not been tested here.

In this release Docker mode deliberately disables host-side previews, including
at `finish`. It does not parse its untrusted geometry in the native renderer. The
export still includes geometry and JSON measurements. Use an isolated viewer until
a containerized rendering stage has also been implemented and tested.

## Inference and spending

No API calls are made by demo, search, evaluate, inspect or replay. The HTTP loop
requires explicit endpoint/model configuration and current prices. It books a
conservative text-token reservation before each request, reconciles returned usage,
and stops on uncertain or exceeded bounds. It does not control spending by external
coding hosts, shared API users, network providers, or account-level charges. Configure
provider-side limits as well. Never put API keys in CAD source or project JSON.

No secrets are copied into the distributed demo. Provider errors are reported
without logging authorization headers. User-provided prompts and CAD source sent
to a configured external model are, by design, sent to that provider.

## Additional v0.1.1 checks

The audit exercises concurrent controller operations, malformed/duplicate/nonfinite
JSON, partial artifact reports, failed proposal rollback, stale execution caches,
pending budget reservations, worker signal death, and a simulated preview-stage
crash. Native rendering now uses a separate bounded interpreter. This contains a
normal graphics-worker crash; it does not turn native rendering or CAD parsing into
a hostile-file sandbox. No actual Docker escape or hostile-code isolation test was
possible here.

Advisory project locks cover complete search, finish and managed-loop operations.
Hard-kill recovery, power-loss consistency, privileged local tampering and
distributed network filesystems are not certified by these tests.
