"""Recompute the given pilot using only Python's standard library."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = ROOT / "pilot.csv"
raw = source.read_bytes()
with source.open(encoding="utf-8-sig", newline="") as stream:
    reader = csv.DictReader(stream)
    expected = ["case", "actual_kw", "baseline_kw", "proposed_kw"]
    if reader.fieldnames != expected:
        raise ValueError(f"Unexpected columns: {reader.fieldnames!r}")
    rows = list(reader)
if len(rows) != 20:
    raise ValueError(f"Expected 20 pilot cases, got {len(rows)}")
if len({row["case"] for row in rows}) != len(rows):
    raise ValueError("Duplicate case identifiers: group-level weighting needs review")

computed = []
for row in rows:
    vals = {field: Decimal(row[field]) for field in expected[1:]}
    if not all(value.is_finite() and value >= 0 for value in vals.values()):
        raise ValueError(f"Invalid load/prediction in case {row['case']}")
    be = vals["baseline_kw"] - vals["actual_kw"]
    pe = vals["proposed_kw"] - vals["actual_kw"]
    difference = abs(pe) - abs(be)
    computed.append({
        **row,
        "baseline_error_kw": str(be),
        "proposed_error_kw": str(pe),
        "baseline_abs_error_kw": str(abs(be)),
        "proposed_abs_error_kw": str(abs(pe)),
        "abs_error_difference_kw": str(difference),
        "comparison": "better" if difference < 0 else "worse" if difference > 0 else "tie",
    })

n = Decimal(len(computed))
bmae = sum(Decimal(row["baseline_abs_error_kw"]) for row in computed) / n
pmae = sum(Decimal(row["proposed_abs_error_kw"]) for row in computed) / n
threshold = Decimal("0.9") * bmae
ratio = pmae / bmae if bmae else None
totals = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "source": source.name,
    "source_sha256": hashlib.sha256(raw).hexdigest(),
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "environment": {"python_version": platform.python_version(), "executable": sys.executable, "dependencies": "standard library only"},
    "scope": "Given synthetic pilot only; not a held-out test or executed forecasting method",
    "row_count": len(rows),
    "case_count": len({row["case"] for row in rows}),
    "weighting": "equal per case; one row per case",
    "actual_range_kw": [str(min(Decimal(row["actual_kw"]) for row in rows)), str(max(Decimal(row["actual_kw"]) for row in rows))],
    "baseline_sum_abs_error_kw": str(bmae * n),
    "proposed_sum_abs_error_kw": str(pmae * n),
    "baseline_mae_kw": str(bmae),
    "proposed_mae_kw": str(pmae),
    "contract_factor": "0.9",
    "contract_threshold_kw": str(threshold),
    "proposed_to_baseline_ratio": str(ratio) if ratio is not None else None,
    "relative_improvement": str(1 - ratio) if ratio is not None else None,
    "mae_difference_kw": str(pmae - bmae),
    "threshold_excess_kw": str(pmae - threshold),
    "contract_satisfied": pmae <= threshold,
    "case_comparison_counts": {label: sum(row["comparison"] == label for row in computed) for label in ["better", "tie", "worse"]},
    "baseline_mean_signed_error_kw": str(sum(Decimal(row["baseline_error_kw"]) for row in computed) / n),
    "proposed_mean_signed_error_kw": str(sum(Decimal(row["proposed_error_kw"]) for row in computed) / n),
    "observed_proposed_residual_equals_four_times_baseline": all(Decimal(row["proposed_error_kw"]) == 4 * Decimal(row["baseline_error_kw"]) for row in computed),
    "generalization_inference": "Not supported: synthetic pilot, independence/provenance/method information absent",
}
with (ROOT / "先导逐工况误差.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(computed[0]))
    writer.writeheader()
    writer.writerows(computed)
(ROOT / "先导指标.json").write_text(json.dumps(totals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(totals, ensure_ascii=False, indent=2))
