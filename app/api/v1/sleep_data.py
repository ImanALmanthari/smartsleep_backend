# ─────────────────────────────────────────────────────────────────────────────
# sleep_data.py  –  Sleep data ingestion, history, and export API endpoints.
#
# Routes in this file:
#   POST /ingest            – Submit pre-sleep (evening) or post-sleep (morning) data
#   GET  /history           – Fetch full sleep history (used for logging stage detection)
#   GET  /analysis/latest   – Fetch the most recent completed analysis
#   POST /analysis/feedback – Submit user's sleep quality rating (triggers ML training)
#   POST /export            – Generate a CSV of the user's history and email it
#
# Two-phase logging workflow:
#   Phase "pre"  (evening): User logs activities BEFORE bed
#   Phase "post" (morning): User logs sleep data AFTER waking
#   Only after BOTH phases are submitted does the backend run the full analysis.
# ─────────────────────────────────────────────────────────────────────────────

import logging
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Optional
import uuid
import base64  # Used to encode the CSV as Base64 for the email attachment
import re      # Used to sanitize the attachment filename (remove unsafe characters)
from datetime import datetime, date as date_type

logger = logging.getLogger(__name__)

from app.api import deps
from app.database import get_db
from app.db.supabase_client import exec
from app.schemas.sleep_data import RawSleepDataCreate, RawSleepDataResponse, ExportRequest
from app.schemas.analysis import DerivedSleepDataResponse, UserFeedback
from app.services.sleep_analysis_service import process_daily_sleep, trigger_training

router = APIRouter()

# ── Field lists for the two logging phases ────────────────────────────────────
# "pre" fields are collected in the evening BEFORE sleep
_PRE_FIELDS = [
    "record_date", "caffeine_time", "caffeine_mg", "alcohol_units",
    "water_liters", "steps", "activity_intensity", "screen_minutes_before_bed", "stress",
]

# "post" fields are collected in the morning AFTER sleep
_POST_FIELDS = [
    "sleep_time", "wake_time", "awakenings", "sleep_latency_minutes",
    "naps", "hr_rest", "hrv", "body_temp", "resp_rate",
    "mood", "room_temp", "noise_db", "light_lux",
]


def _serialize(v):
    """Convert a value to a JSON-safe format for storage in Supabase.

    Supabase doesn't accept Python date/time objects directly; we convert them
    to ISO 8601 strings. Other values are returned unchanged.

    Args:
        v: Any value to potentially convert.

    Returns:
        ISO string if v is a date/time object, otherwise v unchanged.
    """
    return v.isoformat() if hasattr(v, "isoformat") else v


def _create_derived_stub(db, raw_id: str, user_id: str, record_date: str) -> None:
    """Insert a minimal derived_sleep_data row right after pre-sleep is submitted.

    The Flutter app reads derived_sleep_data to determine the current logging stage.
    Without this stub, the app would show "Evening check-in" again instead of
    "Morning check-in" — the stub flips the stage.

    Args:
        db:          Supabase admin client.
        raw_id:      UUID of the just-inserted raw_sleep_data row.
        user_id:     The authenticated user's UUID.
        record_date: The date string for this sleep session (YYYY-MM-DD).
    """
    exec(
        db.table("derived_sleep_data").insert({
            "derived_id": str(uuid.uuid4()),
            "user_id":    user_id,
            "raw_id":     raw_id,
            "date":       record_date,
        })
    )


def _build_csv(records: list) -> str:
    """Generate a CSV (Comma-Separated Values) string from a list of sleep records.

    CSV is a plain-text format that spreadsheet apps (Excel, Google Sheets) can open.
    Each line is one row. Values in a row are separated by commas.
    Example:
        Date,Score,Duration_h       ← header row (column names)
        2024-04-01,78,7.50          ← data row 1
        2024-04-02,65,6.20          ← data row 2

    The columns here match the Flutter app's client-side export so users get
    identical data whether they use "Export as CSV" (share sheet) or "Email Export".

    Args:
        records: A list of dicts, each representing one night's derived_sleep_data row.

    Returns:
        A single string with all rows joined by newlines (\n).
        The first line is always the header.
    """
    # ── Three tiny helper functions that format numbers safely ────────────────
    # All three return "" (empty string) if the value is None/missing,
    # which keeps the CSV valid even for incomplete records.

    def pct(v):
        # Convert a 0-1 fraction to a 0-100 integer percentage string.
        # Example: 0.856 → "85"  |  None → ""
        return f"{int(float(v) * 100)}" if v is not None else ""

    def f2(v):
        # Format a float with exactly 2 decimal places.
        # Example: 7.5 → "7.50"  |  None → ""
        # Used for hours (TST) where precision matters.
        return f"{float(v):.2f}" if v is not None else ""

    def f1(v):
        # Format a float with exactly 1 decimal place.
        # Example: 4.333 → "4.3"  |  None → ""
        # Used for caffeine gap hours and penalty points.
        return f"{float(v):.1f}" if v is not None else ""

    # ── Build the CSV ─────────────────────────────────────────────────────────
    # The header row names each column. These names appear in row 1 of the spreadsheet.
    header = "Date,Score,Classification,Duration_h,Efficiency_%,Consistency_%,Bio_Readiness_%,Psych_Load_%,Env_Score_%,Caffeine_Gap_h,Screen_Impact_%,Penalty,User_Score,User_Class"

    # Start the list with the header; we'll append one data line per record
    lines = [header]

    for r in records:
        # r is a dict like {"date": "2024-04-01", "final_score": 78, "tst": 7.5, ...}
        # r.get("key") safely returns None if the key doesn't exist (no KeyError crash)
        # r.get("key") or "" converts None/0/False to "" so the CSV cell is blank
        row = ",".join([
            str(r.get("date") or ""),              # YYYY-MM-DD date of the sleep session
            str(r.get("final_score") or ""),        # 0-100 overall sleep quality score
            str(r.get("user_class") or ""),         # "Excellent", "Good", "Fair", or "Poor"
            f2(r.get("tst")),                       # Total Sleep Time in decimal hours
            pct(r.get("sleep_eff")),                # Sleep efficiency as a percentage
            pct(r.get("consistency_7d")),            # 7-day schedule consistency %
            pct(r.get("bio_ready")),                 # Biological readiness %
            pct(r.get("psych_load")),               # Psychological load % (higher = more stressed)
            pct(r.get("env_score")),                # Room environment quality %
            f1(r.get("caff_gap_hours")),            # Hours between last caffeine and sleep
            pct(r.get("screen_impact")),            # Screen exposure impact %
            f1(r.get("penalty")),                   # Rule-based penalty points subtracted
            str(r.get("user_score") or ""),         # User's own rating (0-100)
            str(r.get("user_class") or ""),         # Duplicated for easy filtering in sheets
        ])
        lines.append(row)

    # Join all lines with a newline character to produce the final multi-line string
    return "\n".join(lines)


# ── Ingest ────────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=RawSleepDataResponse)
def ingest_sleep_data(
    data_in: RawSleepDataCreate,
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Ingest raw sleep data for either the pre-sleep (evening) or post-sleep (morning) phase.

    The `phase` field in the request body determines the workflow branch:

    Pre-sleep ("pre") — Evening check-in:
    - Blocks if a pending pre-sleep record (without a post-sleep) already exists.
    - Inserts a new raw_sleep_data row with evening habit fields.
    - Creates a derived_sleep_data stub to signal the "Morning check-in" stage.

    Post-sleep ("post") — Morning check-in:
    - Validates that a pre-sleep record exists for today's date.
    - Updates the existing raw row with biometric/sleep-timing fields.
    - Triggers the full sleep analysis pipeline.

    Args:
        data_in:      Sleep data payload including `phase` ("pre" or "post").
        db:           Supabase admin client (injected by FastAPI).
        current_user: Authenticated user (from JWT).

    Returns:
        RawSleepDataResponse: The created or updated raw sleep data row.

    Raises:
        HTTPException 400: Various workflow validation errors (see inline).
    """
    phase = data_in.phase
    record_date_str = data_in.record_date.isoformat()
    now = datetime.utcnow().isoformat()

    # Check if a record already exists for this user + date
    existing = exec(
        db.table("raw_sleep_data")
        .select("*")
        .eq("user_id", current_user.user_id)
        .eq("record_date", record_date_str)
    )
    existing_row = existing[0] if existing else None

    if phase == "pre":
        # ── Evening check-in ──────────────────────────────────────────────
        # Enforce one-at-a-time: block if there's already a pre-sleep record
        # without a corresponding post-sleep record (any date).
        pending = exec(
            db.table("raw_sleep_data")
            .select("raw_id")
            .eq("user_id", current_user.user_id)
            .not_.is_("pre_sleep_submitted_at", "null")
            .is_("post_sleep_submitted_at", "null")
        )
        if pending:
            raise HTTPException(
                status_code=400,
                detail="Complete your morning check-in before starting a new evening log.",
            )
        if existing_row and existing_row.get("pre_sleep_submitted_at"):
            raise HTTPException(status_code=400, detail="Evening habits already logged for today.")

        raw_id = str(uuid.uuid4())
        raw_data = {
            "raw_id": raw_id,
            "user_id": current_user.user_id,
            "pre_sleep_submitted_at": now,
        }
        for k in _PRE_FIELDS:
            v = getattr(data_in, k, None)
            raw_data[k] = _serialize(v)

        rows = exec(db.table("raw_sleep_data").insert(raw_data))
        _create_derived_stub(db, raw_id, current_user.user_id, record_date_str)
        return rows[0] if rows else raw_data

    else:  # phase == "post"
        # ── Morning check-in ──────────────────────────────────────────────
        if not existing_row:
            raise HTTPException(
                status_code=400,
                detail="No evening log found for this date. Log your evening habits first.",
            )
        if not existing_row.get("pre_sleep_submitted_at"):
            raise HTTPException(
                status_code=400,
                detail="Evening habits must be logged before the morning check-in.",
            )
        if existing_row.get("post_sleep_submitted_at"):
            raise HTTPException(status_code=400, detail="Morning check-in already submitted for this date.")

        raw_id = existing_row["raw_id"]
        update_data: dict = {"post_sleep_submitted_at": now}
        for k in _POST_FIELDS:
            v = getattr(data_in, k, None)
            if v is not None:
                update_data[k] = _serialize(v)

        exec(db.table("raw_sleep_data").update(update_data).eq("raw_id", raw_id))
        # Trigger the full analysis pipeline now that both phases are complete
        process_daily_sleep(db, raw_id, current_user)

        rows = exec(db.table("raw_sleep_data").select("*").eq("raw_id", raw_id))
        return rows[0] if rows else existing_row


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", response_model=List[DerivedSleepDataResponse])
def get_sleep_history(db=Depends(get_db), current_user=Depends(deps.get_current_user)):
    """Return the full derived sleep history for the current user, newest first.

    The Flutter app uses this to:
    - Display the sleep history list screen
    - Determine the current logging stage (pre / post / feedback)

    Args:
        db:           Supabase admin client.
        current_user: Authenticated user (from JWT).

    Returns:
        List[DerivedSleepDataResponse]: All records, newest first.
    """
    return exec(
        db.table("derived_sleep_data")
        .select("*")
        .eq("user_id", current_user.user_id)
        .order("date", desc=True)
    )


# ── Latest analysis ────────────────────────────────────────────────────────────

@router.get("/analysis/latest", response_model=DerivedSleepDataResponse)
def get_latest_analysis(db=Depends(get_db), current_user=Depends(deps.get_current_user)):
    """Return the most recent completed sleep analysis for the current user.

    The Flutter Home screen uses this for the "Last Sleep Score" card.

    Raises:
        HTTPException 404: If the user has no analysis records yet.
    """
    rows = exec(
        db.table("derived_sleep_data")
        .select("*")
        .eq("user_id", current_user.user_id)
        .order("date", desc=True)
        .limit(1)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No analysis records found.")
    return rows[0]


# ── Feedback ──────────────────────────────────────────────────────────────────

@router.post("/analysis/feedback", response_model=DerivedSleepDataResponse)
def submit_feedback(
    feedback: UserFeedback,
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Submit the user's subjective sleep quality rating for the most recent unrated analysis.

    This is Step 11 in the ML pipeline. The rating is stored and used to
    train the user's personal ML model via online (incremental) learning.

    Args:
        feedback:     User's self-reported score (0-100) and quality class.
        db:           Supabase admin client.
        current_user: Authenticated user (from JWT).

    Returns:
        DerivedSleepDataResponse: Updated record including user_score.

    Raises:
        HTTPException 404: If no completed analysis is awaiting feedback.
    """
    # Find the most recent fully analysed record that hasn't been rated yet.
    # Select ALL columns (*) so that the fallback below has a complete record
    # in case the update doesn't return rows for any reason.
    latest = exec(
        db.table("derived_sleep_data")
        .select("*")                       # was "derived_id" — full row needed as fallback
        .eq("user_id", current_user.user_id)
        .not_.is_("tst", "null")           # Only fully analysed records
        .is_("user_score", "null")         # Not yet rated
        .order("date", desc=True)
        .limit(1)
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No completed analysis awaiting feedback.")

    derived_id = latest[0]["derived_id"]

    # Update the record. We don't chain .select() here because supabase-py's
    # postgrest-py backend changed its builder API between minor versions —
    # SyncFilterRequestBuilder (returned by .eq()) no longer exposes .select().
    # Instead we return the updated row by merging the known new values into
    # latest[0], which we already fetched as a full row above.
    exec(
        db.table("derived_sleep_data")
        .update({"user_score": feedback.user_score, "user_class": feedback.user_class})
        .eq("derived_id", derived_id)
    )

    # Trigger ML training with this new labelled sample (fire-and-forget).
    # Wrapped in try/except so an ML failure (e.g. missing training_data table,
    # not enough variance in data) never causes a 500 on a successful feedback save.
    try:
        trigger_training(db, derived_id, current_user.user_id, feedback.user_score, feedback.user_class)
    except Exception as exc:
        logger.warning("ML training failed after feedback save (feedback is still stored): %s", exc)

    # Merge the two updated fields into the pre-fetched full row so the response
    # reflects the post-update state without an extra round-trip to the database.
    return {**latest[0], "user_score": feedback.user_score, "user_class": feedback.user_class}


# ── Export (email CSV) ────────────────────────────────────────────────────────

@router.post("/export")
def export_sleep_data(
    # `Body(default_factory=ExportRequest)` means:
    #   - The request body is optional (the client doesn't have to send anything)
    #   - If the body is missing entirely, FastAPI creates a blank ExportRequest()
    #     with both date fields set to None — meaning "export all records"
    body: ExportRequest = Body(default_factory=ExportRequest),
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Generate a CSV of the user's sleep history and email it to them.

    This endpoint does five things in order:
      1. Query the database for the user's derived sleep records (with optional date filter)
      2. Generate a CSV text string from those records
      3. Calculate summary stats (avg / best / worst score) for the email header
      4. Render the data_export.html email template with all the data
      5. Send the email via the Google Apps Script relay

    The CSV contains all computed analysis metrics for each night. An optional
    date range can be specified via the request body; if omitted, all records are exported.

    The email the user receives includes:
    - A summary card (total nights, average/best/worst score)
    - The full CSV as a copy-pasteable code block (for Excel / Google Sheets)

    Args:
        body:         Optional {start_date, end_date} for filtering by date range.
        db:           Supabase admin client (injected by FastAPI dependency).
        current_user: The authenticated user (extracted from the JWT by deps.py).

    Returns:
        dict: {"message": "Export sent to user@example.com (42 nights)"}

    Raises:
        HTTPException 404: No records found for the specified date range.
        HTTPException 502: Records found but email delivery failed.
                           502 = "Bad Gateway" — our server is fine but
                           the downstream service (GAS email relay) failed.
    """
    # ── Step 1: Build the database query with optional date filters ───────
    # We start by chaining Supabase filter methods.
    # Each .method() returns a modified query object — nothing is sent to the
    # database yet. The query runs only when we call exec() at the end.
    query = (
        db.table("derived_sleep_data")
        .select("*")                           # Fetch all columns
        .eq("user_id", current_user.user_id)   # Only this user's records
        .not_.is_("tst", "null")               # Skip stubs (no TST = no analysis yet)
        .order("date", desc=False)             # Oldest first → chronological order in CSV
    )

    # .gte() = "greater than or equal to" — filters dates on or after start_date
    if body.start_date:
        query = query.gte("date", body.start_date.isoformat())  # e.g. "2024-01-01"

    # .lte() = "less than or equal to" — filters dates on or before end_date
    if body.end_date:
        query = query.lte("date", body.end_date.isoformat())

    # NOW run the query — exec() sends it to Supabase and returns a list of dicts
    records = exec(query)

    # If no records were found for this date range, return a 404 error
    if not records:
        raise HTTPException(
            status_code=404,
            detail="No sleep records found for this date range. Log some sleep data first.",
        )

    # ── Step 2: Generate the CSV text ────────────────────────────────────
    # _build_csv() converts the list of dicts into a multi-line CSV string
    csv_content = _build_csv(records)

    # ── Step 3: Calculate summary statistics for the email header ─────────
    # List comprehension: for each record r, get the final_score (or 0 if missing)
    # Example: [78, 65, 82, 71] from four records
    scores = [r.get("final_score") or 0 for r in records]

    # Python's built-in sum(), min(), max() work on any list of numbers
    avg_score   = round(sum(scores) / len(scores)) if scores else 0
    best_score  = max(scores) if scores else 0
    worst_score = min(scores) if scores else 0

    # ── Step 4: Build a human-readable period label for the email subject ─
    if body.start_date and body.end_date:
        period = f"{body.start_date} → {body.end_date}"  # "2024-01-01 → 2024-12-31"
    elif body.start_date:
        period = f"From {body.start_date}"               # "From 2024-01-01"
    elif body.end_date:
        period = f"Up to {body.end_date}"                # "Up to 2024-12-31"
    else:
        period = "All time"                               # No date filter applied

    # ── Step 5: Base64-encode the CSV and build the email attachment ─────────
    #
    # Why Base64?
    # Email protocols (SMTP) can only carry plain ASCII text. A CSV file is
    # also text, but to attach it as a FILE (not inline text) we encode it
    # using Base64 — a scheme that represents any bytes as printable ASCII.
    # The GAS script then decodes it back with Utilities.base64Decode() and
    # wraps it in a Blob object that MailApp.sendEmail() can attach to the email.
    #
    # Step-by-step:
    #   csv_content            → Python string  (e.g. "Date,Score\n2024-01-01,78")
    #   .encode("utf-8")       → Python bytes   (raw bytes representation)
    #   base64.b64encode(...)  → Base64 bytes   (e.g. b"RGF0ZSxTY29y...")
    #   .decode("ascii")       → ASCII string   (safe to include in JSON payload)
    csv_b64 = base64.b64encode(csv_content.encode("utf-8")).decode("ascii")

    # Build a safe, human-readable filename for the attachment.
    # re.sub() replaces any character that is NOT a letter, digit, dash, or
    # underscore with an underscore. This prevents filesystem-unsafe names.
    # Examples:
    #   "All time"                  → "smartsleep_All_time.csv"
    #   "2024-01-01 → 2024-12-31"  → "smartsleep_2024-01-01_to_2024-12-31.csv"
    safe_period = re.sub(r"[^\w\-]", "_", period.replace("→", "to"))
    filename = f"smartsleep_{safe_period}.csv"

    # The attachment dict format the GAS relay script expects.
    # "fileName" is what appears in the email client (e.g. "smartsleep_All_time.csv").
    # "mimeType" tells the email client how to open the file — "text/csv" means
    #   the OS will offer to open it in Excel, Numbers, or Google Sheets.
    # "data" is the Base64-encoded file content as a plain string.
    attachment = {
        "fileName": filename,
        "mimeType": "text/csv",
        "data":     csv_b64,
    }

    # ── Step 6: Render the HTML email body and send with attachment ────────
    # Import here (not at the top) to avoid a circular import risk at module load time
    from app.services.email_service import send_email, render_template
    from datetime import datetime as dt_cls

    # getattr(obj, "attr", default) safely reads an attribute — returns default if missing
    display_name = getattr(current_user, "full_name", None) or current_user.email.split("@")[0]

    # strftime() formats a datetime as a string:
    # %B = full month name, %d = zero-padded day, %Y = 4-digit year
    export_date = dt_cls.utcnow().strftime("%B %d, %Y")  # e.g. "April 23, 2024"

    # render_template() loads data_export.html and substitutes {{KEY}} placeholders.
    # NOTE: we no longer pass CSV_DATA — the CSV is now sent as a file attachment,
    # not embedded as raw text in the email body.
    html = render_template(
        "data_export.html",
        NAME=display_name,
        EMAIL=current_user.email,
        PERIOD=period,
        EXPORT_DATE=export_date,
        TOTAL_NIGHTS=len(records),
        AVG_SCORE=avg_score,
        BEST_SCORE=best_score,
        WORST_SCORE=worst_score,
        FILENAME=filename,            # {{FILENAME}} — shown in the "attached file" box
    )

    # send_email() now accepts an `attachments` list. Passing [attachment] causes
    # the GAS relay to include the CSV as a file attachment in the outgoing email.
    success = send_email(
        current_user.email,
        f"SmartSleep Data Export — {len(records)} nights ({period})",
        html,
        attachments=[attachment],     # ← this is the new parameter
    )

    if not success:
        # HTTP 502 = "Bad Gateway" — our server worked fine but the downstream
        # service (the Google Apps Script email relay) failed or isn't configured.
        raise HTTPException(
            status_code=502,
            detail="Export generated but email delivery failed. Check that GOOGLE_SCRIPT_URL and EMAIL_TOKEN are configured on the server.",
        )

    # Success — return a confirmation message that the Flutter app shows in a SnackBar
    return {"message": f"Export sent to {current_user.email} ({len(records)} nights)"}
