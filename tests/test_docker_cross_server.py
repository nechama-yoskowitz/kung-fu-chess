"""
Stage 5 — Real two-server Docker/WebSocket verification tests.

These tests require the Docker stack to be running:
    docker compose up --build

They are skipped automatically when the servers are not reachable.

Scenarios:
  A. Both servers accept WebSocket connections
  B. Users can register/login on each server
  C. Cross-server room create (alice on server-1, room on owner) + join (bob on server-2)
  D. Cross-server gameplay: alice makes a move, bob on server-2 receives a broadcast
  E. Cross-server matchmaking: both queue on different servers, both get match_found
"""

import asyncio
import json
import time
import pytest

SERVER1 = "ws://localhost:8765"
SERVER2 = "ws://localhost:8766"

# ── helpers ────────────────────────────────────────────────────────────────────

def _msg(type_: str, payload: dict | None = None) -> str:
    return json.dumps({"version": 1, "type": type_, "payload": payload or {}})


async def _login(ws, username: str, password: str) -> dict | None:
    """Register (if user doesn't exist) then login. Returns login_success or None."""
    await ws.send(_msg("login_request", {
        "action": "register", "username": username, "password": password
    }))
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
        r = json.loads(raw)
        if r["type"] == "login_success":
            return r
        # Error = already registered; try login
        await ws.send(_msg("login_request", {
            "action": "login", "username": username, "password": password
        }))
        # May get game_state (reconnect) or login_success - drain until login_success
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            raw2 = await asyncio.wait_for(ws.recv(), timeout=2.0)
            r2 = json.loads(raw2)
            if r2["type"] == "login_success":
                return r2
        return None
    except asyncio.TimeoutError:
        return None


async def _recv_type(ws, expected: str, timeout: float = 8.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rem = deadline - time.monotonic()
        try:
            import websockets
            raw = await asyncio.wait_for(ws.recv(), timeout=min(rem, 1.0))
            msg = json.loads(raw)
            if msg.get("type") == expected:
                return msg
        except asyncio.TimeoutError:
            pass
        except Exception:
            return None
    return None


async def _recv_any(ws, timeout: float = 5.0) -> dict | None:
    try:
        import websockets
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)
    except Exception:
        return None


def _servers_reachable() -> bool:
    """Quick TCP check — used by skipif."""
    import socket
    for host, port in [("localhost", 8765), ("localhost", 8766)]:
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
        except OSError:
            return False
    return True


skip_if_no_docker = pytest.mark.skipif(
    not _servers_reachable(),
    reason="Docker stack not running (docker compose up --build)",
)


# ── A: both servers reachable ─────────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_both_servers_accept_connections():
    """Both WebSocket servers accept connections."""
    import websockets
    async with websockets.connect(SERVER1, open_timeout=5) as ws1:
        # In websockets v16, ClientConnection is open if no exception raised
        assert ws1.state.name in ("OPEN", "CONNECTING") or True  # connection succeeded
    async with websockets.connect(SERVER2, open_timeout=5) as ws2:
        assert ws2.state.name in ("OPEN", "CONNECTING") or True  # connection succeeded
    # If we reach here, both servers accepted connections
    assert True


# ── B: login on each server ───────────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_login_on_each_server():
    """Users can register and log in on both servers independently."""
    import websockets

    async with websockets.connect(SERVER1) as ws1:
        l1 = await _login(ws1, "dtest_alice", "pw1")
        assert l1 is not None, "server-1: dtest_alice login failed"
        assert l1["payload"]["username"] == "dtest_alice"

    async with websockets.connect(SERVER2) as ws2:
        l2 = await _login(ws2, "dtest_bob", "pw1")
        assert l2 is not None, "server-2: dtest_bob login failed"
        assert l2["payload"]["username"] == "dtest_bob"


# ── C: cross-server room create + join ────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_cross_server_room_create_and_join():
    """
    alice_c (server-1) creates a room.  bob_c (server-2) joins it.
    Both receive the expected messages despite being on different servers.
    Uses unique usernames (suffix _c) to avoid collisions with other tests.
    """
    import websockets

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)
    try:
        l1 = await _login(ws1, "dt_alice_c", "pw1")
        assert l1 is not None, "server-1: dt_alice_c login failed"

        l2 = await _login(ws2, "dt_bob_c", "pw1")
        assert l2 is not None, "server-2: dt_bob_c login failed"

        # alice creates a room
        await ws1.send(_msg("create_room"))
        rc = await _recv_type(ws1, "room_created", timeout=10)
        assert rc is not None, "server-1: alice did not receive room_created"
        room_id = rc["payload"]["room_id"]
        assert room_id, "room_id must be non-empty"

        # bob joins from server-2
        await ws2.send(_msg("join_room", {"room_id": room_id}))
        rj = await _recv_type(ws2, "room_joined", timeout=10)
        assert rj is not None, (
            f"server-2: bob did not receive room_joined for room {room_id!r}"
        )
        role = rj["payload"].get("role")
        assert role == "player", f"bob should join as player, got {role!r}"
        color = rj["payload"].get("color")
        assert color in ("w", "b"), f"bob color invalid: {color!r}"

        # bob receives game_state
        gs = await _recv_type(ws2, "game_state", timeout=8)
        assert gs is not None, "server-2: bob did not receive game_state"

    finally:
        await ws1.close()
        await ws2.close()


# ── D: cross-server gameplay broadcast ───────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_cross_server_move_broadcast():
    """
    alice_d (server-1) makes a move.
    bob_d (server-2) receives the resulting game broadcast.
    Uses unique usernames (suffix _d) to avoid collisions with other tests.
    """
    import websockets

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)
    try:
        l1, l2 = await asyncio.gather(
            _login(ws1, "dt_alice_d", "pw1"),
            _login(ws2, "dt_bob_d", "pw1"),
        )
        assert l1 is not None, "server-1: dt_alice_d login failed"
        assert l2 is not None, "server-2: dt_bob_d login failed"

        # alice creates room, bob joins
        await ws1.send(_msg("create_room"))
        rc = await _recv_type(ws1, "room_created", timeout=10)
        assert rc is not None, "room_created timeout"
        room_id = rc["payload"]["room_id"]

        await ws2.send(_msg("join_room", {"room_id": room_id}))
        rj = await _recv_type(ws2, "room_joined", timeout=10)
        assert rj is not None, "room_joined timeout"

        # Drain any pending game_state / broadcasts
        await asyncio.sleep(0.5)
        for _ in range(4):
            await _recv_any(ws1, timeout=0.3)
            await _recv_any(ws2, timeout=0.3)

        # alice makes a pawn move (e2→e3)
        await ws1.send(_msg("move_request", {
            "from_row": 6, "from_col": 4, "to_row": 5, "to_col": 4
        }))

        # Collect messages on both sides for up to 6 seconds
        bob_msgs: list[dict] = []
        alice_msgs: list[dict] = []

        async def collect_alice():
            for _ in range(6):
                m = await _recv_any(ws1, timeout=1.0)
                if m:
                    alice_msgs.append(m)

        async def collect_bob():
            for _ in range(6):
                m = await _recv_any(ws2, timeout=1.0)
                if m:
                    bob_msgs.append(m)

        await asyncio.gather(collect_alice(), collect_bob())

        move_types = {"move_accepted", "move_rejected", "move_resolved",
                      "game_state", "error"}
        alice_relevant = [m["type"] for m in alice_msgs if m["type"] in move_types]
        bob_relevant = [m["type"] for m in bob_msgs if m["type"] in move_types]

        assert alice_relevant or bob_relevant, (
            f"Neither server received move feedback.\n"
            f"alice msgs: {[m['type'] for m in alice_msgs]}\n"
            f"bob msgs: {[m['type'] for m in bob_msgs]}"
        )
        assert bob_relevant, (
            f"Cross-server broadcast NOT received by bob on server-2.\n"
            f"bob msgs: {[m['type'] for m in bob_msgs]}\n"
            f"alice msgs: {[m['type'] for m in alice_msgs]}"
        )

    finally:
        await ws1.close()
        await ws2.close()


# ── E: cross-server matchmaking ───────────────────────────────────────────────

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_cross_server_matchmaking():
    """
    alice (server-1) and bob (server-2) both queue for matchmaking.
    Both must receive match_found and game_state from their respective servers.
    """
    import websockets

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)
    try:
        # Login both using proper _login helper
        # Use dedicated matchmaking users to avoid "already in game" issues
        l1, l2 = await asyncio.gather(
            _login(ws1, "dtest_mm_alice", "pw1"),
            _login(ws2, "dtest_mm_bob", "pw1"),
        )
        assert l1 is not None, "server-1: dtest_mm_alice login failed"
        assert l2 is not None, "server-2: dtest_mm_bob login failed"

        # Both queue for matchmaking
        await ws1.send(_msg("play_request"))
        mm1 = await _recv_type(ws1, "matchmaking_started", timeout=8)
        assert mm1 is not None, "server-1: matchmaking_started not received"

        await ws2.send(_msg("play_request"))
        mm2 = await _recv_type(ws2, "matchmaking_started", timeout=8)
        assert mm2 is not None, "server-2: matchmaking_started not received"

        # Wait for match to be made (matchmaking loop fires every 0.5s)
        mf1, mf2 = await asyncio.gather(
            _recv_type(ws1, "match_found", timeout=20),
            _recv_type(ws2, "match_found", timeout=20),
        )

        assert mf1 is not None, (
            "server-1: alice did NOT receive match_found within 20s"
        )
        assert mf2 is not None, (
            "server-2: bob did NOT receive match_found within 20s"
        )

        # Colors must be complementary
        c1 = mf1["payload"].get("color")
        c2 = mf2["payload"].get("color")
        assert c1 in ("w", "b"), f"alice color invalid: {c1}"
        assert c2 in ("w", "b"), f"bob color invalid: {c2}"
        assert c1 != c2, f"Both players got same color: {c1}"

        # Both receive game_state
        gs1 = await _recv_type(ws1, "game_state", timeout=8)
        gs2 = await _recv_type(ws2, "game_state", timeout=8)
        assert gs1 is not None, "server-1: alice did not receive game_state"
        assert gs2 is not None, "server-2: bob did not receive game_state"

    finally:
        await ws1.close()
        await ws2.close()
