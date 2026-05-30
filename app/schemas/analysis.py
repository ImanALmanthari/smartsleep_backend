# ─────────────────────────────────────────────────────────────────────────────
# schemas/analysis.py  –  Pydantic schemas for sleep analysis endpoints.
#
# These schemas define the response structure for:
#   - GET  /sleep/history         → List[DerivedSleepDataResponse]
#   - GET  /sleep/analysis/latest → DerivedSleepDataResponse
#   - POST /sleep/analysis/feedback → DerivedSleepDataResponse
#   - GET  /insights/recommendations → List[Recommendation]
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional
import datetime


class DerivedSleepDataResponse(BaseModel):
    """Response schema for a single night's computed sleep analysis.

    This mirrors the derived_sleep_data database table. Fields are grouped
    by which analysis step produced them (Steps 2-16 from the methodology).
    Many fields are Optional because the first phase only creates a stub row;
    actual metrics are populated after the post-sleep phase is submitted.
    """
    derived_id: str    # Unique ID for this derived record
    user_id:    str    # Which user this analysis belongs to
    raw_id:     str    # Which raw_sleep_data record this was derived from
    date:       datetime.date  # The date of this sleep session

    # ── Step 2: Core sleep metrics ────────────────────────────────────────────
    tib:             Optional[float] = Field(None, description="Time in Bed (hours)")
    tst:             Optional[float] = Field(None, description="Total Sleep Time (hours)")
    sleep_eff:       Optional[float] = Field(None, description="Sleep Efficiency (0-1)")
    interrupt_index: Optional[float] = Field(None, description="Interruption Index (awakenings per sleep hour)")
    consistency_7d:  Optional[float] = Field(None, description="7-day sleep schedule consistency (0-1)")

    # ── Step 3: Lifestyle features ────────────────────────────────────────────
    caff_gap_hours: Optional[float] = Field(None, description="Hours between last caffeine and sleep")
    caff_impact:    Optional[float] = Field(None, description="Caffeine impact factor (0.1 / 0.5 / 1.0)")
    screen_impact:  Optional[float] = Field(None, description="Screen exposure impact (0-1)")
    act_gap_hours:  Optional[float] = Field(None, description="Activity intensity impact (0/0.5/1.0)")

    # ── Steps 4-6: Bio / Psych / Env composite scores ─────────────────────────
    bio_ready:  Optional[float] = Field(None, description="Biological Readiness Score (0-1)")
    psych_load: Optional[float] = Field(None, description="Psychological Load (0-1)")
    env_score:  Optional[float] = Field(None, description="Environmental Quality Score (0-1)")

    # ── Scoring breakdown (Steps 8, 10, 16) ──────────────────────────────────
    penalty:         float                       # Total point deductions (from rule penalties)
    base_score:      Optional[float] = Field(None, description="Rule-based base score (0-1)")
    ml_score:        Optional[float] = Field(None, description="ML predicted score (0-100)")
    final_score_raw: Optional[float] = Field(None, description="Blended score before clamping to 0-100")
    final_score:     Optional[int]   = Field(None, description="Final sleep quality score (0-100)")

    # ── User feedback fields (set after user rates their sleep) ───────────────
    user_score:      Optional[float] = Field(None, description="User's own rating (0-100)")
    user_class:      Optional[str]   = Field(None, description="Excellent / Good / Fair / Poor")

    created_at: datetime.datetime  # When this record was created

    class Config:
        from_attributes = True  # Allows reading from database row dicts


class UserFeedback(BaseModel):
    """Request schema for POST /sleep/analysis/feedback.

    The user rates how well they slept on a 0-100 scale. This rating
    is used as a training label for their personal ML model.
    """
    user_score: float = Field(..., ge=0, le=100, description="User's own sleep rating (0-100)")
    # user_class is optional — if not provided, the app can auto-assign based on score
    user_class: Optional[str] = Field(None, description="Excellent / Good / Fair / Poor")


class Recommendation(BaseModel):
    """A single actionable sleep improvement recommendation.

    Returned as part of a list by GET /insights/recommendations.
    The Flutter app uses the `priority` field to decide which recommendations
    to highlight at the top of the list.
    """
    category: str = Field(..., description="Sleep improvement area (e.g., 'Caffeine', 'Sleep Duration')")
    message:  str = Field(..., description="The actionable advice text shown to the user")
    priority: str = Field(..., description="Urgency level: 'high', 'medium', or 'low'")
