# ─────────────────────────────────────────────────────────────────────────────
# sleep_analysis_service.py  –  Main sleep analysis pipeline orchestrator.
#
# This service ties together all analysis steps from the methodology:
#
#   process_daily_sleep() — called after both pre & post sleep phases are done
#   ├── Step 1:  Fetch raw record from database
#   ├── Step 2-7: Feature engineering (via feature_engineering.py)
#   ├── Step 8:  Apply rule-based penalties
#   ├── Step 9:  ML prediction (or cold-start fallback to rule score)
#   ├── Step 10: Calculate rule-based base score
#   ├── Step 16: Blend rule + ML scores using learning factor
#   ├── Step 4:  Update Welford running statistics
#   └── Step 11: Send sleep report email (fire-and-forget)
#
#   trigger_training()  — called after user submits feedback
#   ├── Step 12: Store labelled sample in training_data table
#   ├── Step 13: Check if enough samples to train (n >= 14)
#   ├── Step 14: Run online learning (partial_fit)
#   └── Step 15: Update model_artifact metadata
# ─────────────────────────────────────────────────────────────────────────────

from types import SimpleNamespace
from datetime import date as date_cls, timedelta, datetime
import uuid

from app.db.supabase_client import exec
from app.core.feature_engineering import compute_features, feature_vector
from app.core.rule_analyzer import calculate_base_score, calculate_penalties
from app.core.scoring import blend_scores
from app.core.statistics import update_stats
from app.core.ml.predictor import predictor


def _classify(score_0_100: float) -> str:
    """Map a numeric score (0-100) to a sleep quality label.

    Thresholds are based on typical sleep quality classification:
    - Excellent: 85-100 (very restorative sleep)
    - Good:      70-84  (adequate sleep)
    - Fair:      50-69  (suboptimal sleep)
    - Poor:      0-49   (significantly disrupted sleep)

    Args:
        score_0_100: The final sleep score on a 0-100 scale.

    Returns:
        One of "Excellent", "Good", "Fair", or "Poor".
    """
    if score_0_100 >= 85:
        return "Excellent"
    if score_0_100 >= 70:
        return "Good"
    if score_0_100 >= 50:
        return "Fair"
    return "Poor"


def _get_model_artifact(db, user_id: str) -> dict:
    """Fetch the user's ML model metadata from the model_artifact table.

    The model_artifact row tracks how many labelled samples the user has
    provided and the current learning factor. Used to determine whether
    the ML model is ready to be used (cold-start check).

    Args:
        db:      Supabase admin client.
        user_id: The user's UUID string.

    Returns:
        The model_artifact row as a dict, or a default dict with 0 samples
        if the user has no artifact yet (brand new user).
    """
    rows = exec(db.table("model_artifact").select("*").eq("user_id", user_id))
    return rows[0] if rows else {"training_samples": 0, "current_learning_factor": 0.0}


def process_daily_sleep(db, raw_id: str, user):
    """Run the full sleep analysis pipeline after both pre and post phases are complete.

    This is the main analysis function. It takes the raw sleep data for one
    night, runs all analysis steps, and writes the results to derived_sleep_data.
    It also updates the user's biometric running statistics and sends a report email.

    Args:
        db:     Supabase admin database client.
        raw_id: The UUID of the raw_sleep_data record to analyse.
        user:   The authenticated user (SimpleNamespace with user_id, email, etc.).

    Returns:
        None. Results are persisted to the database.
    """
    # ── Step 1: Fetch the raw sleep record ────────────────────────────────────
    rows = exec(db.table("raw_sleep_data").select("*").eq("raw_id", raw_id))
    if not rows:
        return None  # Record was deleted — nothing to analyse
    raw_dict = rows[0]
    # Convert the dict to a SimpleNamespace for dot-notation access (raw_data.sleep_time etc.)
    raw_data = SimpleNamespace(**raw_dict)

    # ── Step 2 context: Get biometric baseline and recent sleep history ────────
    stat_rows = exec(db.table("user_stat").select("*").eq("user_id", user.user_id))
    user_stat = stat_rows[0] if stat_rows else None

    # Fetch sleep times for the last 7 days (for consistency calculation)
    seven_ago = (date_cls.today() - timedelta(days=7)).isoformat()
    hist_rows = exec(
        db.table("raw_sleep_data")
        .select("sleep_time")
        .eq("user_id", user.user_id)
        .gte("record_date", seven_ago)
    )
    last_7_sleep_times = [r["sleep_time"] for r in hist_rows if r.get("sleep_time")]

    # ── Steps 2-7: Feature engineering ────────────────────────────────────────
    # Compute all 12 features from the raw data
    features = compute_features(raw_data, user_stat=user_stat, last_7_sleep_times=last_7_sleep_times)
    # Extract the 10-element ML input vector
    fv = feature_vector(features)

    # ── Step 10: Rule-based base score (0-1) ──────────────────────────────────
    base_score = calculate_base_score(features)

    # ── Step 8: Apply deterministic penalties ─────────────────────────────────
    # Penalties are hard point deductions (e.g., -10 for sleep efficiency < 75%)
    penalty = calculate_penalties(raw_data, features)

    # ── Step 16: Determine learning factor ────────────────────────────────────
    # learning_factor (λ) = min(1, n/60). Starts at 0 and grows to 1 over 60 feedback samples.
    artifact = _get_model_artifact(db, user.user_id)
    n = artifact.get("training_samples", 0)
    learning_factor = min(1.0, n / 60) if n >= 14 else 0.0

    # ── Steps 9/13: ML prediction ─────────────────────────────────────────────
    ml_score, user_class = None, None
    if n >= 14:
        # User has enough feedback samples — use their personal ML model
        ml_score, user_class = predictor.predict(user.user_id, fv)

    # Cold-start fallback: when no personal model exists, use rule-based score as ML score
    if ml_score is None:
        ml_score = base_score * 100   # Convert 0-1 to 0-100 scale
    if user_class is None:
        user_class = _classify(base_score * 100)

    # ── Step 16: Final blended score ──────────────────────────────────────────
    # Blend rule-based and ML scores, then subtract penalties, then clamp to [0, 100]
    final_score_raw = blend_scores(base_score, ml_score, learning_factor) - penalty
    final_score = int(round(max(0, min(100, final_score_raw))))

    # ── Persist to derived_sleep_data ─────────────────────────────────────────
    # Build the full derived record payload
    derived_payload = {
        "user_id":         user.user_id,
        "raw_id":          raw_id,
        "date":            raw_dict["record_date"],
        # Step 2 features
        "tib":             features["tib"],
        "tst":             features["tst"],
        "sleep_eff":       features["sleep_eff"],
        "interrupt_index": features["interrupt_index"],
        "consistency_7d":  features["consistency_7d"],
        # Step 3 features
        "caff_gap_hours":  features["caff_gap_hours"],
        "caff_impact":     features["caff_impact"],
        "screen_impact":   features["screen_impact"],
        "act_gap_hours":   features["act_gap_hours"],
        # Steps 4-6 features
        "bio_ready":       features["bio_ready"],
        "psych_load":      features["psych_load"],
        "env_score":       features["env_score"],
        # Scoring results
        "penalty":         penalty,
        "base_score":      base_score,
        "ml_score":        ml_score,
        "final_score_raw": final_score_raw,
        "final_score":     final_score,
        "user_class":      user_class,
    }

    # Upsert (update if exists, insert if not).
    # A stub row was already created by _create_derived_stub() after the pre-sleep phase.
    existing_derived = exec(
        db.table("derived_sleep_data").select("derived_id").eq("raw_id", raw_id)
    )
    if existing_derived:
        # Update the existing stub row with full analysis data
        derived_id = existing_derived[0]["derived_id"]
        exec(
            db.table("derived_sleep_data")
            .update(derived_payload)
            .eq("derived_id", derived_id)
        )
    else:
        # No stub found — create a new derived record from scratch
        derived_id = str(uuid.uuid4())
        exec(db.table("derived_sleep_data").insert({"derived_id": derived_id, **derived_payload}))

    # ── Step 4: Update Welford running statistics ─────────────────────────────
    # Initialise stats with zeros if this is the user's first record
    stats = user_stat or {
        "mean_hr_rest": 0.0, "std_hr_rest": 0.0,
        "mean_hrv": 0.0,     "std_hrv": 0.0,
        "mean_body_temp": 0.0, "std_body_temp": 0.0,
        "sample_count": 0,
    }
    current_n = stats.get("sample_count", 0)
    new_stat = {"user_id": user.user_id}

    # Update each biometric stat individually (only if data was provided tonight)
    if raw_dict.get("hr_rest"):
        m, s, current_n = update_stats(stats["mean_hr_rest"], stats["std_hr_rest"], current_n, raw_dict["hr_rest"])
        new_stat.update({"mean_hr_rest": m, "std_hr_rest": s})

    if raw_dict.get("hrv"):
        m, s, _ = update_stats(stats.get("mean_hrv", 0.0), stats.get("std_hrv", 0.0), current_n, raw_dict["hrv"])
        new_stat.update({"mean_hrv": m, "std_hrv": s})

    if raw_dict.get("body_temp"):
        m, s, _ = update_stats(stats.get("mean_body_temp", 0.0), stats.get("std_body_temp", 0.0), current_n, raw_dict["body_temp"])
        new_stat.update({"mean_body_temp": m, "std_body_temp": s})

    new_stat["sample_count"] = current_n
    # upsert = insert if no row exists, update if it does
    exec(db.table("user_stat").upsert(new_stat))

    # ── Send sleep report email (fire-and-forget) ─────────────────────────────
    try:
        from app.services.email_service import send_email, render_template

        def _fmt(h):
            """Format decimal hours as 'Xh Ym' (e.g., 7.5 → '7h 30m')."""
            if not h:
                return "N/A"
            hh, mm = int(h), int((h - int(h)) * 60)
            return f"{hh}h {mm}m"

        # Choose background gradient colour based on score tier
        score_bg = (
            "linear-gradient(135deg,#16A34A,#15803D)" if final_score >= 85     # Green for Excellent
            else "linear-gradient(135deg,#2563EB,#1D4ED8)" if final_score >= 70 # Blue for Good
            else "linear-gradient(135deg,#F59E0B,#D97706)" if final_score >= 50 # Amber for Fair
            else "linear-gradient(135deg,#EF4444,#DC2626)"                      # Red for Poor
        )
        display_name = getattr(user, "full_name", None) or user.email.split("@")[0]
        html = render_template(
            "sleep_report.html",
            NAME=display_name,
            EMAIL=user.email,
            SCORE=final_score,
            CLASSIFICATION=user_class,
            SCORE_BG=score_bg,
            REPORT_DATE=raw_dict.get("record_date", "Today"),
            DURATION=_fmt(features.get("tst")),
            EFFICIENCY=f"{int((features.get('sleep_eff') or 0) * 100)}%",
            CONSISTENCY=f"{int((features.get('consistency_7d') or 0) * 100)}%",
            BIO_READY=f"{int((features.get('bio_ready') or 0) * 100)}%",
        )
        send_email(user.email, f"\U0001f319 SmartSleep Report — Score: {final_score}", html)
    except Exception as _exc:
        import logging
        logging.getLogger(__name__).warning("Sleep report email failed: %s", _exc)


def trigger_training(db, derived_id: str, user_id: str, user_score: float, user_class: str):
    """Run the ML training pipeline after the user submits sleep feedback (Steps 11-14).

    This is called after the user rates their sleep quality. It:
    1. Retrieves the feature vector from the derived_sleep_data record.
    2. Stores the labelled (feature_vector, user_score, user_class) sample in training_data.
    3. If n >= 14 total samples, runs one incremental training step (partial_fit).
    4. Updates the model_artifact metadata (learning_factor, training_samples, last_trained).

    Args:
        db:         Supabase admin database client.
        derived_id: The UUID of the derived_sleep_data record the user is rating.
        user_id:    The user's UUID string.
        user_score: The user's self-reported sleep quality (0-100).
        user_class: The user's quality label ("Poor"/"Fair"/"Good"/"Excellent").
    """
    # Step 11: Fetch the derived record to get the feature vector
    rows = exec(db.table("derived_sleep_data").select("*").eq("derived_id", derived_id))
    if not rows:
        return  # Record was deleted — nothing to do
    d = rows[0]

    # Reconstruct the 10-element feature vector from stored derived values
    # (We use .get() with sensible defaults in case any field is missing)
    fv = [
        d.get("tst") or 0.0,
        d.get("sleep_eff") or 0.0,
        d.get("interrupt_index") or 0.0,
        d.get("consistency_7d") or 1.0,
        d.get("caff_impact") or 0.1,
        d.get("screen_impact") or 0.0,
        d.get("act_gap_hours") or 0.0,
        d.get("bio_ready") or 0.5,
        d.get("psych_load") or 0.5,
        d.get("env_score") or 0.5,
    ]

    # Step 12: Store the labelled sample in the training_data table
    # We store features as a JSON dict keyed by index for flexibility
    exec(db.table("training_data").insert({
        "id":          str(uuid.uuid4()),
        "user_id":     user_id,
        "derived_id":  derived_id,
        "date":        d["date"],
        "features":    {str(i): v for i, v in enumerate(fv)},  # {"0": 7.5, "1": 0.85, ...}
        "user_score":  user_score,
        "user_class":  user_class,
    }))

    # Count total labelled samples for this user (including the one just inserted)
    all_samples = exec(db.table("training_data").select("id").eq("user_id", user_id))
    n = len(all_samples)

    # Step 14: Online learning — only once we have enough samples (cold-start threshold = 14)
    if n >= 14:
        predictor.partial_fit(user_id, fv, user_score, user_class)

    # Step 15: Update model_artifact metadata
    # learning_factor grows from 0 to 1 as samples increase from 14 to 60
    learning_factor = round(min(1.0, n / 60), 4)
    artifact_rows = exec(db.table("model_artifact").select("model_id").eq("user_id", user_id))

    now = datetime.utcnow().isoformat()
    if artifact_rows:
        # Update existing artifact row
        exec(
            db.table("model_artifact")
            .update({
                "training_samples": n,
                "current_learning_factor": learning_factor,
                "last_trained": now,
            })
            .eq("user_id", user_id)
        )
    else:
        # Create the artifact row for the first time
        exec(db.table("model_artifact").insert({
            "model_id":               str(uuid.uuid4()),
            "user_id":                user_id,
            "training_samples":       n,
            "current_learning_factor": learning_factor,
            "last_trained":           now,
        }))
