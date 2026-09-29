"""Independent CSV aggregation checks for manuscript 8-0928, V2.

Reads exported CSVs only; does not call the MATLAB summary functions or mutate
the manuscript. Fails on a numeric mismatch above exported precision.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SIM = ROOT / "仿真"
VERSION = "V2_constant_PQ_AC"
RATE = 0.08
HARDEN_RATE = 0.5
N_LINE = 12


def rows(name: str) -> list[dict[str, str]]:
    with (SIM / name).open(encoding="utf-8", newline="") as stream:
        result = list(csv.DictReader(stream))
    if any(row.get("model_version") != VERSION for row in result):
        raise AssertionError(f"model version mismatch in {name}")
    return result


def close(a: float, b: float, label: str, tol: float = 1e-9) -> float:
    difference = abs(a - b)
    if difference > tol:
        raise AssertionError(f"{label}: {a} != {b}, difference={difference}")
    return difference


raw = rows("raw_results.csv")
pairs = rows("hardening_pairs.csv")
summary = rows("summary_metrics.csv")
faults = rows("fault_breakdown.csv")
risk = rows("risk_by_line.csv")
qa = rows("qa_v2.csv")
assert len(raw) == 57600 and len(pairs) == 316800
assert len(summary) == 5 and len(faults) == len(risk) == 12 and len(qa) == 72

max_ens_identity = 0.0
raw_groups: dict[tuple[str, str, int], list[dict[str, str]]] = defaultdict(list)
for row in raw:
    calculated = (float(row["initial_unserved_MW"]) * 5
                  + float(row["final_unserved_MW"]) * 55) / 60
    max_ens_identity = max(max_ens_identity,
                           close(calculated, float(row["ens_MWh"]), "ENS identity"))
    raw_groups[(row["dataset"], row["method"], int(row["initial_line"]))].append(row)

for dataset in ("main", "reference"):
    per_line = 200 if dataset == "main" else 2000
    methods = ("prob", "deterministic", "no_cascade", "none") if dataset == "main" else ("prob", "no_cascade")
    for method in methods:
        for line in range(1, N_LINE + 1):
            assert len(raw_groups[(dataset, method, line)]) == per_line

max_fault_difference = 0.0
for row in faults:
    line = int(row["initial_line"])
    full = raw_groups[("reference", "prob", line)]
    nosec = raw_groups[("reference", "no_cascade", line)]
    full_ens = [float(x["ens_MWh"]) for x in full]
    nosec_ens = [float(x["ens_MWh"]) for x in nosec]
    differences = [a - b for a, b in zip(full_ens, nosec_ens)]
    checks = {
        "full_ENS_MWh_per_event": statistics.mean(full_ens),
        "no_secondary_ENS_MWh_per_event": statistics.mean(nosec_ens),
        "signed_secondary_ENS_MWh_per_event": statistics.mean(differences),
        "full_EENS_MWh_per_year": RATE * statistics.mean(full_ens),
        "no_secondary_EENS_MWh_per_year": RATE * statistics.mean(nosec_ens),
        "signed_secondary_EENS_MWh_per_year": RATE * statistics.mean(differences),
        "signed_secondary_95pct_halfwidth": RATE * 1.96 * statistics.stdev(differences) / math.sqrt(2000),
        "full_95pct_halfwidth": RATE * 1.96 * statistics.stdev(full_ens) / math.sqrt(2000),
        "secondary_trip_fraction": sum(int(x["secondary_trips"]) > 0 for x in full) / 2000,
    }
    for key, calculated in checks.items():
        max_fault_difference = max(max_fault_difference,
                                   close(calculated, float(row[key]), f"fault {line} {key}"))

method_map = {
    "Probability+cascade": "prob",
    "Deterministic tie": "deterministic",
    "No secondary trip": "no_cascade",
    "Static N-1": "none",
    "No transfer ablation": "none",
}
max_summary_difference = 0.0
for row in summary:
    method = method_map[row["method"]]
    groups = [raw_groups[("main", method, line)] for line in range(1, N_LINE + 1)]
    annual = RATE * sum(statistics.mean(float(x["ens_MWh"]) for x in group) for group in groups)
    cascade = sum(int(x["secondary_trips"]) > 0 for group in groups for x in group) / 2400
    max_summary_difference = max(max_summary_difference,
                                 close(annual, float(row["annual_eens_MWh_per_year"]), f"summary {method} EENS"),
                                 close(cascade, float(row["secondary_trip_fraction"]), f"summary {method} cascade"))

pair_groups: dict[tuple[str, int, int], list[dict[str, str]]] = defaultdict(list)
max_pair_identity = 0.0
for row in pairs:
    dataset = row["dataset"]
    e = int(row["hardened_line"])
    f = int(row["initial_line"])
    expected = RATE * float(row["base_ENS_MWh"]) - RATE * (HARDEN_RATE if e == f else 1) * float(row["hardened_ENS_MWh"])
    max_pair_identity = max(max_pair_identity,
                            close(expected, float(row["annual_pair_contribution"]), "pair contribution"))
    pair_groups[(dataset, e, f)].append(row)

max_risk_difference = 0.0
reference_deltas: dict[int, float] = {}
for row in risk:
    e = int(row["line_id"])
    means = []
    variances = []
    for f in range(1, N_LINE + 1):
        group = pair_groups[("reference", e, f)]
        assert len(group) == 2000
        values = [float(x["annual_pair_contribution"]) for x in group]
        means.append(statistics.mean(values))
        variances.append(statistics.variance(values))
    delta = sum(means)
    halfwidth = 1.96 * math.sqrt(sum(value / 2000 for value in variances))
    reference_deltas[e] = delta
    for key, value in (("reference_delta_MWh_per_year", delta),
                       ("reference_ci_low", delta - halfwidth),
                       ("reference_ci_high", delta + halfwidth)):
        max_risk_difference = max(max_risk_difference,
                                  close(value, float(row[key]), f"risk {e} {key}"))

full_eens = sum(float(x["full_EENS_MWh_per_year"]) for x in faults)
nosec_eens = sum(float(x["no_secondary_EENS_MWh_per_year"]) for x in faults)
signed_difference = sum(float(x["signed_secondary_EENS_MWh_per_year"]) for x in faults)
close(full_eens - nosec_eens, signed_difference, "signed EENS difference")
main_prob = [x for line in range(1, N_LINE + 1) for x in raw_groups[("main", "prob", line)]]
secondary_cases = sum(int(x["secondary_trips"]) > 0 for x in main_prob)
assert secondary_cases == 173
assert all(int(x["secondary_trips"]) <= 1 for x in main_prob)
top3 = sorted(reference_deltas, key=reference_deltas.get, reverse=True)[:3]
assert top3 == [9, 5, 1]

for language in ("中文", "英文"):
    source = (ROOT / f"论文_{language}.md").read_text(encoding="utf-8")
    for value in ("0.119187123", "0.083115301", "0.036071822", "0.024776700", "0.023362696", "0.019709605"):
        assert value in source, f"{language} manuscript missing {value}"

result = {
    "raw_rows": len(raw), "hardening_pair_rows": len(pairs), "qa_rows": len(qa),
    "max_ens_identity_error_MWh": max_ens_identity,
    "max_pair_identity_error_MWh_per_year": max_pair_identity,
    "max_fault_table_difference": max_fault_difference,
    "max_summary_difference": max_summary_difference,
    "max_risk_table_difference": max_risk_difference,
    "main_secondary_cases": secondary_cases,
    "reference_full_EENS_MWh_per_year": full_eens,
    "reference_no_secondary_EENS_MWh_per_year": nosec_eens,
    "reference_signed_difference_MWh_per_year": signed_difference,
    "top3_reference_lines": top3,
    "reference_delta_9_minus_5": reference_deltas[9] - reference_deltas[5],
    "max_QA_power_residual_MW": max(abs(float(x["power_residual_MW"])) for x in qa),
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
