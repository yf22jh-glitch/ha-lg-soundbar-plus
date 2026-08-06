"""Switch entities for the soundbar's boolean settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LGSoundbarConfigEntry
from .device import LGSoundbarDevice
from .entity import LGSoundbarEntity


@dataclass(frozen=True, kw_only=True)
class LGSoundbarSwitchDescription(SwitchEntityDescription):
    """Ties a SETTING_VIEW_INFO field to its temescal setter."""

    field: str
    setter: str


SWITCHES: tuple[LGSoundbarSwitchDescription, ...] = (
    LGSoundbarSwitchDescription(
        key="drc",
        name="Dynamic range control",
        field="b_drc",
        setter="set_drc",
    ),
    LGSoundbarSwitchDescription(
        key="neuralx",
        name="Neural:X",
        field="b_neuralx",
        setter="set_neuralx",
    ),
    LGSoundbarSwitchDescription(
        key="night_mode",
        name="Night mode",
        field="b_night_time",
        setter="set_night_mode",
    ),
    LGSoundbarSwitchDescription(
        key="auto_volume",
        name="Auto volume",
        field="b_auto_vol",
        setter="set_avc",
    ),
    LGSoundbarSwitchDescription(
        key="auto_power",
        name="Auto power",
        field="b_auto_power",
        setter="set_auto_power",
    ),
    LGSoundbarSwitchDescription(
        key="tv_remote",
        name="TV remote control",
        field="b_tv_remote",
        setter="set_tv_remote",
    ),
    LGSoundbarSwitchDescription(
        key="rear_speaker",
        name="Rear speakers",
        field="b_rear",
        setter="set_rear_control",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LGSoundbarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a switch for each setting this unit reports."""
    device = entry.runtime_data
    async_add_entities(
        LGSoundbarSwitch(device, entry.entry_id, description)
        for description in SWITCHES
        if isinstance(device.setting.get(description.field), bool)
    )


class LGSoundbarSwitch(LGSoundbarEntity, SwitchEntity):
    """One boolean setting on the speaker."""

    entity_description: LGSoundbarSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        device: LGSoundbarDevice,
        unique_id: str,
        description: LGSoundbarSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(device, unique_id)
        self.entity_description = description
        self._attr_unique_id = f"{unique_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Whether the setting is enabled."""
        return self.device.setting_bool(self.entity_description.field)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the setting."""
        await self.device.async_call(self.entity_description.setter, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the setting."""
        await self.device.async_call(self.entity_description.setter, False)
