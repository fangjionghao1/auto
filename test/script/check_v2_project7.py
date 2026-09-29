"""Independent numerical audit of project 7 V2 simulation outputs.

Reads exported CSV observations/trajectories/parameters rather than calling the
generator. The audit re-derives PCC elimination, electrical powers, swing ODE
steps, fixed-mode energy balance, equilibrium residuals, and outcome labels.
It is an evidence aid for V2, not a publication or gate decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp


OMEGA_B = 2 * math.pi * 50
TWO_PI = 2 * math.pi
EDGE_PAIRS = ((1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def number(row: dict[str, str], *names: str, default: float | None = None) -> float:
    for name in names:
        if name in row and row[name].strip():
            return float(row[name])
    if default is not None:
        return default
    raise KeyError(f"Missing numeric column among {names}")


def integer(row: dict[str, str], *names: str) -> int:
    return int(round(number(row, *names)))


def truth(row: dict[str, str], *names: str) -> bool:
    for name in names:
        if name in row:
            return row[name].strip().lower() in {"1", "true", "yes", "y"}
    raise KeyError(f"Missing Boolean column among {names}")


def optional_label(row: dict[str, str]) -> int | None:
    raw = row.get("label", "").strip().lower()
    if raw in {"", "nan", "none", "na"}:
        return None
    value = int(round(float(raw)))
    if value not in (0, 1):
        raise ValueError(f"Invalid label {raw!r}")
    return value


def vector(row: dict[str, str], prefix: str) -> np.ndarray:
    return np.array([number(row, f"{prefix}{index}") for index in range(1, 5)], dtype=float)


def family_from_row(row: dict[str, str]) -> dict:
    edge = np.zeros((4, 4), dtype=float)
    for i, j in EDGE_PAIRS:
        edge[i - 1, j - 1] = edge[j - 1, i - 1] = number(row, f"Ke{i}{j}")
    family = {
        "id": integer(row, "family_id", "id"),
        "H": vector(row, "H"), "D": vector(row, "D"),
        "P": vector(row, "P"), "k": vector(row, "k"),
        "r": vector(row, "r"), "edge": edge,
        "Kt": number(row, "K_tie_pre", "Kt_pre"),
        "beta": number(row, "beta"), "q": number(row, "q"),
        "delta_pre": vector(row, "delta_pre"),
        "delta_post": vector(row, "delta_post"),
        "post_certified": truth(row, "post_eq_certified", "post_eq_cert"),
        "post_eig_recorded": number(row, "post_eq_eigmin", default=math.nan),
        "pre_eig_recorded": number(row, "pre_eq_eigmin", default=math.nan),
        "pre_residual_recorded": number(row, "pre_eq_residual", default=math.nan),
        "post_residual_recorded": number(row, "post_eq_residual", default=math.nan),
        "tc_pair": np.array([number(row, "tc_short"), number(row, "tc_long")]),
        "row": row,
    }
    return family


def phase_parameters(family: dict, phase: str) -> tuple[np.ndarray, float, np.ndarray]:
    if phase == "fault":
        return family["q"] * family["k"], family["q"] * family["Kt"], family["r"] * family["P"]
    if phase == "post":
        return family["k"], family["beta"] * family["Kt"], family["P"]
    if phase == "pre":
        return family["k"], family["Kt"], family["P"]
    raise ValueError(f"Unknown phase {phase}")


def electrical(delta: np.ndarray, family: dict, phase: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Closed-form positive-stiffness PCC branch and nodal electrical power."""
    k, kt, _ = phase_parameters(family, phase)
    z = kt + np.exp(1j * delta) @ k
    theta = np.angle(z)
    zabs = np.abs(z)
    diff = delta[:, :, None] - delta[:, None, :]
    pe = np.sum(family["edge"][None, :, :] * np.sin(diff), axis=2)
    pe += k[None, :] * np.sin(delta - theta[:, None])
    return theta, zabs, pe


def equilibrium_check(delta: np.ndarray, family: dict, phase: str) -> dict:
    if not np.isfinite(delta).all():
        return {"available": False}
    k, kt, pref = phase_parameters(family, phase)
    theta, zabs, pe = electrical(delta.reshape(1, 4), family, phase)
    if zabs[0] <= 1e-12:
        return {"available": True, "power_residual_max": None,
                "pcc_stiffness": float(zabs[0]), "jacobian_eigmin": None,
                "theta": None, "error": "singular PCC branch"}
    a = k * np.cos(delta - theta[0])
    laplacian = np.diag(np.sum(family["edge"] * np.cos(delta[:, None] - delta[None, :]), axis=1))
    laplacian -= family["edge"] * np.cos(delta[:, None] - delta[None, :])
    jacobian = laplacian + np.diag(a) - np.outer(a, a) / zabs[0]
    eigmin = float(np.linalg.eigvalsh(jacobian).min())
    return {"available": True, "power_residual_max": float(np.max(np.abs(pe[0] - pref))),
            "pcc_stiffness": float(zabs[0]), "jacobian_eigmin": eigmin,
            "theta": float(theta[0])}


def phase_audit(rows: list[dict[str, str]], family: dict, phase: str) -> dict:
    if not rows:
        return {"points": 0, "error": "phase has no trajectory points"}
    times = np.array([number(row, "t") for row in rows], dtype=float)
    delta = np.array([vector(row, "delta") for row in rows])
    omega = np.array([vector(row, "omega") for row in rows])
    stored_theta = np.array([number(row, "theta_unwrapped") for row in rows])
    stored_zabs = np.array([number(row, "Zabs", "zabs") for row in rows])
    k, kt, pref = phase_parameters(family, phase)
    theta, zabs, pe = electrical(delta, family, phase)
    theta_error = np.arctan2(np.sin(stored_theta - theta), np.cos(stored_theta - theta))
    pcc_residual = np.sum(k[None, :] * np.sin(delta - stored_theta[:, None]), axis=1) - kt * np.sin(stored_theta)
    rhs = (pref[None, :] - family["D"][None, :] * omega - pe) / (2 * family["H"][None, :])
    dt = np.diff(times)
    angle_defect = np.diff(delta, axis=0) - 0.5 * OMEGA_B * dt[:, None] * (omega[1:] + omega[:-1])
    omega_defect = np.diff(omega, axis=0) - 0.5 * dt[:, None] * (rhs[1:] + rhs[:-1])
    upper = np.triu_indices(4, 1)
    edge_potential = -np.sum(family["edge"][upper][None, :] *
                             np.cos((delta[:, :, None] - delta[:, None, :])[:, upper[0], upper[1]]), axis=1)
    energy = (np.sum(family["H"][None, :] * omega * omega, axis=1) +
              (edge_potential - zabs - delta @ pref) / OMEGA_B)
    dissipation = np.sum(family["D"][None, :] * omega * omega, axis=1)
    energy_defect = np.diff(energy) + 0.5 * dt * (dissipation[1:] + dissipation[:-1])
    return {
        "points": len(rows), "t_start": float(times[0]), "t_end": float(times[-1]),
        "nonpositive_time_steps": int(np.sum(dt <= 0)), "max_step_s": float(np.max(dt)) if len(dt) else None,
        "min_pcc_stiffness": float(np.min(zabs)),
        "max_stored_pcc_stiffness_error": float(np.max(np.abs(stored_zabs - zabs))),
        "max_theta_modulo_error_rad": float(np.max(np.abs(theta_error))),
        "max_pcc_power_residual_pu": float(np.max(np.abs(pcc_residual))),
        "max_angle_step_defect_rad": float(np.max(np.abs(angle_defect))) if len(dt) else None,
        "max_frequency_step_defect_pu": float(np.max(np.abs(omega_defect))) if len(dt) else None,
        "max_energy_step_defect_pu_s": float(np.max(np.abs(energy_defect))) if len(dt) else None,
        "energy_change_pu_s": float(energy[-1] - energy[0]),
        "integrated_dissipation_pu_s": float(np.trapezoid(dissipation, times)),
        "times": times, "delta": delta, "omega": omega,
    }


def first_slip_time(times: np.ndarray, delta: np.ndarray, reference: float) -> float | None:
    gap = np.abs(delta - reference)
    indices = np.flatnonzero(gap >= TWO_PI - 1e-5)
    if not len(indices):
        return None
    index = int(indices[0])
    if index == 0:
        return float(times[0])
    low, high = gap[index - 1], gap[index]
    fraction = min(1.0, max(0.0, (TWO_PI - low) / (high - low))) if high != low else 1.0
    return float(times[index - 1] + fraction * (times[index] - times[index - 1]))


def stable_return_details(post: dict, family: dict) -> dict:
    if not family["post_certified"] or not np.isfinite(family["delta_post"]).all():
        return {"sampled_21": False, "all_saved_knots": False, "available": False}
    times, delta, omega = post["times"], post["delta"], post["omega"]
    if times[-1] < 40 - 1e-4 or times[0] > 39:
        return {"sampled_21": False, "all_saved_knots": False, "available": False}
    check_times = np.linspace(39, 40, 21)
    delta_sample = np.column_stack([np.interp(check_times, times, delta[:, i]) for i in range(4)])
    omega_sample = np.column_stack([np.interp(check_times, times, omega[:, i]) for i in range(4)])
    sampled_angle = float(np.max(np.abs(delta_sample - family["delta_post"])))
    sampled_frequency = float(np.max(np.abs(omega_sample)))
    mask = times >= 39 - 1e-9
    knot_angle = float(np.max(np.abs(delta[mask] - family["delta_post"])))
    knot_frequency = float(np.max(np.abs(omega[mask])))
    return {"sampled_21": sampled_angle < 0.02 and sampled_frequency < 1e-3,
            "all_saved_knots": knot_angle < 0.02 and knot_frequency < 1e-3,
            "sampled_max_angle_rad": sampled_angle, "sampled_max_frequency_pu": sampled_frequency,
            "knots_max_angle_rad": knot_angle, "knots_max_frequency_pu": knot_frequency,
            "saved_knots_in_last_second": int(np.sum(mask)), "available": True}


def derived_label(fault: dict, post: dict, family: dict) -> dict:
    pre = family["delta_pre"]
    fault_sc = first_slip_time(fault["times"], fault["delta"][:, 0], pre[0])
    fault_other = [first_slip_time(fault["times"], fault["delta"][:, i], pre[i]) for i in range(1, 4)]
    post_sc = (first_slip_time(post["times"], post["delta"][:, 0], pre[0])
               if post.get("points") else None)
    post_other = ([first_slip_time(post["times"], post["delta"][:, i], pre[i]) for i in range(1, 4)]
                  if post.get("points") else [])
    first_other = min((value for value in post_other if value is not None), default=None)
    if fault["min_pcc_stiffness"] < 1e-6:
        label, reason = None, "pcc_singular_fault"
    elif post.get("points") and post["min_pcc_stiffness"] < 1e-6:
        label, reason = None, "pcc_singular_post"
    elif fault_sc is not None:
        label, reason = None, "pre_sc_slip"
    elif any(value is not None for value in fault_other):
        label, reason = None, "pre_other_slip"
    elif post_sc is not None:
        label, reason = 1, "post_sc_slip"
    elif first_other is not None:
        label, reason = None, "post_other_only_slip"
    elif post.get("points") and stable_return_details(post, family)["sampled_21"]:
        label, reason = 0, "stable_return"
    else:
        label, reason = None, "undetermined"
    return {"label": label, "reason": reason, "fault_sc_time": fault_sc,
            "post_sc_time": post_sc, "post_other_first_time": first_other}


def expected_observation_features(rows: list[dict[str, str]], family: dict, tc: float) -> np.ndarray:
    times = np.array([number(row, "t") for row in rows])
    delta = np.array([vector(row, "delta") for row in rows])
    omega = np.array([vector(row, "omega") for row in rows])
    theta = np.unwrap(electrical(delta, family, "fault")[0])
    theta_pre = equilibrium_check(family["delta_pre"], family, "pre")["theta"]
    dynamic = np.column_stack(((delta - family["delta_pre"]) / math.pi,
                               np.sin(delta), np.cos(delta), omega,
                               (theta - theta_pre) / math.pi,
                               ((delta[:, 0] - theta) -
                                (family["delta_pre"][0] - theta_pre)) / math.pi,
                               times / tc))
    # MATLAB's logical indexing F.K_edge(triu(true(4),1)) is column-major.
    matlab_edge_order = ((1, 2), (1, 3), (2, 3), (1, 4), (2, 4), (3, 4))
    edge_features = np.array([family["edge"][i - 1, j - 1] for i, j in matlab_edge_order])
    static = np.concatenate((family["H"], family["D"], family["P"], family["k"],
                             edge_features,
                             [family["Kt"], family["beta"], family["q"]],
                             family["r"][1:], [tc]))
    assert dynamic.shape[1] == 19 and len(static) == 29
    return np.column_stack((dynamic, np.tile(static, (len(rows), 1))))


def independent_step_rerun(family: dict, tc: float) -> dict:
    """Reintegrate one scenario with a stricter independent SciPy solver."""
    initial = np.concatenate((family["delta_pre"], np.zeros(4)))

    def rhs(phase: str):
        def evaluate(_time, x):
            _, _, pref = phase_parameters(family, phase)
            _, _, pe = electrical(x[:4].reshape(1, 4), family, phase)
            return np.concatenate((OMEGA_B * x[4:],
                                   (pref - family["D"] * x[4:] - pe[0]) / (2 * family["H"])))
        return evaluate

    def singularity(phase: str):
        def evaluate(_time, x):
            return float(electrical(x[:4].reshape(1, 4), family, phase)[1][0] - 1e-6)
        evaluate.terminal = True
        evaluate.direction = -1
        return evaluate

    fault = solve_ivp(rhs("fault"), (0, tc), initial, rtol=1e-9, atol=1e-10,
                      max_step=0.01, events=[singularity("fault")])
    fault_delta = fault.y[:4].T
    fault_record = {"points": len(fault.t), "times": fault.t, "delta": fault_delta,
                    "omega": fault.y[4:].T,
                    "min_pcc_stiffness": float(electrical(fault_delta, family, "fault")[1].min())}
    post_record = {"points": 0}
    post = None
    if fault.success and fault.t[-1] >= tc - 1e-8 and fault_record["min_pcc_stiffness"] >= 1e-6:
        def sc_event(_time, x):
            return TWO_PI - abs(x[0] - family["delta_pre"][0])
        sc_event.terminal = True
        sc_event.direction = -1
        post = solve_ivp(rhs("post"), (tc, 40), fault.y[:, -1], rtol=1e-9, atol=1e-10,
                         max_step=0.01, events=[sc_event, singularity("post")])
        post_delta = post.y[:4].T
        post_record = {"points": len(post.t), "times": post.t, "delta": post_delta,
                       "omega": post.y[4:].T,
                       "min_pcc_stiffness": float(electrical(post_delta, family, "post")[1].min())}
    derived = derived_label(fault_record, post_record, family)
    return {"fault_success": bool(fault.success), "post_success": bool(post.success) if post else None,
            "fault_points": len(fault.t), "post_points": len(post.t) if post else 0,
            "fault_end_s": float(fault.t[-1]), "post_end_s": float(post.t[-1]) if post else None,
            "label": derived["label"], "reason": derived["reason"],
            "post_sc_slip_time_s": derived["post_sc_time"],
            "clearing_state": fault.y[:, -1].tolist(),
            "post_end_state": post.y[:, -1].tolist() if post else None}


def prediction_metrics(rows: list[dict[str, str]], column: str, split_id: int,
                       beta: float | None = None) -> dict:
    selected = [row for row in rows if integer(row, "split") == split_id and
                (beta is None or math.isclose(number(row, "beta"), beta, abs_tol=1e-12))]
    labeled = [row for row in selected if optional_label(row) is not None]
    used = [(optional_label(row), number(row, column)) for row in labeled
            if math.isfinite(number(row, column))]
    truth = np.array([item[0] for item in used], dtype=int)
    probability = np.array([item[1] for item in used], dtype=float)
    clipped = np.clip(probability, 1e-12, 1 - 1e-12)
    predicted = probability >= 0.5
    tp = int(np.sum(predicted & (truth == 1)))
    fp = int(np.sum(predicted & (truth == 0)))
    fn = int(np.sum(~predicted & (truth == 1)))
    tn = int(np.sum(~predicted & (truth == 0)))
    n_pos, n_neg = int(np.sum(truth == 1)), int(np.sum(truth == 0))
    both_classes = n_pos > 0 and n_neg > 0
    return {
        "n_total": len(selected), "n_labeled": len(labeled),
        "n_unresolved": len(selected) - len(labeled),
        "label_coverage": len(labeled) / len(selected) if selected else None,
        "prediction_coverage": len(used) / len(labeled) if labeled else None,
        "n": len(used), "n_positive": n_pos, "n_negative": n_neg,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": float(np.mean(predicted == truth)) if len(used) else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / n_pos if n_pos else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if both_classes else None,
        "balanced_accuracy": 0.5 * (tp / n_pos + tn / n_neg) if both_classes else None,
        "brier": float(np.mean((clipped - truth) ** 2)) if len(used) else None,
        "bce": float(np.mean(-truth * np.log(clipped) - (1 - truth) * np.log(1 - clipped)))
               if len(used) else None,
        "sc_slip_false_negatives": fn,
        "f1_defined": both_classes,
        "balanced_accuracy_defined": both_classes,
    }


def audit_prediction_files(sim: Path, census: dict[int, dict[str, str]]) -> dict:
    path = sim / "predictions.csv"
    if not path.is_file():
        return {"status": "pending predictions.csv"}
    rows = csv_rows(path)
    fixed = {"case_id", "family_id", "split", "beta", "tc", "label", "status", "capacity_margin"}
    methods = [name for name in rows[0] if name not in fixed]
    metadata_mismatches = []
    invalid_probability = []
    unresolved_with_prediction = []
    for row in rows:
        case_id = integer(row, "case_id")
        original = census.get(case_id)
        if (original is None or optional_label(row) != optional_label(original) or
                integer(row, "family_id") != integer(original, "family_id") or
                integer(row, "split") != integer(original, "split") or
                abs(number(row, "beta") - number(original, "beta")) > 1e-12 or
                abs(number(row, "tc") - number(original, "tc")) > 1e-12 or
                abs(number(row, "capacity_margin") - number(original, "capacity_margin")) > 1e-10):
            metadata_mismatches.append(case_id)
        for column in methods:
            value = number(row, column)
            if math.isfinite(value) and not 0 <= value <= 1:
                invalid_probability.append((case_id, column))
            if optional_label(row) is None and math.isfinite(value):
                unresolved_with_prediction.append((case_id, column))
    split_names = {1: "train", 2: "validation", 3: "test"}
    calculated = {column: {name: prediction_metrics(rows, column, split_id)
                           for split_id, name in split_names.items()} for column in methods}
    stratified_test = {str(beta): {column: prediction_metrics(rows, column, 3, beta)
                                   for column in methods} for beta in (1.0, 0.65, 0.35)}
    reported_path = sim / "metrics.csv"
    metric_differences = []
    if reported_path.is_file():
        for row in csv_rows(reported_path):
            method = row["method"].strip()
            seed_raw = row.get("seed", "").strip().lower()
            seed = None if seed_raw in {"", "nan"} else int(round(float(seed_raw)))
            column = f"{method}_seed{seed}" if seed is not None else method
            split_name = row["split"].strip()
            if column not in calculated or split_name not in calculated[column]:
                metric_differences.append({"key": [method, seed, split_name], "issue": "unknown row"})
                continue
            expected = calculated[column][split_name]
            for field, value in expected.items():
                if field not in row:
                    metric_differences.append({"key": [method, seed, split_name],
                                               "field": field, "issue": "missing column"})
                    continue
                raw = row[field].strip().lower()
                if isinstance(value, bool):
                    agree = (raw in {"1", "true"}) == value
                elif value is None:
                    agree = raw in {"nan", "", "na"}
                else:
                    agree = (raw not in {"nan", "", "na"} and
                             abs(float(raw) - value) <= 1e-8 * max(1.0, abs(value)))
                if not agree:
                    metric_differences.append({"key": [method, seed, split_name], "field": field,
                                               "reported": row[field], "recomputed": value})
    return {
        "status": "complete" if reported_path.is_file() else "metrics.csv pending",
        "prediction_sha256": sha256(path),
        "metrics_sha256": sha256(reported_path) if reported_path.is_file() else None,
        "prediction_rows": len(rows), "method_columns": methods,
        "metadata_mismatch_case_ids": metadata_mismatches,
        "invalid_probability_entries": invalid_probability,
        "unresolved_with_prediction_entries": unresolved_with_prediction,
        "recomputed": calculated,
        "test_by_beta": stratified_test,
        "reported_metric_differences": metric_differences,
    }


def audit(project: Path, rerun: bool = False) -> dict:
    sim = project / "仿真"
    required = [sim / name for name in ("family_params.csv", "case_census.csv",
                                        "trajectory_points.csv", "observations.csv")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required independent-audit inputs missing: " + "; ".join(missing))
    families = {family["id"]: family for family in
                (family_from_row(row) for row in csv_rows(required[0]))}
    census = {integer(row, "case_id", "id"): row for row in csv_rows(required[1])}
    family_equilibria = {}
    for family_id, family in families.items():
        family_equilibria[family_id] = {
            "pre": equilibrium_check(family["delta_pre"], family, "pre"),
            "post": equilibrium_check(family["delta_post"], family, "post"),
        }
    family_design_issues = []
    for family_id, family in families.items():
        issues = []
        if abs(family["P"][0]) > 1e-12:
            issues.append("SC mechanical reference is not zero")
        if np.any(family["H"] <= 0) or np.any(family["D"] <= 0):
            issues.append("nonpositive inertia or damping")
        if (np.any(family["k"] <= 0) or family["Kt"] <= 0 or
                np.any(family["edge"] < 0) or not np.allclose(family["edge"], family["edge"].T)):
            issues.append("invalid or asymmetric coupling")
        if not np.isclose(family["r"][0], 1):
            issues.append("SC fault multiplier differs from one")
        if not np.isclose(family["tc_pair"], sorted(family["tc_pair"])).all():
            issues.append("fault duration pair not ordered")
        pre_check = family_equilibria[family_id]["pre"]
        if (pre_check.get("power_residual_max") is None or
                pre_check["power_residual_max"] > 1e-7 or
                pre_check["jacobian_eigmin"] is None or pre_check["jacobian_eigmin"] <= 1e-6):
            issues.append("pre-fault equilibrium not independently certified")
        if (math.isfinite(family["pre_eig_recorded"]) and
                pre_check.get("jacobian_eigmin") is not None and
                abs(family["pre_eig_recorded"] - pre_check["jacobian_eigmin"]) > 1e-6):
            issues.append("recorded pre-fault eigenvalue differs from independent Jacobian")
        post_check = family_equilibria[family_id]["post"]
        if family["post_certified"] and family["beta"] * family["Kt"] - np.sum(family["P"]) < -1e-8:
            issues.append("certified post-fault equilibrium violates export necessary condition")
        if family["post_certified"] and (
                post_check.get("power_residual_max") is None or
                post_check["power_residual_max"] > 1e-7 or
                post_check["jacobian_eigmin"] is None or
                post_check["jacobian_eigmin"] <= 1e-6):
            issues.append("claimed post-fault equilibrium not independently certified")
        if (family["post_certified"] and math.isfinite(family["post_eig_recorded"]) and
                post_check.get("jacobian_eigmin") is not None and
                abs(family["post_eig_recorded"] - post_check["jacobian_eigmin"]) > 1e-6):
            issues.append("recorded post-fault eigenvalue differs from independent Jacobian")
        if issues:
            family_design_issues.append({"family_id": family_id, "issues": issues})
    per_case = {}
    with required[2].open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for case_id, rows_iter in itertools.groupby(reader, key=lambda row: integer(row, "case_id")):
            if case_id in per_case:
                raise ValueError(f"case_id {case_id} is not a contiguous trajectory block")
            rows = list(rows_iter)
            if case_id not in census:
                raise ValueError(f"Trajectory case {case_id} absent from census")
            family_id = integer(census[case_id], "family_id")
            family = families[family_id]
            tc = number(census[case_id], "tc", "tc_s")
            phase_rows = {phase: [row for row in rows if row["phase"].strip().lower() == phase]
                          for phase in ("fault", "post")}
            fault = phase_audit(phase_rows["fault"], family, "fault")
            post = phase_audit(phase_rows["post"], family, "post")
            derived = derived_label(fault, post, family)
            return_check = (stable_return_details(post, family) if post.get("points") else
                            {"available": False, "sampled_21": False, "all_saved_knots": False})
            claimed = optional_label(census[case_id])
            claimed_margin = number(census[case_id], "capacity_margin", default=math.nan)
            calculated_margin = float(family["beta"] * family["Kt"] - np.sum(family["P"]))
            per_case[case_id] = {
                "family_id": family_id, "split": census[case_id].get("split", ""),
                "tc_s": tc,
                "tc_matches_family_pair": bool(np.any(np.isclose(tc, family["tc_pair"], atol=1e-9))),
                "capacity_margin_error_pu": (abs(claimed_margin - calculated_margin)
                                             if math.isfinite(claimed_margin) else None),
                "claimed_label": claimed, "derived_label": derived["label"],
                "claimed_status": census[case_id].get("status", ""),
                "derived_reason": derived["reason"],
                "label_agrees": claimed == derived["label"],
                "fault": {key: value for key, value in fault.items() if key not in {"times", "delta", "omega"}},
                "post": {key: value for key, value in post.items() if key not in {"times", "delta", "omega"}},
                "event_times": {key: value for key, value in derived.items() if key.endswith("time")},
                "return_check": return_check,
                "clearing_state": (np.concatenate((fault["delta"][-1], fault["omega"][-1])).tolist()
                                   if fault.get("points") else None),
                "post_end_state": (np.concatenate((post["delta"][-1], post["omega"][-1])).tolist()
                                   if post.get("points") else None),
            }
    observed = defaultdict(list)
    with required[3].open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            observed[integer(row, "case_id")].append(row)
    observation_issues = []
    censored_observation_cases = []
    feature_error_by_case = {}
    for case_id, rows in observed.items():
        rows.sort(key=lambda row: integer(row, "sample_index"))
        tc = number(census[case_id], "tc", "tc_s")
        t = np.array([number(row, "t") for row in rows])
        features = np.array([[number(row, f"feature{i}") for i in range(1, 49)] for row in rows])
        time_issue = len(rows) != 24 or np.any(t < -1e-9) or np.any(t > tc + 1e-9)
        if time_issue:
            observation_issues.append(case_id)
            continue
        if not np.isfinite(features).all():
            if (per_case[case_id]["derived_reason"] == "pcc_singular_fault" and
                    per_case[case_id]["derived_label"] is None):
                censored_observation_cases.append(case_id)
            else:
                observation_issues.append(case_id)
            continue
        family = families[per_case[case_id]["family_id"]]
        expected = expected_observation_features(rows, family, tc)
        feature_error_by_case[case_id] = float(np.max(np.abs(features - expected)))
    label_mismatches = [case_id for case_id, result in per_case.items() if not result["label_agrees"]]
    return_grid_knot_disagreements = [case_id for case_id, result in per_case.items()
                                      if result["return_check"]["available"] and
                                      result["return_check"]["sampled_21"] !=
                                      result["return_check"]["all_saved_knots"]]
    phase_keys = ("min_pcc_stiffness", "max_stored_pcc_stiffness_error",
                  "max_theta_modulo_error_rad", "max_pcc_power_residual_pu",
                  "max_angle_step_defect_rad", "max_frequency_step_defect_pu",
                  "max_energy_step_defect_pu_s")
    extrema = {}
    for key in phase_keys:
        values = [result[phase][key] for result in per_case.values()
                  for phase in ("fault", "post") if result[phase].get(key) is not None]
        extrema[key] = (min(values) if key == "min_pcc_stiffness" else max(values)) if values else None
    split = defaultdict(set)
    for result in per_case.values():
        split[result["split"]].add(result["family_id"])
    family_split_disjoint = all(not split[a].intersection(split[b]) for a, b in
                                itertools.combinations(split, 2))
    label_counts = Counter((result["split"], result["derived_label"]) for result in per_case.values())
    rerun_results = {}
    if rerun:
        selected = []
        for beta in (1.0, 0.65, 0.35):
            for label in (0, 1, None):
                candidates = [case_id for case_id, result in per_case.items()
                              if np.isclose(families[result["family_id"]]["beta"], beta) and
                              result["derived_label"] == label]
                if candidates:
                    selected.append(min(candidates))
        for case_id in sorted(set(selected)):
            saved = per_case[case_id]
            independent = independent_step_rerun(families[saved["family_id"]], saved["tc_s"])
            independent["label_agrees_saved"] = independent["label"] == saved["derived_label"]
            independent["clearing_state_max_abs_error"] = float(np.max(np.abs(
                np.asarray(independent["clearing_state"]) - np.asarray(saved["clearing_state"]))))
            if independent["post_end_state"] is not None and saved["post_end_state"] is not None:
                independent["post_end_state_max_abs_error"] = float(np.max(np.abs(
                    np.asarray(independent["post_end_state"]) - np.asarray(saved["post_end_state"]))))
            rerun_results[case_id] = independent
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_dir": str(project.resolve()),
        "input_sha256": {path.name: sha256(path) for path in required},
        "family_count": len(families), "case_count": len(per_case),
        "family_equilibria": family_equilibria,
        "family_design_issues": family_design_issues,
        "family_split_counts": {key: len(value) for key, value in split.items()},
        "family_split_disjoint": family_split_disjoint,
        "beta_family_counts": dict(Counter(family["beta"] for family in families.values())),
        "derived_label_counts_by_split": {f"{key[0]}:{key[1]}": count for key, count in label_counts.items()},
        "label_mismatch_case_ids": label_mismatches,
        "return_grid_knot_disagreement_case_ids": return_grid_knot_disagreements,
        "observation_issue_case_ids": observation_issues,
        "censored_observation_case_ids": censored_observation_cases,
        "max_feature_reconstruction_error": (max(feature_error_by_case.values())
                                             if feature_error_by_case else None),
        "feature_reconstruction_error_by_case": feature_error_by_case,
        "observation_case_count": len(observed),
        "physics_extrema": extrema,
        "independent_stricter_step_reruns": rerun_results,
        "per_case": per_case,
        "metrics_audit": audit_prediction_files(sim, census),
        "notes": ["All PCC, ODE, energy and label calculations are independent Python calculations from exported values.",
                  "A matching CSV label alone is not a gate pass; verify scientific assumptions and manuscript claims separately."],
    }


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rerun", action="store_true",
                        help="Reintegrate stratified cases with SciPy at half the stored max step")
    args = parser.parse_args()
    result = audit(args.project_dir, rerun=args.rerun)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(f"Audited {result['family_count']} families / {result['case_count']} cases")
    print(f"Label mismatches: {len(result['label_mismatch_case_ids'])}; "
          f"observation issues: {len(result['observation_issue_case_ids'])}")
    print(f"Evidence: {args.output}")


if __name__ == "__main__":
    main()
