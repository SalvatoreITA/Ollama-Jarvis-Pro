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
    """L'entità IBRIDA."""

    def __init__(self, entry, hass):
        self.entry = entry
        self.hass = hass
        self._attr_name = self.entry.data.get(CONF_TITLE, DEFAULT_TITLE)
        self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
        self._client = None

    @property
    def supported_languages(self) -> list[str]:
        return ["it", "en"]

    async def async_process(self, user_input: conversation.ConversationInput) -> conversation.ConversationResult:
        """Processa l'input utente."""

        # ---------------------------------------------------------
        # FASE 1: TENTATIVO CON HOME ASSISTANT NATIVO
        # ---------------------------------------------------------
        try:
            # FIX 1: Rimosso 'await', async_get_agent non è asincrona
            native_agent = conversation.async_get_agent(self.hass, "homeassistant")

            if native_agent is not None:
                native_result = await native_agent.async_process(user_input)

                # FIX 2: IL CONTROLLO GIUSTO
                # Non controlliamo .intent (che a volte è vuoto), ma controlliamo l'errore.
                # Se NON c'è l'errore "no_intent_recognized", vuol dire che HA ha capito!
                if native_result.response.error_code != intent.IntentResponseErrorCode.NO_INTENT_RECOGNIZED:
                    _LOGGER.info(f"Hybrid: HA ha gestito '{user_input.text}'. Blocco Ollama.")
                    return native_result
            else:
                 _LOGGER.debug("Hybrid: Agente nativo non trovato.")

        except Exception as e:
            _LOGGER.warning(f"Hybrid: Errore agente nativo ({e}). Passo a Ollama.")

        # ---------------------------------------------------------
        # FASE 2: OLLAMA (SOLO SE HA NON HA CAPITO NIENTE)
        # ---------------------------------------------------------

        # Se siamo qui, HA non ha fatto nulla. Tocca a Ollama.
        url = self.entry.options.get(CONF_URL, self.entry.data.get(CONF_URL, DEFAULT_URL))
        model = self.entry.options.get(CONF_MODEL, self.entry.data.get(CONF_MODEL, DEFAULT_MODEL))
        max_tokens = self.entry.options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
        temp = self.entry.options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
        base_prompt = self.entry.options.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT)
        max_devices = self.entry.options.get(CONF_MAX_DEVICES, self.entry.data.get(CONF_MAX_DEVICES, DEFAULT_MAX_DEVICES))
        keep_alive_setting = self.entry.options.get(CONF_KEEP_ALIVE, self.entry.data.get(CONF_KEEP_ALIVE, DEFAULT_KEEP_ALIVE))
        keep_alive_val = -1 if keep_alive_setting == -1 else f"{keep_alive_setting}m"

        # Contesto Dispositivi
        device_context = "LISTA DISPOSITIVI:\n"
        count = 0
        all_states = self.hass.states.async_all()

        for state in all_states:
            if count >= max_devices: break
            if state.state in ["unavailable", "unknown"]: continue
            if not async_should_expose(self.hass, "conversation", state.entity_id): continue

            if state.domain in ["light", "switch", "input_boolean", "climate", "sensor"]:
                friendly_name = state.attributes.get("friendly_name", state.entity_id)
                details = f"Stato: {state.state}"
                if state.domain == "climate":
                    curr = state.attributes.get("current_temperature", "N/A")
                    details += f", Temp Attuale: {curr}°C"
                device_context += f"- {friendly_name} (ID: {state.entity_id}) -> {details}\n"
                count += 1

        full_system_prompt = (
            f"{base_prompt}\n\n"
            f"{device_context}\n"
            "REGOLE:\n"
            "1. Agisci SUI DISPOSITIVI usando i TOOLS.\n"
            "2. Non rispondere 'fatto' se non hai chiamato il tool.\n"
        )

        tools = [
            {'type': 'function', 'function': {'name': 'turn_on', 'description': 'Accende', 'parameters': {'type': 'object', 'properties': {'entity_id': {'type': 'string'}}, 'required': ['entity_id']}}},
            {'type': 'function', 'function': {'name': 'turn_off', 'description': 'Spegne', 'parameters': {'type': 'object', 'properties': {'entity_id': {'type': 'string'}}, 'required': ['entity_id']}}},
            {'type': 'function', 'function': {'name': 'set_temperature', 'description': 'Temp', 'parameters': {'type': 'object', 'properties': {'entity_id': {'type': 'string'}, 'temperature': {'type': 'number'}}, 'required': ['entity_id', 'temperature']}}},
             {'type': 'function', 'function': {'name': 'set_hvac_mode', 'description': 'Mode', 'parameters': {'type': 'object', 'properties': {'entity_id': {'type': 'string'}, 'hvac_mode': {'type': 'string', 'enum': ['heat', 'cool', 'auto', 'off']}}, 'required': ['entity_id', 'hvac_mode']}}}
        ]

        # Creazione Client (Thread Safe)
        if self._client is None:
            def _create_client():
                return ollama.AsyncClient(host=url)
            self._client = await self.hass.async_add_executor_job(_create_client)

        messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_input.text}
        ]

        options = {
            "num_predict": max_tokens,
            "temperature": temp,
            "top_p": 0.1,
            "num_ctx": 4096
        }

        intent_response = intent.IntentResponse(language=user_input.language)
        should_continue = True

        try:
            response = await self._client.chat(
                model=model, messages=messages, options=options, tools=tools, keep_alive=keep_alive_val
            )
            message = response['message']

            if message.get('tool_calls'):
                tasks = []
                for tool in message['tool_calls']:
                    fn_name = tool['function']['name']
                    args = tool['function']['arguments']
                    raw_entity = args.get('entity_id')

                    # Gestione target multipli o singoli
                    targets = []
                    if raw_entity:
                        if isinstance(raw_entity, str):
                            targets = [e.strip() for e in raw_entity.split(",")] if "," in raw_entity else [raw_entity]
                        elif isinstance(raw_entity, list):
                            targets = raw_entity

                    if fn_name == 'turn_on':
                        for e in targets: tasks.append(self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": e}))
                    elif fn_name == 'turn_off':
                        for e in targets: tasks.append(self.hass.services.async_call("homeassistant", "turn_off", {"entity_id": e}))
                    elif fn_name == 'set_temperature':
                        val = args.get('temperature')
                        if targets: tasks.append(self.hass.services.async_call("climate", "set_temperature", {"entity_id": targets[0], "temperature": val}))
                    elif fn_name == 'set_hvac_mode':
                        val = args.get('hvac_mode')
                        if targets: tasks.append(self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": targets[0], "hvac_mode": val}))

                if tasks:
                    await asyncio.gather(*tasks)
                    final_text = "Fatto."
                else:
                    final_text = "Nessun dispositivo."
                intent_response.async_set_speech(final_text)

            else:
                content = message['content']
                intent_response.async_set_speech(content)
                if any(w in (user_input.text or "").lower() for w in ["stop", "basta", "grazie"]):
                    should_continue = False

        except Exception as e:
            _LOGGER.error(f"Hybrid Error: {e}")
            intent_response.async_set_speech(f"Errore: {str(e)}")
            should_continue = False

        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id or str(uuid4()),
            continue_conversation=bool(should_continue)
        )
