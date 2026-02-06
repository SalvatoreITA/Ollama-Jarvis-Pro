"""Init semplice."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Carica l'integrazione."""
    await hass.config_entries.async_forward_entry_setups(entry, ["conversation"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica l'integrazione."""
    return await hass.config_entries.async_unload_platforms(entry, ["conversation"])
