# ─────────────────────────────────────────────────────────────────────────────
# schemas/auth.py  –  Pydantic models (schemas) for authentication endpoints.
#
# In FastAPI, "schemas" are Pydantic models that define:
#   - What data the API expects to receive in request bodies (INPUT)
#   - What data the API returns in response bodies (OUTPUT)
#
# Pydantic automatically validates incoming data against these schemas.
# If the request doesn't match (e.g., missing a required field, wrong type),
# FastAPI returns a 422 Unprocessable Entity error with details about what's wrong.
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class Token(BaseModel):
    """Response schema returned after a successful login or signup.

    The access_token is a JWT (JSON Web Token) string. The Flutter app
    stores this and sends it with every subsequent API request in the
    Authorization header: "Authorization: Bearer <access_token>"
    """
    access_token: str = Field(..., description="The JWT access token")
    token_type: str = Field(..., description="The type of token (e.g., bearer)")


class TokenData(BaseModel):
    """Internal schema used when decoding a JWT token.

    When we decode an incoming token, we extract the email ("sub" field)
    and store it in this model for type safety.
    """
    email: Optional[str] = Field(None, description="The user's email encoded in the token")


class UserLogin(BaseModel):
    """Request schema for the login endpoint.

    Note: The actual login endpoint uses OAuth2PasswordRequestForm (form data),
    not this JSON schema. This is kept for documentation purposes.
    """
    email: EmailStr = Field(..., example="user@example.com")
    password: str = Field(..., example="secure_password123")


class UserCreate(BaseModel):
    """Request schema for the signup endpoint.

    All fields except email and password are optional — users can complete
    their profile later from the Profile screen.

    Validation rules:
    - email: Must be a valid email format (validated by EmailStr)
    - password: Minimum 8 characters
    - age: Between 0 and 120
    - gender: Must be exactly "Male", "Female", or "Other"
    - weight_kg / height_cm: Must be positive numbers
    """
    email: EmailStr = Field(..., example="newuser@example.com")
    password: str = Field(..., min_length=8, example="strong_pass_123")
    full_name: Optional[str] = Field(None, max_length=120, example="John Doe")
    age: Optional[int] = Field(None, ge=0, le=120, example=25)
    # pattern= is a regex: only these three exact strings are allowed
    gender: Optional[str] = Field(None, pattern="^(Male|Female|Other)$", example="Male")
    weight_kg: Optional[float] = Field(None, gt=0, example=70.5)   # gt=0 means greater than 0
    height_cm: Optional[float] = Field(None, gt=0, example=175.0)


class PasswordResetRequest(BaseModel):
    """Request schema for the password reset endpoint.

    Only the email address is needed. A new random password is generated
    server-side and emailed to the user.
    """
    email: EmailStr = Field(..., description="Email address to send the reset password to")


class PasswordChangeRequest(BaseModel):
    """Request schema for the change-password endpoint (requires login).

    The user supplies their current password (so we can verify identity) and
    the new password they want to switch to. Both fields are required.

    Validation rules:
    - current_password: must not be empty
    - new_password: minimum 8 characters (same rule as signup)
    """
    # The user's existing password — used to verify they are who they claim to be
    current_password: str = Field(..., min_length=1, example="old_password_123")
    # The new password they want to set
    new_password: str = Field(..., min_length=8, example="new_secure_pass_456")
