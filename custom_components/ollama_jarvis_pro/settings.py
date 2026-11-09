"""Lettura impostazioni: options > data > default, con tipi corretti."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

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
    CONF_URL,
    CONF_WARMUP,
    DEFAULT_DISABLE_THINKING,
    DEFAULT_HISTORY_TURNS,
    DEFAULT_INCLUDE_SENSORS,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_LOCAL_FIRST,
    DEFAULT_MAX_DEVICES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_THREAD,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DEFAULT_WARMUP,
)

DEFAULTS: dict[str, Any] = {
    CONF_URL: DEFAULT_URL,
    CONF_MODEL: DEFAULT_MODEL,
    CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
    CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
    CONF_MAX_DEVICES: DEFAULT_MAX_DEVICES,
    CONF_SYSTEM_PROMPT: DEFAULT_SYSTEM_PROMPT,
    CONF_KEEP_ALIVE: DEFAULT_KEEP_ALIVE,
    CONF_NUM_CTX: DEFAULT_NUM_CTX,
    CONF_NUM_THREAD: DEFAULT_NUM_THREAD,
    CONF_LOCAL_FIRST: DEFAULT_LOCAL_FIRST,
    CONF_HISTORY_TURNS: DEFAULT_HISTORY_TURNS,
    CONF_INCLUDE_SENSORS: DEFAULT_INCLUDE_SENSORS,
    CONF_DISABLE_THINKING: DEFAULT_DISABLE_THINKING,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_WARMUP: DEFAULT_WARMUP,
}

_INT_KEYS = (CONF_MAX_TOKENS, CONF_MAX_DEVICES, CONF_KEEP_ALIVE, CONF_NUM_CTX,
             CONF_NUM_THREAD, CONF_HISTORY_TURNS, CONF_TIMEOUT)


def merge_settings(data: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULTS, **data, **options}
    for key in _INT_KEYS:
        try:
            out[key] = int(float(out[key]))
        except (TypeError, ValueError):
            out[key] = DEFAULTS[key]
    try:
        out[CONF_TEMPERATURE] = float(out[CONF_TEMPERATURE])
    except (TypeError, ValueError):
        out[CONF_TEMPERATURE] = DEFAULT_TEMPERATURE
    out[CONF_URL] = str(out[CONF_URL]).strip().rstrip("/")
    out[CONF_MODEL] = str(out[CONF_MODEL]).strip()
    out[CONF_SYSTEM_PROMPT] = str(out[CONF_SYSTEM_PROMPT] or DEFAULT_SYSTEM_PROMPT)
    out[CONF_MAX_TOKENS] = max(16, out[CONF_MAX_TOKENS])
    out[CONF_MAX_DEVICES] = max(1, out[CONF_MAX_DEVICES])
    out[CONF_NUM_CTX] = max(1024, out[CONF_NUM_CTX])
    out[CONF_TIMEOUT] = max(5, out[CONF_TIMEOUT])
    return out


def get_settings(entry: ConfigEntry) -> dict[str, Any]:
    return merge_settings(dict(entry.data), dict(entry.options))
