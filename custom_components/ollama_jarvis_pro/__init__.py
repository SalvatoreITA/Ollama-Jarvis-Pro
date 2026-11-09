"""Ollama Jarvis Pro: agente conversazione Ollama veloce per Home Assistant."""

from __future__ import annotations

import asyncio
import logging

import ollama

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_URL
from .settings import get_settings

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]


async def async_create_client(hass: HomeAssistant, url: str) -> ollama.AsyncClient:
    """Crea il client fuori dal loop (httpx carica i certificati in modo bloccante)."""
    return await hass.async_add_executor_job(lambda: ollama.AsyncClient(host=url))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Carica l'integrazione."""
    settings = get_settings(entry)
    client = await async_create_client(hass, settings[CONF_URL])
    try:
        async with asyncio.timeout(10):
            await client.list()
    except Exception as err:
        raise ConfigEntryNotReady(f"Ollama non raggiungibile su {settings[CONF_URL]}: {err}") from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica l'integrazione."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
