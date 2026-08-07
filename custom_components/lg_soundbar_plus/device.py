"""Connection handling for an LG soundbar.

The device pushes state changes on its own, so this integration never polls.
That is deliberate: any request sent to the speaker wakes it up (the LED panel
comes back on), so a heartbeat would keep it permanently awake. Everything
here is driven by the push callback plus a single fetch at connect time.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import temescal

from homeassistant.core import HomeAssistant, callback

from .const import (
    MSG_EQ,
    MSG_FUNC,
    MSG_PLAY,
    MSG_PRODUCT,
    MSG_SETTING,
    MSG_SPK_LIST,
    SOURCE_ALIASES,
    SOURCE_IDLE,
    SOURCES,
)

_LOGGER = logging.getLogger(__name__)

# Replies the first dump has to deliver before entities can be built. Which
# switches and trim levels exist is decided from SETTING_VIEW_INFO, so setting
# up the platforms before it lands silently produces a media player and nothing
# else. EQ_VIEW_INFO is needed for the sound mode list, SPK_LIST_VIEW_INFO for
# the volume range, FUNC_VIEW_INFO for the current input.
INITIAL_DUMP: frozenset[str] = frozenset(
    {MSG_SPK_LIST, MSG_FUNC, MSG_SETTING, MSG_EQ}
)

# How long to wait for that dump. Replies normally arrive well inside a second;
# this only has to cover a speaker that is slow to wake.
INITIAL_DUMP_TIMEOUT = 15


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

        # Which message types have been seen, and an event fired once the first
        # dump is complete. Replies come back on temescal's listener thread, so
        # setup has to wait on this rather than assume the requests were
        # answered by the time they returned.
        self._seen: set[str] = set()
        self._dump_complete = asyncio.Event()

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
        """Connect, pull the initial state, and wait for it to arrive.

        The wait matters: the requests are fire-and-forget and every reply is
        pushed back asynchronously, so returning as soon as they are sent would
        hand the platforms an empty state and they would create no entities.
        """
        await self.hass.async_add_executor_job(self._connect)
        await self.async_refresh()

        with suppress(TimeoutError):
            async with asyncio.timeout(INITIAL_DUMP_TIMEOUT):
                await self._dump_complete.wait()

        if missing := INITIAL_DUMP - self._seen:
            # Not fatal — the media player still works off whatever arrives
            # later — but entities keyed off the missing message will be absent
            # until the entry is reloaded.
            _LOGGER.warning(
                "%s did not answer %s within %ss; some entities may be missing",
                self.host,
                ", ".join(sorted(missing)),
                INITIAL_DUMP_TIMEOUT,
            )

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
        previous_source = self.source_id

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
        elif msg == MSG_PRODUCT:
            self.product.update(data)
        else:
            return

        # Track info belongs to the input that was playing it. The speaker does
        # not retract it on a switch, so drop it here rather than let it trail
        # the next input around.
        if (
            msg != MSG_PLAY
            and previous_source is not None
            and self.source_id != previous_source
        ):
            self.play.clear()

        self.available = True
        self.hass.loop.call_soon_threadsafe(self._notify, msg)

    @callback
    def _notify(self, msg: str) -> None:
        self._seen.add(msg)
        if not self._dump_complete.is_set() and INITIAL_DUMP <= self._seen:
            self._dump_complete.set()
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
        """Whether a real input is selected.

        This hardware never sends b_powerstatus, so the selected input is all
        there is to go on: the speaker parks on the network input (0) and moves
        to a physical one when it wakes.

        Network playback deliberately does not count. PLAY_INFO would be the
        only way to spot it, and it cannot be trusted here: the speaker answers
        a query for it truthfully but never pushes the transition to empty, so
        a cached title outlives the playback that produced it indefinitely —
        observed still reporting a streaming app twelve hours after the fact.
        Whatever is streaming over the network already has its own media player
        entity in Home Assistant; this one reports the amplifier.
        """
        source_id = self.source_id
        if source_id is None:
            return False
        return source_id != SOURCE_IDLE

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
