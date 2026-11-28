"""Dichotomous 1PL Rasch: normal-population MML / EAP, no runtime SDK.

P(X=1 | theta,b) = logistic(theta-b), discrimination fixed to one.
Item calibration uses EM with a fixed N(0,1) population and deterministic
normal quadrature. Extreme items are excluded, not assigned invented logits.
EAP keeps extreme-person estimates finite. See docs/rasch-scoring.md.
"""

from collections import Counter
from math import exp, fsum, log, sqrt

VERSION = "rasch-mml-eap-1"
NODES = tuple(-7 + i / 8 for i in range(113))
LOG_WEIGHTS = tuple(-x * x / 2 for x in NODES)


def logistic(value):
    if value >= 0:
        return 1 / (1 + exp(-value))
    e = exp(value)
    return e / (1 + e)


def _kernel(difficulties):
    return [w - fsum(max(0, x - b) + log(1 + exp(-abs(x - b))) for b in difficulties)
            for x, w in zip(NODES, LOG_WEIGHTS)]


def _posterior(score, kernel):
    # The response-dependent sum(x_i*b_i) is constant in theta and cancels.
    logs = [w + score * x for x, w in zip(NODES, kernel)]
    peak = max(logs)
    masses = [exp(value - peak) for value in logs]
    total = fsum(masses)
    return [value / total for value in masses]


def calibrate(responses, *, item_count=None, max_iterations=400, tolerance=1e-7):
    """Complete person-by-item binary matrix -> immutable scoring snapshot.

    Missing answers must have been settled as incorrect before calling. Do not
    silently impute missing rows, partial-credit categories or pending grades.
    Empty/constant cohorts return no standardized score, never a fabricated 50.
    """
    n = len(responses)
    m = len(responses[0]) if n else (item_count or 0)
    if item_count is not None and item_count != m:
        raise ValueError("Question count does not match response matrix")
    if any(len(row) != m or any(type(x) is not int or x not in (0, 1) for x in row)
           for row in responses):
        raise ValueError("Rasch requires a complete binary response matrix")
    counts = [sum(row[j] for row in responses) for j in range(m)]
    used = [j for j, count in enumerate(counts) if 0 < count < n]
    raw = [sum(row) for row in responses]
    scores = [sum(row[j] for j in used) for row in responses]
    frequency = Counter(scores)
    warnings = []
    if n < 100:
        warnings.append("small_cohort")
    if len(used) < 20:
        warnings.append("short_test")
    if len(used) != m:
        warnings.append("extreme_items")
    result = {
        "version": VERSION, "method": "normal_mml_eap", "status": "unavailable",
        "population": "session", "prior": {"mean": 0, "sd": 1},
        "quadrature": {"min": -7, "max": 7, "step": 0.125},
        "participants": n, "items_count": m, "informative_items": len(used),
        "warnings": warnings, "converged": False, "iterations": 0,
        "mean": None, "sd": None, "eap_reliability": None,
        "items": [{"correct": count, "difficulty": None, "infit": None,
                   "status": "estimated" if j in used else "extreme"}
                  for j, count in enumerate(counts)],
        "persons": [{"raw": value, "theta": None, "se": None, "score": None}
                    for value in raw],
    }
    if not used or len(frequency) < 2:
        warnings.append("no_variation")
        return result
    b = [log((n - counts[j]) / counts[j]) for j in used]
    for iteration in range(max_iterations):
        kernel = _kernel(b)
        posteriors = {score: _posterior(score, kernel) for score in frequency}
        weights = [fsum(frequency[score] * p[k] for score, p in posteriors.items())
                   for k in range(len(NODES))]
        updated = []
        for index, j in enumerate(used):
            value = b[index]
            for _ in range(30):
                probabilities = [logistic(x - value) for x in NODES]
                expected = fsum(w * p for w, p in zip(weights, probabilities))
                information = fsum(w * p * (1 - p) for w, p in zip(weights, probabilities))
                step = (expected - counts[j]) / max(information, 1e-12)
                new = max(-12, min(12, value + max(-1, min(1, step))))
                if abs(new - value) < tolerance / 10:
                    value = new
                    break
                value = new
            updated.append(value)
        change = max(abs(x - y) for x, y in zip(b, updated))
        b = updated
        result["iterations"] = iteration + 1
        if change < tolerance:
            result["converged"] = True
            break
    if not result["converged"]:
        warnings.append("nonconvergence")
        return result

    estimates = {}
    kernel = _kernel(b)
    for score in frequency:
        posterior = _posterior(score, kernel)
        theta = fsum(w * x for w, x in zip(posterior, NODES))
        variance = fsum(w * (x - theta) ** 2 for w, x in zip(posterior, NODES))
        estimates[score] = (theta, sqrt(variance))
    mean = fsum(estimates[score][0] for score in scores) / n
    variance = fsum((estimates[score][0] - mean) ** 2 for score in scores) / n
    sd = sqrt(variance)
    if sd < 1e-8:
        warnings.append("no_variation")
        return result
    posterior_variance = fsum(estimates[score][1] ** 2 for score in scores) / n
    reliability = variance / (variance + posterior_variance)
    result.update(status="provisional", mean=mean, sd=sd, eap_reliability=reliability)
    if reliability < 0.7:
        warnings.append("low_reliability")
    for person, score in zip(result["persons"], scores):
        theta, se = estimates[score]
        person.update(theta=theta, se=se, score=50 + 10 * (theta - mean) / sd)
    for index, j in enumerate(used):
        numerator = denominator = 0.0
        for row, score in zip(responses, scores):
            p = logistic(estimates[score][0] - b[index])
            numerator += (row[j] - p) ** 2
            denominator += p * (1 - p)
        # Descriptive EAP residual diagnostic, not a formal fit test.
        infit = numerator / denominator if denominator else None
        result["items"][j].update(difficulty=b[index], infit=infit)
        if infit is not None and infit > 1.5 and "item_misfit" not in warnings:
            warnings.append("item_misfit")
    return result


def public_scoring(test):
    """Student-safe metadata: no item difficulties, keys or peer estimates."""
    import json

    if test.get("scoring_method") != "rasch_v1":
        return {"method": "legacy_tertile"}
    if test["status"] != "finished":
        return {"method": "rasch_v1", "status": "pending"}
    snapshot = json.loads(test.get("scoring_json") or "{}")
    return {"method": "rasch_v1", "status": snapshot.get("status", "unavailable"),
            "version": snapshot.get("version"), "participants": snapshot.get("participants", 0),
            "warnings": snapshot.get("warnings", []), "label": "Rash modeli asosidagi mashq natijasi"}
