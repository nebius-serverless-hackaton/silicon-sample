import numpy as np


def align_shares(
    codes: list[int], target: dict[int, float], synth: dict[int, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Aligns both sides over the question's full option list so absent codes count as zero share."""
    p = np.array([target.get(c, 0.0) for c in codes], dtype=float)
    q = np.array([synth.get(c, 0.0) for c in codes], dtype=float)
    return p, q


def mae_pp(p: np.ndarray, q: np.ndarray) -> float:
    return float(np.abs(p - q).mean() * 100)


def js_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Base-2 Jensen-Shannon distance: bounded [0, 1] and defined when one side has zero mass on an option."""
    ps, qs = p.sum(), q.sum()
    if ps == 0 or qs == 0:
        return float("nan")
    p, q = p / ps, q / qs
    m = (p + q) / 2

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float((a[mask] * np.log2(a[mask] / b[mask])).sum())

    jsd = 0.5 * kl(p, m) + 0.5 * kl(q, m)
    return float(np.sqrt(max(jsd, 0.0)))
