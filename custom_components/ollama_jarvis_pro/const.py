"""Costanti per Ollama Jarvis Pro."""

DOMAIN = "ollama_jarvis_pro"

# --- Chiavi configurazione (compatibili con la v1) ---
CONF_TITLE = "title"
CONF_URL = "url"
CONF_MODEL = "model"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_MAX_DEVICES = "max_devices"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_KEEP_ALIVE = "keep_alive"
# Nuove in v2
CONF_NUM_CTX = "num_ctx"
CONF_NUM_THREAD = "num_thread"
CONF_LOCAL_FIRST = "local_first"
CONF_HISTORY_TURNS = "history_turns"
CONF_INCLUDE_SENSORS = "include_sensors"
CONF_DISABLE_THINKING = "disable_thinking"
CONF_TIMEOUT = "timeout"
CONF_WARMUP = "warmup"

# --- Default ---
DEFAULT_TITLE = "Ollama Jarvis"
DEFAULT_URL = "http://192.168.1.10:11434"
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_MAX_TOKENS = 160  # una tool call sta in ~50 token
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_DEVICES = 80
DEFAULT_SYSTEM_PROMPT = "Sei Jarvis, l'assistente domotico di casa. Rispondi in italiano, breve."
DEFAULT_KEEP_ALIVE = -1  # minuti, -1 = sempre in RAM
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_THREAD = 0  # 0 = decide Ollama
DEFAULT_LOCAL_FIRST = True
DEFAULT_HISTORY_TURNS = 2
DEFAULT_INCLUDE_SENSORS = True
DEFAULT_DISABLE_THINKING = True
DEFAULT_TIMEOUT = 60  # secondi
DEFAULT_WARMUP = True

# Domini comandabili (in ordine di priorità nella lista). Serrature e allarmi
# sono esclusi di proposito: un LLM non deve poterli aprire/disarmare.
CONTROL_DOMAINS = (
    "light",
    "switch",
    "cover",
    "climate",
    "fan",
    "scene",
    "script",
    "input_boolean",
    "media_player",
    "humidifier",
    "valve",
)
# Domini solo lettura (usati per rispondere alle domande)
READ_DOMAINS = ("sensor", "binary_sensor", "weather")

SERVICE_TIMEOUT = 8  # secondi per singola chiamata servizio
HISTORY_TTL = 300  # secondi: dopo 5 minuti di silenzio la conversazione riparte
MAX_RELEVANT_STATES = 8
