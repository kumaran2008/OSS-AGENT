import re
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class StatisticalAuditReport:
    sample_size: int
    mean: float
    std_dev: float
    variance: float
    ci_95_lower: float
    ci_95_upper: float
    coefficient_of_variation: float
    p_value_vs_baseline: Optional[float]
    t_statistic: Optional[float]
    is_significant: bool
    reproduction_gap: float
    flags: List[str]
    verdict: str


class MathAndStatsVerifier:
    """
    Symbolic & Statistical Sanity Engine:
    - Verifies symbolic mathematical equivalence (SymPy with numeric fallback).
    - Executes Welch's two-sample t-tests and two-tailed p-value derivations.
    - Flags p-hacking, high variance, and single-seed non-reproducible trials.
    """

    # -------------------------------------------------------------------------
    # 1. Symbolic & Numeric Math Verification
    # -------------------------------------------------------------------------
    @classmethod
    def verify_symbolic_equivalence(cls, expr_a: str, expr_b: str, variables: Optional[List[str]] = None) -> Tuple[bool, str]:
        """
        Tests if expr_a == expr_b symbolically using SymPy,
        falling back to high-precision Monte Carlo numeric evaluation.
        """
        # Engine 1: SymPy CAS
        try:
            import sympy
            s_a = sympy.sympify(expr_a)
            s_b = sympy.sympify(expr_b)
            diff = sympy.simplify(s_a - s_b)
            if diff == 0:
                return True, f"SymPy Verified: {expr_a} ≡ {expr_b} (diff = 0)"
        except Exception:
            pass

        # Engine 2: Numeric Monte Carlo Evaluation
        vars_to_test = variables or ["x", "y", "z"]
        # Normalize simple math symbols
        clean_a = expr_a.replace("^", "**")
        clean_b = expr_b.replace("^", "**")

        random.seed(42)
        trials = 15
        max_err = 0.0

        for _ in range(trials):
            env = {v: random.uniform(1.1, 8.5) for v in vars_to_test}
            # Add safe math builtins
            env.update({"exp": math.exp, "log": math.log, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos})
            try:
                val_a = eval(clean_a, {"__builtins__": {}}, env)
                val_b = eval(clean_b, {"__builtins__": {}}, env)
                err = abs(val_a - val_b)
                if err > max_err:
                    max_err = err
                if err > 1e-4:
                    return False, f"Numeric Divergence at {env}: {clean_a}={val_a:.4f} != {clean_b}={val_b:.4f} (err={err:.4e})"
            except Exception as eval_err:
                return False, f"Evaluation error during symbolic verification: {eval_err}"

        return True, f"Numeric Verified: {expr_a} ≡ {expr_b} (max residual: {max_err:.2e} across {trials} points)"

    # -------------------------------------------------------------------------
    # 2. Welch's t-test (Pure Python Distribution Engine)
    # -------------------------------------------------------------------------
    @staticmethod
    def compute_welch_t_test(sample_a: List[float], sample_b: List[float]) -> Tuple[float, float, float]:
        """
        Computes Welch's t-test for samples with unequal variances.
        Returns (t_stat, degrees_of_freedom, two_tailed_p_value).
        """
        n1, n2 = len(sample_a), len(sample_b)
        if n1 < 2 or n2 < 2:
            return 0.0, 1.0, 1.0

        mean1 = sum(sample_a) / n1
        mean2 = sum(sample_b) / n2

        var1 = sum((x - mean1) ** 2 for x in sample_a) / (n1 - 1)
        var2 = sum((x - mean2) ** 2 for x in sample_b) / (n2 - 1)

        se = math.sqrt((var1 / n1) + (var2 / n2))
        if se == 0:
            return 0.0, float(n1 + n2 - 2), 1.0

        t_stat = (mean1 - mean2) / se

        # Welch-Satterthwaite degrees of freedom
        num = ((var1 / n1) + (var2 / n2)) ** 2
        denom = (((var1 / n1) ** 2) / (n1 - 1)) + (((var2 / n2) ** 2) / (n2 - 1))
        df = max(1.0, num / denom if denom != 0 else 1.0)

        # Standard normal approximation of p-value via math.erfc
        p_val = math.erfc(abs(t_stat) / math.sqrt(2.0))
        return round(t_stat, 4), round(df, 2), round(max(0.0, min(1.0, p_val)), 5)

    # -------------------------------------------------------------------------
    # 3. Statistical Sanity & P-Hacking Auditor
    # -------------------------------------------------------------------------
    def audit_reproduced_metrics(
        self,
        values: List[float],
        baseline_target: Optional[float] = None,
        alpha: float = 0.05
    ) -> StatisticalAuditReport:
        n = len(values)
        flags: List[str] = []

        if n == 0:
            return StatisticalAuditReport(
                sample_size=0, mean=0.0, std_dev=0.0, variance=0.0, ci_95_lower=0.0, ci_95_upper=0.0,
                coefficient_of_variation=0.0, p_value_vs_baseline=None, t_statistic=None,
                is_significant=False, reproduction_gap=1.0, flags=["EMPTY_SAMPLE_DATA"],
                verdict="REJECT: No empirical observations recorded."
            )

        mean_val = sum(values) / n
        variance = (sum((x - mean_val) ** 2 for x in values) / (n - 1)) if n > 1 else 0.0
        std_dev = math.sqrt(variance)
        cv = (std_dev / abs(mean_val)) if mean_val != 0 else 0.0

        # Confidence Interval (95%)
        # Standard error * critical z (1.96)
        se = std_dev / math.sqrt(n) if n > 1 else 0.0
        ci_lower = mean_val - (1.96 * se)
        ci_upper = mean_val + (1.96 * se)

        # Flag 1: Single-seed trial warning (P-Hacking vulnerability)
        if n < 3:
            flags.append("SINGLE_SEED_RISK: Trial ran with N < 3. Results are non-reproducible and susceptible to seed-cherry-picking.")

        # Flag 2: High coefficient of variation
        if cv > 0.15:
            flags.append(f"HIGH_VARIANCE_WARNING: Coefficient of variation ({cv:.1%}) exceeds 15% threshold. Execution is unstable.")

        # Baseline comparison & Welch's t-test
        p_val = None
        t_stat = None
        is_sig = False
        gap = 0.0

        if baseline_target is not None:
            gap = abs(mean_val - baseline_target) / abs(baseline_target) if baseline_target != 0 else abs(mean_val)
            # Create synthetic baseline anchor distribution with low noise for hypothesis testing
            synthetic_baseline = [baseline_target + (0.005 * baseline_target * (i - 1)) for i in range(max(3, n))]
            t_stat, _, p_val = self.compute_welch_t_test(values, synthetic_baseline)
            is_sig = (p_val < alpha)

            if gap > 0.08:
                flags.append(f"REPRODUCTION_GAP_BREACH: Reproduction metric diverged by {gap:.1%} from paper's reported baseline.")

        # Determine Verdict
        if "SINGLE_SEED_RISK" in str(flags) or gap > 0.10:
            verdict = "DIVERGED / UNRELIABLE: High variance or failure to reproduce reported baseline within statistical bounds."
        elif gap <= 0.05:
            verdict = "REPRODUCED (GREEN): Empirical results reproduce reported baseline within 5% tolerance."
        else:
            verdict = "MARGINAL REPRODUCTION: Within acceptable envelope; minor variance detected."

        return StatisticalAuditReport(
            sample_size=n,
            mean=round(mean_val, 4),
            std_dev=round(std_dev, 4),
            variance=round(variance, 6),
            ci_95_lower=round(ci_lower, 4),
            ci_95_upper=round(ci_upper, 4),
            coefficient_of_variation=round(cv, 4),
            p_value_vs_baseline=p_val,
            t_statistic=t_stat,
            is_significant=is_sig,
            reproduction_gap=round(gap, 4),
            flags=flags,
            verdict=verdict
        )
