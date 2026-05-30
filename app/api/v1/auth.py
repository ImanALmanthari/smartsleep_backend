# ─────────────────────────────────────────────────────────────────────────────
# auth.py  –  Authentication API endpoints.
#
# Routes (all prefixed /api/v1/auth via main.py):
#   POST /signup              – Create account, send confirmation email
#   GET  /confirm-email       – Mark email as confirmed (user clicks link)
#   POST /login               – Verify credentials, return JWT
#   POST /reset-password      – Email a new random password (forgot password)
#   POST /change-password     – Change password using current password (requires login)
#   POST /resend-confirmation – Re-send the confirmation link
#
# ─── IMPORTANT: Required Supabase migration ───────────────────────────────────
# The email-confirmation feature requires two columns that may not exist yet
# in your `users` table. Run this SQL once in the Supabase SQL Editor
# (Dashboard → SQL Editor → New Query):
#
#   ALTER TABLE public.users
#     ADD COLUMN IF NOT EXISTS email_confirmed          BOOLEAN DEFAULT TRUE,
#     ADD COLUMN IF NOT EXISTS email_confirmation_token TEXT;
#
#   -- Mark all existing users as confirmed so they keep access:
#   UPDATE public.users SET email_confirmed = TRUE WHERE email_confirmed IS NULL;
#
# Until you run this migration, signup and confirmation still work but the
# confirmation-token features will fall back gracefully (see inline comments).
# ─────────────────────────────────────────────────────────────────────────────

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timezone
import uuid

from app.database import get_db
from app.db.supabase_client import exec
from app.schemas.auth import Token, UserCreate, PasswordResetRequest, PasswordChangeRequest
from app.utils.security import (
    create_access_token, verify_password,
    get_password_hash, generate_random_password,
)
from app.services.email_service import send_email, render_template
from app.config import settings
from app.api import deps

# postgrest.exceptions.APIError is the exception Supabase raises when a
# database operation fails (e.g. unknown column, constraint violation).
# We import it so we can detect and handle missing-column errors specifically.
from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Tiny helper ───────────────────────────────────────────────────────────────

def _is_missing_column(exc: APIError) -> bool:
    """Return True if this PostgREST error means a column does not exist.

    PostgREST error PGRST204 = "Could not find the '<column>' column of '<table>'
    in the schema cache."  This happens when the code tries to INSERT/UPDATE/
    SELECT a column that was never added to the Supabase table.

    We need to distinguish this specific error from other database errors
    (constraint violations, permission errors, etc.) so we can handle them
    differently instead of crashing.

    Args:
        exc: The APIError raised by postgrest.

    Returns:
        True if the error is a missing-column error (PGRST204), False otherwise.
    """
    # exc.args[0] is the raw JSON dict from PostgREST, e.g.:
    # {"code": "PGRST204", "message": "Could not find the 'email_confirmation_token' column..."}
    if exc.args and isinstance(exc.args[0], dict):
        return exc.args[0].get("code") == "PGRST204"
    return False


# ── Signup ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
def signup(user_in: UserCreate, db=Depends(get_db)):
    """Register a new user account and send an email confirmation link.

    Steps:
    1. Reject the request if the email is already registered.
    2. Generate a one-time confirmation token (UUID).
    3. Insert the user row (with hashed password and confirmation token).
    4. Send a confirmation email — fire-and-forget (never blocks signup on failure).
    5. Return a JWT so the user is immediately logged in.

    Graceful fallback:
        If the `email_confirmed` / `email_confirmation_token` columns don't exist
        yet (PGRST204), the user is still created WITHOUT those fields and a
        warning is logged. Run the SQL migration in the module docstring to enable
        the full confirmation flow.

    Args:
        user_in: Registration data (email, password, optional demographics).
        db:      Supabase admin client (injected by FastAPI).

    Returns:
        Token: {"access_token": "...", "token_type": "bearer"}

    Raises:
        HTTPException 400: Email already registered.
    """
    # Step 1 — block duplicate emails
    existing = exec(db.table("users").select("user_id").eq("email", user_in.email))
    if existing:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )

    # Step 2 — generate a confirmation token (a random UUID string)
    confirmation_token = str(uuid.uuid4())

    # Build the full user row, including the confirmation columns.
    # If the columns don't exist we'll catch the error below and retry.
    user_data = {
        "user_id":                    str(uuid.uuid4()),
        "email":                      user_in.email,
        "password_hash":              get_password_hash(user_in.password),
        "full_name":                  user_in.full_name,
        "age":                        user_in.age,
        "gender":                     user_in.gender,
        "weight_kg":                  user_in.weight_kg,
        "height_cm":                  user_in.height_cm,
        "email_confirmed":            False,               # Not yet confirmed
        "email_confirmation_token":   confirmation_token,  # One-time link token
    }

    confirmation_supported = True  # Assume columns exist; flip to False if not

    try:
        # Step 3 — insert the full row (with confirmation columns)
        exec(db.table("users").insert(user_data))

    except APIError as e:
        if _is_missing_column(e):
            # ── Graceful fallback: confirmation columns missing ────────────
            # Log a clear warning with the exact SQL to fix the problem.
            logger.warning(
                "PGRST204: email_confirmed / email_confirmation_token columns are "
                "missing from the 'users' table. Signup will proceed WITHOUT email "
                "confirmation. Fix by running in Supabase SQL Editor:\n"
                "  ALTER TABLE public.users\n"
                "    ADD COLUMN IF NOT EXISTS email_confirmed BOOLEAN DEFAULT TRUE,\n"
                "    ADD COLUMN IF NOT EXISTS email_confirmation_token TEXT;\n"
                "  UPDATE public.users SET email_confirmed = TRUE WHERE email_confirmed IS NULL;"
            )
            # Retry the insert without the missing columns
            user_data.pop("email_confirmed", None)
            user_data.pop("email_confirmation_token", None)
            exec(db.table("users").insert(user_data))
            confirmation_supported = False
        else:
            # Some other database error — re-raise so FastAPI returns a 500
            raise

    # Step 4 — send the appropriate email (fire-and-forget)
    display_name = user_in.full_name or user_in.email.split("@")[0]
    try:
        if confirmation_supported:
            # Full flow: send a confirmation link the user must click
            confirm_link = (
                f"{settings.frontend_url}/api/v1/auth/confirm-email"
                f"?token={confirmation_token}"
            )
            html = render_template(
                "confirmation.html",
                NAME=display_name,
                EMAIL=user_in.email,
                LINK=confirm_link,
            )
            send_email(user_in.email, "Confirm your SmartSleep email", html)
        else:
            # Degraded flow: skip confirmation and send a welcome email directly
            html = render_template("welcome.html", NAME=display_name, EMAIL=user_in.email)
            send_email(user_in.email, "Welcome to SmartSleep! 🌙", html)
    except Exception:
        # Email failure must never block signup — log and continue
        pass

    # Step 5 — return JWT (user is usable immediately, before email confirmation)
    return {
        "access_token": create_access_token(subject=user_in.email),
        "token_type":   "bearer",
    }


# ── Confirm email ─────────────────────────────────────────────────────────────

@router.get("/confirm-email", response_class=HTMLResponse)
def confirm_email(token: str, db=Depends(get_db)):
    """Mark the user's email as confirmed via the one-time link token.

    The user clicks the link in their confirmation email.
    This route looks up the token, marks the email confirmed, and shows
    an HTML success/error page in the browser.

    Graceful fallback:
        If the confirmation columns don't exist (PGRST204), an error page
        is shown asking the user to contact support. No crash occurs.

    Args:
        token: UUID from the ?token= query parameter in the confirmation link.
        db:    Supabase admin client.

    Returns:
        HTMLResponse: Styled success or failure page.
    """
    # Try to find the user that owns this token.
    # If the column doesn't exist, catch the error and show a friendly page.
    try:
        rows = exec(
            db.table("users").select("*").eq("email_confirmation_token", token)
        )
    except APIError as e:
        if _is_missing_column(e):
            logger.warning(
                "confirm_email: email_confirmation_token column missing. "
                "Run the ALTER TABLE migration described at the top of auth.py."
            )
            return HTMLResponse(
                _confirmation_page(
                    success=False,
                    msg="Email confirmation is not available on this server yet. "
                        "Please contact support.",
                ),
                status_code=503,  # 503 = Service Unavailable (server-side issue, not user error)
            )
        raise  # Unknown database error — let FastAPI handle it as 500

    if not rows:
        # Token not found or already used
        return HTMLResponse(
            _confirmation_page(success=False, msg="Invalid or expired confirmation link."),
            status_code=400,
        )

    user = rows[0]

    # Mark email as confirmed and clear the one-time token (so it can't be reused)
    try:
        exec(
            db.table("users")
            .update({"email_confirmed": True, "email_confirmation_token": None})
            .eq("user_id", user["user_id"])
        )
    except APIError as e:
        if _is_missing_column(e):
            # Column missing on update side too — log and continue anyway
            # (the user clicked the link, so show them success)
            logger.warning("confirm_email: could not update email_confirmed column (missing).")
        else:
            raise

    # Send a welcome email now that the address is verified
    display_name = user.get("full_name") or user["email"].split("@")[0]
    try:
        html = render_template("welcome.html", NAME=display_name, EMAIL=user["email"])
        send_email(user["email"], "Welcome to SmartSleep! 🌙", html)
    except Exception:
        pass  # Email failure never blocks the confirmation response

    return HTMLResponse(
        _confirmation_page(
            success=True,
            msg=f"Email confirmed! Welcome to SmartSleep, {display_name}.",
        )
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
def login(db=Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate a user and return a JWT access token.

    Uses the OAuth2 password flow — the request body must be form-encoded
    (not JSON) with fields `username` (= email) and `password`.

    A login-notification email is sent after each successful login as a
    security alert (fire-and-forget).

    Args:
        db:        Supabase admin client.
        form_data: OAuth2 form data with username and password.

    Returns:
        Token: {"access_token": "...", "token_type": "bearer"}

    Raises:
        HTTPException 401: Wrong email or password.
    """
    # Look up the user by their email address
    rows = exec(db.table("users").select("*").eq("email", form_data.username))
    user = rows[0] if rows else None

    # verify_password() compares the plain-text input against the stored bcrypt hash.
    # If either the user doesn't exist OR the password is wrong, return 401.
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Send a login-notification email (fire-and-forget — failure is silent)
    now = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")
    display_name = user.get("full_name") or user["email"].split("@")[0]
    try:
        html = render_template(
            "login_notification.html",
            NAME=display_name,
            EMAIL=user["email"],
            LOGIN_TIME=now,
        )
        send_email(user["email"], "New sign-in to your SmartSleep account", html)
    except Exception:
        pass

    return {
        "access_token": create_access_token(subject=user["email"]),
        "token_type":   "bearer",
    }


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(body: PasswordResetRequest, db=Depends(get_db)):
    """Reset a user's password and email them a newly generated random one.

    Security note — always returns the same message regardless of whether
    the email exists. This prevents "email enumeration" attacks where an
    attacker probes which email addresses have accounts.

    Args:
        body: {"email": "..."} — the address to send the reset to.
        db:   Supabase admin client.

    Returns:
        dict: Generic success message (same whether email found or not).
    """
    rows = exec(db.table("users").select("*").eq("email", body.email))
    if not rows:
        # Same message as success — never reveal whether the email exists
        return {"message": "If an account with that email exists, a reset email has been sent."}

    user = rows[0]

    # generate_random_password() creates a secure random 12-character string.
    # We store the HASH of the new password, not the plain text.
    new_password = generate_random_password()
    exec(
        db.table("users")
        .update({"password_hash": get_password_hash(new_password)})
        .eq("user_id", user["user_id"])
    )

    # Email the temporary password to the user (fire-and-forget)
    display_name = user.get("full_name") or user["email"].split("@")[0]
    try:
        html = render_template(
            "password_reset.html",
            NAME=display_name,
            EMAIL=user["email"],
            NEW_PASSWORD=new_password,  # Plain text sent once in the email, then discarded
        )
        send_email(user["email"], "Your SmartSleep password has been reset", html)
    except Exception:
        pass

    return {"message": "If an account with that email exists, a reset email has been sent."}


# ── Resend confirmation ────────────────────────────────────────────────────────

@router.post("/resend-confirmation")
def resend_confirmation(
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Re-send the email confirmation link for the currently logged-in user.

    This is a no-op if the email is already confirmed.
    Generates a fresh one-time token to replace any previous one.

    Graceful fallback:
        If the confirmation columns don't exist (PGRST204), returns HTTP 503
        with a clear message and instructions for the server admin instead
        of crashing with a 500 error.

    Args:
        db:           Supabase admin client.
        current_user: Authenticated user (from JWT, via deps.get_current_user).

    Returns:
        dict: Status message.

    Raises:
        HTTPException 503: Confirmation columns missing from the database.
                           (503 = Service Unavailable — server-side config issue)
    """
    # getattr() safely reads an attribute with a default value.
    # If current_user doesn't have email_confirmed, default to False
    # so we proceed with the re-send rather than silently skipping it.
    if getattr(current_user, "email_confirmed", False):
        return {"message": "Email is already confirmed."}

    # Generate a new one-time UUID token for the confirmation link
    new_token = str(uuid.uuid4())

    # Try to save the new token in the database.
    # This is the operation that was previously crashing with PGRST204.
    try:
        exec(
            db.table("users")
            .update({"email_confirmation_token": new_token})
            .eq("user_id", current_user.user_id)
        )
    except APIError as e:
        if _is_missing_column(e):
            # ── Root cause of the original PGRST204 crash ─────────────────
            # The `email_confirmation_token` column doesn't exist in Supabase.
            # Instead of a 500 server error, we return a 503 with clear instructions.
            logger.error(
                "PGRST204: Cannot resend confirmation — email_confirmation_token column "
                "is missing from the 'users' table. Fix by running in Supabase SQL Editor:\n"
                "  ALTER TABLE public.users\n"
                "    ADD COLUMN IF NOT EXISTS email_confirmed BOOLEAN DEFAULT TRUE,\n"
                "    ADD COLUMN IF NOT EXISTS email_confirmation_token TEXT;\n"
                "  UPDATE public.users SET email_confirmed = TRUE WHERE email_confirmed IS NULL;"
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Email confirmation is not set up on this server. "
                    "The database is missing required columns. "
                    "Please ask your server administrator to run the SQL migration "
                    "described in app/api/v1/auth.py."
                ),
            )
        raise  # Re-raise any other database error as a 500

    # Build and send the confirmation email (fire-and-forget)
    display_name = getattr(current_user, "full_name", None) or current_user.email.split("@")[0]
    confirm_link = (
        f"{settings.frontend_url}/api/v1/auth/confirm-email?token={new_token}"
    )
    try:
        html = render_template(
            "confirmation.html",
            NAME=display_name,
            EMAIL=current_user.email,
            LINK=confirm_link,
        )
        send_email(current_user.email, "Confirm your SmartSleep email", html)
    except Exception:
        pass  # Email failure never blocks the response

    return {"message": "Confirmation email sent. Please check your inbox."}


# ── Change password ───────────────────────────────────────────────────────────

@router.post("/change-password")
def change_password(
    body: PasswordChangeRequest,
    db=Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Change the password for the currently logged-in user.

    Unlike reset-password (which emails a random password), this endpoint lets
    the user supply their current password and a new one directly. The current
    password is verified before the update is applied — this prevents an
    attacker with a stolen session token from quietly changing the password.

    A security-notification email is sent after a successful change so the
    user knows if something unexpected happened.

    Args:
        body:         JSON body with current_password and new_password fields.
        db:           Supabase admin client.
        current_user: Authenticated user decoded from the JWT token.

    Returns:
        dict: {"message": "Password changed successfully."}

    Raises:
        HTTPException 400: current_password does not match the stored hash.
    """
    # Fetch the user's current password hash from the database.
    # We need the hash so we can verify the current_password the user provided.
    rows = exec(
        db.table("users")
        .select("user_id, password_hash, full_name, email")
        .eq("user_id", current_user.user_id)
    )
    if not rows:
        # Should never happen for an authenticated user, but guard just in case
        raise HTTPException(status_code=404, detail="User not found.")

    user = rows[0]

    # verify_password() uses bcrypt to compare the plain-text input against the
    # stored hash. If they don't match, reject the request with a 400 error.
    # We do NOT reveal whether the email or current password was wrong — just "incorrect".
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    # Hash the new password before storing it.
    # NEVER store plain-text passwords — always store the bcrypt hash.
    exec(
        db.table("users")
        .update({"password_hash": get_password_hash(body.new_password)})
        .eq("user_id", user["user_id"])
    )

    # Send a security-alert email notifying the user their password changed.
    # If the change was unauthorised, this email lets them know immediately.
    display_name = user.get("full_name") or user["email"].split("@")[0]
    now = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")
    try:
        html = render_template(
            "password_changed.html",
            NAME=display_name,
            EMAIL=user["email"],
            CHANGE_TIME=now,
        )
        send_email(user["email"], "Your SmartSleep password was changed", html)
    except Exception:
        pass  # Email failure should never block a successful password change

    return {"message": "Password changed successfully."}


# ── HTML page builder ─────────────────────────────────────────────────────────

def _confirmation_page(success: bool, msg: str) -> str:
    """Build an inline HTML page shown in the browser after clicking a confirmation link.

    We return HTML directly (not JSON) because this endpoint is opened in a
    browser by clicking a link — the user needs to see a readable result page,
    not a raw API response.

    Args:
        success: True → green checkmark page. False → red X error page.
        msg:     The main message text to display.

    Returns:
        A complete HTML document as a string.
    """
    icon  = "✅" if success else "❌"
    color = "#16A34A" if success else "#EF4444"
    return (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8"/>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1.0"/>'
        f'<title>Email Confirmation — SmartSleep</title></head>'
        f'<body style="margin:0;padding:0;background:#F0F4F8;font-family:-apple-system,'
        f"BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;min-height:100vh;"
        f'align-items:center;justify-content:center;">'
        f'<div style="max-width:480px;width:100%;margin:40px auto;background:#fff;'
        f'border-radius:20px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">'
        f'<div style="background:linear-gradient(135deg,#1B3A6B,#243B55);padding:32px;text-align:center;">'
        f'<div style="font-size:28px;font-weight:800;color:#fff;">🌙 SmartSleep</div></div>'
        f'<div style="padding:40px;text-align:center;">'
        f'<div style="font-size:56px;margin-bottom:16px;">{icon}</div>'
        f'<h1 style="font-size:22px;color:#1E293B;margin:0 0 12px;">{msg}</h1>'
        f'<p style="font-size:15px;color:#64748B;line-height:1.6;margin:0;">'
        f"You can close this tab and return to the SmartSleep app.</p>"
        f"</div></div></body></html>"
    )
