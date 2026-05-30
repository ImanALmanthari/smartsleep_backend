# ─────────────────────────────────────────────────────────────────────────────
# database.py  –  FastAPI dependency that provides a database connection.
#
# In FastAPI, "dependencies" are functions that can be injected into route
# handlers using `Depends(...)`. This file defines the `get_db` dependency,
# which gives every API route a ready-to-use Supabase admin client.
# ─────────────────────────────────────────────────────────────────────────────

from app.db.supabase_client import get_supabase_admin


def get_db():
    """Return a Supabase admin client for use inside route handlers.

    This function is used as a FastAPI dependency:
        @router.get("/example")
        def my_route(db=Depends(get_db)):
            ...

    The admin client uses the service-role key, which bypasses Supabase's
    Row Level Security (RLS) rules. This is safe because all access control
    is enforced at the API level (via JWT authentication) before reaching here.
    """
    return get_supabase_admin()
