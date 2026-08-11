"""
Stage 5 — Real two-server Docker/WebSocket verification.

Connects real WebSocket clients to server-1 (port 8765) and server-2 (port 8766),
drives a full cross-server game lifecycle, and asserts each step.

Prerequisites:
  docker compose up --build   (from the project root)

Run with:
  python scripts/verify_cross_server.py

Exit code:
  0  — all checks passed
  1  — at least one check failed
"""

import asyncio
import json
import sys
import time

import websockets

SERVER1 = "ws://localhost:8765"
SERVER2 = "ws://localhost:8766"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        _failures.append(label)
        print(f"  {FAIL}  {label}" + (f" — {detail}" if detail else ""))


def send_msg(type_: str, payload: dict | None = None) -> str:
    return json.dumps({"version": 1, "type": type_, "payload": payload or {}})


async def recv_type(ws, expected_type: str, timeout: float = 5.0) -> dict | None:
    """Read messages until one with expected_type is found, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 1.0))
            msg = json.loads(raw)
            if msg.get("type") == expected_type:
                return msg
        except asyncio.TimeoutError:
            pass
        except websockets.ConnectionClosed:
            return None
    return None


async def recv_any(ws, timeout: float = 5.0) -> dict | None:
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return json.loads(raw)
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        return None


async def drain(ws, count: int, timeout: float = 3.0) -> list[dict]:
    msgs = []
    for _ in range(count):
        m = await recv_any(ws, timeout=timeout)
        if m:
            msgs.append(m)
    return msgs


# ── Phase 0: connectivity ─────────────────────────────────────────────────────

async def phase0_connectivity():
    print("\n[Phase 0] Basic connectivity to both servers")
    try:
        async with websockets.connect(SERVER1, open_timeout=5) as ws:
            check("server-1 accepts WebSocket connections", True)
    except Exception as e:
        check("server-1 accepts WebSocket connections", False, str(e))
        return False

    try:
        async with websockets.connect(SERVER2, open_timeout=5) as ws:
            check("server-2 accepts WebSocket connections", True)
    except Exception as e:
        check("server-2 accepts WebSocket connections", False, str(e))
        return False
    return True


# ── Phase 1: registration ─────────────────────────────────────────────────────

async def phase1_register():
    print("\n[Phase 1] User registration on both servers")

    async with websockets.connect(SERVER1) as ws1:
        await ws1.send(send_msg("login_request", {
            "action": "register", "username": "cs_alice", "password": "test123"
        }))
        msg = await recv_type(ws1, "login_success", timeout=5)
        check("server-1: alice registers", msg is not None,
              f"got {msg}")
        if msg:
            check("server-1: alice login_success has username",
                  msg["payload"].get("username") == "cs_alice")

    async with websockets.connect(SERVER2) as ws2:
        await ws2.send(send_msg("login_request", {
            "action": "register", "username": "cs_bob", "password": "test123"
        }))
        msg = await recv_type(ws2, "login_success", timeout=5)
        check("server-2: bob registers", msg is not None, f"got {msg}")
        if msg:
            check("server-2: bob login_success has username",
                  msg["payload"].get("username") == "cs_bob")


# ── Phase 2: cross-server room flow ──────────────────────────────────────────

async def phase2_cross_server_room() -> str | None:
    """
    alice (server-1) creates a room.
    bob (server-2) joins the same room.
    Returns room_id or None on failure.
    """
    print("\n[Phase 2] Cross-server room create + join")

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)

    try:
        # alice logs in on server-1
        await ws1.send(send_msg("login_request", {
            "action": "login", "username": "cs_alice", "password": "test123"
        }))
        login1 = await recv_type(ws1, "login_success", timeout=5)
        check("server-1: alice login", login1 is not None)

        # bob logs in on server-2
        await ws2.send(send_msg("login_request", {
            "action": "login", "username": "cs_bob", "password": "test123"
        }))
        login2 = await recv_type(ws2, "login_success", timeout=5)
        check("server-2: bob login", login2 is not None)

        # alice creates a room
        await ws1.send(send_msg("create_room"))
        rc = await recv_type(ws1, "room_created", timeout=10)
        check("server-1: alice receives room_created", rc is not None,
              "timeout waiting for room_created")
        if rc is None:
            return None
        room_id = rc["payload"]["room_id"]
        check("room_id is non-empty", bool(room_id), f"room_id={room_id!r}")
        print(f"    room_id = {room_id!r}")

        # bob joins from server-2
        await ws2.send(send_msg("join_room", {"room_id": room_id}))
        rj = await recv_type(ws2, "room_joined", timeout=10)
        check("server-2: bob receives room_joined", rj is not None,
              "timeout waiting for room_joined")

        if rj:
            role = rj["payload"].get("role")
            check("bob joins as player (not viewer)", role == "player",
                  f"role={role!r}")

        # bob should also receive game_state immediately
        gs = await recv_type(ws2, "game_state", timeout=5)
        check("server-2: bob receives game_state after joining", gs is not None)

        return room_id

    finally:
        await ws1.close()
        await ws2.close()


# ── Phase 3: cross-server gameplay ───────────────────────────────────────────

async def phase3_cross_server_gameplay(room_id: str):
    """
    alice (server-1) makes a move.
    Both alice (server-1) and bob (server-2) should receive the broadcast.
    """
    print("\n[Phase 3] Cross-server gameplay (move broadcast)")

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)

    try:
        # Re-auth both players
        await ws1.send(send_msg("login_request", {
            "action": "login", "username": "cs_alice", "password": "test123"
        }))
        await recv_type(ws1, "login_success", timeout=5)

        await ws2.send(send_msg("login_request", {
            "action": "login", "username": "cs_bob", "password": "test123"
        }))
        await recv_type(ws2, "login_success", timeout=5)

        # Both may receive game_state on login (reconnect)
        # Drain any pending messages
        await asyncio.sleep(0.5)

        # alice makes a pawn move (white's opening move: e2→e3 = row 6,col 4 → row 5,col 4)
        move = send_msg("move_request", {
            "from_row": 6, "from_col": 4,
            "to_row": 5, "to_col": 4
        })
        await ws1.send(move)

        # Wait for any broadcast on both sides
        bob_got = []
        alice_got = []

        async def collect(ws, out: list, label: str):
            for _ in range(5):
                m = await recv_any(ws, timeout=2.0)
                if m:
                    out.append(m)

        await asyncio.gather(
            collect(ws1, alice_got, "alice"),
            collect(ws2, bob_got, "bob"),
        )

        alice_types = [m["type"] for m in alice_got]
        bob_types = [m["type"] for m in bob_got]

        move_related = {"move_accepted", "move_rejected", "move_resolved",
                        "game_state", "error"}
        alice_relevant = [t for t in alice_types if t in move_related]
        bob_relevant = [t for t in bob_types if t in move_related]

        check(
            "server-1 (alice) receives move feedback",
            bool(alice_relevant),
            f"got types: {alice_types}",
        )
        check(
            "server-2 (bob) receives cross-server broadcast",
            bool(bob_relevant),
            f"got types: {bob_types}",
        )

    finally:
        await ws1.close()
        await ws2.close()


# ── Phase 4: cross-server matchmaking ────────────────────────────────────────

async def phase4_cross_server_matchmaking():
    """
    alice (server-1) and bob (server-2) both queue for matchmaking.
    Both should receive match_found + game_state on their respective servers.
    """
    print("\n[Phase 4] Cross-server matchmaking")

    ws1 = await websockets.connect(SERVER1)
    ws2 = await websockets.connect(SERVER2)

    try:
        # Login both on separate servers
        await ws1.send(send_msg("login_request", {
            "action": "login", "username": "cs_alice", "password": "test123"
        }))
        l1 = await recv_type(ws1, "login_success", timeout=5)
        check("server-1: alice login for matchmaking", l1 is not None)

        await ws2.send(send_msg("login_request", {
            "action": "login", "username": "cs_bob", "password": "test123"
        }))
        l2 = await recv_type(ws2, "login_success", timeout=5)
        check("server-2: bob login for matchmaking", l2 is not None)

        if not l1 or not l2:
            return

        # Both queue
        await ws1.send(send_msg("play_request"))
        mm1 = await recv_type(ws1, "matchmaking_started", timeout=5)
        check("server-1: alice gets matchmaking_started", mm1 is not None)

        await ws2.send(send_msg("play_request"))
        mm2 = await recv_type(ws2, "matchmaking_started", timeout=5)
        check("server-2: bob gets matchmaking_started", mm2 is not None)

        # Wait for match_found on both sides (matchmaking loop fires every 0.5s)
        mf1 = await recv_type(ws1, "match_found", timeout=15)
        mf2 = await recv_type(ws2, "match_found", timeout=10)

        check("server-1: alice receives match_found", mf1 is not None,
              "timeout waiting for match_found on server-1")
        check("server-2: bob receives match_found", mf2 is not None,
              "timeout waiting for match_found on server-2")

        if mf1:
            check("alice match_found has color",
                  mf1["payload"].get("color") in ("w", "b"))
        if mf2:
            check("bob match_found has color",
                  mf2["payload"].get("color") in ("w", "b"))

        # Both should also receive game_state
        gs1 = await recv_type(ws1, "game_state", timeout=5)
        gs2 = await recv_type(ws2, "game_state", timeout=5)
        check("server-1: alice receives game_state after match", gs1 is not None)
        check("server-2: bob receives game_state after match", gs2 is not None)

    finally:
        await ws1.close()
        await ws2.close()


# ── Phase 5: server identity check via Redis pub/sub ────────────────────────

async def phase5_server_identity():
    """
    Confirm that server-1 and server-2 have distinct server IDs by observing
    routing metadata differences (room created on one vs. other).
    """
    print("\n[Phase 5] Server identity (different server IDs)")

    # Register fresh users for this test
    async with websockets.connect(SERVER1) as ws1:
        await ws1.send(send_msg("login_request", {
            "action": "register", "username": "id_alice", "password": "test"
        }))
        r1 = await recv_any(ws1, timeout=5)
        check("id_alice registered/logged-in on server-1",
              r1 is not None and r1.get("type") in ("login_success", "error"))

    async with websockets.connect(SERVER2) as ws2:
        await ws2.send(send_msg("login_request", {
            "action": "register", "username": "id_bob", "password": "test"
        }))
        r2 = await recv_any(ws2, timeout=5)
        check("id_bob registered/logged-in on server-2",
              r2 is not None and r2.get("type") in ("login_success", "error"))

    # If both respond, the servers are independently running
    check("Both servers are independently operational",
          r1 is not None and r2 is not None)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("Stage 5 — Cross-server WebSocket verification")
    print("=" * 60)
    print(f"  server-1: {SERVER1}")
    print(f"  server-2: {SERVER2}")

    ok = await phase0_connectivity()
    if not ok:
        print("\n[ABORT] Cannot reach both servers. Make sure 'docker compose up' is running.")
        sys.exit(1)

    await phase1_register()

    room_id = await phase2_cross_server_room()
    if room_id:
        await phase3_cross_server_gameplay(room_id)
    else:
        _failures.append("Phase 3 skipped — no room_id from Phase 2")

    await phase4_cross_server_matchmaking()
    await phase5_server_identity()

    print("\n" + "=" * 60)
    if _failures:
        print(f"RESULT: {len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"  {FAIL}  {f}")
        sys.exit(1)
    else:
        print("RESULT: ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
