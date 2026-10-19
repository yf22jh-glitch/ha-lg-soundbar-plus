"""Reliable socket transport for the archived temescal client.

The wire protocol is a one-byte marker, a four-byte big-endian payload length,
and an AES-encrypted payload.  TCP does not preserve those message boundaries,
so every receive must be buffered until the complete frame has arrived.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Lock, RLock, current_thread
from typing import Any

import temescal

_LOGGER = logging.getLogger(__name__)

FRAME_MARKER = 0x10
FRAME_HEADER_SIZE = 5
MAX_PAYLOAD_SIZE = 1024 * 1024
CONNECT_TIMEOUT = 5
RECONNECT_MAX_DELAY = 30


class FrameBuffer:
    """Reassemble complete protocol frames from an arbitrary TCP byte stream."""

    def __init__(self, max_payload_size: int = MAX_PAYLOAD_SIZE) -> None:
        self._buffer = bytearray()
        self._max_payload_size = max_payload_size

    def clear(self) -> None:
        """Discard bytes belonging to a connection that has closed."""
        self._buffer.clear()

    def feed(self, data: bytes) -> list[bytes]:
        """Return every complete encrypted payload now in the buffer."""
        self._buffer.extend(data)
        frames: list[bytes] = []

        while self._buffer:
            marker = self._buffer.find(FRAME_MARKER)
            if marker < 0:
                self._buffer.clear()
                break
            if marker:
                del self._buffer[:marker]
            if len(self._buffer) < FRAME_HEADER_SIZE:
                break

            length = struct.unpack(">I", self._buffer[1:FRAME_HEADER_SIZE])[0]
            if length <= 0 or length > self._max_payload_size or length % 16 != 0:
                # This cannot be a valid encrypted frame. Drop only the marker
                # and resynchronise rather than throwing away a later frame.
                del self._buffer[0]
                continue

            end = FRAME_HEADER_SIZE + length
            if len(self._buffer) < end:
                break

            frames.append(bytes(self._buffer[FRAME_HEADER_SIZE:end]))
            del self._buffer[:end]

        return frames


class ResilientTemescal(temescal.temescal):
    """temescal client with framed reads and observable reconnection."""

    def __init__(
        self,
        address: str,
        port: int = 9741,
        callback: Callable[[dict[str, Any]], None] | None = None,
        connection_callback: Callable[[bool], None] | None = None,
    ) -> None:
        self._connection_callback = connection_callback
        self._connected = False
        self._connect_lock = Lock()
        self._socket_lock = RLock()
        self._send_lock = Lock()
        self._stopped = Event()
        super().__init__(address, port=port, callback=callback, logger=_LOGGER)

    @property
    def connected(self) -> bool:
        """Whether a live socket is currently installed."""
        with self._socket_lock:
            return self._connected and self.socket is not None

    def connect(self) -> None:
        """Open a socket, serialising competing command/listener reconnects."""
        if self._stopped.is_set():
            raise ConnectionError("Soundbar transport is closed")

        with self._connect_lock:
            if self._stopped.is_set():
                raise ConnectionError("Soundbar transport is closed")
            if self.connected:
                return
            new_socket = socket.create_connection(
                (self.address, self.port), timeout=CONNECT_TIMEOUT
            )
            # A blocking receive is intentional. close() interrupts it, and
            # time-based polling would wake the soundbar for no useful state.
            try:
                new_socket.settimeout(None)
            except BaseException:
                self._close_socket(new_socket)
                raise
            with self._socket_lock:
                if self._stopped.is_set():
                    self._close_socket(new_socket)
                    raise ConnectionError("Soundbar transport closed during connect")
                old_socket = self.socket
                self.socket = new_socket
                changed = not self._connected
                self._connected = True
                # Serialize notifications with close/drop so an old connect
                # cannot report success after the disconnect notification.
                if changed:
                    self._notify_connection(True)
            self._close_socket(old_socket)

    def listen(self) -> None:
        """Read complete frames forever, reconnecting after EOF or socket errors."""
        frames = FrameBuffer()
        reconnect_delay = 1

        while not self._stopped.is_set():
            sock = self._current_socket()
            if sock is None:
                try:
                    self.connect()
                    frames.clear()
                    continue
                except OSError as err:
                    _LOGGER.debug(
                        "Unable to reconnect to LG soundbar %s: %s",
                        self.address,
                        err,
                    )
                    if self._stopped.wait(reconnect_delay):
                        break
                    reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_DELAY)
                    continue

            try:
                data = sock.recv(4096)
                if not data:
                    raise ConnectionError("Soundbar closed the connection")
            except OSError as err:
                self._drop_socket(sock)
                frames.clear()
                if not self._stopped.is_set():
                    _LOGGER.debug(
                        "LG soundbar %s connection lost: %s",
                        self.address,
                        err,
                    )
                    if self._stopped.wait(reconnect_delay):
                        break
                    reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_DELAY)
                continue

            reconnect_delay = 1
            for payload in frames.feed(data):
                try:
                    response = self.decrypt_packet(payload)
                    decoded = json.loads(response) if response is not None else None
                except (UnicodeDecodeError, ValueError, TypeError, IndexError) as err:
                    _LOGGER.warning(
                        "Discarding an invalid packet from LG soundbar %s: %s",
                        self.address,
                        err,
                    )
                    continue
                if decoded is not None and self.callback is not None:
                    try:
                        self.callback(decoded)
                    except Exception:  # protect the long-lived listener thread
                        _LOGGER.exception("LG soundbar message callback failed")

    def send_packet(self, data: dict[str, Any]) -> None:
        """Send the whole packet, reconnect once, and surface a final failure."""
        packet = self.encrypt_packet(json.dumps(data))
        last_error: OSError | None = None

        for _attempt in range(2):
            sock: socket.socket | None = None
            try:
                if not self.connected:
                    self.connect()
                sock = self._current_socket()
                if sock is None:
                    raise ConnectionError("Soundbar is not connected")
                with self._send_lock:
                    sock.sendall(packet)
                return
            except OSError as err:
                last_error = err
                self._drop_socket(sock)

        raise ConnectionError(
            f"Unable to send command to LG soundbar {self.address}"
        ) from last_error

    def close(self) -> None:
        """Stop reconnection and close the active socket."""
        with self._socket_lock:
            self._stopped.set()
            self._drop_socket(self.socket)
        thread = getattr(self, "thread", None)
        if thread is not None and thread is not current_thread():
            thread.join(timeout=CONNECT_TIMEOUT + 1)

    def _current_socket(self) -> socket.socket | None:
        with self._socket_lock:
            return self.socket

    def _drop_socket(self, expected: socket.socket | None) -> None:
        if expected is None:
            return
        with self._socket_lock:
            if self.socket is not expected:
                self._close_socket(expected)
                return
            self.socket = None
            changed = self._connected
            self._connected = False
            if changed:
                self._notify_connection(False)
        self._close_socket(expected)

    @staticmethod
    def _close_socket(sock: socket.socket | None) -> None:
        if sock is None:
            return
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            sock.close()

    def _notify_connection(self, connected: bool) -> None:
        if self._connection_callback is not None:
            try:
                self._connection_callback(connected)
            except Exception:  # pragma: no cover - protects the socket thread
                _LOGGER.exception("LG soundbar connection callback failed")
