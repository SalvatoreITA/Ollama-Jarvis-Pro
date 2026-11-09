"""Config flow + options flow (impostazioni modificabili senza reinstallare)."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import async_create_client
from .const import (
    CONF_DISABLE_THINKING,
    CONF_HISTORY_TURNS,
    CONF_INCLUDE_SENSORS,
    CONF_KEEP_ALIVE,
    CONF_LOCAL_FIRST,
    CONF_MAX_DEVICES,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_NUM_CTX,
    CONF_NUM_THREAD,
    CONF_SYSTEM_PROMPT,
    CONF_TEMPERATURE,
    CONF_TIMEOUT,
    CONF_TITLE,
    CONF_URL,
    CONF_WARMUP,
    DEFAULT_MODEL,
    DEFAULT_TITLE,
    DEFAULT_URL,
    DOMAIN,
)
from .settings import merge_settings


async def _async_list_models(hass: HomeAssistant, url: str) -> list[str]:
    client = await async_create_client(hass, url)
    async with asyncio.timeout(10):
        resp = await client.list()
    models = resp.get("models") or []
    names = [m.get("model") or m.get("name") for m in models]
    return sorted(n for n in names if n)


def _model_known(model: str, models: list[str]) -> bool:
    return model in models or f"{model}:latest" in models


def _int(min_: int, max_: int, step: int = 1, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(min=min_, max=max_, step=step, mode="box")
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


class OllamaJarvisConfigFlow(ConfigFlow, domain=DOMAIN):
    """Installazione: basta URL e modello, il resto si regola dalle opzioni."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            try:
                models = await _async_list_models(self.hass, url)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                if not _model_known(user_input[CONF_MODEL].strip(), models):
                    errors[CONF_MODEL] = "model_not_found"
                else:
                    data = {**user_input, CONF_URL: url}
                    return self.async_create_entry(title=user_input[CONF_TITLE], data=data)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_TITLE, default=defaults.get(CONF_TITLE, DEFAULT_TITLE)): str,
                vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)): str,
                vol.Required(CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_MODEL)): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OllamaJarvisOptionsFlow()


class OllamaJarvisOptionsFlow(OptionsFlow):
    """Tutte le regolazioni di prestazioni."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = merge_settings(dict(self.config_entry.data), dict(self.config_entry.options))
        errors: dict[str, str] = {}
        models: list[str] = []
        try:
            models = await _async_list_models(self.hass, (user_input or current)[CONF_URL])
        except Exception:  # noqa: BLE001
            if user_input is not None:
                errors["base"] = "cannot_connect"

        if user_input is not None and not errors:
            if models and not _model_known(user_input[CONF_MODEL], models):
                errors[CONF_MODEL] = "model_not_found"
            else:
                return self.async_create_entry(data=merge_settings({}, user_input))

        values = {**current, **(user_input or {})}
        model_selector: Any = str
        if models:
            options = list(dict.fromkeys([*models, values[CONF_MODEL]]))
            model_selector = selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, custom_value=True, mode="dropdown")
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=values[CONF_URL]): str,
                vol.Required(CONF_MODEL, default=values[CONF_MODEL]): model_selector,
                vol.Required(CONF_LOCAL_FIRST, default=values[CONF_LOCAL_FIRST]): bool,
                vol.Required(CONF_KEEP_ALIVE, default=values[CONF_KEEP_ALIVE]): _int(-1, 1440, unit="min"),
                vol.Required(CONF_WARMUP, default=values[CONF_WARMUP]): bool,
                vol.Required(CONF_NUM_CTX, default=values[CONF_NUM_CTX]): _int(1024, 32768, 512),
                vol.Required(CONF_NUM_THREAD, default=values[CONF_NUM_THREAD]): _int(0, 64),
                vol.Required(CONF_MAX_TOKENS, default=values[CONF_MAX_TOKENS]): _int(16, 2048),
                vol.Required(CONF_TEMPERATURE, default=values[CONF_TEMPERATURE]): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1, step=0.05, mode="slider")
                ),
                vol.Required(CONF_MAX_DEVICES, default=values[CONF_MAX_DEVICES]): _int(1, 500),
                vol.Required(CONF_INCLUDE_SENSORS, default=values[CONF_INCLUDE_SENSORS]): bool,
                vol.Required(CONF_HISTORY_TURNS, default=values[CONF_HISTORY_TURNS]): _int(0, 10),
                vol.Required(CONF_DISABLE_THINKING, default=values[CONF_DISABLE_THINKING]): bool,
                vol.Required(CONF_TIMEOUT, default=values[CONF_TIMEOUT]): _int(5, 600, unit="s"),
                vol.Required(CONF_SYSTEM_PROMPT, default=values[CONF_SYSTEM_PROMPT]): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
