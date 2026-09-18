# Codex-account add-on for CADLoop v0.1.1

Merge this archive's `cadloop/` folder into your extracted CADLoop v0.1.1 folder.
Only new files are included; existing CAD code, requirements and validators are
not replaced. The base source manifest still describes v0.1.1, not this add-on;
the add-on has its own ADDON_MANIFEST.json.

Run locally after installing the official Codex CLI and signing in:

```sh
codex login
codex login status
cd /path/to/cadloop
python3 scripts/start_codex.py --dry-run
python3 scripts/start_codex.py
```

Read docs/CODEX_ACCOUNT.md before executing CAD. This is supervised local use,
not a hardened unattended agent setup. For your account, do not use CADLoop's
separate HTTP-provider loop. Plan/workspace usage limits still apply.

Read docs/CADGENBENCH_PROTOCOL.md for the benchmark design and remaining integration
work. No CADGenBench run or live Codex inference has occurred. Eighteen launcher
contract tests passed with mocked subprocesses; these are not CAD benchmark cases.

Reproduce the added tests:

```sh
python3 -m pytest tests/test_codex_launcher.py -q
```

Included files: local launcher, operating guide, benchmark protocol, tests,
recorded test log/XML/summary and dry-run output. No credentials are included.
