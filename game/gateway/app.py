"""
HTTP API Gateway for Kung-Fu Chess — Stage 6.

Responsibilities
────────────────
Handles non-real-time HTTP requests so the Game Servers can stay focused
on live WebSocket gameplay.

Endpoints
─────────
GET  /health                   — liveness probe (always 200)
GET  /ready                    — readiness probe (checks DB)
POST /auth/register            — register a new user
POST /auth/login               — authenticate an existing user
GET  /users/{username}         — fetch public profile (username + rating)

Design decisions
────────────────
- Reuses UserService and the same repository layer as the Game Servers.
  No second auth system.
- UserService is synchronous (psycopg3 sync driver).  Each handler runs
  it directly; psycopg3 sync calls are fast enough at this concurrency
  level.  A thread-pool executor is used so the event loop never blocks.
- No JWT / session tokens are issued here.  The WebSocket servers handle
  their own stateful session after a login handshake.  This gateway
  returns a plain JSON payload with username + rating so clients can
  display account info before opening a WebSocket connection.
- Error responses always include {"error": "<code>", "message": "..."}.
- All successful responses are 200 OK with a JSON body.
"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

from game.server.auth.user_service import UserService

logger = logging.getLogger(__name__)

# Thread pool for blocking (synchronous) repository calls.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gw-db")


def _err(code: str, message: str, status: int = 400) -> web.Response:
    """Return a JSON error response."""
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"error": code, "message": message}),
    )


def _ok(payload: dict) -> web.Response:
    """Return a 200 JSON response."""
    return web.Response(
        status=200,
        content_type="application/json",
        text=json.dumps(payload),
    )


# ── /health ───────────────────────────────────────────────────────────────────

async def health(request: web.Request) -> web.Response:
    """Liveness probe — always 200 while the process is alive."""
    return _ok({"status": "ok"})


# ── /ready ────────────────────────────────────────────────────────────────────

async def ready(request: web.Request) -> web.Response:
    """
    Readiness probe — checks that the database is reachable.

    Returns 200 {"status": "ready"} or 503 {"status": "unavailable"}.
    """
    svc: UserService = request.app["user_service"]

    loop = asyncio.get_running_loop()
    try:
        # A lightweight DB round-trip: look up a known-absent username.
        await loop.run_in_executor(_EXECUTOR, svc._repo.username_exists, "__healthcheck__")
        return _ok({"status": "ready"})
    except Exception as exc:
        logger.warning(f"Readiness check failed: {exc}")
        return web.Response(
            status=503,
            content_type="application/json",
            text=json.dumps({"status": "unavailable", "detail": str(exc)}),
        )


# ── POST /auth/register ───────────────────────────────────────────────────────

async def register(request: web.Request) -> web.Response:
    """
    Register a new user.

    Request body (JSON):
        {"username": "alice", "password": "s3cr3t"}

    Responses:
        200  {"username": "alice", "rating": 1200}
        400  {"error": "username_taken",   "message": "..."}
        400  {"error": "empty_username",   "message": "..."}
        400  {"error": "empty_password",   "message": "..."}
        400  {"error": "invalid_json",     "message": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return _err("invalid_json", "Request body must be valid JSON")

    username = body.get("username", "")
    password = body.get("password", "")

    svc: UserService = request.app["user_service"]
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        _EXECUTOR, svc.register, username, password
    )

    if not result.success:
        error_messages = {
            "username_taken": "That username is already registered",
            "empty_username": "Username must not be empty",
            "empty_password": "Password must not be empty",
        }
        msg = error_messages.get(result.error, result.error or "registration failed")
        return _err(result.error or "registration_failed", msg)

    logger.info(f"API register: username={result.user.username!r}")
    return _ok({"username": result.user.username, "rating": result.user.rating})


# ── POST /auth/login ──────────────────────────────────────────────────────────

async def login(request: web.Request) -> web.Response:
    """
    Authenticate an existing user.

    Request body (JSON):
        {"username": "alice", "password": "s3cr3t"}

    Responses:
        200  {"username": "alice", "rating": 1200}
        401  {"error": "invalid_credentials", "message": "..."}
        400  {"error": "empty_username",       "message": "..."}
        400  {"error": "empty_password",       "message": "..."}
        400  {"error": "invalid_json",         "message": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return _err("invalid_json", "Request body must be valid JSON")

    username = body.get("username", "")
    password = body.get("password", "")

    svc: UserService = request.app["user_service"]
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        _EXECUTOR, svc.authenticate, username, password
    )

    if not result.success:
        status = 401 if result.error == "invalid_credentials" else 400
        error_messages = {
            "invalid_credentials": "Invalid username or password",
            "empty_username": "Username must not be empty",
            "empty_password": "Password must not be empty",
        }
        msg = error_messages.get(result.error, result.error or "authentication failed")
        return _err(result.error or "auth_failed", msg, status=status)

    logger.info(f"API login: username={result.user.username!r}")
    return _ok({"username": result.user.username, "rating": result.user.rating})


# ── GET /users/{username} ─────────────────────────────────────────────────────

async def user_profile(request: web.Request) -> web.Response:
    """
    Fetch public profile for a registered user.

    Path parameter:
        username — the player's username

    Responses:
        200  {"username": "alice", "rating": 1250}
        404  {"error": "user_not_found", "message": "..."}
    """
    username = request.match_info["username"]
    svc: UserService = request.app["user_service"]
    loop = asyncio.get_running_loop()

    record = await loop.run_in_executor(
        _EXECUTOR, svc._repo.get_user_by_username, username
    )

    if record is None:
        return _err("user_not_found", f"User {username!r} not found", status=404)

    return _ok({"username": record.username, "rating": record.rating})


# ── Application factory ───────────────────────────────────────────────────────

def create_app(user_service: UserService) -> web.Application:
    """
    Build and return the aiohttp Application.

    Parameters
    ----------
    user_service : UserService
        The shared auth/user service instance.  Injected so the gateway
        and the Game Servers can share the same repository connection.
    """
    app = web.Application()
    app["user_service"] = user_service

    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_post("/auth/register", register)
    app.router.add_post("/auth/login", login)
    app.router.add_get("/users/{username}", user_profile)

    return app
