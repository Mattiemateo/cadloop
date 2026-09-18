"""Measured acceptance over imported geometry and protected requirements."""
from __future__ import annotations
from itertools import combinations
import math
from . import kernel as k
from .errors import CadLoopError


def result(id, status, code, message, evidence=None, hint=""):
    return {"id": id, "status": status, "blocking": True, "code": code,
            "message": message, "evidence": evidence or {}, "edit_hint": hint}


def interval(value, minimum, maximum, epsilon):
    # IEEE NaN compares false in both directions; never let that mean "pass".
    numbers = [value, epsilon, *[v for v in (minimum, maximum) if v is not None]]
    if (any(type(v) not in (float, int) or not math.isfinite(v) for v in numbers)
            or epsilon <= 0 or (minimum is not None and maximum is not None and minimum > maximum)):
        return "indeterminate"
    if minimum is not None and value < minimum - epsilon:
        return "fail"
    if maximum is not None and value > maximum + epsilon:
        return "fail"
    if ((minimum is not None and abs(value-minimum) <= epsilon) or
            (maximum is not None and abs(value-maximum) <= epsilon)):
        return "indeterminate"
    return "pass"


class GeometryQueries:
    """Memoize repeated traversals within a single imported, immutable scene.

    Never persisted or shared between revisions. Returned distance dictionaries
    are copied so one check's thresholds cannot overwrite another's evidence.
    """
    def __init__(self, parts):
        self.parts = parts
        self.cache = {}

    def _get(self, key, compute):
        if key not in self.cache:
            self.cache[key] = compute()
        return self.cache[key]

    def metrics(self, name):
        m = self._get(("metrics",name), lambda: k.metrics(self.parts[name]))
        self.cache[("bounds",name)] = m["bounds_mm"]
        return m

    def bounds(self, name):
        return self._get(("bounds",name), lambda: k.bounds(self.parts[name]))

    def holes(self, name):
        return self._get(("holes",name), lambda: k.holes_z(self.parts[name]))

    def reference(self, name, ref):
        return self._get(("ref",name), lambda:
                        k.cylinder_ref(self.parts[ref.part], ref, observed=self.holes(ref.part))
                        if ref.kind == "cylinder" else k.plane_ref(self.parts[ref.part], ref))

    def distance(self, a, b):
        return self._get(("distance",a,b), lambda: k.distance(self.parts[a],self.parts[b])).copy()

    def disjoint(self, a, b, eps):
        ba, bb = self.bounds(a), self.bounds(b)
        return any(ba["max"][i]+eps < bb["min"][i] or bb["max"][i]+eps < ba["min"][i] for i in range(3))


def check_one(check, parts, req, *, queries=None):
    eps = req.numerical_mm
    queries = queries if queries is not None else GeometryQueries(parts)
    def part(name):
        if name not in parts:
            raise CadLoopError("MISSING_REQUIRED_PART", "Cannot measure a missing part", part=name)
        return parts[name]
    def ref(name):
        r = req.refs[name]
        part(r.part)  # Retain a typed missing-part error for standalone checks.
        return queries.reference(name, r)

    if check.kind == "dimension":
        part(check.part)
        b = queries.bounds(check.part)
        value = b["size"]["xyz".index(check.axis)]
        status = interval(value, check.minimum, check.maximum, eps)
        ev = {"measured_mm": value, "range_mm": [check.minimum, check.maximum],
              "axis": check.axis, "part": check.part,
              "method": "axis_aligned_BREP_bounds", "bounds_mm": b}
        code = "DIMENSION_OUT_OF_RANGE"
    elif check.kind == "clearance":
        part(check.a); part(check.b)
        ev = queries.distance(check.a, check.b)
        value = ev["distance_mm"]
        ev.update({"range_mm": [check.minimum, check.maximum], "parts": [check.a, check.b]})
        # A zero lower bound is a physical domain boundary, not an uncertain threshold.
        status = interval(value, check.minimum if check.minimum > 0 else None,
                          check.maximum, eps)
        code = "CLEARANCE_OUT_OF_RANGE"
    elif check.kind == "through_holes_z":
        shape = part(check.part)
        observed = queries.holes(check.part)
        expected = [x.model_dump() for x in check.holes]
        b = queries.bounds(check.part)
        remaining = list(range(len(observed)))
        matches, defects = [], []
        for target in expected:
            ids = [i for i in remaining if
                   abs(observed[i]["radius_mm"]-target["radius"]) <= check.tolerance and
                   math.hypot(observed[i]["axis_origin_mm"][0]-target["x"],
                              observed[i]["axis_origin_mm"][1]-target["y"]) <= check.tolerance]
            if len(ids) != 1:
                defects.append({"expected": target, "matches": len(ids)})
                continue
            i = ids[0]
            remaining.remove(i)
            obs = observed[i]
            through = (abs(obs["bounds_mm"]["min"][2]-b["min"][2]) <= check.tolerance and
                       abs(obs["bounds_mm"]["max"][2]-b["max"][2]) <= check.tolerance)
            match = {"expected": target, "through": through}
            matches.append(match)
            if not through:
                defects.append({"expected": target, "reason": "BLIND_OR_PARTIAL_HOLE"})
            else:
                probe = k.bore_obstruction(shape, obs, b["min"][2], b["max"][2], eps)
                probe["allowed_numerical_mm3"] = req.max_overlap_mm3
                match["lumen_check"] = probe
                obstruction_status = interval(probe["obstruction_mm3"], None,
                                              req.max_overlap_mm3, eps**3)
                if obstruction_status == "indeterminate":
                    raise CadLoopError("KERNEL_INDETERMINATE", "Bore obstruction is on a numerical decision boundary",
                                       expected=target, **probe)
                if obstruction_status == "fail":
                    defects.append({"expected": target, "reason": "BORE_OBSTRUCTED", **probe})
        status = "pass" if not defects and not remaining else "fail"
        ev = {"expected": expected, "observed": observed, "matches": matches, "defects": defects,
              "unexpected_cylinders": remaining, "part": check.part,
              "coverage": "complete_unsplit_analytic_Z_bores_only"}
        code = "HOLE_MISMATCH"
    elif check.kind == "coaxial":
        a, b = ref(check.a), ref(check.b)
        angle = math.degrees(math.acos(min(1., max(0., abs(k.dot(a["axis"], b["axis"]))))))
        offset = k.norm(k.cross(k.sub(a["axis_origin_mm"], b["axis_origin_mm"]), a["axis"]))
        statuses = [interval(offset, None, check.max_offset, eps),
                    interval(angle, None, check.max_angle_deg, 1e-7)]
        status = "fail" if "fail" in statuses else "indeterminate" if "indeterminate" in statuses else "pass"
        ev = {"offset_mm": offset, "angle_deg": angle, "max_offset_mm": check.max_offset,
              "max_angle_deg": check.max_angle_deg, "axis_a": a, "axis_b": b,
              "method": "analytic_axes_from_imported_cylindrical_faces"}
        code = "AXES_MISALIGNED"
    elif check.kind == "plane_contact":
        af, ai = ref(check.a)
        bf, bi = ref(check.b)
        ev = k.projected_contact(af, ai, bf, bi)
        ev.update({"max_gap_mm": check.max_gap, "min_area_mm2": check.min_area})
        statuses = [interval(ev["distance_mm"], None, check.max_gap, eps),
                    interval(ev["projected_contact_area_mm2"], check.min_area, None, eps**2)]
        status = "fail" if not ev["opposing_normals"] or "fail" in statuses else "indeterminate" if "indeterminate" in statuses else "pass"
        code = "CONTACT_NOT_ESTABLISHED"
    else:
        raise CadLoopError("CHECK_UNSUPPORTED", "Unknown check kind")
    return result(check.id, status, "OK" if status == "pass" else
                  "NUMERICAL_BOUNDARY" if status == "indeterminate" else code,
                  check.description, ev, check.edit_hint)


def required_check_ids(req):
    """The controller owns the full acceptance checklist, including automatic checks."""
    return {"AUTO_inventory", "AUTO_export_assembly_brep", "AUTO_export_assembly_step",
            *[f"AUTO_valid_{name}" for name in req.expected_parts],
            *[f"AUTO_overlap_{a}_{b}" for a,b in combinations(req.expected_parts, 2)],
            *[c.id for c in req.checks]}


def run_checks(parts, req, *, metrics_out=None):
    checks = []
    queries = GeometryQueries(parts)
    missing = sorted(set(req.expected_parts)-set(parts))
    extra = sorted(set(parts)-set(req.expected_parts))
    checks.append(result("AUTO_inventory", "fail" if missing or extra else "pass",
                         "INVENTORY_MISMATCH" if missing or extra else "OK",
                         "Every required part must exist; extra physical parts are rejected.",
                         {"missing": missing, "unexpected": extra, "expected": req.expected_parts},
                         "Inspect build() and Scene.add() registrations."))
    valid = {}
    for name in sorted(set(parts) | set(req.expected_parts)):
        try:
            if name not in parts:
                raise CadLoopError("MISSING_REQUIRED_PART", "Required part is absent", part=name)
            m = queries.metrics(name)
            if metrics_out is not None:
                metrics_out[name] = m
            passed = m["valid"] and m["solid_count"] == 1 and not m["contains_free_topology"] and m["volume_mm3"] > 1e-8
            valid[name] = passed
            checks.append(result(f"AUTO_valid_{name}", "pass" if passed else "fail",
                                 "OK" if passed else "INVALID_SOLID", f"One valid closed solid: {name}", m))
        except Exception as e:
            checks.append(result(f"AUTO_valid_{name}", "indeterminate",
                                 getattr(e, "code", "KERNEL_INDETERMINATE"), str(e)))
    # All expected pairs have an explicit no-overlap check. No blanket ignore list.
    for a, b in combinations(req.expected_parts, 2):
        id = f"AUTO_overlap_{a}_{b}"
        try:
            if not valid.get(a) or not valid.get(b):
                raise CadLoopError("DEPENDENCY_INVALID", "Cannot validate overlap with a missing/invalid solid")
            broadphase = queries.disjoint(a, b, req.numerical_mm)
            v = 0. if broadphase else k.common_volume(parts[a], parts[b])
            status = interval(v, None, req.max_overlap_mm3, req.numerical_mm**3)
            checks.append(result(id, status, "OK" if status == "pass" else "INTERFERENCE",
                                 f"No unintended overlap: {a} / {b}",
                                 {"overlap_mm3": v, "allowed_numerical_mm3": req.max_overlap_mm3,
                                  "method": "disjoint_conservative_bounds" if broadphase else "BREP_boolean_common",
                                  "parts": [a, b]}))
        except Exception as e:
            checks.append(result(id, "indeterminate", getattr(e, "code", "KERNEL_INDETERMINATE"), str(e)))
    for check in req.checks:
        try:
            referenced = [getattr(check, "part", None)]
            if check.kind == "clearance":
                referenced += [check.a, check.b]
            if check.kind in ("coaxial", "plane_contact"):
                referenced += [req.refs[check.a].part, req.refs[check.b].part]
            if any(name is not None and not valid.get(name, False) for name in referenced):
                raise CadLoopError("DEPENDENCY_INVALID", "A referenced part is missing or invalid")
            checks.append(check_one(check, parts, req, queries=queries))
        except Exception as e:
            ev = e.details if isinstance(e, CadLoopError) else {}
            checks.append(result(check.id, "indeterminate", getattr(e, "code", "KERNEL_INDETERMINATE"),
                                 str(e), ev, check.edit_hint))
    return checks
