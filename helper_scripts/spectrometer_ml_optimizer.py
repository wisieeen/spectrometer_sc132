"""
Spectrometer Geometry ML Optimizer

Optimizes optical geometry using:
1. Bayesian Optimization (gp_minimize) - sample-efficient
2. Genetic Algorithm (Differential Evolution) - robust, multimodal

Objective: maximize resolution (minimize Δλ) over design range.
Design variables: grooves/mm, θᵢ, f_coll, f_cam, slit_width.

Requires: scipy, scikit-optimize
  pip install scipy scikit-optimize
"""

import numpy as np
from typing import Tuple, Optional

# Optional imports - fail gracefully if not installed
try:
    from scipy.optimize import differential_evolution
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import skopt
    from skopt import gp_minimize
    from skopt.space import Real, Integer
    HAS_SKOPT = True
except ImportError:
    HAS_SKOPT = False


# ========== OPTICAL MODEL (from OPTICAL_EQUATIONS.md) ==========

def grating_diffraction_angle(lam_nm: float, grooves_per_mm: float,
                              theta_i_rad: float, m: int = 1) -> Optional[float]:
    """β = arcsin(mλ/d - sin α). Returns radians or None."""
    lam_m = lam_nm * 1e-9
    d = 1e-3 / grooves_per_mm
    sin_beta = (m * lam_m / d) - np.sin(theta_i_rad)
    if abs(sin_beta) > 1:
        return None
    return np.arcsin(sin_beta)


def resolution_diffraction_limit(lam_nm: float, N: int, m: int = 1) -> float:
    """Δλ = λ / (Nm) in nm."""
    return lam_nm / (N * m)


def resolution_slit_limit(grooves_per_mm: float, slit_width_um: float,
                          f_coll_mm: float, m: int = 1) -> float:
    """Δλ ≈ d·Δx/(f·m) in nm."""
    d_m = 1e-3 / grooves_per_mm
    return d_m * (slit_width_um * 1e-6) / (f_coll_mm * 1e-3 * m) * 1e9


def effective_resolution(lam_nm: float, grooves_per_mm: float, slit_width_um: float,
                        f_coll_mm: float, N: int = 50000, m: int = 1) -> float:
    """Worst of diffraction and slit limit."""
    dlam_diff = resolution_diffraction_limit(lam_nm, N, m)
    dlam_slit = resolution_slit_limit(grooves_per_mm, slit_width_um, f_coll_mm, m)
    return max(dlam_diff, dlam_slit)


def spectral_range_covered(lam_min: float, lam_max: float, grooves_per_mm: float,
                           theta_i_rad: float, m: int = 1) -> Tuple[bool, float]:
    """
    Check if [lam_min, lam_max] is fully diffracted (no |sin β| > 1).
    Returns (all_valid, fraction_covered).
    """
    n = 50
    lambdas = np.linspace(lam_min, lam_max, n)
    valid = 0
    for lam in lambdas:
        if grating_diffraction_angle(lam, grooves_per_mm, theta_i_rad, m) is not None:
            valid += 1
    return valid == n, valid / n


# ========== MERIT FUNCTION ==========

LAM_MIN, LAM_MAX = 400, 700
N_GROOVES = 50000


def merit(x) -> float:
    """
    Merit to minimize. Lower is better.
    x = [grooves_per_mm, theta_i_deg, f_coll_mm, f_cam_mm, slit_width_um]
    """
    x = np.atleast_1d(x)
    grooves, theta_deg, f_coll, f_cam, slit = x[0], x[1], x[2], x[3], x[4]
    theta_i = np.deg2rad(theta_deg)

    # Penalty if range not covered
    all_ok, frac = spectral_range_covered(LAM_MIN, LAM_MAX, grooves, theta_i)
    range_penalty = 0 if all_ok else (1 - frac) * 10.0

    # Mean resolution over range (nm)
    lambdas = np.linspace(LAM_MIN, LAM_MAX, 20)
    res = [effective_resolution(lam, grooves, slit, f_coll, N_GROOVES) for lam in lambdas]
    mean_res = np.mean(res)

    # Merit: resolution + range penalty (minimize)
    return mean_res + range_penalty


# ========== BOUNDS ==========

BOUNDS = [
    (300, 2400),   # grooves_per_mm
    (10, 70),      # theta_i_deg
    (25, 80),      # f_coll_mm
    (40, 100),     # f_cam_mm
    (15, 80),      # slit_width_um
]


# ========== BAYESIAN OPTIMIZATION ==========

def run_bayesian_optimization(n_calls: int = 50, random_state: int = 42) -> dict:
    """Run Bayesian optimization via skopt.gp_minimize."""
    if not HAS_SKOPT:
        raise ImportError("scikit-optimize required: pip install scikit-optimize")

    space = [
        Real(300, 2400, name="grooves_per_mm"),
        Real(10, 70, name="theta_i_deg"),
        Real(25, 80, name="f_coll_mm"),
        Real(40, 100, name="f_cam_mm"),
        Real(15, 80, name="slit_width_um"),
    ]

    result = gp_minimize(
        merit,
        space,
        n_calls=n_calls,
        random_state=random_state,
        verbose=True,
    )

    best_x = result.x
    return {
        "method": "Bayesian (gp_minimize)",
        "best_merit": result.fun,
        "best_params": {
            "grooves_per_mm": best_x[0],
            "theta_i_deg": best_x[1],
            "f_coll_mm": best_x[2],
            "f_cam_mm": best_x[3],
            "slit_width_um": best_x[4],
        },
        "n_evals": n_calls,
    }


# ========== GENETIC ALGORITHM (Differential Evolution) ==========

def run_genetic_optimization(maxiter: int = 100, popsize: int = 15,
                             seed: int = 42) -> dict:
    """Run Differential Evolution (evolutionary/genetic algorithm)."""
    if not HAS_SCIPY:
        raise ImportError("scipy required: pip install scipy")

    result = differential_evolution(
        merit,
        bounds=BOUNDS,
        strategy="best1bin",
        maxiter=maxiter,
        popsize=popsize,
        seed=seed,
        disp=True,
        polish=True,
    )

    x = result.x
    return {
        "method": "Genetic (Differential Evolution)",
        "best_merit": float(result.fun),
        "best_params": {
            "grooves_per_mm": x[0],
            "theta_i_deg": x[1],
            "f_coll_mm": x[2],
            "f_cam_mm": x[3],
            "slit_width_um": x[4],
        },
        "n_evals": result.nfev,
        "success": result.success,
    }


# ========== MAIN ==========

def main():
    """CLI entrypoint: run geometry optimization and print best parameters.

    Inputs:
        Command-line args:
        - `--method` selects `bayesian`, `genetic`, or `both`
        - `--n-calls` controls the number of evaluations for Bayesian optimization
        - `--maxiter` controls iterations for the genetic optimizer
    Output:
        Prints optimization results to stdout (best merit + best parameter set).
    Transformation:
        Chooses which optimization routine(s) to run, collects results, and reports the
        best overall solution when multiple methods are executed.
    """
    import argparse
    parser = argparse.ArgumentParser(description="Spectrometer geometry ML optimizer")
    parser.add_argument("--method", choices=["bayesian", "genetic", "both"],
                        default="both", help="Optimization method")
    parser.add_argument("--n-calls", type=int, default=50,
                        help="Bayesian: number of evaluations")
    parser.add_argument("--maxiter", type=int, default=80,
                        help="Genetic: max iterations")
    args = parser.parse_args()

    results = []
    if args.method in ("bayesian", "both"):
        print("\n=== Bayesian Optimization ===\n")
        r = run_bayesian_optimization(n_calls=args.n_calls)
        results.append(r)
        print(f"Best merit: {r['best_merit']:.4f}")
        print("Best params:", r["best_params"])

    if args.method in ("genetic", "both"):
        print("\n=== Genetic Algorithm (Differential Evolution) ===\n")
        r = run_genetic_optimization(maxiter=args.maxiter)
        results.append(r)
        print(f"Best merit: {r['best_merit']:.4f}")
        print("Best params:", r["best_params"])

    if len(results) > 1:
        best = min(results, key=lambda x: x["best_merit"])
        print(f"\nOverall best: {best['method']} with merit {best['best_merit']:.4f}")


if __name__ == "__main__":
    main()
