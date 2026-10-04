"""Revision-bound planning transactions; the small state pointer commits last."""
from __future__ import annotations

from datetime import datetime, timezone
import contextlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from ..errors import CadLoopError
from ..util import MAX_JSON_BYTES, canonical, digest, file_hash, project_lock, read_json, tree_hashes, within, write_json
from .contracts import DesignContract, PlanningProposal, apply_updates, update_target


def _text(path: Path, value: str):
    """Atomic UTF-8 writes for SVG/Markdown; JSON uses the shared write_json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _record_hash(record):
    value = dict(record)
    value.pop("revision", None)
    value["contract"] = {**value["contract"], "revision": ""}
    value["events"] = [{k: v for k, v in event.items()
                        if k not in ("new_revision", "resulting_contract_hash")}
                       for event in value["events"]]
    return digest(value)


class PlanningProject:
    """A planning workspace needs no model.py, CAD runtime, or model provider."""

    def __init__(self, root: str | Path):
        raw = Path(root).absolute()
        if raw.is_symlink():
            raise CadLoopError("UNSAFE_PATH", "Planning workspace must not be a symlink")
        self.root = raw.resolve()
        self.control = self.root / ".cadloop"
        self.folder = self.control / "planning"
        self._safe_paths()
        if not (self.folder / "state.json").is_file():
            raise CadLoopError("PLANNING_NOT_INITIALIZED", "Run design-init before using planning tools")

    def _safe_paths(self):
        for path in (self.control, self.folder, self.control / "controller.lock"):
            if path.is_symlink():
                raise CadLoopError("UNSAFE_PATH", "Planning control paths must not be symlinks")
        if self.folder.exists() and not self.folder.is_dir():
            raise CadLoopError("UNSAFE_PATH", "Planning control area must be a directory")

    @contextlib.contextmanager
    def _lock(self):
        self._safe_paths()
        with project_lock(self.control):
            self._safe_paths()
            yield

    def _path(self, relative, *, exists=True):
        return within(self.root, ".cadloop/planning/" + str(relative), must_exist=exists)

    @classmethod
    def initialize(cls, root, *, brief: str, task_id: str | None = None):
        root = Path(root).absolute()
        if root.is_symlink() or root.exists() and any(root.iterdir()):
            raise CadLoopError("DIRECTORY_NOT_EMPTY", "Planning initialization never overwrites a workspace")
        if not isinstance(brief, str) or not brief.strip() or len(brief.encode()) > 16_000:
            raise CadLoopError("PLANNING_BRIEF_INVALID", "Provide a nonempty brief of at most 16000 UTF-8 bytes")
        contract = DesignContract.model_validate({
            "task_id": task_id or "design_" + uuid.uuid4().hex[:16], "revision": "0" * 64,
            "brief": brief, "sources": [{"id": "src_user_1", "kind": "USER", "description": brief}],
        })
        root.mkdir(parents=True, exist_ok=True)
        folder = root / ".cadloop" / "planning"
        folder.mkdir(parents=True)
        instance = cls.__new__(cls)
        instance.root, instance.control, instance.folder = root.resolve(), folder.parent, folder
        with instance._lock():
            write_json(folder / "brief.json", {"schema_version": 1, "task_id": contract.task_id, "brief": brief})
            record = instance._make_record(contract, None, "Initial human brief", events=[], rounds=0)
            instance._publish(record, None)
        (root / ".gitignore").write_text(".cadloop/\nexports/\n__pycache__/\n", encoding="utf-8")
        return cls(root)

    def _make_record(self, contract, previous, reason, *, events=None, rounds=None):
        record = {"schema_version": 1, "sequence": previous["sequence"] + 1 if previous else 0,
                  "parent_revision": previous["revision"] if previous else None,
                  "created_ns": time.time_ns(), "reason": reason,
                  "contract": contract.model_dump(),
                  "events": previous["events"] if events is None and previous else events or [],
                  "review_rounds": previous["review_rounds"] if rounds is None and previous else rounds or 0}
        record["revision"] = _record_hash(record)
        record["contract"]["revision"] = record["revision"]
        return record

    def _publish(self, record, old_state, *, frozen=None):
        """Immutable record + derived log; state.json is the transaction commit marker.

        Readers take the shared controller lock. Failed commits remove the new
        record and restore projections; historical revisions are never rewritten.
        """
        from .questions import rank_questions
        if record["sequence"] > 1024:
            raise CadLoopError("PLANNING_HISTORY_LIMIT", "Start a new workspace after 1024 planning revisions")
        if len(canonical(record)) + 1 > MAX_JSON_BYTES:
            raise CadLoopError("PLANNING_REVISION_TOO_LARGE", "Planning revision exceeds the shared JSON artifact budget")
        path = self._path(f"revisions/{record['sequence']:06d}.json", exists=False)
        if path.exists():
            raise CadLoopError("PLANNING_HISTORY_EXISTS", "Refusing to overwrite a planning revision")
        state = {"schema_version": 1, "sequence": record["sequence"], "revision": record["revision"],
                 "contract_hash": digest(record["contract"]), "status": record["contract"]["status"],
                 "brief_hash": file_hash(self._path("brief.json")),
                 "frozen_revision": record["revision"] if frozen else None,
                 "last_frozen_revision": record["revision"] if frozen else
                 (old_state or {}).get("last_frozen_revision")}
        if frozen:
            state["frozen_manifest_hash"] = frozen
        journal = self._path("transaction.json", exists=False)
        if journal.exists():
            raise CadLoopError("PLANNING_TRANSACTION_PENDING", "Recover the previous transaction before publishing")
        write_json(journal, {"schema_version": 1, "old_state": old_state, "new_state": state,
                             "record_hash": digest(record)})
        try:
            write_json(path, record)
            _text(self._path("decisions.jsonl", exists=False), self._decision_text(record))
            write_json(self._path("questions.json", exists=False), {
                "revision": record["revision"], "questions": rank_questions(DesignContract.model_validate(record["contract"]))})
            write_json(self._path("state.json", exists=False), state)
        except BaseException:
            self._recover()
            raise
        # The pointer has committed. A failed housekeeping unlink must never
        # make the caller roll back artifacts belonging to the committed head.
        with contextlib.suppress(OSError):
            journal.unlink()
        return state

    def _recover(self):
        """Recover a killed controller using the atomic pointer, never a guessed head."""
        journal = self._path("transaction.json", exists=False)
        if not journal.exists():
            return
        transaction = read_json(journal)
        state_path = self._path("state.json", exists=False)
        current = read_json(state_path) if state_path.exists() else None
        if current == transaction["new_state"]:
            journal.unlink()
            return
        if current != transaction["old_state"]:
            raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Transaction journal disagrees with the committed state")
        pending = transaction["new_state"]
        if type(pending["sequence"]) is not int or not 0 <= pending["sequence"] <= 1024:
            raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Invalid pending sequence")
        record_path = self._path(f"revisions/{pending['sequence']:06d}.json", exists=False)
        if record_path.exists():
            record = read_json(record_path)
            if digest(record) != transaction["record_hash"] or record["revision"] != pending["revision"]:
                raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Uncommitted revision disagrees with its journal")
            record_path.unlink()
        if pending["status"] == "FROZEN":
            revision = pending["revision"]
            if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
                raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Invalid pending freeze revision")
            for category in ("frozen", "renders"):
                path = self._path(f"{category}/{revision}", exists=False)
                if path.exists():
                    shutil.rmtree(path)
        if current is None:
            for name in ("decisions.jsonl", "questions.json"):
                self._path(name, exists=False).unlink(missing_ok=True)
        else:
            old = read_json(self._path(f"revisions/{current['sequence']:06d}.json"))
            if _record_hash(old) != current["revision"]:
                raise CadLoopError("PLANNING_TAMPERED", "Cannot recover from a changed historical revision")
            from .questions import rank_questions
            _text(self._path("decisions.jsonl", exists=False), self._decision_text(old))
            write_json(self._path("questions.json", exists=False), {
                "revision": old["revision"], "questions": rank_questions(DesignContract.model_validate(old["contract"]))})
        journal.unlink()

    @staticmethod
    def _decision_text(record):
        # New revision is derived from the immutable record; keeping it out of
        # the hashed contract avoids a circular self-hash.
        return "".join(canonical(event).decode() + "\n" for event in record["events"])

    def _load(self):
        self._safe_paths()
        self._recover()
        self._recover_materialization()
        state = read_json(self._path("state.json"))
        sequence = state.get("sequence")
        if type(sequence) is not int or not 0 <= sequence <= 1024:
            raise CadLoopError("PLANNING_STATE_INVALID", "Invalid planning revision sequence")
        records = []
        parent = state["revision"]
        # ponytail: bounded history walk; add an indexed audit only if long plans need it.
        for number in range(sequence, -1, -1):
            record = read_json(self._path(f"revisions/{number:06d}.json"))
            if (record["sequence"] != number or _record_hash(record) != record["revision"] or
                    record["revision"] != parent or record["contract"]["revision"] != parent):
                raise CadLoopError("PLANNING_TAMPERED", "Planning revision history does not match its hashes")
            DesignContract.model_validate(record["contract"])
            records.append(record)
            parent = record["parent_revision"]
        for child, ancestor in zip(records, records[1:]):
            prefix = len(ancestor["events"])
            if child["events"][:prefix] != ancestor["events"]:
                raise CadLoopError("PLANNING_TAMPERED", "Historical decision records were rewritten")
            for event in child["events"][prefix:]:
                if (event.get("new_revision") != child["revision"] or
                        event.get("resulting_contract_hash") != digest(child["contract"]) or
                        event.get("previous_revision") != ancestor["revision"]):
                    raise CadLoopError("PLANNING_TAMPERED", "Decision log has a stale revision binding")
        if records[-1]["events"]:
            raise CadLoopError("PLANNING_TAMPERED", "Initial planning revision cannot contain answers")
        record = records[0]
        if (parent is not None or digest(record["contract"]) != state["contract_hash"] or
                record["contract"]["status"] != state["status"] or
                file_hash(self._path("brief.json")) != state["brief_hash"]):
            raise CadLoopError("PLANNING_TAMPERED", "Planning state disagrees with its immutable inputs")
        if self._path("decisions.jsonl").read_text(encoding="utf-8") != self._decision_text(record):
            raise CadLoopError("PLANNING_TAMPERED", "Decision log disagrees with the committed revision")
        historical = {item["revision"]: item for item in records}
        for decision in record["contract"]["accepted_decisions"]:
            origin = historical.get(decision["previous_revision"])
            candidates = origin["contract"]["decision_candidates"] if origin else []
            candidate = next((q for q in candidates if q["id"] == decision["question_id"]), None)
            option = next((o for o in candidate["options"] if o["id"] == decision["option_id"]), None) if candidate else None
            if (option is None or option["updates"] != decision["updates"] or
                    option.get("approved_source_refs", []) != decision["source_refs"]):
                raise CadLoopError("PLANNING_DECISION_HISTORY_INVALID", "Accepted decision has no matching historical option")
        return state, record, DesignContract.model_validate(record["contract"])

    def _base(self, base, *, mutable=True):
        state, record, contract = self._load()
        if base != state["revision"]:
            raise CadLoopError("STALE_REVISION", "Planning operation needs the exact current base revision",
                               current_revision=state["revision"])
        if mutable and state["status"] == "FROZEN":
            raise CadLoopError("PLANNING_FROZEN", "Use design-reopen before changing frozen design intent")
        return state, record, contract

    def _audit(self, contract, sequence):
        from .audit import audit
        history = {}
        for number in range(sequence + 1):
            item = read_json(self._path(f"revisions/{number:06d}.json"))
            history[item["revision"]] = item["contract"]
        return audit(contract, accepted_history=history)

    def state(self):
        with self._lock():
            state, record, contract = self._load()
            from .questions import rank_questions
            render = self._render_manifest(contract, required=False)
            return {**state, "task_id": contract.task_id, "review_rounds": record["review_rounds"],
                    "questions": rank_questions(contract), "render_available": render is not None,
                    "render_directory": str(self.folder / "renders" / contract.revision) if render else None,
                    "frozen_contract_hash": state["contract_hash"] if state["status"] == "FROZEN" else None}

    def context(self):
        with self._lock():
            state, record, contract = self._load()
            from .questions import rank_questions
            return {"original_brief": read_json(self._path("brief.json")), "revision": state["revision"],
                    "contract": contract.model_dump(), "sources": [s.model_dump() for s in contract.sources],
                    "accepted_decisions": [d.model_dump() for d in contract.accepted_decisions],
                    "audit": self._audit(contract, record["sequence"]), "questions": rank_questions(contract),
                    "proposal_schema": PlanningProposal.model_json_schema()}

    def questions(self):
        state = self.state()
        return {"revision": state["revision"], "questions": state["questions"]}

    def audit(self):
        with self._lock():
            state, record, contract = self._load()
            return {"revision": state["revision"], **self._audit(contract, record["sequence"])}

    def propose(self, proposal, *, base=None):
        proposal = PlanningProposal.model_validate(proposal)
        if base is not None and base != proposal.base_revision:
            raise CadLoopError("STALE_REVISION", "CLI base and proposal base must agree")
        with self._lock():
            state, previous, current = self._base(proposal.base_revision)
            proposed = proposal.contract
            if (proposed.task_id != current.task_id or proposed.brief != current.brief or
                    proposed.accepted_decisions != current.accepted_decisions or proposed.status != current.status):
                raise CadLoopError("PLANNING_PROTECTED_STATE", "Task, brief, decisions and status are controller-owned")
            sources = {s.id: s for s in proposed.sources}
            if any(sources.get(s.id) != s for s in current.sources):
                raise CadLoopError("PLANNING_PROTECTED_STATE", "Existing source records are immutable; add a new source ID")
            existing_source_ids = {s.id for s in current.sources}
            if any(s.id not in existing_source_ids and s.kind in
                   ("USER", "ATTACHMENT_MEASURED", "APPROVED_REFERENCE") for s in proposed.sources):
                raise CadLoopError("PLANNING_SOURCE_AUTHORITY", "New reference claims need external provenance and explicit approval")
            assumptions = {a.id: a for a in current.assumptions}
            if any(a.accepted != (assumptions[a.id].accepted if a.id in assumptions else False) for a in proposed.assumptions):
                raise CadLoopError("PLANNING_PROTECTED_STATE", "Only explicit user answers can approve assumptions")
            final_updates = {}
            for decision in current.accepted_decisions:
                candidate = next((q for q in proposed.decision_candidates if q.id == decision.question_id), None)
                option = next((o for o in candidate.options if o.id == decision.option_id), None) if candidate else None
                if candidate is not None and (option is None or option.updates != decision.updates or option.approved_source_refs != decision.source_refs):
                    raise CadLoopError("PLANNING_PROTECTED_STATE", "A proposal cannot rewrite an accepted option")
                for update in decision.updates:
                    final_updates[update.path] = update
            for update in final_updates.values():
                _, target, field = update_target(proposed, update.path)
                if getattr(target, field) != update.value:
                    raise CadLoopError("PLANNING_PROTECTED_STATE", "A proposal cannot undo a user-selected update")
            # A selected value retains its meaning and enforcement, not merely
            # its JSON scalar. Otherwise FIXED=3 could silently become FREE=3,
            # or millimeters could become degrees while the recorded answer
            # still appeared unchanged. Explicit answers may revise these
            # semantics; an agent-authored hypothesis may not.
            selected_parameters = set()
            for path in final_updates:
                collection, identifier, field = path.split("/")[1:]
                if collection == "parameters" and field in ("value", "minimum", "maximum", "mode", "objective"):
                    selected_parameters.add(identifier)
            previous_parameters = {parameter.id: parameter for parameter in current.parameters}
            proposed_parameters = {parameter.id: parameter for parameter in proposed.parameters}
            protected_fields = ("kind", "unit", "mode", "minimum", "maximum", "enum_values",
                                "derived_from", "objective")
            for identifier in selected_parameters:
                old, new = previous_parameters[identifier], proposed_parameters[identifier]
                changed_fields = [field for field in protected_fields if getattr(old, field) != getattr(new, field)]
                if changed_fields:
                    raise CadLoopError("PLANNING_PROTECTED_STATE",
                                       "A proposal cannot change a user-selected parameter's meaning or enforcement; use an explicit user decision",
                                       parameter=identifier, fields=changed_fields)
            data = proposed.model_dump()
            data["status"] = self._audit(proposed, previous["sequence"])["status"]
            candidate = DesignContract.model_validate(data)
            record = self._make_record(candidate, previous, proposal.reason)
            self._publish(record, state)
            return self.state()

    def answer(self, *, base, answers):
        answers = list(answers)
        if not answers or len({q for q, _ in answers}) != len(answers):
            raise CadLoopError("PLANNING_ANSWERS_INVALID", "Provide nonempty, unique question answers")
        with self._lock():
            state, previous, current = self._base(base)
            from .questions import rank_questions
            active = {q["id"] for q in rank_questions(current)}
            updates, accepted, events = [], [], []
            now = datetime.now(timezone.utc).isoformat()
            candidates = {q.id: q for q in current.decision_candidates}
            for question, option_id in answers:
                if question not in active:
                    raise CadLoopError("PLANNING_QUESTION_INACTIVE", "Question is unknown or no longer active", question=question)
                candidate = candidates[question]
                option = next((o for o in candidate.options if o.id == option_id), None)
                if option is None:
                    raise CadLoopError("PLANNING_OPTION_UNKNOWN", "Unknown option for active question", question=question)
                updates.extend(option.updates)
                accepted.append({"id": "decision_" + uuid.uuid4().hex[:16], "question_id": question,
                                 "option_id": option.id, "updates": [u.model_dump() for u in option.updates],
                                 "source_refs": option.approved_source_refs, "previous_revision": base, "timestamp": now})
                events.append({"question_id": question, "selected_option": option.id,
                               "previous_revision": base, "timestamp": now})
            unique_updates = {}
            for update in updates:
                if update.path in unique_updates and unique_updates[update.path] != update:
                    raise CadLoopError("PLANNING_ANSWERS_CONFLICT", "Selected answers assign different values to the same field", path=update.path)
                unique_updates[update.path] = update
            changed = apply_updates(current, list(unique_updates.values())).model_dump()
            changed["accepted_decisions"] += accepted
            contract = DesignContract.model_validate(changed)
            changed["status"] = self._audit(contract, previous["sequence"])["status"]
            record = self._make_record(DesignContract.model_validate(changed), previous, "Explicit user decisions",
                                       events=previous["events"] + events, rounds=previous["review_rounds"] + 1)
            # Bind each appended log entry to the content revision without hashing
            # its own new_revision field into that same revision.
            for event in record["events"][-len(events):]:
                event["new_revision"] = record["revision"]
                event["resulting_contract_hash"] = digest(record["contract"])
            # Event self references are excluded from the record hash below.
            self._publish(record, state)
            return self.state()

    def _render_manifest(self, contract, *, required=True):
        relative = f"renders/{contract.revision}/manifest.json"
        path = self._path(relative, exists=False)
        if not path.exists():
            if required:
                raise CadLoopError("PLANNING_RENDER_REQUIRED", "Render and review this exact revision before freeze")
            return None
        manifest = read_json(path)
        from .diagrams import render_svgs
        expected = {name + ".svg": digest_text(value) for name, value in render_svgs(contract).items()}
        if (manifest.get("revision") != contract.revision or manifest.get("contract_hash") != digest(contract.model_dump()) or
                manifest.get("files") != expected or any(file_hash(self._path(f"renders/{contract.revision}/{name}")) != sha
                                                         for name, sha in expected.items())):
            raise CadLoopError("PLANNING_RENDER_TAMPERED", "Rendered concept does not match the current contract")
        return manifest

    def _write_render(self, contract):
        from .diagrams import render_svgs
        existing = self._render_manifest(contract, required=False)
        if existing:
            return existing
        target = self._path(f"renders/{contract.revision}", exists=False)
        staging = Path(tempfile.mkdtemp(prefix="render-", dir=self.folder))
        try:
            images = render_svgs(contract)
            for name, content in images.items():
                _text(staging / (name + ".svg"), content)
            manifest = {"schema_version": 1, "revision": contract.revision,
                        "contract_hash": digest(contract.model_dump()),
                        "files": {name + ".svg": file_hash(staging / (name + ".svg")) for name in images}}
            write_json(staging / "manifest.json", manifest)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise CadLoopError("PLANNING_HISTORY_EXISTS", "Render directory already exists")
            staging.rename(target)
            return manifest
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def render(self, *, base=None):
        with self._lock():
            state, _, contract = self._load()
            if base is not None and base != state["revision"]:
                raise CadLoopError("STALE_REVISION", "Render needs the exact current revision")
            manifest = self._write_render(contract)
            return {"revision": contract.revision, "render_directory": str(self.folder / "renders" / contract.revision),
                    "manifest": manifest}

    def freeze(self, *, base):
        with self._lock():
            state, previous, current = self._base(base)
            report = self._audit(current, previous["sequence"])
            if report["blocking"]:
                return {"revision": base, **report, "frozen": False}
            reviewed = self._render_manifest(current)
            changed = current.model_dump()
            changed["status"] = "FROZEN"
            record = self._make_record(DesignContract.model_validate(changed), previous, "User confirmed rendered design intent")
            contract = DesignContract.model_validate(record["contract"])
            target = self._path(f"frozen/{record['revision']}", exists=False)
            if target.exists():
                raise CadLoopError("PLANNING_HISTORY_EXISTS", "Frozen artifact already exists")
            render_existed = self._path(f"renders/{record['revision']}", exists=False).exists()
            promoted = False
            staging = Path(tempfile.mkdtemp(prefix="freeze-", dir=self.folder))
            try:
                from .handoff import compile_handoff, compile_requirements
                write_json(staging / "contract.json", contract.model_dump())
                _text(staging / "modeling_context.md", compile_handoff(contract))
                write_json(staging / "requirements_adapter.json", compile_requirements(contract))
                renders = self._write_render(contract)
                manifest = {"schema_version": 1, "planning_revision": contract.revision,
                            "contract_hash": digest(contract.model_dump()), "brief_hash": state["brief_hash"],
                            "decision_log_hash": digest_text(self._decision_text(record)),
                            "render_hashes": renders["files"], "reviewed_revision": base,
                            "reviewed_render_hashes": reviewed["files"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "files": {name: file_hash(staging / name) for name in
                                      ("contract.json", "modeling_context.md", "requirements_adapter.json")}}
                write_json(staging / "manifest.json", manifest)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise CadLoopError("PLANNING_HISTORY_EXISTS", "Frozen artifact already exists")
                staging.rename(target)
                promoted = True
                self._publish(record, state, frozen=file_hash(target / "manifest.json"))
            except BaseException:
                pointer = read_json(self._path("state.json"))
                committed = pointer.get("revision") == record["revision"]
                if promoted and not committed:
                    shutil.rmtree(target, ignore_errors=True)
                if not render_existed and not committed:
                    shutil.rmtree(self.folder / "renders" / record["revision"], ignore_errors=True)
                raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            return {**self.state(), "frozen": True, "frozen_directory": str(target)}

    def handoff(self):
        with self._lock():
            state, _, contract = self._load()
            if state["status"] != "FROZEN" or state["frozen_revision"] != contract.revision:
                raise CadLoopError("PLANNING_NOT_FROZEN", "Freeze the current contract before modeling")
            directory = self.folder / "frozen" / contract.revision
            manifest_path = self._path(f"frozen/{contract.revision}/manifest.json")
            manifest = read_json(manifest_path)
            if (file_hash(manifest_path) != state["frozen_manifest_hash"] or
                    manifest["contract_hash"] != digest(contract.model_dump()) or
                    manifest["planning_revision"] != contract.revision or
                    any(file_hash(self._path(f"frozen/{contract.revision}/{name}")) != sha
                        for name, sha in manifest["files"].items())):
                raise CadLoopError("PLANNING_FROZEN_TAMPERED", "Frozen contract/handoff no longer matches the freeze manifest")
            self._render_manifest(contract)
            return {"status": "FROZEN", "design_contract_revision": contract.revision,
                    "design_contract_hash": state["contract_hash"], "contract": contract.model_dump(),
                    "modeling_context": self._path(f"frozen/{contract.revision}/modeling_context.md").read_text(encoding="utf-8"),
                    "directory": str(directory), "manifest": manifest,
                    "requirements_adapter": read_json(self._path(f"frozen/{contract.revision}/requirements_adapter.json"))}

    def reopen(self, *, base, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise CadLoopError("PLANNING_REASON_REQUIRED", "Explain why the frozen intent is being reopened")
        with self._lock():
            state, previous, current = self._base(base, mutable=False)
            if state["status"] != "FROZEN":
                raise CadLoopError("PLANNING_NOT_FROZEN", "Only a frozen contract can be reopened")
            self.handoff()  # Verify the old freeze before preserving it.
            changed = current.model_dump()
            changed["status"] = "DRAFT"
            changed["accepted_decisions"] = []
            for assumption in changed["assumptions"]:
                assumption["accepted"] = False
            record = self._make_record(DesignContract.model_validate(changed), previous, reason)
            self._publish(record, state)
            return self.state()

    def materialize(self, *, base, design_dir, requirements=None):
        """Promote a reviewed source import into this workspace, anchor written last."""
        from ..contracts import Requirements
        from ..project import Project
        with self._lock():
            self._base(base, mutable=False)
            handoff = self.handoff()
            if (self.control / "anchor.json").exists():
                raise CadLoopError("PLANNING_ALREADY_MATERIALIZED", "Never rebind existing CAD; create a new workspace for changed intent")
            adapter = handoff["requirements_adapter"]
            # A valid old freeze may contain adapter output from before a
            # fail-closed bug fix. Recheck its immutable contract with today's
            # compiler without rewriting the reviewed artifacts or their hashes.
            from .handoff import compile_requirements
            current_adapter = compile_requirements(DesignContract.model_validate(handoff["contract"]))
            unsupported = list({(item["code"], item["id"]): item
                                for item in [*adapter["unsupported"], *current_adapter["unsupported"]]
                                if item["critical"]}.values())
            if unsupported:
                raise CadLoopError("PLANNING_VERIFICATION_UNSUPPORTED", "Resolve unsupported mandatory planning intent before materialization",
                                   unsupported=unsupported)
            compiled = adapter["requirements"]
            if compiled is None:
                raise CadLoopError("PLANNING_VERIFICATION_MISSING", "Provide explicit supported geometric verification intent")
            data = read_json(Path(requirements)) if requirements else compiled
            req = Requirements.model_validate(data)
            required = Requirements.model_validate(compiled)
            by_id = {check.id: check.model_dump() for check in req.checks}
            if (req.expected_parts != required.expected_parts or
                    any(by_id.get(check.id) != check.model_dump() for check in required.checks) or
                    any(req.parameters.get(key) != value for key, value in required.parameters.items()) or
                    not set(required.engineering_blockers) <= set(req.engineering_blockers) or
                    req.numerical_mm > required.numerical_mm or req.max_overlap_mm3 > required.max_overlap_mm3):
                raise CadLoopError("PLANNING_REQUIREMENTS_MISMATCH", "Reviewed requirements must preserve all compiled targets and parameter bounds")
            staging = Path(tempfile.mkdtemp(prefix="materialize-", dir=self.folder))
            journal = self._path("materialization.json", exists=False)
            try:
                write_json(staging / "requirements.json", data)
                imported = Project.create(staging / "project", requirements=staging / "requirements.json", design_dir=design_dir)
                binding = {"design_contract_revision": handoff["design_contract_revision"],
                           "design_contract_hash": handoff["design_contract_hash"]}
                anchor = read_json(imported.control / "anchor.json")
                anchor["planning"] = binding
                targets = ((imported.design, "design"),
                           (imported.root / "requirements.json", "requirements.json"),
                           (imported.control / "receipts.json", ".cadloop/receipts.json"))
                for _, relative in targets:
                    target = within(self.root, relative, must_exist=False)
                    if target.exists() or target.is_symlink():
                        raise CadLoopError("DIRECTORY_NOT_EMPTY", "Materialization never overwrites workspace files")
                write_json(journal, {"schema_version": 1, "staging": staging.name,
                                     "anchor_hash": digest(anchor), "targets": {
                                         relative: digest(tree_hashes(source)) if source.is_dir() else file_hash(source)
                                         for source, relative in targets}})
                for source, relative in targets:
                    target = within(self.root, relative, must_exist=False)
                    source.rename(target)
                write_json(self.control / "anchor.json", anchor)
            except BaseException:
                self._recover_materialization()
                raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            self._recover_materialization()
            project = Project(self.root)
            return {"status": "MATERIALIZED", "revision": project.revision(), **binding, "project": str(self.root)}

    def _recover_materialization(self):
        """The existing project anchor commits import; remove only owned partials."""
        journal = self._path("materialization.json", exists=False)
        if not journal.exists():
            return
        transaction = read_json(journal)
        targets = transaction.get("targets", {})
        staging_name = transaction.get("staging", "")
        if (set(targets) != {"design", "requirements.json", ".cadloop/receipts.json"} or
                not isinstance(staging_name, str) or not staging_name.startswith("materialize-") or
                Path(staging_name).name != staging_name):
            raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Invalid materialization journal")
        staging = self._path(staging_name, exists=False)
        anchor = within(self.root, ".cadloop/anchor.json", must_exist=False)
        if anchor.exists():
            if digest(read_json(anchor)) != transaction["anchor_hash"]:
                raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Materialized anchor differs from pending import")
        else:
            owned = []
            for relative, expected in targets.items():
                path = within(self.root, relative, must_exist=False)
                if path.exists():
                    actual = digest(tree_hashes(path)) if path.is_dir() else file_hash(path)
                    if actual != expected:
                        raise CadLoopError("PLANNING_TRANSACTION_INVALID", "Partial import was changed; refusing cleanup", path=relative)
                    owned.append(path)
            for path in owned:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        shutil.rmtree(staging, ignore_errors=True)
        journal.unlink()


def digest_text(value):
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
