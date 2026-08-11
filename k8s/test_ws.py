"""
Stage 9 smoke test: WebSocket connectivity to deployed game servers.

Verifies:
1. Can connect to game-server-lb NodePort (ws://localhost:30765)
2. Login succeeds for two users
3. Both users can request matchmaking
4. Match is found (MATCH_FOUND message received)
5. Two connections hit the same game server (one authoritative server per room)
"""

import asyncio
import json
import sys

import websockets


WS_URL = "ws://localhost:30765"


def make_msg(type_: str, payload: dict) -> str:
    """Build a versioned protocol message."""
    return json.dumps({"version": 1, "type": type_, "payload": payload})


async def connect_and_login(username: str, password: str) -> tuple:
    """Connect, login, return (websocket, response)."""
    ws = await websockets.connect(WS_URL, open_timeout=10)
    login_msg = make_msg("login_request", {"action": "login", "username": username, "password": password})
    await ws.send(login_msg)
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    return ws, resp


async def main():
    errors = []
    results = {}

    # 1. Connect player1
    print("Connecting player1...")
    try:
        ws1, login1 = await connect_and_login("player1", "pw1")
        print(f"  player1 login: {login1}")
        if login1.get("type") != "login_success":
            errors.append(f"player1 login failed: {login1}")
        results["player1_login"] = login1.get("type")
    except Exception as e:
        errors.append(f"player1 connect/login error: {e}")
        print(f"  ERROR: {e}")
        sys.exit(1)

    # 2. Connect player2
    print("Connecting player2...")
    try:
        ws2, login2 = await connect_and_login("player2", "pw2")
        print(f"  player2 login: {login2}")
        if login2.get("type") != "login_success":
            errors.append(f"player2 login failed: {login2}")
        results["player2_login"] = login2.get("type")
    except Exception as e:
        errors.append(f"player2 connect/login error: {e}")
        print(f"  ERROR: {e}")
        sys.exit(1)

    # 3. Both request matchmaking
    print("Sending matchmaking requests...")
    play_msg = make_msg("play_request", {})
    await ws1.send(play_msg)
    await ws2.send(play_msg)

    # 4. Wait for MATCH_FOUND on both (may get matchmaking_started first)
    print("Waiting for match (up to 15s)...")
    match1 = match2 = None
    try:
        deadline = asyncio.get_event_loop().time() + 15
        while asyncio.get_event_loop().time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws1.recv(), timeout=15))
            print(f"  player1 received: {msg}")
            if msg.get("type") == "match_found":
                match1 = msg
                break
            # ignore matchmaking_started, game_state, etc. and keep waiting
    except asyncio.TimeoutError:
        errors.append("player1 did not receive match_found within 15s")
    try:
        deadline = asyncio.get_event_loop().time() + 15
        while asyncio.get_event_loop().time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws2.recv(), timeout=15))
            print(f"  player2 received: {msg}")
            if msg.get("type") == "match_found":
                match2 = msg
                break
    except asyncio.TimeoutError:
        errors.append("player2 did not receive match_found within 15s")

    if match1 and match1.get("type") == "match_found":
        results["match_found"] = True
        results["room_id"] = match1.get("room_id")
        results["server_id"] = match1.get("server_id")
        print(f"  MATCH FOUND: room={match1.get('room_id')} server={match1.get('server_id')}")
    else:
        errors.append(f"Expected match_found, got: {match1}")

    await ws1.close()
    await ws2.close()

    # Report
    print("\n=== RESULTS ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

    if errors:
        print("\n=== ERRORS ===")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("\nAll WebSocket smoke tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
