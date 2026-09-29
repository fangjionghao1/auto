"""Paired, topology-stratified bootstrap audit of project 6 test-case MAE.

This reads the archived MATLAB output and does not retrain or relabel any case.
The resampling unit is the test case; model seeds are averaged within each case.
"""

import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "gen/artifacts/6-0928/V1/基于图神经网络的新能源场站同步调相机小干扰稳定评估"
    / "仿真/raw_results.csv"
)
OUTPUT = ROOT / "test/script/reports/evidence/2026-09-29_6-0928_bootstrap_mae.json"
SEEDS = (101, 202, 303)
RESAMPLES = 20000
RNG_SEED = 20260929


def main():
    by_topology = defaultdict(list)
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["split"] != "test":
                continue
            alpha = float(row["alpha_exact_s_inv"])
            gnn = sum(abs(float(row[f"gnn_seed{s}_s_inv"]) - alpha) for s in SEEDS) / len(SEEDS)
            no_message = sum(
                abs(float(row[f"no_message_seed{s}_s_inv"]) - alpha) for s in SEEDS
            ) / len(SEEDS)
            by_topology[row["topology"]].append(gnn - no_message)

    groups = [by_topology[k] for k in sorted(by_topology, key=int)]
    count = sum(len(group) for group in groups)
    if count != 80 or sorted(map(len, groups)) != [26, 27, 27]:
        raise ValueError("Unexpected test split or topology counts")
    point = sum(sum(group) for group in groups) / count

    rng = random.Random(RNG_SEED)
    boot = []
    for _ in range(RESAMPLES):
        total = 0.0
        for group in groups:
            total += sum(group[rng.randrange(len(group))] for _ in group)
        boot.append(total / count)
    boot.sort()
    lower = boot[int(0.025 * RESAMPLES)]
    upper = boot[int(0.975 * RESAMPLES)]

    result = {
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "estimand": "mean over test cases of mean-seed absolute-error(GNN) minus mean-seed absolute-error(no-message), s^-1",
        "resampling_unit": "test case, paired by case, stratified within the three fixed topology templates",
        "method": "percentile bootstrap, conditional on the one archived dataset and trained seed set",
        "test_case_count": count,
        "topology_counts": {key: len(by_topology[key]) for key in sorted(by_topology, key=int)},
        "rng_seed": RNG_SEED,
        "resamples": RESAMPLES,
        "point_difference_s_inv": point,
        "ci_95_s_inv": [lower, upper],
        "fraction_positive_case_differences": sum(d > 0 for group in groups for d in group) / count,
        "mean_difference_by_topology_s_inv": {
            key: sum(by_topology[key]) / len(by_topology[key])
            for key in sorted(by_topology, key=int)
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
