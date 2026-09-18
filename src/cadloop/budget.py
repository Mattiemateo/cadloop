"""Atomic request reservations; pending/uncertain charges block further requests."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from pathlib import Path
import uuid
from .util import read_json, write_json, project_lock
from .errors import CadLoopError


class Budget:
    def __init__(self, path: Path, *, cap_usd, input_per_million, output_per_million):
        self.path = Path(path)
        self.lock_dir = self.path.parent / ("." + self.path.name + ".lock")
        try:
            self.cap = Decimal(str(cap_usd))
            self.input_rate = Decimal(str(input_per_million)) / Decimal(1_000_000)
            self.output_rate = Decimal(str(output_per_million)) / Decimal(1_000_000)
        except InvalidOperation as e:
            raise CadLoopError("PRICING_INVALID", "Costs must be finite nonnegative numbers") from e
        if any(not v.is_finite() or v < 0 for v in (self.cap, self.input_rate, self.output_rate)):
            raise CadLoopError("PRICING_INVALID", "Costs must be finite and nonnegative")
        self.config = {"cap_usd": str(self.cap), "input_rate": str(self.input_rate), "output_rate": str(self.output_rate)}
        with project_lock(self.lock_dir):
            if not self.path.exists():
                write_json(self.path, {"config": self.config, "requests": [], "blocked": False})
            self._read()

    def _read(self):
        data = read_json(self.path)
        if data["config"] != self.config:
            raise CadLoopError("PRICING_CHANGED", "Use a new session to change the budget or pricing")
        return data

    @staticmethod
    def _booked(data):
        return sum((Decimal(r["booked_usd"]) for r in data["requests"]), Decimal(0))

    @staticmethod
    def _request(data, rid):
        for r in data["requests"]:
            if r["id"] == rid:
                return r
        raise CadLoopError("REQUEST_UNKNOWN", "Unknown budget request id")

    def booked(self):
        with project_lock(self.lock_dir):
            return self._booked(self._read())

    def reserve(self, input_upper: int, output_upper: int):
        with project_lock(self.lock_dir):
            data = self._read()
            if data["blocked"] or any(r["status"] in ("pending", "uncertain") for r in data["requests"]):
                raise CadLoopError("BUDGET_UNCERTAIN", "A pending or uncertain request blocks further API calls")
            if any(type(x) is not int or x < 0 for x in (input_upper, output_upper)):
                raise CadLoopError("USAGE_INVALID", "Token bounds must be nonnegative integers")
            charge = input_upper * self.input_rate + output_upper * self.output_rate
            if self._booked(data) + charge > self.cap:
                raise CadLoopError("BUDGET_EXHAUSTED", "Remaining budget cannot cover this request reservation")
            rid = uuid.uuid4().hex
            data["requests"].append({"id": rid, "status": "pending", "input_upper": input_upper,
                                      "output_upper": output_upper, "booked_usd": str(charge),
                                      "reserved_usd": str(charge)})
            write_json(self.path, data)
            return rid

    def reconcile(self, rid: str, prompt_tokens: int, completion_tokens: int):
        with project_lock(self.lock_dir):
            if any(type(x) is not int or x < 0 for x in (prompt_tokens, completion_tokens)):
                self.uncertain(rid)
                raise CadLoopError("USAGE_INVALID", "Provider returned invalid token usage")
            data = self._read()
            r = self._request(data, rid)
            if r["status"] != "pending":
                raise CadLoopError("REQUEST_ALREADY_ACCOUNTED", "A request cannot be reconciled twice")
            actual = prompt_tokens * self.input_rate + completion_tokens * self.output_rate
            bound_broken = prompt_tokens > r["input_upper"] or completion_tokens > r["output_upper"]
            r.update({"status": "complete", "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "booked_usd": str(actual), "reservation_bound_broken": bound_broken})
            data["blocked"] = data["blocked"] or bound_broken or self._booked(data) > self.cap
            write_json(self.path, data)
            if data["blocked"]:
                raise CadLoopError("BUDGET_BOUND_BROKEN", "Provider usage exceeded the configured reservation; future calls are blocked")

    def uncertain(self, rid):
        with project_lock(self.lock_dir):
            data = self._read()
            r = self._request(data, rid)
            if r["status"] == "pending":
                r["status"] = "uncertain"
            data["blocked"] = True
            write_json(self.path, data)

    def summary(self):
        with project_lock(self.lock_dir):
            data = self._read()
            pending = any(r["status"] in ("pending", "uncertain") for r in data["requests"])
            return {"booked_usd": str(self._booked(data)), "cap_usd": str(self.cap),
                    "request_count": len(data["requests"]), "uncertain": pending,
                    "blocked": data["blocked"] or pending,
                    "scope": "This controller session only; user-supplied text-token tariffs, not a provider-side billing guarantee."}
