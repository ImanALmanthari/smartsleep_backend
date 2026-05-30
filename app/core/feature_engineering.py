# ─────────────────────────────────────────────────────────────────────────────
# feature_engineering.py  –  Compute all sleep features from raw input data.
#
# "Feature engineering" means transforming raw measurements into meaningful
# numbers that capture the QUALITY of something. For example, instead of
# storing "slept at 11pm, woke at 6am", we compute "7 hours of actual sleep
# with 85% efficiency."
#
# This file implements Steps 2-7 of the analysis pipeline:
#   Step 2: Core sleep metrics (TIB, TST, efficiency, continuity, consistency)
#   Step 3: Lifestyle features (caffeine, screen, activity)
#   Step 4: Biological readiness (z-score of biometrics vs personal baseline)
#   Step 5: Psychological load (stress + mood composite)
#   Step 6: Environmental score (temperature, noise, light)
#   Step 7: Full feature vector assembly
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, time, date, timedelta
from typing import Any, Optional, List
import statistics  # Python standard library for basic statistical functions


# ── Internal helper functions ─────────────────────────────────────────────────

def _to_time(val) -> Optional[time]:
    """Convert a value to a Python time object, handling multiple input formats.

    Supabase may return time fields as strings ("22:30:00"), Python time objects,
    or None. This normalises all three cases.

    Args:
        val: The raw value (str, time, or None).

    Returns:
        A Python time object, or None if the input is None.
    """
    if val is None:
        return None
    if isinstance(val, time):
        return val  # Already the right type
    if isinstance(val, str):
        # Parse "HH:MM:SS" or "HH:MM" string format
        parts = val.split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2].split(".")[0]) if len(parts) > 2 else 0)
    return val


def _duration_hours(start: time, end: time) -> float:
    """Calculate the number of hours between two time objects, crossing midnight if needed.

    Sleep times often span midnight (e.g., 11pm to 7am), so we must handle
    the case where end < start by adding one day to the end.

    Args:
        start: The earlier time (e.g., 23:00 — bedtime).
        end:   The later time (e.g., 07:00 — wake time).

    Returns:
        Duration in decimal hours (e.g., 8.0 for 11pm to 7am).

    Example:
        _duration_hours(time(23, 0), time(7, 0)) → 8.0
    """
    # Combine times with today's date to get full datetime objects
    s = datetime.combine(date.today(), start)
    e = datetime.combine(date.today(), end)
    # If end is earlier than start, the sleep crossed midnight — add one day
    if e < s:
        e += timedelta(days=1)
    return (e - s).total_seconds() / 3600


# ── Step 2: Core sleep metrics ────────────────────────────────────────────────

def _tib_tst(raw_data: Any):
    """Compute Time in Bed (TIB) and Total Sleep Time (TST) in hours.

    - TIB (Time in Bed): How long from lights-out to getting up.
    - TST (Total Sleep Time): Actual sleep = TIB - time to fall asleep - awakening time.
      We estimate each awakening costs ~5 minutes of sleep.

    Args:
        raw_data: Object with sleep_time, wake_time, sleep_latency_minutes, awakenings.

    Returns:
        Tuple (tib_hours, tst_hours) as floats. Both are 0.0 if times are missing.
    """
    st = _to_time(raw_data.sleep_time)
    wt = _to_time(raw_data.wake_time)
    if not st or not wt:
        return 0.0, 0.0
    tib = _duration_hours(st, wt)
    if tib <= 0:
        return 0.0, 0.0

    # Convert latency from minutes to hours
    latency_h = (raw_data.sleep_latency_minutes or 0) / 60

    # Each awakening costs approximately 5 minutes = 5/60 hours
    awakening_h = (raw_data.awakenings or 0) * 5 / 60

    # TST must be non-negative (can't have negative sleep time)
    tst = max(0.0, tib - latency_h - awakening_h)
    return round(tib, 4), round(tst, 4)


# ── Step 3: Lifestyle features ────────────────────────────────────────────────

def _caff_gap(raw_data: Any) -> float:
    """Compute hours between last caffeine intake and sleep time.

    Caffeine has a half-life of ~5-7 hours. The longer the gap before bed,
    the less caffeine remains in your system at sleep time.

    Args:
        raw_data: Object with caffeine_time and sleep_time.

    Returns:
        Hours between last caffeine and sleep time.
        Returns 24.0 (a full day) if either time is missing — meaning no impact.
    """
    ct = _to_time(raw_data.caffeine_time)
    st = _to_time(raw_data.sleep_time)
    if not ct or not st:
        return 24.0  # No caffeine data → assume no caffeine impact
    return round(_duration_hours(ct, st), 4)


def _caff_impact(gap_hours: float) -> float:
    """Convert caffeine gap hours into a 0-1 impact score (Step 3 formula).

    The thresholds are based on caffeine research:
    - < 4 hours: High impact (caffeine still near peak in bloodstream)
    - 4-6 hours: Medium impact (one half-life has passed)
    - > 6 hours: Low impact (mostly metabolised)

    Args:
        gap_hours: Hours between last caffeine and sleep time.

    Returns:
        1.0 = high impact, 0.5 = medium impact, 0.1 = low/no impact.
    """
    if gap_hours < 4:
        return 1.0   # Caffeine still strongly affecting the body
    if gap_hours < 6:
        return 0.5   # Moderate amount of caffeine remaining
    return 0.1       # Most caffeine has been metabolised


def _screen_impact(raw_data: Any) -> float:
    """Compute screen exposure impact score (Step 3).

    Blue light from screens suppresses melatonin production, making it
    harder to fall asleep. We normalise screen minutes against 120 minutes
    (2 hours) as the reference "bad" amount.

    Formula: screen_minutes / 120 (capped implicitly; can exceed 1.0 for extreme use)

    Args:
        raw_data: Object with screen_minutes_before_bed.

    Returns:
        Impact score (0.0 to 1.0+). Higher means more screen exposure.
    """
    return round((raw_data.screen_minutes_before_bed or 0) / 120.0, 4)


def _act_impact(raw_data: Any) -> float:
    """Encode activity intensity as a numeric impact factor (proxy for act_gap).

    High-intensity exercise close to bed raises core body temperature and
    adrenaline, which can delay sleep onset. Without a timestamp for when
    the activity occurred, we use the intensity level as a proxy.

    Args:
        raw_data: Object with activity_intensity ("Low", "Medium", "High").

    Returns:
        0.0 = low/sedentary, 0.5 = moderate, 1.0 = high intensity.
    """
    intensity = (raw_data.activity_intensity or "").strip().lower()
    if intensity == "high":
        return 1.0
    if intensity == "medium":
        return 0.5
    return 0.0  # Low or no activity


# ── Step 4: Biological Readiness ──────────────────────────────────────────────

def _bio_ready(raw_data: Any, user_stat: Optional[dict]) -> float:
    """Compute biological readiness score based on biometric z-scores (Step 4).

    Instead of comparing the user's biometrics to population norms, we compare
    them to THEIR OWN personal baseline. A resting HR of 70 bpm might be normal
    for one person but high for another.

    We use the z-score: how many standard deviations away from the personal mean?
    High z-score = unusual = lower readiness.

    Bio-readiness = 1 - (average_z / 3), clamped to [0, 1]
    (a z-score of 3 or more = 0 readiness)

    Args:
        raw_data:  Object with hr_rest, hrv, body_temp.
        user_stat: The user's stored baseline stats (mean and std for each metric).
                   None or insufficient data → neutral score of 0.5.

    Returns:
        Float [0.0, 1.0]. 1.0 = biometrics right on personal average (fully ready).
        0.5 = no baseline yet (neutral). 0.0 = very far from personal baseline.
    """
    # Not enough baseline data yet — return neutral score
    if not user_stat or (user_stat.get("sample_count") or 0) < 2:
        return 0.5

    z_sum = 0.0  # Sum of absolute z-scores
    n = 0        # Number of available biometric measurements

    # Compute |z-score| for resting heart rate
    if raw_data.hr_rest and (user_stat.get("std_hr_rest") or 0) > 0:
        z_sum += abs((raw_data.hr_rest - user_stat["mean_hr_rest"]) / user_stat["std_hr_rest"])
        n += 1

    # Compute |z-score| for HRV (Heart Rate Variability)
    # Note: High HRV is good, but ANY deviation from personal norm indicates irregularity
    if raw_data.hrv and (user_stat.get("std_hrv") or 0) > 0:
        z_sum += abs((raw_data.hrv - user_stat["mean_hrv"]) / user_stat["std_hrv"])
        n += 1

    # Compute |z-score| for body temperature
    if raw_data.body_temp and (user_stat.get("std_body_temp") or 0) > 0:
        z_sum += abs((raw_data.body_temp - user_stat["mean_body_temp"]) / user_stat["std_body_temp"])
        n += 1

    if n == 0:
        return 0.5  # No biometric data available

    # Average z-score across available measurements
    avg_z = z_sum / n

    # Convert to [0, 1] readiness score: z=0 → 1.0, z=3 → 0.0
    return round(max(0.0, min(1.0, 1 - avg_z / 3)), 4)


# ── Step 5: Psychological Load ────────────────────────────────────────────────

def _psych_load(raw_data: Any) -> float:
    """Compute a composite psychological load score from stress and mood (Step 5).

    A high psychological load (high stress, low mood) is strongly associated
    with poor sleep quality and increased sleep onset latency.

    Formula:
        stress_factor = stress / 10         (high stress → high load)
        mood_factor   = 1 - mood / 10       (low mood → high load)
        psych_load    = (stress_factor + mood_factor) / 2

    Both stress and mood are on a 1-10 scale. Default is 5 (neutral).

    Args:
        raw_data: Object with stress (1-10) and mood (1-10).

    Returns:
        Float [0.0, 1.0]. 0.0 = very relaxed and happy, 1.0 = very stressed and sad.
    """
    stress_factor = (raw_data.stress or 5) / 10       # 5/10 stress → 0.5
    mood_factor = 1 - (raw_data.mood or 5) / 10       # 5/10 mood → 0.5 (inverted)
    return round((stress_factor + mood_factor) / 2, 4)


# ── Step 6: Environmental Score ───────────────────────────────────────────────

def _env_score(raw_data: Any) -> float:
    """Compute a composite sleep environment quality score (Step 6).

    The ideal sleep environment has:
    - Temperature: ~18-22°C (cool but not cold)
    - Noise: <40 dB (quiet; 80 dB is loud conversation level)
    - Light: <5 lux (dark; 300 lux is bright office lighting)

    Each sub-score is 1.0 when ideal and decreases linearly as conditions worsen.

    Args:
        raw_data: Object with room_temp (°C), noise_db (dB), light_lux (lux).

    Returns:
        Float [0.0, 1.0]. 1.0 = perfect sleep environment, 0.0 = very poor.
    """
    # Temperature: perfect at 22°C, 0 at 12°C or 32°C (±10 degrees from ideal)
    temp_score  = max(0.0, 1 - abs((raw_data.room_temp  or 22)  - 22) / 10)

    # Noise: perfect at 0 dB, 0 at 80 dB or louder
    noise_score = max(0.0, 1 - (raw_data.noise_db or 0) / 80)

    # Light: perfect at 0 lux, 0 at 300 lux or brighter
    light_score = max(0.0, 1 - (raw_data.light_lux or 0) / 300)

    # Average the three environment components
    return round((temp_score + noise_score + light_score) / 3, 4)


# ── Step 2 continued: 7-day sleep schedule consistency ───────────────────────

def _consistency_7d(last_7_sleep_times: Optional[List[str]]) -> float:
    """Measure how consistent the user's sleep schedule was over the past 7 days.

    A consistent sleep schedule strengthens the circadian rhythm.
    We measure the standard deviation of sleep times (in hours) over 7 days.
    Lower std_dev = more consistent = higher score.

    Formula: 1 - std_dev(sleep_hours) / 24
    (dividing by 24 normalises the std_dev; a 24h std_dev would be completely random)

    Args:
        last_7_sleep_times: List of sleep time strings (e.g., ["23:00:00", "22:30:00"]).
                            Needs at least 2 entries to compute std_dev.

    Returns:
        Float [0.0, 1.0]. 1.0 = perfectly consistent timing. Lower = more irregular.
    """
    if not last_7_sleep_times or len(last_7_sleep_times) < 2:
        return 1.0  # Not enough data — assume consistent (neutral)

    def to_h(t_str):
        """Convert a time string to fractional hours (e.g., "22:30:00" → 22.5)."""
        t = _to_time(t_str)
        return (t.hour + t.minute / 60) if t else None

    # Convert all sleep times to fractional hours
    hours = [h for h in (to_h(t) for t in last_7_sleep_times) if h is not None]
    if len(hours) < 2:
        return 1.0

    # Standard deviation of sleep times (how spread out the bedtimes are)
    return round(max(0.0, min(1.0, 1 - statistics.stdev(hours) / 24)), 4)


# ── Step 7: Full feature computation (main public function) ───────────────────

def compute_features(
    raw_data: Any,
    user_stat: Optional[dict] = None,
    last_7_sleep_times: Optional[List[str]] = None,
) -> dict:
    """Compute all 12 sleep quality features from raw input data (Steps 2-7).

    This is the main function called by the analysis pipeline. It orchestrates
    all the helper functions above and returns a single feature dictionary.

    Args:
        raw_data:           The raw sleep data object for one night.
        user_stat:          The user's biometric baseline statistics (from user_stat table).
        last_7_sleep_times: Sleep time strings from the past 7 days (for consistency calc).

    Returns:
        A dict with 12 feature keys:
            tib, tst, sleep_eff, interrupt_index, consistency_7d,  (Step 2)
            caff_gap_hours, caff_impact, screen_impact, act_gap_hours,  (Step 3)
            bio_ready, psych_load, env_score  (Steps 4-6)
    """
    tib, tst = _tib_tst(raw_data)

    # Sleep efficiency = what fraction of bed time was actual sleep
    sleep_eff = round(tst / tib, 4) if tib > 0 else 0.0

    # Interrupt index = awakenings per hour of sleep (lower is better)
    interrupt_index = round((raw_data.awakenings or 0) / tst, 4) if tst > 0 else 0.0

    caff_gap = _caff_gap(raw_data)

    return {
        # Step 2: Core sleep metrics
        "tib":             tib,              # Time in Bed (hours)
        "tst":             tst,              # Total Sleep Time (hours)
        "sleep_eff":       sleep_eff,        # Sleep Efficiency (0-1)
        "interrupt_index": interrupt_index,  # Awakenings per hour of sleep
        "consistency_7d":  _consistency_7d(last_7_sleep_times),  # Schedule consistency (0-1)

        # Step 3: Lifestyle features
        "caff_gap_hours":  caff_gap,                  # Hours from last caffeine to sleep
        "caff_impact":     _caff_impact(caff_gap),    # Caffeine impact (0.1/0.5/1.0)
        "screen_impact":   _screen_impact(raw_data),  # Screen exposure impact (0-1)
        "act_gap_hours":   _act_impact(raw_data),     # Activity intensity impact (0/0.5/1.0)

        # Steps 4-6: Bio / Psych / Env
        "bio_ready":  _bio_ready(raw_data, user_stat),  # Biometric readiness (0-1)
        "psych_load": _psych_load(raw_data),             # Psychological load (0-1)
        "env_score":  _env_score(raw_data),              # Environment quality (0-1)
    }


def feature_vector(features: dict) -> list:
    """Extract the ordered 10-element feature vector for ML model input (Step 7).

    Machine learning models need a consistent, ordered list of numbers — not
    a dict. This function extracts and orders the features used by the ML model.

    Args:
        features: The full feature dict from compute_features().

    Returns:
        A 10-element list [tst, sleep_eff, interrupt_index, consistency_7d,
        caff_impact, screen_impact, act_gap_hours, bio_ready, psych_load, env_score]
    """
    return [
        features["tst"],              # Total sleep time (hours)
        features["sleep_eff"],        # Sleep efficiency (0-1)
        features["interrupt_index"],  # Interruption frequency
        features["consistency_7d"],   # Schedule consistency
        features["caff_impact"],      # Caffeine impact
        features["screen_impact"],    # Screen exposure impact
        features["act_gap_hours"],    # Activity intensity impact
        features["bio_ready"],        # Biological readiness
        features["psych_load"],       # Psychological load
        features["env_score"],        # Environmental quality
    ]
