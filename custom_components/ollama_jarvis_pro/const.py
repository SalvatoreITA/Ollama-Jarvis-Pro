"""Costanti per Ollama Jarvis Pro."""

DOMAIN = "ollama_jarvis_pro"

# Chiavi configurazione
CONF_TITLE = "title"  # <--- Nome personalizzato (es. Jarvis)
CONF_URL = "url"
CONF_MODEL = "model"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_MAX_DEVICES = "max_devices"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_KEEP_ALIVE = "keep_alive"

# Default
DEFAULT_TITLE = "Ollama Jarvis"
DEFAULT_URL = "http://192.168.1.236:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_DEVICES = 60
DEFAULT_SYSTEM_PROMPT = "Sei un assistente domotico. Rispondi in italiano."
DEFAULT_KEEP_ALIVE = -1  # <--- NUOVO (5 minuti default)
