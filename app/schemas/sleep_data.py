# ─────────────────────────────────────────────────────────────────────────────
# schemas/sleep_data.py  –  Pydantic schemas for sleep data ingestion endpoints.
#
# These schemas validate the data submitted by the Flutter app's two-phase
# check-in workflow:
#   Phase "pre"  (evening): caffeine, alcohol, steps, stress, screen time
#   Phase "post" (morning): sleep/wake times, biometrics, mood, environment
#
# All fields except `record_date` and `phase` are Optional because:
#   - Pre-sleep submission only includes pre-sleep fields
#   - Post-sleep submission only includes post-sleep fields
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date, time, datetime


class RawSleepDataBase(BaseModel):
    """Base schema containing all possible fields for one night's raw sleep data.

    Fields are split between the two logging phases:
    - Evening (pre): lifestyle and subjective state before bed
    - Morning (post): actual sleep measurements and environment after waking
    """

    # ── Record date ───────────────────────────────────────────────────────────
    record_date: date = Field(..., description="The date of the sleep record (YYYY-MM-DD)", example="2024-04-23")

    # ── Morning (post) — Sleep timing ─────────────────────────────────────────
    sleep_time: Optional[time] = Field(None, description="Time the user went to bed", example="22:30:00")
    wake_time: Optional[time] = Field(None, description="Time the user woke up", example="07:00:00")
    awakenings: Optional[int] = Field(None, description="Number of times the user woke up during sleep", ge=0, example=2)
    sleep_latency_minutes: Optional[int] = Field(None, description="Minutes it took to fall asleep", ge=0, example=15)
    naps: Optional[int] = Field(None, description="Number of naps during the day", ge=0, example=0)

    # ── Morning (post) — Biometrics ───────────────────────────────────────────
    # These are typically from a smartwatch or manual entry
    hr_rest: Optional[int] = Field(None, description="Resting heart rate (BPM)", ge=30, le=200, example=60)
    hrv: Optional[int] = Field(None, description="Heart Rate Variability (ms) — higher is generally better", ge=1, example=50)
    body_temp: Optional[float] = Field(None, description="Body temperature in Celsius", example=36.6)
    resp_rate: Optional[int] = Field(None, description="Respiratory rate (breaths per minute)", ge=8, example=14)

    # ── Evening (pre) — Lifestyle factors ─────────────────────────────────────
    caffeine_time: Optional[time] = Field(None, description="Time of last caffeine intake", example="15:00:00")
    caffeine_mg: Optional[int] = Field(None, description="Amount of caffeine consumed in milligrams", ge=0, example=100)
    alcohol_units: Optional[int] = Field(None, description="Alcohol units consumed (1 unit ≈ 1 beer)", ge=0, example=0)
    water_liters: Optional[float] = Field(None, description="Total water intake in litres", ge=0, example=2.0)
    steps: Optional[int] = Field(None, description="Total daily step count", ge=0, example=10000)
    activity_intensity: Optional[str] = Field(None, description="Daily activity level (Low, Medium, High)", example="Medium")
    screen_minutes_before_bed: Optional[int] = Field(None, description="Screen time in minutes before going to bed", ge=0, example=30)

    # ── Evening (pre) — Subjective state ──────────────────────────────────────
    stress: Optional[int] = Field(None, description="Subjective stress level (1=very calm, 10=extremely stressed)", ge=1, le=10, example=3)
    mood: Optional[int] = Field(None, description="Subjective mood level (1=very bad, 10=excellent)", ge=1, le=10, example=7)

    # ── Morning (post) — Sleep environment ────────────────────────────────────
    room_temp: Optional[float] = Field(None, description="Bedroom temperature in Celsius (ideal: 18-22°C)", example=20.5)
    noise_db: Optional[int] = Field(None, description="Average bedroom noise in decibels (ideal: <40dB)", ge=0, example=30)
    light_lux: Optional[int] = Field(None, description="Average bedroom light in lux (ideal: <5 lux)", ge=0, example=5)


class ExportRequest(BaseModel):
    """Optional date-range filter for the POST /sleep/export endpoint.

    This schema is used as the request body for the CSV email export endpoint.
    BOTH fields are Optional — if the Flutter app sends an empty body {},
    both dates default to None and the server exports ALL records the user has ever logged.

    How the date filter works:
    - Send only start_date  → export from that date to today
    - Send only end_date    → export from the very beginning up to that date
    - Send both             → export only records within that window
    - Send neither          → export everything

    Pydantic automatically validates and converts date strings:
    - "2024-01-01" (string from JSON) → datetime.date(2024, 1, 1) (Python object)
    - Any other format raises an HTTP 422 validation error automatically.
    """

    # start_date: the earliest date to include.
    # `Optional[date]` means the value can be a Python date object OR None.
    # `Field(None, ...)` sets the default to None (not required in the request).
    start_date: Optional[date] = Field(
        None,
        description="Earliest date to include in the export (YYYY-MM-DD)",
        example="2024-01-01",
    )

    # end_date: the latest date to include (inclusive).
    end_date: Optional[date] = Field(
        None,
        description="Latest date to include in the export (YYYY-MM-DD)",
        example="2024-12-31",
    )


class RawSleepDataCreate(RawSleepDataBase):
    """Request schema for POST /api/v1/sleep/ingest.

    Extends RawSleepDataBase with the required `phase` field that tells
    the backend which half of the daily workflow is being submitted.

    Literal["pre", "post"] means the value MUST be exactly "pre" or "post" —
    any other string will fail Pydantic validation with a 422 error.
    """
    phase: Literal["pre", "post"] = Field(
        ..., description="Submission phase: 'pre' for evening habits, 'post' for morning check-in"
    )


class RawSleepDataResponse(RawSleepDataBase):
    """Response schema returned after a successful /ingest request.

    Includes the generated IDs and timestamps added by the server.
    The `Config` class enables ORM mode so this schema can read from
    database row objects (not just plain dicts).
    """
    raw_id: str = Field(..., description="Unique UUID for this raw data record")
    user_id: str = Field(..., description="UUID of the user who submitted this data")

    # Timestamps that track the two-phase submission workflow
    pre_sleep_submitted_at: Optional[datetime] = None   # Set when phase="pre" is submitted
    post_sleep_submitted_at: Optional[datetime] = None  # Set when phase="post" is submitted
    created_at: datetime                                  # Row creation timestamp

    class Config:
        from_attributes = True  # Allows Pydantic to read from Supabase row dicts
