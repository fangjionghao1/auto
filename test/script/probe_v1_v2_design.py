"""Pre-design scale probe for paired degree-preserving small-signal networks.

This exploratory probe contains no trained model and does not select cases by label.
The production MATLAB experiment must freeze its own parameters before training.
"""

import numpy as np


def symmetric_weight(w, i, j, value):
    w[i, j] = value
    w[j, i] = value


def spectral_abscissa(h, d, kg, w):
    n = len(h)
    lap = np.diag(w.sum(axis=1) + kg) - w
    state = np.block(
        [
            [np.zeros((n, n)), (2 * np.pi * 50) * np.eye(n)],
            [-np.diag(1 / (2 * h)) @ lap, -np.diag(d / (2 * h))],
        ]
    )
    normalizer = np.diag(1 / np.sqrt(2 * h))
    _, vectors = np.linalg.eigh(normalizer @ lap @ normalizer)
    modal_damping = np.einsum("ij,i,ij->j", vectors, d / (2 * h), vectors)
    proxy = -0.5 * modal_damping.min()
    return np.linalg.eigvals(state).real.max(), np.linalg.eigvalsh(lap).min(), proxy


def main():
    rng = np.random.default_rng(42)
    n = 8
    edges = {(i, (i + 1) % n) for i in range(n)}
    edges.update({(0, 2), (1, 3), (4, 6), (5, 7)})
    changes = ((0, 1, 1), (2, 3, 1), (0, 2, -1), (1, 3, -1))
    shifts = []
    alpha_values = []
    proxy_errors = []
    proxy_shift_errors = []
    flips = 0
    min_lap = float("inf")
    min_weight = float("inf")
    degree_error = 0.0
    for _ in range(1000):
        h = np.r_[3.0, rng.uniform(1, 3, n - 1)]
        d = np.r_[rng.uniform(0.4, 1.2), rng.uniform(-0.6, 0.8, n - 1)]
        kg = np.r_[rng.uniform(0.1, 0.3), rng.uniform(0.2, 0.5, n - 1)]
        base = np.zeros((n, n))
        for i, j in edges:
            symmetric_weight(base, i, j, rng.uniform(0.4, 0.7))
        pair = []
        proxy_pair = []
        for sign in (1, -1):
            w = base.copy()
            for i, j, coeff in changes:
                symmetric_weight(w, i, j, base[i, j] + sign * coeff * 0.25)
            min_weight = min(min_weight, w[w > 0].min())
            degree_error = max(degree_error, np.max(np.abs(w.sum(axis=1) - base.sum(axis=1))))
            a, eigmin, proxy = spectral_abscissa(h, d, kg, w)
            pair.append(a)
            proxy_pair.append(proxy)
            alpha_values.append(a)
            proxy_errors.append(abs(a - proxy))
            min_lap = min(min_lap, eigmin)
        shifts.append(abs(pair[0] - pair[1]))
        proxy_shift_errors.append(abs((pair[0] - pair[1]) - (proxy_pair[0] - proxy_pair[1])))
        flips += (pair[0] >= 0) != (pair[1] >= 0)
    print("alpha quantiles", np.quantile(alpha_values, [0, 0.1, 0.5, 0.9, 1]))
    print("pair shift quantiles", np.quantile(shifts, [0, 0.1, 0.5, 0.9, 1]))
    print("modal proxy MAE", np.mean(proxy_errors))
    print("modal proxy pair-shift error MAE", np.mean(proxy_shift_errors))
    print("label flips", flips, "of", len(shifts))
    print("min positive edge", min_weight, "min laplacian eigen", min_lap)
    print("max weighted-degree mismatch", degree_error)


if __name__ == "__main__":
    main()
