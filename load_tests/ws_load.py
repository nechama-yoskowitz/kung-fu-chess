"""
WebSocket game-server load test.

Simulates n_clients users, pairing them into matchmaking couples:
  • Connects to ws://localhost:30765 (game-server-lb NodePort)
  • Logs in each user (login_request)
  • Sends play_request for all users simultaneously
  • Waits for match_found on each pair
  • After matching, each player in a game sends one move_request
  • Records latency for login and match phases

Metrics captured:
  • connections opened/succeeded/failed
  • logins succeeded/failed
  • matches found (pairs)
  • move_accepted count
  • per-phase latency (login, match_found, move roundtrip)

Design constraints:
  • n_clients must be even (pairs)
  • local kind cluster → keep n_clients ≤ 40 to avoid starving CI
  • The load test registers users on every run (using a timestamp suffix)
    so repeated runs don't collide.

Usage:
  python load_tests/ws_load.py
  python load_tests/ws_load.py --clients 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

import websockets
import aiohttp

from load_tests.config import (
    GATEWAY_URL,
    WS_URL,
    WS_CLIENTS,
    WS_MATCH_TIMEOUT_S,
    WS_CONNECT_TIMEOUT,
    USER_PREFIX,
)


# ── Result containers ─────────────────────────────────────────────────────────

@dataclass
class WSResult:
    n_clients: int = 0
    connected: int = 0
    connect_failed: int = 0
    login_ok: int = 0
    login_failed: int = 0
    matches_found: int = 0
    matches_failed: int = 0
    moves_accepted: int = 0
    moves_sent: int = 0
    login_latencies: List[float] = field(default_factory=list)
    match_latencies: List[float] = field(default_factory=list)
    move_latencies:  List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    server_ids_seen: List[str] = field(default_factory=list)

    def _pct_summary(self, lats: List[float]) -> str:
        if not lats:
            return "n/a"
        s = sorted(lats)
        n = len(s)
        def p(q): return s[min(int(n * q / 100), n - 1)]
        return (
            f"min={s[0]:.3f}s "
            f"p50={p(50):.3f}s "
            f"p90={p(90):.3f}s "
            f"max={s[-1]:.3f}s "
            f"mean={statistics.mean(s):.3f}s"
        )

    def print_summary(self) -> None:
        print(f"\n[WS] Results  (elapsed={self.elapsed_s:.2f}s  clients={self.n_clients})")
        print("-" * 70)
        print(f"  Connections  : ok={self.connected}  failed={self.connect_failed}")
        print(f"  Logins       : ok={self.login_ok}  failed={self.login_failed}")
        print(f"  Matches      : found={self.matches_found}  failed={self.matches_failed}")
        print(f"  Moves        : sent={self.moves_sent}  accepted={self.moves_accepted}")
        print(f"  Login  latency: {self._pct_summary(self.login_latencies)}")
        print(f"  Match  latency: {self._pct_summary(self.match_latencies)}")
        if self.move_latencies:
            print(f"  Move   latency: {self._pct_summary(self.move_latencies)}")
        if self.server_ids_seen:
            unique = sorted(set(self.server_ids_seen))
            print(f"  Server IDs seen (from game-state): {unique}")
        if self.errors:
            print(f"  Errors ({len(self.errors)}):")
            for e in self.errors[:5]:
                print(f"    {e}")
        print("-" * 70)

    def to_dict(self) -> dict:
        lats = self.login_latencies
        mlats = self.match_latencies
        def summ(l):
            if not l: return {}
            s = sorted(l)
            n = len(s)
            def p(q): return s[min(int(n*q/100), n-1)]
            return {"min": s[0], "p50": p(50), "p90": p(90), "max": s[-1], "mean": statistics.mean(s)}
        return {
            "n_clients": self.n_clients,
            "connected": self.connected,
            "connect_failed": self.connect_failed,
            "login_ok": self.login_ok,
            "login_failed": self.login_failed,
            "matches_found": self.matches_found,
            "matches_failed": self.matches_failed,
            "moves_accepted": self.moves_accepted,
            "elapsed_s": self.elapsed_s,
            "login_latency": summ(lats),
            "match_latency": summ(mlats),
            "server_ids_seen": sorted(set(self.server_ids_seen)),
        }


# ── Protocol helpers ──────────────────────────────────────────────────────────

def _msg(type_: str, payload: dict = None) -> str:
    return json.dumps({"version": 1, "type": type_, "payload": payload or {}})


async def _recv_until(ws, wanted: set, timeout: float) -> Optional[dict]:
    """Read messages from ws until we get one whose type is in `wanted`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            if msg.get("type") in wanted:
                return msg
            # silently skip other message types (game_state, etc.)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            break
    return None


# ── Pre-register users via HTTP gateway ──────────────────────────────────────

async def _register_users(usernames: List[str], password: str) -> None:
    """Register all users via the HTTP gateway before the WS phase."""
    timeout  = aiohttp.ClientTimeout(total=10)
    conn     = aiohttp.TCPConnector(limit=20)
    reg_url  = f"{GATEWAY_URL}/auth/register"

    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as sess:
        async def reg(u):
            try:
                async with sess.post(reg_url, json={"username": u, "password": password}) as r:
                    await r.read()
            except Exception:
                pass
        await asyncio.gather(*[reg(u) for u in usernames])


# ── Single-client coroutine ───────────────────────────────────────────────────

async def _client_session(
    username: str,
    password: str,
    result: WSResult,
    match_event: asyncio.Event,
    sem: asyncio.Semaphore,
) -> None:
    """Run one simulated player: connect → login → play → wait for match → move."""
    async with sem:
        # ── Connect ────────────────────────────────────────────────────────
        try:
            ws = await websockets.connect(
                WS_URL,
                open_timeout=WS_CONNECT_TIMEOUT,
                ping_interval=None,  # disable auto-ping to keep test clean
            )
        except Exception as e:
            result.connect_failed += 1
            result.errors.append(f"connect failed for {username}: {e}")
            return

        result.connected += 1

        try:
            # ── Login ───────────────────────────────────────────────────────
            t0 = time.monotonic()
            await ws.send(_msg("login_request", {
                "action": "login", "username": username, "password": password,
            }))
            login_resp = await _recv_until(ws, {"login_success", "error"}, timeout=5.0)
            login_lat  = time.monotonic() - t0

            if not login_resp or login_resp.get("type") != "login_success":
                result.login_failed += 1
                result.errors.append(
                    f"login failed for {username}: {login_resp}"
                )
                return

            result.login_ok += 1
            result.login_latencies.append(login_lat)

            # ── Request matchmaking ─────────────────────────────────────────
            await ws.send(_msg("play_request"))

            # ── Wait for match ──────────────────────────────────────────────
            t1 = time.monotonic()
            match_resp = await _recv_until(
                ws,
                {"match_found", "error", "matchmaking_timeout"},
                timeout=WS_MATCH_TIMEOUT_S,
            )
            match_lat = time.monotonic() - t1

            if not match_resp or match_resp.get("type") != "match_found":
                result.matches_failed += 1
                result.errors.append(
                    f"no match for {username}: {match_resp}"
                )
                return

            result.matches_found += 1
            result.match_latencies.append(match_lat)

            # ── Send one move ───────────────────────────────────────────────
            # White player (color 'w') starts from row 6; Black from row 1.
            # We send a move regardless — server will reject invalid ones,
            # which is fine; we're testing throughput not game logic here.
            color = match_resp.get("payload", {}).get("color", "w")
            if color == "w":
                move = _msg("move_request", {
                    "from_row": 6, "from_col": 4,
                    "to_row":   4, "to_col":   4,
                })
            else:
                move = _msg("move_request", {
                    "from_row": 1, "from_col": 4,
                    "to_row":   3, "to_col":   4,
                })

            t2 = time.monotonic()
            result.moves_sent += 1
            await ws.send(move)

            # Wait for game_state or move_accepted (confirms server processed it)
            move_resp = await _recv_until(
                ws,
                {"move_accepted", "move_rejected", "game_state", "error"},
                timeout=5.0,
            )
            move_lat = time.monotonic() - t2
            if move_resp and move_resp.get("type") == "move_accepted":
                result.moves_accepted += 1
                result.move_latencies.append(move_lat)

            # Collect server_id from game_state if available
            if move_resp and move_resp.get("type") == "game_state":
                pass  # game_state doesn't include server_id directly

            await ws.close()

        except Exception as e:
            result.errors.append(f"error for {username}: {e}")
        finally:
            try:
                await ws.close()
            except Exception:
                pass


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run(n_clients: int = WS_CLIENTS) -> WSResult:
    if n_clients % 2 != 0:
        n_clients -= 1  # ensure even number for pairing

    result   = WSResult(n_clients=n_clients)
    password = "loadtest_pw"
    usernames = [f"{USER_PREFIX}w{i}" for i in range(n_clients)]

    print(f"\n[WS] Pre-registering {n_clients} users...")
    await _register_users(usernames, password)

    print(f"[WS] Starting {n_clients} WebSocket clients → {WS_URL}")
    sem = asyncio.Semaphore(n_clients)
    match_event = asyncio.Event()

    t_start = time.monotonic()
    await asyncio.gather(*[
        _client_session(u, password, result, match_event, sem)
        for u in usernames
    ])
    result.elapsed_s = round(time.monotonic() - t_start, 2)

    result.print_summary()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="WebSocket load test")
    parser.add_argument("--clients", type=int, default=WS_CLIENTS)
    args = parser.parse_args()
    asyncio.run(run(args.clients))


if __name__ == "__main__":
    main()
