"""Media player for LG Soundbar Plus."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LGSoundbarConfigEntry
from .const import (
    EQUALISERS,
    SOURCE_IDLE,
    SOURCE_IDS,
    SOURCES,
    TURN_OFF_SLEEP_MINUTES,
)
from .device import LGSoundbarDevice
from .entity import LGSoundbarEntity

# Where turn_on sends the speaker when nothing better is known. Optical is the
# input a TV-attached soundbar wakes to in practice.
DEFAULT_WAKE_SOURCE = 4


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player."""
    async_add_entities([LGSoundbarMediaPlayer(entry.runtime_data, entry.entry_id)])


class LGSoundbarMediaPlayer(LGSoundbarEntity, MediaPlayerEntity):
    """The soundbar itself."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )

    def __init__(self, device: LGSoundbarDevice, unique_id: str) -> None:
        """Initialise the media player."""
        super().__init__(device, unique_id)
        self._attr_unique_id = unique_id
        self._last_active_source = DEFAULT_WAKE_SOURCE

    @property
    def state(self) -> MediaPlayerState:
        """Whether the speaker is awake."""
        if self.device.is_on:
            source_id = self.device.source_id
            if source_id is not None and source_id != SOURCE_IDLE:
                self._last_active_source = source_id
            return MediaPlayerState.ON
        return MediaPlayerState.OFF

    # ------------------------------------------------------------------
    # volume
    # ------------------------------------------------------------------

    @property
    def volume_level(self) -> float | None:
        """Volume as a 0..1 fraction."""
        volume = self.device.spk.get("i_vol")
        maximum = self.device.spk.get("i_vol_max")
        if volume is None or not maximum:
            return None
        return volume / maximum

    @property
    def is_volume_muted(self) -> bool | None:
        """Whether the speaker is muted."""
        return self.device.spk.get("b_mute")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume."""
        maximum = self.device.spk.get("i_vol_max") or 0
        await self.device.async_call("set_volume", round(volume * maximum))

    async def async_volume_up(self) -> None:
        """Nudge the volume up one step."""
        await self._step_volume(1)

    async def async_volume_down(self) -> None:
        """Nudge the volume down one step."""
        await self._step_volume(-1)

    async def _step_volume(self, delta: int) -> None:
        current = self.device.spk.get("i_vol")
        if current is None:
            return
        minimum = self.device.spk.get("i_vol_min", 0)
        maximum = self.device.spk.get("i_vol_max", 0)
        await self.device.async_call(
            "set_volume", max(minimum, min(maximum, current + delta))
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.device.async_call("set_mute", mute)

    # ------------------------------------------------------------------
    # source
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        """Current input."""
        return self.device.source

    @property
    def source_list(self) -> list[str]:
        """Selectable inputs.

        The device's own ai_func_list is not used: it advertises indices the
        firmware rewrites on the way in and omits ones that work, so a source
        the speaker is actually sitting on can be missing from its own list.
        """
        return list(SOURCES.values())

    async def async_select_source(self, source: str) -> None:
        """Switch input."""
        source_id = SOURCE_IDS.get(source)
        if source_id is None:
            return
        await self.device.async_call("set_func", source_id)

    # ------------------------------------------------------------------
    # sound mode
    # ------------------------------------------------------------------

    @property
    def sound_mode(self) -> str | None:
        """Current equaliser preset."""
        index = self.device.eq.get("i_curr_eq", self.device.setting.get("i_curr_eq"))
        if index is None or index >= len(EQUALISERS):
            return None
        return EQUALISERS[index]

    @property
    def sound_mode_list(self) -> list[str]:
        """Presets this unit offers."""
        available = self.device.eq.get("ai_eq_list") or []
        return sorted(
            EQUALISERS[index] for index in available if index < len(EQUALISERS)
        )

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Change the equaliser preset."""
        if sound_mode not in EQUALISERS:
            return
        await self.device.async_call("set_eq", EQUALISERS.index(sound_mode))

    # ------------------------------------------------------------------
    # power
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Wake the speaker by selecting its last real input."""
        await self.device.async_call("set_func", self._last_active_source)

    async def async_turn_off(self) -> None:
        """Send the speaker to standby.

        There is no immediate power-off on this hardware. The b_powerkey field
        the core integration uses is ignored outright here — it draws no
        response and changes nothing, with or without an active input signal.
        A one-minute sleep timer is the shortest standby trigger that works.
        """
        await self.device.async_call("set_sleep_time", TURN_OFF_SLEEP_MINUTES)

    # ------------------------------------------------------------------
    # now playing
    # ------------------------------------------------------------------

    @property
    def media_title(self) -> str | None:
        """Track title, when the speaker is streaming."""
        return (self.device.play.get("s_title") or "").strip() or None

    @property
    def media_artist(self) -> str | None:
        """Track artist, when the speaker is streaming."""
        return (self.device.play.get("s_artist") or "").strip() or None

    @property
    def extra_state_attributes(self) -> dict[str, int | str]:
        """Expose the raw input index, which is useful when mapping a new model."""
        attributes: dict[str, int | str] = {}
        source_id = self.device.source_id
        if source_id is not None:
            attributes["source_index"] = source_id
        sleep = self.device.setting_int("i_sleep_time")
        if sleep is not None and sleep > 0:
            attributes["sleep_timer_minutes"] = sleep
        return attributes

    async def async_update(self) -> None:
        """Pull a fresh dump.

        Only reached if someone calls homeassistant.update_entity; polling is
        off because every request wakes the speaker.
        """
        await self.device.async_refresh()
