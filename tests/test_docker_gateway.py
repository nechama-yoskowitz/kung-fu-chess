"""
Stage 6 — Real Docker HTTP API Gateway integration tests.

Requires the Docker stack to be running:
    docker compose up --build

These tests are skipped automatically when the API Gateway is not reachable.
"""

import socket

import pytest


def _gateway_reachable() -> bool:
    """Check if the API Gateway is responding on port 8080."""
    try:
        s = socket.create_connection(("localhost", 8080), timeout=2)
        s.close()
        return True
    except OSError:
        return False


skip_if_no_docker = pytest.mark.skipif(
    not _gateway_reachable(),
    reason="Docker API Gateway not running (docker compose up --build)",
)


# ── GET /health ───────────────────────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_health():
    """Liveness probe returns 200."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8080/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"


# ── GET /ready ────────────────────────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_ready():
    """Readiness probe returns 200 when connected to PostgreSQL."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8080/ready") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ready"


# ── POST /auth/register → POST /auth/login → GET /users/{username} ───────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_register_login_profile():
    """End-to-end: register, login, fetch profile via real HTTP API."""
    import aiohttp
    import time

    username = f"docker_test_{int(time.time())}"
    password = "test_pw"

    async with aiohttp.ClientSession() as session:
        # Register
        async with session.post(
            "http://localhost:8080/auth/register",
            json={"username": username, "password": password}
        ) as resp:
            # May return 400 username_taken if user already exists (from prev run)
            if resp.status == 400:
                data = await resp.json()
                if data.get("error") == "username_taken":
                    # Re-run using a different username
                    username = f"docker_test_{int(time.time() * 1000)}"
                    async with session.post(
                        "http://localhost:8080/auth/register",
                        json={"username": username, "password": password}
                    ) as resp2:
                        assert resp2.status == 200
                        reg_data = await resp2.json()
                        assert reg_data["username"] == username
                        assert reg_data["rating"] == 1200
            else:
                assert resp.status == 200
                reg_data = await resp.json()
                assert reg_data["username"] == username
                assert reg_data["rating"] == 1200

        # Login
        async with session.post(
            "http://localhost:8080/auth/login",
            json={"username": username, "password": password}
        ) as resp:
            assert resp.status == 200
            login_data = await resp.json()
            assert login_data["username"] == username
            assert login_data["rating"] == 1200

        # Fetch profile
        async with session.get(f"http://localhost:8080/users/{username}") as resp:
            assert resp.status == 200
            profile_data = await resp.json()
            assert profile_data["username"] == username
            assert profile_data["rating"] == 1200


# ── Error handling ────────────────────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_login_invalid_credentials():
    """Login with wrong password returns 401."""
    import aiohttp
    import time
    
    username = f"docker_err_test_{int(time.time())}"
    
    async with aiohttp.ClientSession() as session:
        # Register
        await session.post(
            "http://localhost:8080/auth/register",
            json={"username": username, "password": "correct"}
        )
        # Login with wrong password
        async with session.post(
            "http://localhost:8080/auth/login",
            json={"username": username, "password": "wrong"}
        ) as resp:
            assert resp.status == 401
            data = await resp.json()
            assert data["error"] == "invalid_credentials"


@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_user_not_found():
    """GET /users/{username} returns 404 for nonexistent user."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8080/users/__nonexistent__") as resp:
            assert resp.status == 404
            data = await resp.json()
            assert data["error"] == "user_not_found"
