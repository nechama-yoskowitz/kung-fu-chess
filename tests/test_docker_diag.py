"""Diagnostic test — inspect raw messages from Docker servers."""
import asyncio
import json
import time
import pytest

SERVER1 = "ws://localhost:8765"
SERVER2 = "ws://localhost:8766"

def _msg(type_: str, payload: dict | None = None) -> str:
    return json.dumps({"version": 1, "type": type_, "payload": payload or {}})

def _servers_reachable() -> bool:
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
    reason="Docker stack not running",
)

async def _login(ws, username: str, password: str) -> dict | None:
    """Register (if needed) then login. Returns login_success msg or None."""
    # Try register
    await ws.send(_msg("login_request", {
        "action": "register", "username": username, "password": password
    }))
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        r = json.loads(raw)
        print(f"  register {username}: {r['type']}")
        if r["type"] == "login_success":
            return r
        # Error means already exists — try login
        await ws.send(_msg("login_request", {
            "action": "login", "username": username, "password": password
        }))
        raw2 = await asyncio.wait_for(ws.recv(), timeout=5.0)
        r2 = json.loads(raw2)
        print(f"  login {username}: {r2['type']} payload={json.dumps(r2.get('payload',{}))[:100]}")
        if r2["type"] != "login_success":
            # Drain one more message in case login_success is next
            try:
                raw3 = await asyncio.wait_for(ws.recv(), timeout=2.0)
                r3 = json.loads(raw3)
                print(f"  login2 {username}: {r3['type']}")
                if r3["type"] == "login_success":
                    return r3
            except asyncio.TimeoutError:
                pass
        return r2 if r2["type"] == "login_success" else None
    except asyncio.TimeoutError:
        print(f"  login→{username}: TIMEOUT")
        return None

@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_diag_join_room_raw():
    """Print ALL messages received by bob after joining a cross-server room."""
    import websockets

    # alice on server-1
    ws1 = await websockets.connect(SERVER1)
    # bob on server-2
    ws2 = await websockets.connect(SERVER2)
    try:
        # Login alice
        alice_login = await _login(ws1, "diag_alice", "pw1")
        assert alice_login is not None, "alice login failed"
        print(f"  alice logged in, rating={alice_login['payload'].get('rating')}")

        # alice creates room
        await ws1.send(_msg("create_room"))
        rc = None
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws1.recv(), timeout=1.0)
                msg = json.loads(raw)
                print(f"  alice RECV: {msg['type']}")
                if msg["type"] == "room_created":
                    rc = msg
                    break
            except asyncio.TimeoutError:
                pass
        assert rc is not None, "alice: room_created not received"
        room_id = rc["payload"]["room_id"]
        print(f"  room_id = {room_id!r}")

        # Login bob on server-2
        bob_login = await _login(ws2, "diag_bob", "pw1")
        assert bob_login is not None, "bob login failed"
        print(f"  bob logged in on server-2")

        # bob joins
        await ws2.send(_msg("join_room", {"room_id": room_id}))
        print(f"  SENT: join_room {room_id!r} from server-2")

        # Collect ALL messages for 12 seconds
        bob_msgs = []
        deadline2 = time.monotonic() + 12
        while time.monotonic() < deadline2:
            try:
                raw = await asyncio.wait_for(ws2.recv(), timeout=1.0)
                msg = json.loads(raw)
                bob_msgs.append(msg)
                print(f"  bob RECV: {msg['type']} payload={json.dumps(msg.get('payload',{}))[:120]}")
            except asyncio.TimeoutError:
                pass

        types = [m["type"] for m in bob_msgs]
        print(f"  All bob message types: {types}")
        assert "room_joined" in types, f"room_joined not found: {types}"
        assert "game_state" in types, f"game_state not found: {types}"
    finally:
        await ws1.close()
        await ws2.close()
    """Print ALL raw messages received after create_room for debugging."""
    import websockets
    ws = await websockets.connect(SERVER1)
    try:
        login = await _login(ws, "diag_alice", "pw1")
        assert login is not None, "Login failed"
        print(f"  Logged in as diag_alice, rating={login['payload'].get('rating')}")

        # Send create_room and collect all responses
        await ws.send(_msg("create_room"))
        print("  SENT: create_room")

        msgs = []
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw)
                msgs.append(msg)
                print(f"  RECV: {msg['type']} payload={json.dumps(msg.get('payload', {}))[:120]}")
            except asyncio.TimeoutError:
                pass

        print(f"  All message types: {[m['type'] for m in msgs]}")
        room_created = [m for m in msgs if m["type"] == "room_created"]
        assert room_created, (
            f"room_created not received. Got: {[m['type'] for m in msgs]}"
        )
    finally:
        await ws.close()


@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_diag_create_room_raw():
    """Print ALL raw messages received after create_room for debugging."""
    import websockets
    ws = await websockets.connect(SERVER1)
    try:
        login = await _login(ws, "diag_alice", "pw1")
        assert login is not None, "Login failed"
        print(f"  Logged in as diag_alice, rating={login['payload'].get('rating')}")

        await ws.send(_msg("create_room"))
        print("  SENT: create_room")

        msgs = []
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw)
                msgs.append(msg)
                print(f"  RECV: {msg['type']} payload={json.dumps(msg.get('payload', {}))[:120]}")
            except asyncio.TimeoutError:
                pass

        print(f"  All message types: {[m['type'] for m in msgs]}")
        room_created = [m for m in msgs if m["type"] == "room_created"]
        assert room_created, (
            f"room_created not received. Got: {[m['type'] for m in msgs]}"
        )
    finally:
        await ws.close()
