"""Pin connection/close interleavings without real network sockets."""

import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).parents[1] / "custom_components/lg_soundbar_plus/transport.py"
spec = importlib.util.spec_from_file_location("soundbar_race_transport", path)
assert spec is not None and spec.loader is not None
TRANSPORT = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TRANSPORT
spec.loader.exec_module(TRANSPORT)
ResilientTemescal = TRANSPORT.ResilientTemescal
FrameBuffer = TRANSPORT.FrameBuffer


class Socket:
    def __init__(self):
        self.closed = False

    def settimeout(self, value):
        pass

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class SoundbarTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.speaker = object.__new__(ResilientTemescal)
        for name, value in {
            "_connection_callback": self.events.append,
            "_connected": False,
            "_connect_lock": threading.Lock(),
            "_socket_lock": threading.RLock(),
            "_send_lock": threading.Lock(),
            "_stopped": threading.Event(),
            "socket": None,
            "address": "invalid.test",
            "port": 9741,
        }.items():
            setattr(self.speaker, name, value)

    def test_close_while_connecting_closes_pending_socket(self):
        started = threading.Event()
        finish = threading.Event()
        sock = Socket()
        errors = []

        def create(*args, **kwargs):
            started.set()
            self.assertTrue(finish.wait(2))
            return sock

        def connect():
            try:
                self.speaker.connect()
            except OSError:
                errors.append(True)

        with patch.object(TRANSPORT.socket, "create_connection", create):
            thread = threading.Thread(target=connect)
            thread.start()
            self.assertTrue(started.wait(2))
            self.speaker.close()
            finish.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(sock.closed)
        self.assertFalse(self.speaker.connected)
        self.assertEqual(self.events, [])
        self.assertEqual(errors, [True])

    def test_waiting_connect_rechecks_closed_state(self):
        done = threading.Event()

        def connect():
            try:
                self.speaker.connect()
            except OSError:
                done.set()

        with patch.object(TRANSPORT.socket, "create_connection") as create:
            with self.speaker._connect_lock:
                thread = threading.Thread(target=connect)
                thread.start()
                self.speaker.close()
            thread.join(2)
        self.assertTrue(done.is_set())
        create.assert_not_called()

    def test_connection_and_close_callbacks_are_ordered_once(self):
        sock = Socket()
        with patch.object(TRANSPORT.socket, "create_connection", return_value=sock):
            self.speaker.connect()
            self.speaker.connect()
            self.speaker.close()
            self.speaker.close()
        self.assertEqual(self.events, [True, False])
        self.assertTrue(sock.closed)

    def test_failed_socket_configuration_closes_new_socket(self):
        sock = Socket()

        def fail(_):
            raise OSError("configuration failed")

        sock.settimeout = fail
        with patch.object(TRANSPORT.socket, "create_connection", return_value=sock):
            with self.assertRaises(OSError):
                self.speaker.connect()
        self.assertTrue(sock.closed)
        self.assertFalse(self.speaker.connected)

    def test_stale_socket_drop_does_not_close_current_connection(self):
        old = Socket()
        current = Socket()
        self.speaker.socket = current
        self.speaker._connected = True
        self.speaker._drop_socket(old)
        self.assertTrue(old.closed)
        self.assertFalse(current.closed)
        self.assertTrue(self.speaker.connected)

    def test_frame_buffer_keeps_fragmented_and_combined_frames(self):
        def frame(value):
            return b"\x10" + (16).to_bytes(4, "big") + bytes([value]) * 16

        buffer = FrameBuffer()
        self.assertEqual(buffer.feed(frame(1)[:8]), [])
        self.assertEqual(
            buffer.feed(frame(1)[8:] + frame(2)), [bytes([1]) * 16, bytes([2]) * 16]
        )
