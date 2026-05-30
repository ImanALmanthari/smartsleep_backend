# ─────────────────────────────────────────────────────────────────────────────
# profile.py  –  User profile API endpoints (get and update your own profile).
#
# All routes are prefixed with /api/v1/profile (set in main.py).
# Both routes require a valid JWT (the user must be logged in).
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from app.api import deps
from app.database import get_db
from app.db.supabase_client import exec
from app.schemas.profile import UserResponse, UserUpdate
from app.services.email_service import send_email, render_template

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def read_user_me(current_user=Depends(deps.get_current_user)):
    """Return the currently logged-in user's profile.

    This is the standard "who am I?" endpoint. The Flutter app calls this
    after login to display the user's name, email, and demographics.

    The `current_user` object is automatically extracted from the JWT by
    the `get_current_user` dependency.

    Args:
        current_user: The authenticated user (SimpleNamespace from deps.py).

    Returns:
        UserResponse: The user's profile fields as a JSON object.
    """
    # vars() converts the SimpleNamespace object to a plain dict,
    # which Pydantic then validates against UserResponse.
    return vars(current_user)


@router.put("/me", response_model=UserResponse)
def update_user_me(
    user_in: UserUpdate,
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Update the currently logged-in user's profile fields.

    Only the fields included in the request body with non-null values are
    updated. Fields omitted or set to null are left unchanged.
    An email notification is sent after a successful update.

    Args:
        user_in:      The profile fields to update (partial update supported).
        db:           Supabase database client (injected by FastAPI).
        current_user: The authenticated user (from JWT).

    Returns:
        UserResponse: The updated user profile.
    """
    # model_dump() converts the Pydantic model to a dict.
    # We filter out None values so we only update fields the user actually sent.
    update_data = {k: v for k, v in user_in.model_dump().items() if v is not None}

    # If the request body was empty (all None), return the current profile unchanged.
    if not update_data:
        return vars(current_user)

    # Perform the database update, matching by the current user's ID.
    rows = exec(db.table("users").update(update_data).eq("user_id", current_user.user_id))

    # Build an email listing which fields were changed, then send it.
    # Fire-and-forget: email failure does NOT cause the API to return an error.
    display_name = getattr(current_user, "full_name", None) or current_user.email.split("@")[0]
    # Build a bullet-point HTML list of updated field names for the email body
    field_lines = "<br/>".join(
        f"&#8226; &nbsp;<strong>{k.replace('_', ' ').title()}</strong>"
        for k in update_data
    )
    now = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")
    try:
        html = render_template(
            "profile_update.html",
            NAME=display_name,
            EMAIL=current_user.email,
            UPDATE_TIME=now,
            UPDATED_FIELDS=field_lines,
        )
        send_email(current_user.email, "Your SmartSleep profile was updated", html)
    except Exception:
        pass

    # Return the updated row from the database, or fall back to the in-memory user.
    return rows[0] if rows else vars(current_user)
