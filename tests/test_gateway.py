"""
Unit tests for the HTTP API Gateway — Stage 6.

Tests exercise all endpoints using aiohttp test client (no Docker needed).
"""

import pytest
import pytest_asyncio

from game.gateway.app import create_app
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


@pytest_asyncio.fixture
async def client(aiohttp_client):
    """aiohttp test client for the gateway app."""
    # Create fresh repo and service for each test
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    service = UserService(repo)
    app = create_app(service)
    return await aiohttp_client(app)


# ── GET /health ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_always_returns_200(client):
    """Liveness probe — always 200 while process is alive."""
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data == {"status": "ok"}


# ── GET /ready ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ready_returns_200_when_db_reachable(client):
    """Readiness probe — 200 when database is functional."""
    resp = await client.get("/ready")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ready"


# ── POST /auth/register ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client):
    """Successful registration returns username + rating."""
    resp = await client.post("/auth/register", json={
        "username": "alice",
        "password": "secret123"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["username"] == "alice"
    assert data["rating"] == 1200


@pytest.mark.asyncio
async def test_register_duplicate_username(client):
    """Registering a duplicate username returns 400 username_taken."""
    await client.post("/auth/register", json={
        "username": "bob",
        "password": "pass"
    })
    # Second registration
    resp = await client.post("/auth/register", json={
        "username": "bob",
        "password": "different"
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "username_taken"
    assert "already registered" in data["message"].lower()


@pytest.mark.asyncio
async def test_register_empty_username(client):
    """Empty username returns 400 empty_username."""
    resp = await client.post("/auth/register", json={
        "username": "",
        "password": "pass"
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "empty_username"


@pytest.mark.asyncio
async def test_register_empty_password(client):
    """Empty password returns 400 empty_password."""
    resp = await client.post("/auth/register", json={
        "username": "carol",
        "password": ""
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "empty_password"


@pytest.mark.asyncio
async def test_register_invalid_json(client):
    """Malformed JSON returns 400 invalid_json."""
    resp = await client.post("/auth/register", data="not-json")
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "invalid_json"


# ── POST /auth/login ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client):
    """Successful login returns username + rating."""
    # Register first
    await client.post("/auth/register", json={
        "username": "dave",
        "password": "s3cr3t"
    })
    # Login
    resp = await client.post("/auth/login", json={
        "username": "dave",
        "password": "s3cr3t"
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["username"] == "dave"
    assert data["rating"] == 1200


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    """Wrong password returns 401 invalid_credentials."""
    await client.post("/auth/register", json={
        "username": "eve",
        "password": "correct"
    })
    resp = await client.post("/auth/login", json={
        "username": "eve",
        "password": "wrong"
    })
    assert resp.status == 401
    data = await resp.json()
    assert data["error"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    """Login with unknown username returns 401 invalid_credentials."""
    resp = await client.post("/auth/login", json={
        "username": "ghost",
        "password": "pass"
    })
    assert resp.status == 401
    data = await resp.json()
    assert data["error"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_empty_username(client):
    """Empty username returns 400 empty_username."""
    resp = await client.post("/auth/login", json={
        "username": "",
        "password": "pass"
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "empty_username"


@pytest.mark.asyncio
async def test_login_empty_password(client):
    """Empty password returns 400 empty_password."""
    resp = await client.post("/auth/login", json={
        "username": "frank",
        "password": ""
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "empty_password"


# ── GET /users/{username} ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_profile_found(client):
    """Fetching an existing user returns username + rating."""
    await client.post("/auth/register", json={
        "username": "grace",
        "password": "pass"
    })
    resp = await client.get("/users/grace")
    assert resp.status == 200
    data = await resp.json()
    assert data["username"] == "grace"
    assert data["rating"] == 1200


@pytest.mark.asyncio
async def test_user_profile_not_found(client):
    """Fetching a nonexistent user returns 404 user_not_found."""
    resp = await client.get("/users/nobody")
    assert resp.status == 404
    data = await resp.json()
    assert data["error"] == "user_not_found"
    assert "nobody" in data["message"]


# ── Integration: register → login → profile ───────────────────────────────────

@pytest.mark.asyncio
async def test_register_login_profile_flow(client):
    """End-to-end flow: register, login, fetch profile."""
    # Register
    reg_resp = await client.post("/auth/register", json={
        "username": "heidi",
        "password": "strong_pw"
    })
    assert reg_resp.status == 200
    reg_data = await reg_resp.json()
    assert reg_data["username"] == "heidi"

    # Login
    login_resp = await client.post("/auth/login", json={
        "username": "heidi",
        "password": "strong_pw"
    })
    assert login_resp.status == 200
    login_data = await login_resp.json()
    assert login_data["username"] == "heidi"
    assert login_data["rating"] == 1200

    # Fetch profile
    profile_resp = await client.get("/users/heidi")
    assert profile_resp.status == 200
    profile_data = await profile_resp.json()
    assert profile_data["username"] == "heidi"
    assert profile_data["rating"] == 1200
