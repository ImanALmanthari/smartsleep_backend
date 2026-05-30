# ─────────────────────────────────────────────────────────────────────────────
# security.py  –  Cryptographic utilities for JWT tokens and passwords.
#
# Security is handled in two places:
#   1. Passwords: We NEVER store plain-text passwords. Instead we store a
#      "hash" — a one-way scrambled version. bcrypt is the algorithm we use.
#   2. JWT tokens: After login, we give the client a signed token that
#      proves their identity without requiring another database lookup.
# ─────────────────────────────────────────────────────────────────────────────

import random
import string
from datetime import datetime, timedelta
from typing import Optional, Union, Any

from jose import jwt                          # Library for creating/decoding JWTs
from passlib.context import CryptContext      # Library for password hashing
from app.config import settings

# Configure the password hashing context.
# "bcrypt" is a deliberately slow hashing algorithm — this is intentional!
# Slowness makes brute-force attacks (trying millions of passwords) impractical.
# deprecated="auto" means if we ever switch algorithms, old hashes still work.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token for the given subject (usually an email).

    A JWT (JSON Web Token) is a base64-encoded string with three parts:
        header.payload.signature
    The signature is created using our secret_key, so only our server can
    produce a valid token. Anyone can READ the payload, but they cannot
    FORGE a token without the secret.

    Args:
        subject: The identity to embed in the token (typically the user's email).
        expires_delta: How long until the token expires. Defaults to the value
                       in settings (typically 60 minutes).

    Returns:
        A signed JWT string like: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Use the default expiry time from our app settings
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)

    # Build the payload dict. "exp" is a standard JWT claim for expiry time.
    # "sub" (subject) is the identity the token represents.
    to_encode = {"exp": expire, "sub": str(subject)}

    # Encode and sign the token. Returns the JWT as a string.
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check whether a plain-text password matches its stored bcrypt hash.

    This is used during login: the user types their password, we hash it,
    and compare it to the stored hash. We never "un-hash" the stored value.

    Args:
        plain_password: The raw password the user typed in the login form.
        hashed_password: The bcrypt hash stored in the database.

    Returns:
        True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a plain-text password using bcrypt.

    This is called during signup and password reset. The result is a long
    string starting with "$2b$" — the bcrypt hash format.

    Args:
        password: The raw password the user chose.

    Returns:
        A bcrypt hash string safe to store in the database.
    """
    return pwd_context.hash(password)


def generate_random_password(length: int = 12) -> str:
    """Generate a secure random password for use in password resets.

    The generated password contains a mix of letters, digits, and one symbol
    to satisfy common password policy requirements.

    Args:
        length: Number of characters in the generated password. Default is 12.

    Returns:
        A random password string guaranteed to contain at least one digit
        and one uppercase letter.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(random.choices(alphabet, k=length))
        # Keep generating until we get a password that has at least one digit
        # AND at least one uppercase letter (common password policy requirements).
        if any(c.isdigit() for c in pwd) and any(c.isupper() for c in pwd):
            return pwd
