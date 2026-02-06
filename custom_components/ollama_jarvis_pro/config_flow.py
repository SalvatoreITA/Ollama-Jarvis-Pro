"""Config flow (Solo Installazione)."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import *

class OllamaJarvisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce l'installazione."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Form di installazione unico."""
        if user_input is not None:
            # Usa il nome scelto dall'utente come titolo dell'integrazione
            return self.async_create_entry(title=user_input[CONF_TITLE], data=user_input)

        # Schema campi
        schema = vol.Schema({
            vol.Required(CONF_TITLE, default=DEFAULT_TITLE): str,
            vol.Required(CONF_URL, default=DEFAULT_URL): str,
            vol.Required(CONF_MODEL, default=DEFAULT_MODEL): str,
            vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): int,

            # NUOVO CAMPO: Inserisci minuti o -1 per infinito
            vol.Optional(CONF_KEEP_ALIVE, default=DEFAULT_KEEP_ALIVE): int,

            vol.Optional(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=1.0, step=0.1, mode="slider")
            ),
            vol.Optional(CONF_MAX_DEVICES, default=DEFAULT_MAX_DEVICES): int,
            vol.Optional(CONF_SYSTEM_PROMPT, default=DEFAULT_SYSTEM_PROMPT): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        })

        return self.async_show_form(step_id="user", data_schema=schema)
