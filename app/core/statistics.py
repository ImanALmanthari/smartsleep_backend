# ─────────────────────────────────────────────────────────────────────────────
# statistics.py  –  Welford's online algorithm for running mean and std dev.
#
# We need to track each user's "personal normal" biometric values (resting HR,
# HRV, body temperature). This allows the system to detect when a user's
# biometrics are unusual FOR THEM specifically — not just unusual in general.
#
# The challenge: we don't want to store ALL historical readings and recalculate
# from scratch every day. Instead we use Welford's algorithm, which updates
# the mean and standard deviation INCREMENTALLY with each new data point.
# We only need to store three numbers: mean, std, sample_count.
# ─────────────────────────────────────────────────────────────────────────────

from typing import Tuple


def update_stats(mean: float, std: float, count: int, new_val: float) -> Tuple[float, float, int]:
    """Update running mean and standard deviation with one new value (Welford's algorithm).

    Welford's online algorithm (1962) lets us compute running statistics
    without storing the full history. This is memory-efficient and numerically
    stable (avoids catastrophic cancellation in the classic sum-of-squares formula).

    Mathematical steps:
        n += 1
        delta = new_val - old_mean
        mean += delta / n
        delta2 = new_val - new_mean          # delta uses OLD mean, delta2 uses NEW mean
        M2 += delta × delta2                 # M2 accumulates sum of squared deviations
        std = sqrt(M2 / (n - 1))             # Sample standard deviation

    Args:
        mean:    The current running mean (0.0 if no data yet).
        std:     The current running standard deviation (0.0 if no data yet).
        count:   How many data points have been seen so far (before adding new_val).
        new_val: The new data point to incorporate.

    Returns:
        Tuple of (new_mean, new_std, new_count) after incorporating new_val.

    Example:
        # After first data point (HR=65):
        mean, std, n = update_stats(0.0, 0.0, 0, 65)   → (65.0, 0.0, 1)
        # After second data point (HR=70):
        mean, std, n = update_stats(65.0, 0.0, 1, 70)  → (67.5, 3.5, 2)
    """
    count += 1  # This is now the new total count including new_val

    # Step 1: Compute delta BEFORE updating the mean
    delta = new_val - mean

    # Step 2: Update the mean with the new data point
    mean += delta / count

    # Step 3: Compute delta2 AFTER updating the mean (used for M2 update)
    delta2 = new_val - mean

    # Step 4: Reconstruct M2 from the stored std (M2 = variance × (n-1))
    # Then add the new contribution: delta × delta2
    m2 = (std ** 2) * (count - 1) if count > 1 else 0
    m2 += delta * delta2

    # Step 5: Compute the new sample standard deviation from M2
    # We need at least 2 points to compute standard deviation
    new_std = (m2 / (count - 1)) ** 0.5 if count > 1 else 0

    return mean, new_std, count
