# ─────────────────────────────────────────────────────────────────────────────
# rule_analyzer.py  –  Rule-based base score and penalty calculations.
#
# This implements Steps 8 and 10 of the analysis pipeline using deterministic
# (non-ML) formulas grounded in sleep science research.
#
# Two distinct outputs:
#   1. base_score (0-1): Weighted sum of positive sleep factors
#   2. penalty (0-100):  Point deductions for specific harmful behaviours
# ─────────────────────────────────────────────────────────────────────────────

from typing import Any, Dict


def calculate_base_score(features: Dict[str, float]) -> float:
    """Calculate the rule-based base sleep quality score (Step 10).

    This weighted formula rewards positive sleep factors. The weights are
    based on sleep science research about relative importance of each factor:

    | Factor                 | Weight | Rationale                          |
    |------------------------|--------|------------------------------------|
    | TST (Total Sleep Time) | 25%    | Most important — duration matters most |
    | Sleep Efficiency       | 20%    | Quality of time spent in bed       |
    | 7-Day Consistency      | 15%    | Circadian rhythm stability         |
    | Sleep Continuity       | 15%    | Uninterrupted sleep is restorative |
    | Psychological State    | 15%    | Stress/mood heavily affects sleep  |
    | Biological Readiness   | 10%    | HRV/HR/temp baseline deviation     |

    Args:
        features: Dict of computed features from feature_engineering.py, including:
                  tst, sleep_eff, consistency_7d, interrupt_index,
                  psych_load, bio_ready.

    Returns:
        A float in range [0.0, 1.0] representing overall sleep quality.
        Multiply by 100 to get a percentage score.
    """
    # Normalise TST: cap at 8h (ideal adult sleep duration).
    # tst=8h → 1.0, tst=4h → 0.5, tst=0h → 0.0
    tst_norm = min(1.0, features.get("tst", 0.0) / 8.0)

    score = (
        0.25 * tst_norm +
        0.20 * features.get("sleep_eff", 0.0) +              # Sleep efficiency (0-1)
        0.15 * features.get("consistency_7d", 1.0) +         # Schedule consistency (0-1)
        0.15 * (1.0 - min(1.0, features.get("interrupt_index", 0.0))) +  # Fewer awakenings = better
        0.15 * (1.0 - features.get("psych_load", 0.5)) +     # Lower stress/bad mood = better
        0.10 * features.get("bio_ready", 0.5)                 # Biometric readiness (0-1)
    )
    # Clamp result to [0, 1] to guard against any floating-point edge cases
    return round(max(0.0, min(1.0, score)), 4)


def calculate_penalties(raw_data: Any, features: Dict[str, float]) -> float:
    """Calculate point deductions for specific sleep-harming behaviours (Step 8).

    Unlike the base score (which uses weighted averages), penalties are
    hard rule deductions applied for behaviours with strong negative impact.
    Each penalty is subtracted from the final blended score (0-100 scale).

    | Trigger                           | Points Deducted |
    |-----------------------------------|-----------------|
    | Caffeine <4h before bed           | -8              |
    | Stress level > 7/10               | -6              |
    | Sleep efficiency < 75%            | -10             |
    | More than 4 awakenings            | -6              |
    | Alcohol > 2 units                 | -10             |

    Args:
        raw_data: The raw sleep data object (has attributes like stress, awakenings, etc.)
        features: The computed feature dict (used for caff_gap_hours, sleep_eff).

    Returns:
        Total penalty as a float. Will be subtracted from the 0-100 score.
        For example, penalty=18.0 means 18 points are deducted from the final score.
    """
    penalty = 0.0

    # Caffeine within 4 hours of sleep significantly delays sleep onset
    if features.get("caff_gap_hours", 24.0) < 4:
        penalty += 8.0

    # High stress (7+/10) is a major sleep disruptor
    if (raw_data.stress or 0) > 7:
        penalty += 6.0

    # Poor sleep efficiency indicates significant time awake while in bed
    if features.get("sleep_eff", 1.0) < 0.75:
        penalty += 10.0

    # Frequent awakenings fragment sleep architecture (REM cycles)
    if (raw_data.awakenings or 0) > 4:
        penalty += 6.0

    # Alcohol reduces REM sleep and causes rebound awakenings in the second half of the night
    if (raw_data.alcohol_units or 0) > 2:
        penalty += 10.0

    return penalty
