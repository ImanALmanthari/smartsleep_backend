# ─────────────────────────────────────────────────────────────────────────────
# main.py  –  Entry point for the SmartSleep FastAPI application.
#
# FastAPI is a modern Python web framework that makes it easy to build
# REST APIs (Application Programming Interfaces). Think of an API as a
# waiter in a restaurant: it takes your request, talks to the kitchen
# (database/logic), and brings back the result.
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# These are the four "route groups" (sections) of our API.
# Each one handles a different feature area.
from app.api.v1 import auth, profile, sleep_data, insights
import logging

# Set up a logger so we can print messages that help us debug problems.
# Instead of plain print(), logging lets us control the detail level (INFO, WARNING, etc.)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Create the FastAPI application instance ───────────────────────────────────
# This is the "app" object that FastAPI uses to register all your routes
# and settings. The title/description appear in the auto-generated docs page
# at /docs (Swagger UI) that FastAPI creates for free.
app = FastAPI(
    title="SmartSleep API",
    description="""
The SmartSleep API provides a comprehensive backend for the Personalized Sleep Quality Analyzer.

### Features
* **User Management**: Secure signup and login with JWT.
* **Data Ingestion**: Log raw sleep data, caffeine intake, and lifestyle factors.
* **Sleep Analysis**: Automatic calculation of sleep efficiency, base scores, and penalties.
* **ML Insights**: Blended scoring using machine learning (online learning ready).
* **Statistics**: Rolling averages and standard deviations using Welford's algorithm.

---
**Note**: To access protected routes, use the **Authorize** button with a JWT token obtained from the `/login` endpoint.
    """,
    version="1.0.0",
    contact={
        "name": "SmartSleep Support",
        "url": "https://github.com/yourusername/SmartSleepBackend",
    },
    license_info={
        "name": "MIT License",
    },
)

# ── CORS Middleware ────────────────────────────────────────────────────────────
# CORS (Cross-Origin Resource Sharing) is a browser security feature that
# blocks requests from a different domain by default.
# For example, if your Flutter app is at app.example.com and your API is at
# api.example.com, CORS would normally block that request.
# Adding this middleware tells the browser: "It's okay, allow all origins."
# allow_origins=["*"] means ANY website/app can call this API.
# In production, you should restrict this to only your app's domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Allow requests from any origin (domain)
    allow_credentials=True,    # Allow cookies/auth headers to be sent
    allow_methods=["*"],       # Allow all HTTP methods: GET, POST, PUT, DELETE...
    allow_headers=["*"],       # Allow all request headers
)

# ── Register Routers ──────────────────────────────────────────────────────────
# Routers are like "mini-apps" that group related endpoints together.
# Each router handles one feature area. The `prefix` is the URL path prefix
# that gets added to all routes inside that router.
# `tags` are labels shown in the auto-generated /docs page.
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["Profile"])
app.include_router(sleep_data.router, prefix="/api/v1/sleep", tags=["Sleep Data"])
app.include_router(insights.router, prefix="/api/v1/insights", tags=["Insights"])


@app.get("/")
def root():
    """Health-check endpoint — returns a welcome message.

    When you visit the base URL of the API, this confirms the server is running.
    Useful for deployment platforms (like Render) to verify the app is alive.
    """
    return {"message": "Welcome to SmartSleep API"}


# ── Local development entry point ─────────────────────────────────────────────
# This block only runs when you execute `python app/main.py` directly.
# In production (Render, etc.) the server is started differently via a
# Procfile or command like: uvicorn app.main:app --host 0.0.0.0 --port 8000
if __name__ == "__main__":
    import uvicorn
    # uvicorn is the ASGI server that actually listens for HTTP requests.
    # reload=True means the server restarts automatically when you change a file.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
