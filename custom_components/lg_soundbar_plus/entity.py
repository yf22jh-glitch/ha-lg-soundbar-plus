"""Shared entity base for LG Soundbar Plus."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import LGSoundbarDevice


class LGSoundbarEntity(Entity):
    """Base entity wired to the device's push updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: LGSoundbarDevice, unique_id: str) -> None:
        """Initialise the entity."""
        self.device = device
        self._base_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=device.name,
            manufacturer="LG",
            model=device.product.get("s_model_name"),
            configuration_url=f"http://{device.host}",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to pushes from the speaker."""
        self.async_on_remove(
            self.device.add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Whether the socket is up."""
        return self.device.available
