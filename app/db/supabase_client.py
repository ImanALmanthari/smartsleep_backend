# ─────────────────────────────────────────────────────────────────────────────
# supabase_client.py  –  Supabase database connection helpers.
#
# Supabase is a cloud service that gives us a PostgreSQL database, REST API,
# and authentication — all in one. We use it as our database backend.
#
# There are two types of Supabase clients:
#   1. anon client  — respects Row Level Security (RLS) rules. Safe for
#                     frontend/public access.
#   2. admin client — bypasses RLS. Has full database access. Should ONLY
#                     be used on the server side (never exposed to clients).
# ─────────────────────────────────────────────────────────────────────────────

from supabase import create_client, Client
from app.config import settings


def get_supabase() -> Client:
    """Create a Supabase client with the anonymous (public) key.

    This client respects Row Level Security (RLS) policies defined in Supabase.
    Use this when you want Supabase's built-in access rules to apply.

    Returns:
        A Supabase Client instance using the anon (public) key.
    """
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def get_supabase_admin() -> Client:
    """Create a Supabase client with the service-role (admin) key.

    This client bypasses Row Level Security (RLS). Use only in server-side
    code where you've already verified the user's identity via JWT.
    NEVER expose this client or its key to the frontend.

    Returns:
        A Supabase Client instance with full database access.
    """
    return create_client(settings.supabase_url, settings.supabase_service_key)


def exec(query) -> list:
    """Execute a Supabase query and always return a list (never None).

    The Supabase Python client's .execute() can return None or an object
    whose .data attribute is None. This wrapper normalises the result so
    the rest of the code can always do `for row in exec(...)` safely.

    Args:
        query: A Supabase query builder chain, e.g.:
               db.table("users").select("*").eq("email", email)

    Returns:
        A list of row dicts, or an empty list [] if nothing was found.

    Example:
        rows = exec(db.table("users").select("*").eq("email", "a@b.com"))
        user = rows[0] if rows else None
    """
    result = query.execute()
    if result is None:
        return []
    return result.data or []
