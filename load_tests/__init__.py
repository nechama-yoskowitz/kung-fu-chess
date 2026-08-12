"""
Kung-Fu Chess load tests.

Tests against the deployed kind cluster (or any running instance).
Endpoints:
  HTTP gateway : http://localhost:30080
  WS game srv  : ws://localhost:30765

Usage:
  python load_tests/run_load_test.py           # full report
  python load_tests/http_load.py               # HTTP only
  python load_tests/ws_load.py                 # WebSocket only
  pytest tests/load/                           # pytest integration
"""
