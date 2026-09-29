#!/usr/bin/env python3
"""A deliberately narrow pilot; all values are illustrative, not field data."""
import csv
import json
import math
from pathlib import Path
import random


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260929)
    rows = []
    for case in range(60):
        delta0 = rng.uniform(0.01, 0.05)
        velocity0 = rng.uniform(-0.01, 0.01)
        omega = rng.uniform(2.0, 5.0)
        zeta = rng.uniform(0.2, 0.5)
        alpha = zeta * omega
        damped = omega * math.sqrt(1 - zeta * zeta)
        # Exact underdamped solution of delta''+2*zeta*omega*delta'+omega^2*delta=0.
        peak = max(abs(math.exp(-alpha * i * 0.02) *
                       (delta0 * math.cos(damped * i * 0.02) +
                        (velocity0 + alpha * delta0) / damped * math.sin(damped * i * 0.02)))
                   for i in range(2001))
        # E'= -2*zeta*omega*delta'^2 <= 0 yields an amplitude bound for all t>=0.
        energy_bound = math.sqrt(delta0 * delta0 + (velocity0 / omega) ** 2)
        rows.append({"case": case + 1, "delta0_rad": delta0,
                     "velocity0_rad_s": velocity0, "omega_rad_s": omega, "zeta": zeta,
                     "peak_sampled_rad": peak, "energy_bound_rad": energy_bound,
                     "slip_proxy": int(peak >= 2 * math.pi)})
    with (output / "pilot.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "seed": 20260929, "cases": len(rows), "horizon_s": 40.0, "step_s": 0.02,
        "event_threshold_rad": 2 * math.pi,
        "event_proxy_count": sum(r["slip_proxy"] for r in rows),
        "no_event_proxy_count": sum(not r["slip_proxy"] for r in rows),
        "max_sampled_amplitude_rad": max(r["peak_sampled_rad"] for r in rows),
        "max_energy_bound_rad": max(r["energy_bound_rad"] for r in rows),
        "model": "positive-damping linear oscillator; illustrative synthetic pilot",
        "limitation": "Finite-window proxy is not a validated field stability label; model has no fault or nonlinear loss-of-synchronism mechanism."
    }
    (output / "pilot.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(Path(__file__).resolve().parent / "先导"), ensure_ascii=False, indent=2))
