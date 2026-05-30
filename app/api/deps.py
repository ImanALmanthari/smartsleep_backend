# ─────────────────────────────────────────────────────────────────────────────
# deps.py  –  Shared FastAPI dependencies for authentication.
#
# A "dependency" in FastAPI is a function that runs before your route handler
# and provides it with data or raises an error if something is wrong.
# This file defines `get_current_user`, which:
#   1. Reads the JWT token from the Authorization header
#   2. Verifies the token is valid and not expired
#   3. Looks up the user in the database
#   4. Returns the user object to the route handler
#
# Any route that needs the logged-in user just adds:
#     current_user = Depends(get_current_user)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from types import SimpleNamespace
from app.database import get_db
from app.db.supabase_client import exec
from app.config import settings
from app.schemas.auth import TokenData

# OAuth2PasswordBearer tells FastAPI:
#   "Look for a Bearer token in the Authorization header."
#   "If it's missing, redirect the client to tokenUrl to get one."
# tokenUrl is used in the auto-generated /docs UI to show the login form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),  # FastAPI automatically extracts the token
    db=Depends(get_db),                   # FastAPI injects the database connection
):
    """Verify the JWT token and return the authenticated user.

    This dependency is added to any route that requires a logged-in user.
    It raises HTTP 401 Unauthorized if:
    - The token is missing or malformed
    - The token signature is invalid (tampered with)
    - The token is expired
    - The email encoded in the token doesn't match any user in the database

    Returns:
        SimpleNamespace: A dot-accessible object with all user fields
                         (user_id, email, full_name, age, gender, etc.)
    """
    # Prepare the error we'll raise if anything goes wrong.
    # HTTP 401 means "you are not authenticated."
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},  # Tells the client to use Bearer tokens
    )

    try:
        # Decode the JWT: verify the signature and extract the payload.
        # The payload is a dict with keys like {"sub": "user@email.com", "exp": 1234567890}
        # "sub" stands for "subject" — the identity the token represents.
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        email: str = payload.get("sub")  # Extract the email from the token
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        # JWTError is raised when the token is expired, tampered with, or malformed.
        raise credentials_exception

    # Look up the user in the Supabase database by their email.
    rows = exec(db.table("users").select("*").eq("email", token_data.email))
    if not rows:
        raise credentials_exception  # Token is valid but user was deleted from DB

    # Convert the dict row to a SimpleNamespace so we can access fields with dot notation:
    # e.g., user.email instead of user["email"]
    return SimpleNamespace(**rows[0])
