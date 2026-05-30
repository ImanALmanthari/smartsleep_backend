# ─────────────────────────────────────────────────────────────────────────────
# schemas/profile.py  –  Pydantic schemas for user profile endpoints.
#
# These schemas define the shape of data for GET /me and PUT /me.
# UserBase contains the common fields shared between request and response.
# ─────────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base user fields shared by both the response and internal representations."""
    email: EmailStr            # The user's email address (must be valid format)
    full_name: Optional[str] = None
    email_confirmed: Optional[bool] = None  # Whether the user clicked the confirmation link
    age: Optional[int] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None       # Weight in kilograms
    height_cm: Optional[float] = None       # Height in centimetres


class UserUpdate(BaseModel):
    """Request schema for PUT /profile/me — all fields are optional.

    Only the fields included with non-None values are updated in the database.
    This is a "partial update" (also called PATCH semantics) — you don't need
    to send ALL fields, only the ones you want to change.
    """
    full_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None


class UserResponse(UserBase):
    """Response schema for GET /profile/me — extends UserBase with ID and timestamps.

    The `Config` class tells Pydantic to accept SQLAlchemy/ORM objects as input
    (from_attributes=True means it can read attribute access, not just dict access).
    """
    user_id: str              # The user's unique ID (UUID format)
    created_at: datetime      # When the account was created

    class Config:
        from_attributes = True  # Allows Pydantic to read from ORM model attributes
