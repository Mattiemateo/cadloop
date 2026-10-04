"""Flat JSON planning commands, registered without reshaping the legacy CLI."""
from pathlib import Path
import sys

from ..errors import CadLoopError
from ..util import MAX_JSON_BYTES, file_hash, read_json, strict_loads
from .store import PlanningProject


def add_commands(sub):
    parser = sub.add_parser("design-init", help="Start planning without CAD source or a model API")
    parser.add_argument("project", type=Path)
    brief = parser.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief")
    brief.add_argument("--brief-file", type=Path)
    for command in ("state", "context", "propose", "questions", "answer", "audit", "render",
                    "freeze", "handoff", "reopen", "materialize"):
        parser = sub.add_parser("design-" + command)
        parser.add_argument("project", type=Path)
        if command in ("propose", "answer", "freeze", "reopen", "materialize"):
            parser.add_argument("--base", required=True)
        if command == "render":
            parser.add_argument("--base")
        if command == "propose":
            parser.add_argument("--file", required=True, help="PlanningProposal JSON file, or - for stdin")
        if command == "answer":
            parser.add_argument("--answer", action="append", required=True, help="QUESTION_ID=OPTION_ID")
        if command == "handoff":
            parser.add_argument("--format", choices=("json", "markdown"), default="json")
        if command == "reopen":
            parser.add_argument("--reason", required=True)
        if command == "materialize":
            parser.add_argument("--design-dir", type=Path, required=True)
            parser.add_argument("--requirements", type=Path)


def run_command(args):
    command = args.command.removeprefix("design-")
    if command == "init":
        if args.brief_file:
            file_hash(args.brief_file)
            if args.brief_file.stat().st_size > 16_000:
                raise CadLoopError("PLANNING_BRIEF_INVALID", "Brief file exceeds 16000 UTF-8 bytes")
            brief = args.brief_file.read_text(encoding="utf-8").strip()
        else:
            brief = args.brief
        workspace = PlanningProject.initialize(args.project, brief=brief)
        return {"project": str(workspace.root), **workspace.state()}, 0
    workspace = PlanningProject(args.project)
    if command == "state":
        return workspace.state(), 0
    if command == "context":
        return workspace.context(), 0
    if command == "questions":
        return workspace.questions(), 0
    if command == "propose":
        if args.file == "-":
            data = sys.stdin.read(MAX_JSON_BYTES + 1)
            if len(data.encode("utf-8")) > MAX_JSON_BYTES:
                raise CadLoopError("UNSAFE_INPUT", "PlanningProposal stdin exceeds the JSON budget")
            packet = strict_loads(data)
        else:
            packet = read_json(Path(args.file))
        return workspace.propose(packet, base=args.base), 0
    if command == "answer":
        answers = []
        for answer in args.answer:
            if answer.count("=") != 1:
                raise CadLoopError("PLANNING_ANSWERS_INVALID", "Use --answer QUESTION_ID=OPTION_ID")
            answers.append(tuple(answer.split("=")))
        return workspace.answer(base=args.base, answers=answers), 0
    if command == "audit":
        result = workspace.audit()
        return result, 2 if result["blocking"] else 0
    if command == "render":
        return workspace.render(base=args.base), 0
    if command == "freeze":
        result = workspace.freeze(base=args.base)
        return result, 0 if result["frozen"] else 2
    if command == "handoff":
        handoff = workspace.handoff()
        return handoff["modeling_context"] if args.format == "markdown" else handoff, 0
    if command == "reopen":
        return workspace.reopen(base=args.base, reason=args.reason), 0
    if command == "materialize":
        return workspace.materialize(base=args.base, design_dir=args.design_dir, requirements=args.requirements), 0
    raise CadLoopError("PLANNING_COMMAND_UNKNOWN", "Unknown planning operation")
