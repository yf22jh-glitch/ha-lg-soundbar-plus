"""Connection handling for an LG soundbar.

The device pushes state changes on its own, so this integration never polls.
That is deliberate: any request sent to the speaker wakes it up (the LED panel
comes back on), so a heartbeat would keep it permanently awake. Everything
here is driven by the push callback plus a single fetch at connect time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import temescal

from homeassistant.core import HomeAssistant, callback

from .const import (
    MSG_EQ,
    MSG_FUNC,
    MSG_PLAY,
    MSG_SETTING,
    MSG_SPK_LIST,
    SOURCE_ALIASES,
    SOURCE_IDLE,
    SOURCES,
)

_LOGGER = logging.getLogger(__name__)


class LGSoundbarDevice:
    """Holds the socket to one soundbar and the last state it reported."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        """Initialise the device wrapper."""
        self.hass = hass
        self.host = host
        self.port = port
        self._speaker: temescal.temescal | None = None
        self._listeners: list[Callable[[], None]] = []
        self.available = False

        # Last payload seen per message type. The device sends partial updates
        # (a volume change carries only the volume fields), so these are merged
        # rather than replaced.
        self.spk: dict[str, Any] = {}
        self.func: dict[str, Any] = {}
        self.setting: dict[str, Any] = {}
        self.eq: dict[str, Any] = {}
        self.play: dict[str, Any] = {}
        self.product: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Connect and pull the initial state once."""
        await self.hass.async_add_executor_job(self._connect)
        await self.async_refresh()

    def _connect(self) -> None:
        """Create the temescal client (blocking)."""
        self._speaker = temescal.temescal(
            self.host, port=self.port, callback=self._handle_push
        )
        self.available = True

    async def async_shutdown(self) -> None:
        """Close the socket."""
        speaker = self._speaker
        self._speaker = None
        self.available = False
        if speaker is not None and speaker.socket is not None:
            await self.hass.async_add_executor_job(self._close, speaker)

    @staticmethod
    def _close(speaker: temescal.temescal) -> None:
        try:
            speaker.socket.close()
        except OSError:  # already gone
            pass

    async def async_refresh(self) -> None:
        """Ask the device for a full state dump.

        Only called at setup and when the user explicitly asks, never on a
        timer, because a request wakes the speaker.
        """
        await self.hass.async_add_executor_job(self._refresh)

    def _refresh(self) -> None:
        speaker = self._speaker
        if speaker is None:
            return
        speaker.get_product_info()
        speaker.get_info()
        speaker.get_func()
        speaker.get_settings()
        speaker.get_eq()
        speaker.get_play()

    # ------------------------------------------------------------------
    # push handling
    # ------------------------------------------------------------------

    def _handle_push(self, response: dict[str, Any]) -> None:
        """Merge a pushed message. Runs on temescal's listener thread."""
        data = response.get("data") or {}
        msg = response.get("msg")

        if msg == MSG_SPK_LIST:
            self.spk.update(data)
        elif msg == MSG_FUNC:
            self.func.update(data)
        elif msg == MSG_SETTING:
            self.setting.update(data)
        elif msg == MSG_EQ:
            self.eq.update(data)
        elif msg == MSG_PLAY:
            self.play.update(data)
        elif msg == "PRODUCT_INFO":
            self.product.update(data)
        else:
            return

        self.available = True
        self.hass.loop.call_soon_threadsafe(self._notify)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired whenever the device reports something."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    # ------------------------------------------------------------------
    # derived state
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Friendly name the speaker reports for itself."""
        return (
            self.spk.get("s_user_name")
            or self.setting.get("s_user_name")
            or self.host
        )

    @property
    def source_id(self) -> int | None:
        """Current input, normalised through the firmware's alias rewrites."""
        raw = self.func.get("i_curr_func", self.spk.get("i_curr_func"))
        if raw is None:
            return None
        return SOURCE_ALIASES.get(raw, raw)

    @property
    def source(self) -> str | None:
        """Current input as a name, or None if the index is unknown."""
        source_id = self.source_id
        if source_id is None:
            return None
        return SOURCES.get(source_id)

    @property
    def is_on(self) -> bool:
        """Whether the speaker is doing something.

        This hardware never sends b_powerstatus, so power is inferred from the
        active input: it parks on the network input (0) in standby and moves to
        a real input when it wakes. Network playback still counts as on, which
        is why PLAY_INFO is consulted for the idle case.
        """
        source_id = self.source_id
        if source_id is None:
            return False
        if source_id != SOURCE_IDLE:
            return True
        return bool(self.play.get("s_title") or self.play.get("i_stream_type"))

    def setting_int(self, key: str) -> int | None:
        """Read an int out of SETTING_VIEW_INFO."""
        value = self.setting.get(key)
        return value if isinstance(value, int) else None

    def setting_bool(self, key: str) -> bool | None:
        """Read a bool out of SETTING_VIEW_INFO."""
        value = self.setting.get(key)
        return value if isinstance(value, bool) else None

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def async_call(self, method: str, *args: Any) -> None:
        """Invoke a temescal method off the event loop."""
        speaker = self._speaker
        if speaker is None:
            return
        await self.hass.async_add_executor_job(
            getattr(speaker, method), *args
        )

    async def async_send(self, packet: dict[str, Any]) -> None:
        """Send a raw packet for fields temescal has no helper for."""
        speaker = self._speaker
        if speaker is None:
            return
        await self.hass.async_add_executor_job(speaker.send_packet, packet)
