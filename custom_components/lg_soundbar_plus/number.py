"""Number entities for LG Soundbar Plus: speaker trim and the sleep timer."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LGSoundbarConfigEntry
from .const import LEVEL_KEYS, SLEEP_MAX, SLEEP_OFF
from .device import LGSoundbarDevice
from .entity import LGSoundbarEntity

# temescal setter per trim key.
LEVEL_SETTERS = {
    "woofer": "set_woofer_level",
    "rear": "set_rear_level",
    "center": "set_center_level",
    "top": "set_top_level",
}

LEVEL_NAMES = {
    "woofer": "Woofer level",
    "rear": "Rear level",
    "center": "Centre level",
    "top": "Top level",
    "side": "Side level",
    "dialog": "Dialogue level",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create number entities for whatever this unit reports."""
    device = entry.runtime_data
    entities: list[NumberEntity] = [LGSoundbarSleepTimer(device, entry.entry_id)]

    for key, (level_field, min_field, max_field) in LEVEL_KEYS.items():
        # Only offer a trim the speaker actually reports and can be told to
        # change. Side and dialogue levels are reported by some units but have
        # no setter in temescal, so they are read-only and skipped here.
        if key not in LEVEL_SETTERS:
            continue
        if device.setting.get(level_field) is None:
            continue
        if device.setting.get(min_field) is None or device.setting.get(max_field) is None:
            continue
        entities.append(
            LGSoundbarLevel(
                device, entry.entry_id, key, level_field, min_field, max_field
            )
        )

    async_add_entities(entities)


class LGSoundbarLevel(LGSoundbarEntity, NumberEntity):
    """A speaker trim level, in dB.

    The wire value is a zero-based unsigned step count while the device reports
    its usable range in dB, so the two are converted here. Writing a negative
    value is rejected by the firmware (it comes back as the absolute value),
    which is what confirms the wire value is unsigned.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "dB"

    def __init__(
        self,
        device: LGSoundbarDevice,
        unique_id: str,
        key: str,
        level_field: str,
        min_field: str,
        max_field: str,
    ) -> None:
        """Initialise the trim entity."""
        super().__init__(device, unique_id)
        self._key = key
        self._level_field = level_field
        self._min_field = min_field
        self._max_field = max_field
        self._attr_unique_id = f"{unique_id}_{key}_level"
        self._attr_name = LEVEL_NAMES[key]

    @property
    def native_min_value(self) -> float:
        """Lowest trim the speaker accepts, in dB."""
        return float(self.device.setting.get(self._min_field, 0))

    @property
    def native_max_value(self) -> float:
        """Highest trim the speaker accepts, in dB."""
        return float(self.device.setting.get(self._max_field, 0))

    @property
    def native_value(self) -> float | None:
        """Current trim in dB."""
        raw = self.device.setting.get(self._level_field)
        minimum = self.device.setting.get(self._min_field)
        if raw is None or minimum is None:
            return None
        return float(raw + minimum)

    async def async_set_native_value(self, value: float) -> None:
        """Write a trim, converting dB back to the unsigned wire value."""
        minimum = self.device.setting.get(self._min_field)
        if minimum is None:
            return
        await self.device.async_call(
            LEVEL_SETTERS[self._key], int(value) - minimum
        )


class LGSoundbarSleepTimer(LGSoundbarEntity, NumberEntity):
    """Sleep timer in minutes; 0 turns it off.

    Kept separate from media-player power controls because the timer has been
    seen expiring without sending the speaker to standby.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = SLEEP_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_name = "Sleep timer"

    def __init__(self, device: LGSoundbarDevice, unique_id: str) -> None:
        """Initialise the sleep timer entity."""
        super().__init__(device, unique_id)
        self._attr_unique_id = f"{unique_id}_sleep_timer"

    @property
    def native_value(self) -> float | None:
        """Minutes remaining, or 0 when no timer is set."""
        value = self.device.setting_int("i_sleep_time")
        if value is None:
            return None
        return 0.0 if value < 0 else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Start or cancel the timer.

        A value of 0 is translated to the firmware's "off" sentinel. Writing a
        literal 0 is accepted by the device but never fires, so it would look
        like a timer that silently does nothing.
        """
        minutes = int(value)
        await self.device.async_call(
            "set_sleep_time", SLEEP_OFF if minutes <= 0 else minutes
        )
