"""Small, auditable filesystem and serialization primitives."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import tempfile
import threading
from pathlib import Path
from .errors import CadLoopError

MAX_JSON_BYTES = 4_000_000


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CadLoopError("UNSAFE_PATH", "Expected a regular, non-symlink file", path=str(path))
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def strict_loads(text: str):
    """Reject ambiguous keys and *all* non-finite encodings, including 1e999."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate JSON key: {key}")
            out[key] = value
        return out
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value
    def bad_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    return json.loads(text, object_pairs_hook=pairs, parse_float=finite_float,
                      parse_constant=bad_constant)


def read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise CadLoopError("UNSAFE_INPUT", "JSON must be a bounded regular non-symlink file", path=str(path))
    return strict_loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(obj) + b"\n"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def within(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise CadLoopError("UNSAFE_PATH", "Only relative paths within the declared root are permitted")
    root = root.resolve()
    p = root
    for bit in rel.parts:
        p = p / bit
        if p.is_symlink():
            raise CadLoopError("UNSAFE_PATH", "Symlinks are not permitted", path=relative)
    if not p.resolve().is_relative_to(root):
        raise CadLoopError("UNSAFE_PATH", "Path escapes its root", path=relative)
    if must_exist and not p.is_file():
        raise CadLoopError("ARTIFACT_MISSING", "Required file does not exist", path=relative)
    return p


def tree_hashes(root: Path) -> dict[str, str]:
    result = {}
    for p in sorted(root.rglob("*")):
        if "__pycache__" in p.parts:
            continue
        if p.is_symlink():
            raise CadLoopError("UNSAFE_PATH", "Symlinks are not permitted", path=str(p))
        if p.is_file():
            result[p.relative_to(root).as_posix()] = file_hash(p)
    return result


def versions() -> dict[str, str]:
    answer = {"python": platform.python_version(), "platform": platform.system(),
              "machine": platform.machine()}
    for name in ("cadloop", "cadquery-ocp", "cadquery", "build123d", "pydantic", "numpy", "matplotlib", "vtk"):
        try:
            answer[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            answer[name] = "not-installed" if name != "cadloop" else "0.1.1-source"
    return answer


def package_digest() -> str:
    root = Path(__file__).parent
    return digest({p.relative_to(root).as_posix(): file_hash(p)
                   for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts})


_lock_state = threading.local()


@contextlib.contextmanager
def project_lock(root: Path):
    """Nonblocking cross-process lock, reentrant only in the owning thread.

    Reentrancy lets an entire search/finish/loop transaction hold the same lock as
    its nested propose/evaluate calls. The PID prevents a fork inheriting ownership.
    This is advisory controller serialization, NOT a sandbox.
    """
    import fcntl
    root = root.resolve()
    key = (os.getpid(), str(root))
    held = getattr(_lock_state, "held", None)
    if held is None:
        held = _lock_state.held = set()
    if key in held:
        yield
        return
    root.mkdir(parents=True, exist_ok=True)
    with (root / "controller.lock").open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CadLoopError("PROJECT_BUSY", "Another controller operation is in progress") from exc
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)
            fcntl.flock(f, fcntl.LOCK_UN)
