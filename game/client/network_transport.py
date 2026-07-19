"""
WebSocket network transport — runs in a background thread with its own asyncio loop.

Responsibilities:
- Connect to the server
- Send queued outgoing messages
- Receive and decode incoming messages
- Place decoded messages in the incoming queue
- Handle connection errors and clean shutdown

Does NOT modify ClientGameState, Controller, or graphics directly.
"""

import asyncio
import logging
import queue
import threading

import websockets

from game.server.protocol import decode_message

logger = logging.getLogger(__name__)

SEND_POLL_INTERVAL = 0.01  # 10ms


class NetworkTransport:
    """
    Background WebSocket transport.

    Owns a dedicated asyncio event loop in a separate thread.
    Communicates with the game thread via thread-safe queues.
    """

    def __init__(self, uri: str, outgoing: queue.Queue, incoming: queue.Queue):
        self._uri = uri
        self._outgoing = outgoing
        self._incoming = incoming
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: threading.Event = threading.Event()
        self._connected = False
        self._error: str | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        """Start the background network thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="network-transport"
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Request stop and wait for the background thread to terminate."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def drain_incoming(self) -> list[dict]:
        """
        Pop all pending decoded messages from the incoming queue.

        Called from the game/graphics thread. Returns messages in arrival order.
        """
        messages = []
        while True:
            try:
                msg = self._incoming.get_nowait()
                messages.append(msg)
            except queue.Empty:
                break
        return messages

    # ─── Background thread ────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Entry point for the background thread. Creates and runs an asyncio loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            self._error = str(e)
            logger.error(f"Transport error: {e}")
        finally:
            self._loop.close()
            self._connected = False

    async def _async_main(self) -> None:
        """Connect, then run send/receive loops until stopped."""
        try:
            async with websockets.connect(self._uri) as ws:
                self._connected = True
                logger.info(f"Connected to {self._uri}")

                send_task = asyncio.create_task(self._send_loop(ws))
                recv_task = asyncio.create_task(self._recv_loop(ws))
                stop_task = asyncio.create_task(self._wait_for_stop())

                done, pending = await asyncio.wait(
                    [send_task, recv_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except (ConnectionRefusedError, OSError) as e:
            self._error = f"Connection failed: {e}"
            logger.error(self._error)
        finally:
            self._connected = False

    async def _send_loop(self, ws) -> None:
        """Poll outgoing queue and send messages to the server."""
        while not self._stop_event.is_set():
            try:
                msg = self._outgoing.get_nowait()
                await ws.send(msg)
            except queue.Empty:
                await asyncio.sleep(SEND_POLL_INTERVAL)

    async def _recv_loop(self, ws) -> None:
        """Receive messages from the server and enqueue them."""
        try:
            async for raw in ws:
                decoded = decode_message(raw)
                if decoded is not None:
                    self._incoming.put_nowait(decoded)
                else:
                    # Non-protocol message (e.g. legacy "pong")
                    self._incoming.put_nowait({"type": "raw", "payload": raw})
        except websockets.ConnectionClosed:
            logger.info("Server disconnected")

    async def _wait_for_stop(self) -> None:
        """Await until the stop event is set."""
        while not self._stop_event.is_set():
            await asyncio.sleep(0.05)
