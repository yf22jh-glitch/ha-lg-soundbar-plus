"""Config flow for LG Soundbar Plus."""

from __future__ import annotations

import socket
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from .const import DEFAULT_PORT, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


def _probe(host: str, port: int) -> None:
    """Open a plain TCP connection to check the speaker is listening.

    A full protocol handshake is deliberately avoided: any request wakes the
    speaker up, and doing that just to validate a form is rude.
    """
    with socket.create_connection((host, port), timeout=5):
        pass


class LGSoundbarPlusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup dialog."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the speaker's address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # These speakers do not report a stable identifier: PRODUCT_INFO
            # omits s_uuid and MAC_INFO_DEV goes unanswered on at least the
            # SN series, so the address is the only thing to key on.
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(_probe, host, port)
            except OSError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=host, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
