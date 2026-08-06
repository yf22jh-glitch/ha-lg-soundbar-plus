"""The LG Soundbar Plus integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .device import LGSoundbarDevice

type LGSoundbarConfigEntry = ConfigEntry[LGSoundbarDevice]

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: LGSoundbarConfigEntry
) -> bool:
    """Set up LG Soundbar Plus from a config entry."""
    device = LGSoundbarDevice(hass, entry.data[CONF_HOST], entry.data[CONF_PORT])
    try:
        await device.async_setup()
    except OSError as err:
        raise ConfigEntryNotReady(
            f"Could not reach the soundbar at {entry.data[CONF_HOST]}"
        ) from err

    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: LGSoundbarConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
