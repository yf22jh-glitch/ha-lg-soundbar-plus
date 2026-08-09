"""Regression tests for the soundbar TCP transport."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from threading import Event, Lock, RLock
from unittest.mock import Mock

import pytest

TRANSPORT_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "lg_soundbar_plus"
    / "transport.py"
)
SPEC = importlib.util.spec_from_file_location("lg_soundbar_transport", TRANSPORT_PATH)
assert SPEC is not None and SPEC.loader is not None
TRANSPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TRANSPORT
SPEC.loader.exec_module(TRANSPORT)

FrameBuffer = TRANSPORT.FrameBuffer
ResilientTemescal = TRANSPORT.ResilientTemescal


def _frame(payload: bytes) -> bytes:
    return bytes([TRANSPORT.FRAME_MARKER]) + struct.pack(">I", len(payload)) + payload


def test_frame_buffer_waits_for_fragmented_header_and_payload() -> None:
    payload = bytes(range(32))
    packet = _frame(payload)
    buffer = FrameBuffer()

    assert buffer.feed(packet[:2]) == []
    assert buffer.feed(packet[2:11]) == []
    assert buffer.feed(packet[11:]) == [payload]


def test_frame_buffer_returns_multiple_frames_from_one_receive() -> None:
    first = bytes(range(16))
    second = bytes(reversed(range(32)))

    assert FrameBuffer().feed(_frame(first) + _frame(second)) == [first, second]


def test_frame_buffer_resynchronises_after_garbage_and_invalid_length() -> None:
    payload = b"x" * 16
    invalid = bytes([TRANSPORT.FRAME_MARKER]) + struct.pack(">I", 15) + b"bad"

    assert FrameBuffer().feed(b"garbage" + invalid + _frame(payload)) == [payload]


class FakeSocket:
    """Small send-only socket double."""

    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.sent: list[bytes] = []

    def sendall(self, packet: bytes) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(packet)

    def shutdown(self, _how: int) -> None:
        return

    def close(self) -> None:
        return


def _client(sock: FakeSocket) -> ResilientTemescal:
    client = object.__new__(ResilientTemescal)
    client.address = "192.0.2.10"
    client.socket = sock
    client._connected = True
    client._connection_callback = None
    client._connect_lock = Lock()
    client._socket_lock = RLock()
    client._send_lock = Lock()
    client._stopped = Event()
    client.encrypt_packet = Mock(return_value=b"complete packet")
    return client


def test_send_packet_uses_sendall() -> None:
    sock = FakeSocket()
    client = _client(sock)

    client.send_packet({"cmd": "get"})

    assert sock.sent == [b"complete packet"]


def test_send_packet_reconnects_once_after_broken_socket() -> None:
    broken = FakeSocket(BrokenPipeError("gone"))
    replacement = FakeSocket()
    client = _client(broken)

    def reconnect() -> None:
        client.socket = replacement
        client._connected = True

    client.connect = reconnect
    client.send_packet({"cmd": "get"})

    assert replacement.sent == [b"complete packet"]


def test_send_packet_surfaces_final_failure() -> None:
    client = _client(FakeSocket(BrokenPipeError("gone")))

    def reconnect() -> None:
        client.socket = FakeSocket(BrokenPipeError("still gone"))
        client._connected = True

    client.connect = reconnect

    with pytest.raises(ConnectionError, match="Unable to send command"):
        client.send_packet({"cmd": "get"})


def test_late_failure_from_old_socket_does_not_drop_replacement() -> None:
    old_socket = FakeSocket()
    replacement = FakeSocket()
    client = _client(old_socket)
    client.socket = replacement

    client._drop_socket(old_socket)

    assert client.socket is replacement
    assert client.connected is True
