"""Agente di conversazione Jarvis Pro."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import time
from typing import Any

import ollama

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import (
    async_listen_entity_updates,
    async_should_expose,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, MATCH_ALL
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    intent,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

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
    CONF_WARMUP,
    CONTROL_DOMAINS,
    DEFAULT_TITLE,
    DOMAIN,
    HISTORY_TTL,
    MAX_RELEVANT_STATES,
    READ_DOMAINS,
    SERVICE_TIMEOUT,
)
from .core import (
    TOOL_DOMAINS,
    TOOLS,
    EntityIndex,
    EntityInfo,
    ToolCall,
    build_service_call,
    build_system_prompt,
    claims_action,
    clean_text,
    describe_state,
    extract_tool_calls,
    split_targets,
    text,
)
from .settings import get_settings

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Aggiunge l'agente."""
    async_add_entities([JarvisConversationEntity(hass, entry)])


@dataclass(slots=True)
class _Turn:
    user: str
    assistant: str
    ts: float


class JarvisConversationEntity(conversation.ConversationEntity):
    """Agente ibrido: intent locali di HA prima, poi Ollama con prompt in cache."""

    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = get_settings(entry)
        self._attr_name = entry.data.get(CONF_TITLE) or entry.title or DEFAULT_TITLE
        self._attr_unique_id = entry.entry_id
        self._index: EntityIndex | None = None
        self._system_prompt = ""
        self._think_supported = True
        self._history: dict[str, deque[_Turn]] = {}
        self._warmup_debouncer: Debouncer | None = None

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    @property
    def _client(self) -> ollama.AsyncClient:
        return self.entry.runtime_data

    # ------------------------------------------------------------------
    # Ciclo di vita
    # ------------------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._warmup_debouncer = Debouncer(
            self.hass, _LOGGER, cooldown=10, immediate=False, function=self._async_refresh
        )
        self.async_on_remove(self._warmup_debouncer.async_shutdown)

        @callback
        def _changed(*_: Any) -> None:
            self._index = None  # ricostruito alla prossima richiesta
            if self._warmup_debouncer:
                self._warmup_debouncer.async_schedule_call()

        @callback
        def _state_added_or_removed(event_data: Any) -> bool:
            return event_data.get("old_state") is None or event_data.get("new_state") is None

        self.async_on_remove(async_listen_entity_updates(self.hass, conversation.DOMAIN, _changed))
        self.async_on_remove(self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _changed))
        self.async_on_remove(self.hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _changed))
        self.async_on_remove(self.hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _changed))
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, _changed, event_filter=_state_added_or_removed)
        )

        async def _started(_hass: HomeAssistant) -> None:
            await self._async_refresh()

        self.async_on_remove(async_at_started(self.hass, _started))

    async def _async_refresh(self) -> None:
        """Ricostruisce l'indice e precarica modello + prompt nella cache di Ollama."""
        self._ensure_index()
        if not self.settings[CONF_WARMUP]:
            return
        start = time.monotonic()
        try:
            await self._chat(
                [{"role": "system", "content": self._system_prompt}, {"role": "user", "content": "ok"}],
                num_predict=1,
            )
            _LOGGER.debug("Jarvis: warmup completato in %.1fs", time.monotonic() - start)
        except Exception as err:  # noqa: BLE001 - il warmup non deve mai rompere niente
            _LOGGER.debug("Jarvis: warmup non riuscito: %s", err)

    # ------------------------------------------------------------------
    # Indice entità
    # ------------------------------------------------------------------
    @callback
    def _ensure_index(self) -> EntityIndex:
        if self._index is not None:
            return self._index
        s = self.settings
        domains = CONTROL_DOMAINS + (READ_DOMAINS if s[CONF_INCLUDE_SENSORS] else ())
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        infos: list[EntityInfo] = []
        for state in self.hass.states.async_all(domains):
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue
            area_id = None
            aliases: tuple[str, ...] = ()
            if entry := ent_reg.async_get(state.entity_id):
                aliases = tuple(sorted(a for a in entry.aliases if isinstance(a, str) and a.strip()))
                area_id = entry.area_id
                if not area_id and entry.device_id and (dev := dev_reg.async_get(entry.device_id)):
                    area_id = dev.area_id
            area = area_reg.async_get_area(area_id) if area_id else None
            infos.append(EntityInfo(state.entity_id, state.name, area.name if area else None, aliases))

        self._index = EntityIndex(infos, domains, s[CONF_MAX_DEVICES])
        self._system_prompt = build_system_prompt(s[CONF_SYSTEM_PROMPT], self._index)
        est_tokens = len(self._system_prompt) // 3 + 450  # + definizione tool
        if self._index.truncated:
            _LOGGER.warning(
                "Jarvis: %s entità esposte escluse dal limite Max Devices (%s). "
                "Esponi meno sensori o alza il limite",
                self._index.truncated, s[CONF_MAX_DEVICES],
            )
        if est_tokens > s[CONF_NUM_CTX] * 0.7:
            _LOGGER.warning(
                "Jarvis: prompt di circa %s token con num_ctx=%s: alza num_ctx o esponi meno entità",
                est_tokens, s[CONF_NUM_CTX],
            )
        _LOGGER.debug("Jarvis: indice con %s entità, prompt ~%s token", len(self._index), est_tokens)
        return self._index

    # ------------------------------------------------------------------
    # Gestione messaggio
    # ------------------------------------------------------------------
    async def _async_handle_message(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult:
        conv_id = chat_log.conversation_id
        lang = user_input.language

        # 1) Intent locali di HA: istantanei, nessun LLM.
        if self.settings[CONF_LOCAL_FIRST]:
            local = await self._async_try_local(user_input, chat_log)
            if local is not None:
                speech = local.speech.get("plain", {}).get("speech", "") or text(lang, "done")
                self._remember(conv_id, user_input.text, speech)
                return self._result(local, chat_log, speech, user_input)

        # 2) Ollama
        index = self._ensure_index()
        messages: list[dict[str, str]] = [{"role": "system", "content": self._system_prompt}]
        messages += self._history_messages(conv_id)
        messages.append({"role": "user", "content": self._dynamic_user_message(user_input, index)})

        response = intent.IntentResponse(language=lang)
        try:
            message = await self._chat(messages, num_predict=self.settings[CONF_MAX_TOKENS])
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Jarvis: errore Ollama: %s", err)
            speech = text(lang, "error", x=_short(err))
            response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, speech)
            return self._result(response, chat_log, speech, user_input)

        calls = extract_tool_calls(message)
        if calls:
            speech, summary = await self._async_execute(calls, index, user_input.context, lang)
            self._remember(conv_id, user_input.text, summary)
        else:
            speech = clean_text(message.get("content")) or text(lang, "nothing")
            if claims_action(speech):
                _LOGGER.debug("Jarvis: risposta scartata, azione inventata: %s", speech)
                speech = text(lang, "no_action")
            self._remember(conv_id, user_input.text, speech)

        response.async_set_speech(speech)
        return self._result(response, chat_log, speech, user_input)

    async def _async_try_local(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> intent.IntentResponse | None:
        handler = getattr(conversation, "async_handle_intents", None)
        if handler is None:
            return None
        try:
            result = await handler(self.hass, user_input, chat_log)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Jarvis: intent locali non disponibili: %s", err)
            return None
        if result is not None:
            _LOGGER.debug("Jarvis: '%s' gestito da HA senza LLM", user_input.text)
        return result

    def _dynamic_user_message(self, user_input: conversation.ConversationInput, index: EntityIndex) -> str:
        """Unica parte che cambia: va in fondo, così il prefisso resta in cache."""
        area = self._satellite_area(user_input)
        now = dt_util.now()
        ctx = [f"ora {now:%H:%M} {now:%d/%m/%Y}"]
        if area:
            ctx.append(f"stanza di chi parla: {area}")
        states = []
        for info in index.relevant(user_input.text, area, MAX_RELEVANT_STATES):
            if st := self.hass.states.get(info.entity_id):
                states.append(f"{info.entity_id}={describe_state(st.domain, st.state, st.attributes)}")
        if states:
            ctx.append("stati: " + "; ".join(states))
        if user_input.extra_system_prompt:
            ctx.append(user_input.extra_system_prompt.strip())
        return f"{user_input.text}\n[{' | '.join(ctx)}]"

    @callback
    def _satellite_area(self, user_input: conversation.ConversationInput) -> str | None:
        device_id = user_input.device_id
        satellite_id = getattr(user_input, "satellite_id", None)
        if not device_id and satellite_id and (ent := er.async_get(self.hass).async_get(satellite_id)):
            if ent.area_id and (area := ar.async_get(self.hass).async_get_area(ent.area_id)):
                return area.name
            device_id = ent.device_id
        if not device_id or not (dev := dr.async_get(self.hass).async_get(device_id)) or not dev.area_id:
            return None
        area = ar.async_get(self.hass).async_get_area(dev.area_id)
        return area.name if area else None

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------
    async def _chat(self, messages: list[dict[str, str]], num_predict: int) -> Any:
        s = self.settings
        # num_ctx/num_thread devono restare IDENTICI tra le richieste: se cambiano
        # Ollama ricarica il modello e butta la cache.
        options: dict[str, Any] = {
            "num_ctx": s[CONF_NUM_CTX],
            "num_predict": num_predict,
            "temperature": s[CONF_TEMPERATURE],
            "top_p": 0.9,
        }
        if s[CONF_NUM_THREAD] > 0:
            options["num_thread"] = s[CONF_NUM_THREAD]
        keep_alive = s[CONF_KEEP_ALIVE]
        kwargs: dict[str, Any] = {
            "model": s[CONF_MODEL],
            "messages": messages,
            "tools": TOOLS,
            "options": options,
            "keep_alive": -1 if keep_alive < 0 else f"{keep_alive}m",
        }
        if s[CONF_DISABLE_THINKING] and self._think_supported:
            kwargs["think"] = False

        start = time.monotonic()
        async with asyncio.timeout(s[CONF_TIMEOUT]):
            try:
                resp = await self._client.chat(**kwargs)
            except (ollama.ResponseError, TypeError) as err:
                if "think" not in kwargs or "think" not in str(err).lower():
                    raise
                self._think_supported = False
                kwargs.pop("think")
                resp = await self._client.chat(**kwargs)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Jarvis: %.2fs totali | load %.2fs | prompt %s token in %.2fs | risposta %s token in %.2fs",
                time.monotonic() - start,
                (resp.get("load_duration") or 0) / 1e9,
                resp.get("prompt_eval_count"),
                (resp.get("prompt_eval_duration") or 0) / 1e9,
                resp.get("eval_count"),
                (resp.get("eval_duration") or 0) / 1e9,
            )
        return resp.get("message") or {}

    # ------------------------------------------------------------------
    # Esecuzione tool
    # ------------------------------------------------------------------
    async def _async_execute(
        self, calls: list[ToolCall], index: EntityIndex, context: Context, lang: str
    ) -> tuple[str, str]:
        jobs: dict[tuple[str, str, str], tuple[str, str, dict[str, Any]]] = {}
        missing: list[str] = []
        invalid: list[str] = []

        for call in calls:
            domains = TOOL_DOMAINS.get(call.name)
            if domains is None:
                invalid.append(call.name)
                continue
            targets = split_targets(call.args)
            if not targets:
                invalid.append(call.name)
                continue
            for raw in targets:
                info = index.resolve(raw, domains)
                if info is None:
                    missing.append(raw)
                    continue
                st = self.hass.states.get(info.entity_id)
                try:
                    svc = build_service_call(call, info, st.attributes if st else {})
                except ValueError as err:
                    invalid.append(f"{info.name}: {err}")
                    continue
                jobs[(svc[0], svc[1], info.entity_id)] = svc

        _LOGGER.debug("Jarvis tool: %s -> %s", [(c.name, c.args) for c in calls], list(jobs))

        results = await asyncio.gather(
            *(self._async_call_service(d, s, data, context) for d, s, data in jobs.values()),
            return_exceptions=True,
        )
        done = [eid for (_, _, eid), r in zip(jobs, results, strict=True) if not isinstance(r, Exception)]
        failed = [_short(r) for r in results if isinstance(r, Exception)]
        failed += invalid

        if done and not missing and not failed:
            speech = text(lang, "done")
        elif done:
            speech = text(lang, "partial", x=", ".join(missing + failed))
        elif missing and not failed:
            speech = text(lang, "notfound", x=", ".join(missing))
        elif failed:
            speech = text(lang, "failed", x=", ".join(failed[:2]))
        else:
            speech = text(lang, "nothing")

        actions = "; ".join(f"{svc} {data.get('entity_id')}" for _, svc, data in jobs.values())
        summary = f"{speech} [{actions}]" if actions else speech
        return speech, summary

    async def _async_call_service(self, domain: str, service: str, data: dict[str, Any], context: Context) -> None:
        try:
            async with asyncio.timeout(SERVICE_TIMEOUT):
                await self.hass.services.async_call(domain, service, data, blocking=True, context=context)
        except TimeoutError:
            # Il comando è partito, il dispositivo è solo lento a confermare.
            _LOGGER.warning("Jarvis: %s.%s su %s lento a rispondere", domain, service, data.get("entity_id"))

    # ------------------------------------------------------------------
    # Cronologia breve (per "spegnila", "e anche in camera")
    # ------------------------------------------------------------------
    def _history_messages(self, conv_id: str) -> list[dict[str, str]]:
        turns = self._history.get(conv_id)
        if not turns:
            return []
        now = time.monotonic()
        if now - turns[-1].ts > HISTORY_TTL:
            self._history.pop(conv_id, None)
            return []
        out: list[dict[str, str]] = []
        for t in turns:
            out.append({"role": "user", "content": t.user})
            out.append({"role": "assistant", "content": t.assistant})
        return out

    def _remember(self, conv_id: str, user: str, assistant: str) -> None:
        n = self.settings[CONF_HISTORY_TURNS]
        if n <= 0:
            return
        now = time.monotonic()
        # pulizia conversazioni vecchie
        for key in [k for k, v in self._history.items() if v and now - v[-1].ts > HISTORY_TTL]:
            self._history.pop(key, None)
        self._history.setdefault(conv_id, deque(maxlen=n)).append(_Turn(user, assistant, now))

    # ------------------------------------------------------------------
    @callback
    def _result(
        self,
        response: intent.IntentResponse,
        chat_log: conversation.ChatLog,
        speech: str,
        user_input: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        return conversation.ConversationResult(
            response=response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=chat_log.continue_conversation,
        )


def _short(err: Any) -> str:
    msg = str(err).strip() or type(err).__name__
    return msg if len(msg) <= 80 else msg[:77] + "..."
