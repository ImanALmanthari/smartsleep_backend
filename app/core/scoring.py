# ─────────────────────────────────────────────────────────────────────────────
# scoring.py  –  Score blending formula (Step 16 of the analysis pipeline).
#
# The final sleep score is a weighted blend of two signals:
#   1. base_score — computed by deterministic rules (reliable from day 1)
#   2. ml_score   — predicted by the personal ML model (improves over time)
#
# Early in the user's journey (few days logged), the rule-based score
# dominates. As the user accumulates more labelled sleep records and provides
# feedback, the ML model gradually takes over.
# ─────────────────────────────────────────────────────────────────────────────


def blend_scores(base_score: float, ml_score: float, learning_factor: float) -> float:
    """Blend the rule-based score and ML score using a progressive weighting.

    This implements Step 16 of the analysis pipeline: progressive personalisation.
    The formula is a simple linear interpolation:

        final = (1 - λ) × base_score × 100  +  λ × ml_score

    Where λ (lambda) = learning_factor = min(1.0, n / 60):
    - At n=0  labelled samples:  λ=0.0 → 100% rule-based score
    - At n=14 labelled samples:  λ=0.23 → 77% rule-based, 23% ML
    - At n=30 labelled samples:  λ=0.5  → 50% / 50%
    - At n=60+ labelled samples: λ=1.0  → 100% ML (fully personalised)

    Args:
        base_score:      Rule-based score in range [0, 1] (from rule_analyzer.py).
        ml_score:        ML-predicted score in range [0, 100] (from predictor.py).
        learning_factor: λ in range [0.0, 1.0] — how much to trust the ML model.

    Returns:
        Raw blended score in range [0, 100] BEFORE penalty subtraction.
        May slightly exceed 0-100; the caller clamps it after subtracting penalties.
    """
    # Convert base_score from 0-1 scale to 0-100 scale before blending
    return (1 - learning_factor) * base_score * 100 + learning_factor * ml_score
