"""Logica di conversazione per Ollama Jarvis Pro - BASE + TURBO + MUTE + CLIMA FIX + KEEP ALIVE CONFIG."""
import logging
import ollama
import asyncio
from uuid import uuid4
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import intent
from homeassistant.core import HomeAssistant
from .const import *

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Aggiunge l'agente di conversazione."""
    async_add_entities([OllamaJarvisEntity(entry, hass)])

class OllamaJarvisEntity(conversation.ConversationEntity):
    """L'entità che parla con Ollama."""

    def __init__(self, entry, hass):
        self.entry = entry
        self.hass = hass
        self._attr_name = self.entry.data.get(CONF_TITLE, DEFAULT_TITLE)
        self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        self._histories = domain_data.setdefault("histories", {})

    @property
    def supported_languages(self) -> list[str]:
        return ["it", "en"]

    async def async_process(self, user_input: conversation.ConversationInput) -> conversation.ConversationResult:
        # 1. Recupero opzioni
        # Nota: usa .get() annidati per supportare sia la config iniziale che eventuali (future) opzioni
        url = self.entry.options.get(CONF_URL, self.entry.data.get(CONF_URL, DEFAULT_URL))
        model = self.entry.options.get(CONF_MODEL, self.entry.data.get(CONF_MODEL, DEFAULT_MODEL))
        max_tokens = self.entry.options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        temp = self.entry.options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        base_prompt = self.entry.options.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT)
        max_devices = self.entry.options.get(CONF_MAX_DEVICES, self.entry.data.get(CONF_MAX_DEVICES, DEFAULT_MAX_DEVICES))

        # Recupero Keep Alive (default 5 min se non specificato)
        keep_alive_setting = self.entry.options.get(CONF_KEEP_ALIVE, self.entry.data.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE))

        # Logica conversione Keep Alive per Ollama
        # Se è -1 (int), Ollama lo interpreta come infinito.
        # Se è un numero positivo, lo convertiamo in stringa "Nm" (es. "5m").
        if keep_alive_setting == -1:
            keep_alive_val = -1
        else:
            keep_alive_val = f"{keep_alive_setting}m"

        # 2. COSTRUISCE IL CONTESTO DISPOSITIVI
        device_context = "Ecco la lista dei dispositivi con ID e STATO:\n"
        count = 0
        all_states = self.hass.states.async_all()

        for state in all_states:
            if count >= max_devices: break

            if state.state in ["unavailable", "unknown"]: continue

            # Controllo "Esponi"
            if not async_should_expose(self.hass, "conversation", state.entity_id):
                continue

            if state.domain in ["light", "switch", "climate", "sensor", "binary_sensor"]:
                friendly_name = state.attributes.get("friendly_name", state.entity_id)

                details = f"Stato: {state.state}"
                if state.domain == "climate":
                    current_temp = state.attributes.get("current_temperature", "N/A")
                    details += f", Temp Attuale: {current_temp}°C"

                device_context += f"- {friendly_name} (ID: {state.entity_id}) -> {details}\n"
                count += 1

        # PROMPT AGGIORNATO
        full_system_prompt = (
            f"{base_prompt}\n\n"
            f"{device_context}\n"
            "IMPORTANTE: Usa i TOOLS per modificare stato o cambiare temperatura.\n"
            "REGOLE CLIMA:\n"
            "1. Se l'utente dice un NUMERO (es. 20, 21.5), usa 'set_temperature'.\n"
            "2. Se l'utente cambia MODALITÀ (caldo, freddo, auto) SENZA numeri, usa 'set_hvac_mode'."
        )

        # 3. DEFINIZIONE TOOLS
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'turn_on',
                    'description': 'Accende un dispositivo',
                    'parameters': {
                        'type': 'object',
                        'properties': {'entity_id': {'type': 'string'}},
                        'required': ['entity_id'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'turn_off',
                    'description': 'Spegne un dispositivo',
                    'parameters': {
                        'type': 'object',
                        'properties': {'entity_id': {'type': 'string'}},
                        'required': ['entity_id'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'set_hvac_mode',
                    'description': 'Imposta modalità (heat/caldo, cool/freddo, auto, off). NON USARE PER I GRADI.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'entity_id': {'type': 'string'},
                            'mode': {'type': 'string', 'enum': ['heat', 'cool', 'auto', 'off']}
                        },
                        'required': ['entity_id', 'mode'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'set_temperature',
                    'description': 'Imposta la temperatura (Gradi).',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'entity_id': {'type': 'string'},
                            'temperature': {'type': 'number'}
                        },
                        'required': ['entity_id', 'temperature'],
                    },
                },
            },
        ]

        # 4. Configura Client
        client = ollama.AsyncClient(host=url)
        conv_id = user_input.conversation_id or self._histories.get("_last_conv_id") or str(uuid4())
        self._histories["_last_conv_id"] = conv_id
        prev = self._histories.get(conv_id, [])
        messages = [{"role": "system", "content": full_system_prompt}] + prev + [{"role": "user", "content": user_input.text}]
        options = {
            "num_predict": max_tokens,
            "temperature": temp,
            "top_p": 0.1,
            "num_ctx": 4096
        }

        intent_response = intent.IntentResponse(language=user_input.language)

        try:
            # KEEP ALIVE DINAMICO
            response = await client.chat(
                model=model,
                messages=messages,
                options=options,
                tools=tools,
                keep_alive=keep_alive_val
            )
            message = response['message']

            # 5. ESECUZIONE PARALLELA (RISPOSTE BREVI)
            if message.get('tool_calls'):
                _LOGGER.info(f"Jarvis Tools: {message['tool_calls']}")

                tool_outputs = []
                tasks = []

                for tool in message['tool_calls']:
                    fn_name = tool['function']['name']
                    args = tool['function']['arguments']
                    entity_id = args.get('entity_id')

                    # Esecuzione comandi
                    if fn_name == 'turn_on':
                        tasks.append(self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": entity_id}))
                        tool_outputs.append("Ok.")

                    elif fn_name == 'turn_off':
                        tasks.append(self.hass.services.async_call("homeassistant", "turn_off", {"entity_id": entity_id}))
                        tool_outputs.append("Ok.")

                    elif fn_name == 'set_hvac_mode':
                        mode = args.get('mode')
                        tasks.append(self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": mode}))
                        tool_outputs.append("Ok.")

                    elif fn_name == 'set_temperature':
                        temp_val = args.get('temperature')
                        if temp_val is not None:
                            tasks.append(self.hass.services.async_call("climate", "set_temperature", {"entity_id": entity_id, "temperature": temp_val}))
                            tool_outputs.append("Ok.")
                        else:
                            _LOGGER.warning("Jarvis ha provato a settare la temperatura senza numero.")
                            tool_outputs.append("Errore.")

                if tasks:
                    await asyncio.gather(*tasks)

                # Unisce le risposte doppie
                final_text = " ".join(sorted(set(tool_outputs), key=tool_outputs.index))
                intent_response.async_set_speech(final_text)
                new_hist = prev + [{"role": "user", "content": user_input.text}, {"role": "assistant", "content": final_text}]
                self._histories[conv_id] = new_hist[-20:]
                should_continue = final_text.strip().endswith("?")

            else:
                intent_response.async_set_speech(message['content'])
                new_hist = prev + [{"role": "user", "content": user_input.text}, {"role": "assistant", "content": message['content']}]
                self._histories[conv_id] = new_hist[-20:]
                txt = message.get('content', '') or ''
                low = txt.lower()
                follow_triggers = ["vuoi", "preferisci", "posso", "desideri", "ti va", "altro", "cos'altro", "altra", "continuare"]
                should_continue = txt.strip().endswith("?") or any(w in low for w in follow_triggers)

        except Exception as e:
            _LOGGER.error(f"Errore Ollama: {e}")
            intent_response.async_set_speech(f"Errore: {str(e)}")
            should_continue = False

        user_low = (user_input.text or "").lower()
        stop_triggers = ["stop", "basta", "fine", "chiudi", "annulla"]
        if any(w in user_low for w in stop_triggers):
            should_continue = False

        result = conversation.ConversationResult(
            response=intent_response,
            conversation_id=conv_id,
            continue_conversation=bool(should_continue)
        )

        return result
