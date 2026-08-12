"""
Shared configuration for all load tests.

All values are intentionally small — this is a single-node kind cluster
running on a development laptop.  The numbers are chosen to be realistic
for what the local machine can sustain, not to simulate production load.

Extrapolation notes (at bottom of this file) explain how results scale.
"""

import os

# ── Endpoints ──────────────────────────────────────────────────────────────────
GATEWAY_URL    = os.environ.get("KFC_GW_URL",  "http://localhost:30080")
WS_URL         = os.environ.get("KFC_WS_URL",  "ws://localhost:30765")
KUBECTL_CTX    = os.environ.get("KFC_K8S_CTX", "kind-kungfu-chess")
K8S_NAMESPACE  = "kungfu-chess"
STATEFULSET    = "game-server"

# ── HTTP load parameters ───────────────────────────────────────────────────────
HTTP_CONCURRENCY   = 20     # simultaneous coroutines
HTTP_REQUESTS      = 200    # total requests per endpoint
HTTP_TIMEOUT_S     = 10.0   # per-request timeout

# ── WebSocket load parameters ─────────────────────────────────────────────────
WS_CLIENTS         = 20     # simultaneous WebSocket clients (must be even for matchmaking)
WS_MATCH_TIMEOUT_S = 15.0   # seconds to wait for match_found
WS_CONNECT_TIMEOUT = 10.0   # websockets open_timeout

# ── User name prefix ──────────────────────────────────────────────────────────
# Unique per run so tests don't collide with existing accounts.
import time as _time
_RUN_SUFFIX = str(int(_time.time()))[-6:]   # last 6 digits of unix ts
USER_PREFIX = f"lt{_RUN_SUFFIX}"           # e.g. lt123456

# ── Extrapolation notes ────────────────────────────────────────────────────────
# A single game-server Pod (Python asyncio, ~256 MB limit) can handle:
#   • O(100-500) concurrent WebSocket connections on a laptop core
#   • O(1000) move validations/sec (GameEngine is pure in-memory dict ops)
#
# The bottleneck at scale is NOT the game logic but the I/O fan-out:
#   • Each matched pair produces 2+ WS messages → 2x amplification
#   • Redis pub/sub adds ~1 ms per cross-server event
#
# At the Server_Design.md target of 10 M concurrent players:
#   • 5 M active games, each on one authoritative Game Server
#   • Assuming 2000 games/pod → 2500 Game Server pods
#   • At 1 move/sec/game → 2000 messages/sec/pod (well within asyncio capacity)
#   • Network bandwidth: 2000 × ~150 bytes = ~300 KB/sec/pod (trivial)
#
# The local test with 20 clients / 200 HTTP requests validates:
#   (a) Correct protocol handling under concurrent load
#   (b) Kubernetes readiness probe / health endpoint stability
#   (c) That scaling replicas up/down does not break existing sessions
#   (d) That each new replica registers with a unique KFC_SERVER_ID
