"""Logica pura di Jarvis Pro (nessun import di Home Assistant: testabile da sola).

- Indice delle entità esposte -> blocco di prompt STATICO (sfrutta la cache KV di Ollama)
- Risoluzione tollerante degli entity_id restituiti dal modello (solo entità esposte)
- Selezione degli stati rilevanti per la frase (prompt dinamico minimo)
- Estrazione delle tool call (anche quando i modelli piccoli le scrivono nel testo)
- Traduzione tool -> chiamata di servizio HA, con validazione argomenti
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import difflib
import json
import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------------------
# Normalizzazione testo
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """
    il lo la le gli una uno della dello delle degli dei del nella nello nelle negli
    nel sul sulla sulle sugli dal dalla dalle dagli con per tra fra che chi cosa come
    quanto quanta quanti quante quale quali sono sei siamo hai abbiamo era tutto tutta
    tutti tutte anche ancora poi adesso ora subito per favore grazie please
    accendi spegni accendere spegnere metti imposta alza abbassa apri chiudi attiva
    disattiva dimmi qual quanti fammi puoi potresti vorrei voglio casa
    the and for with what how turn set open close please
    """.split()
)


def normalize(text: str) -> str:
    """Minuscolo, senza accenti, solo [a-z0-9] separati da spazio."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text: str) -> set[str]:
    """Parole significative (>=3 lettere, no stopword)."""
    return {t for t in normalize(text).split() if len(t) >= 3 and t not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Indice entità
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EntityInfo:
    """Entità esposta, come la vede il modello."""

    entity_id: str
    name: str
    area: str | None = None
    aliases: tuple[str, ...] = ()
    domain: str = field(init=False)
    keys: tuple[str, ...] = field(init=False)  # forme normalizzate per il match
    words: frozenset[str] = field(init=False)  # parole per la rilevanza

    def __post_init__(self) -> None:
        self.domain = self.entity_id.split(".", 1)[0]
        object_id = self.entity_id.split(".", 1)[1]
        keys = [normalize(object_id), normalize(self.name)]
        keys += [normalize(a) for a in self.aliases]
        if self.area:
            keys.append(normalize(f"{self.name} {self.area}"))
        self.keys = tuple(dict.fromkeys(k for k in keys if k))
        words = tokens(f"{self.name} {object_id.replace('_', ' ')} {' '.join(self.aliases)}")
        if self.area:
            words |= tokens(self.area)
        self.words = frozenset(words)

    def prompt_line(self) -> str:
        line = f"{self.entity_id}|{self.name.replace('|', '/')}"
        if self.area:
            line += f"|{self.area.replace('|', '/')}"
        if self.aliases:
            line += f"|alias: {', '.join(self.aliases)}"
        return line


class EntityIndex:
    """Elenco deterministico delle entità esposte."""

    def __init__(self, entities: Iterable[EntityInfo], domain_order: Iterable[str], max_devices: int) -> None:
        order = {d: i for i, d in enumerate(domain_order)}
        ordered = sorted(
            entities,
            key=lambda e: (order.get(e.domain, 99), normalize(e.area or "~"), normalize(e.name), e.entity_id),
        )
        self.truncated = max(0, len(ordered) - max_devices)
        self.entities: dict[str, EntityInfo] = {e.entity_id: e for e in ordered[:max_devices]}
        # Il blocco è identico finché non cambiano le entità -> prefisso in cache.
        self.prompt_block = "\n".join(e.prompt_line() for e in self.entities.values())

    def __len__(self) -> int:
        return len(self.entities)

    # ---- risoluzione ----------------------------------------------------
    def resolve(self, raw: Any, allowed_domains: Iterable[str]) -> EntityInfo | None:
        """Trova l'entità indicata dal modello. Mai fuori dalle entità esposte."""
        if not isinstance(raw, str) or not raw.strip():
            return None
        allowed = set(allowed_domains)
        raw = raw.strip().strip("'\"` ")

        if (info := self.entities.get(raw.lower())) is not None:
            return info if info.domain in allowed else None

        candidates = [e for e in self.entities.values() if e.domain in allowed]
        if not candidates:
            return None

        wanted_domain, _, rest = raw.partition(".")
        query = normalize(rest if rest and wanted_domain.lower() in allowed else raw)
        if not query:
            return None
        if rest and wanted_domain.lower() in allowed:
            same = [e for e in candidates if e.domain == wanted_domain.lower()]
            candidates = same or candidates

        # 1) match esatto su id/nome/alias
        exact = [e for e in candidates if query in e.keys]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None  # ambiguo: meglio non fare niente che fare la cosa sbagliata

        # 2) fuzzy, solo se il migliore è chiaramente il migliore
        best: list[tuple[float, EntityInfo]] = []
        for e in candidates:
            score = max(difflib.SequenceMatcher(None, query, k).ratio() for k in e.keys)
            best.append((score, e))
        best.sort(key=lambda x: x[0], reverse=True)
        top_score, top = best[0]
        if top_score < 0.82:
            return None
        if len(best) > 1 and best[1][0] > top_score - 0.04 and best[1][1] is not top:
            return None
        return top

    # ---- rilevanza ------------------------------------------------------
    def relevant(self, text: str, area: str | None = None, limit: int = 8) -> list[EntityInfo]:
        """Entità citate nella frase (per allegare solo gli stati che servono)."""
        words = tokens(text)
        if not words:
            return []
        area_n = normalize(area) if area else None
        scored: list[tuple[float, int, EntityInfo]] = []
        for pos, e in enumerate(self.entities.values()):
            score = float(len(words & e.words))
            if score <= 0:
                continue
            if area_n and e.area and normalize(e.area) == area_n:
                score += 0.5
            scored.append((score, -pos, e))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [e for _, _, e in scored[:limit]]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

RULES_IT = """REGOLE:
- Per un comando chiama SUBITO il tool giusto, senza scrivere testo.
- Usa SOLO entity_id della lista DISPOSITIVI. Più dispositivi: separa gli id con la virgola.
- set_temperature vuole solo un numero; set_hvac_mode solo una modalità.
- Per una domanda rispondi in massimo 2 frasi usando gli stati tra [ ].
- Se l'utente chiacchiera o saluta rispondi con una frase breve e NON chiamare tool.
- Non dire MAI di aver acceso, spento o cambiato qualcosa se non hai chiamato un tool.
- Se il dispositivo non c'è nella lista, dillo. Non inventare.

ESEMPI:
utente: ciao, che fai? -> testo: "Sono qui, dimmi pure cosa ti serve."
utente: accendi la luce della cucina -> tool turn_on(entity_id=<id luce cucina>)
utente: quanti gradi ci sono fuori? -> testo con il valore preso dagli stati tra [ ]"""


def build_system_prompt(base_prompt: str, index: EntityIndex) -> str:
    """Prompt di sistema statico: niente orari, niente stati -> cache sempre valida."""
    return (
        f"{base_prompt.strip()}\n\n{RULES_IT}\n\n"
        f"DISPOSITIVI (entity_id|nome|stanza):\n{index.prompt_block or '(nessuno esposto)'}"
    )


def describe_state(domain: str, state: str, attrs: Mapping[str, Any]) -> str:
    """Stato compatto per il prompt dinamico."""
    out = state
    if unit := attrs.get("unit_of_measurement"):
        out = f"{out} {unit}"
    if domain == "light" and state == "on" and attrs.get("brightness") is not None:
        out += f" {round(int(attrs['brightness']) / 2.55)}%"
    elif domain == "cover" and attrs.get("current_position") is not None:
        out += f" {attrs['current_position']}%"
    elif domain == "climate":
        if attrs.get("current_temperature") is not None:
            out += f" attuale {attrs['current_temperature']}°"
        if attrs.get("temperature") is not None:
            out += f" impostata {attrs['temperature']}°"
    elif domain == "media_player" and attrs.get("media_title"):
        out += f" ({attrs['media_title']})"
    elif domain == "weather" and attrs.get("temperature") is not None:
        out += f" {attrs['temperature']}°"
    return out


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def clean_text(text: str | None) -> str:
    """Toglie ragionamenti e markdown inutile per il TTS."""
    if not text:
        return ""
    text = _THINK_RE.sub("", text)
    text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.S)
    text = text.replace("**", "").replace("__", "").strip()
    return text


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

_ON_DOMAINS = (
    "light", "switch", "fan", "cover", "climate", "scene", "script",
    "input_boolean", "media_player", "humidifier", "valve",
)
_OFF_DOMAINS = tuple(d for d in _ON_DOMAINS if d != "scene")

TOOL_DOMAINS: dict[str, tuple[str, ...]] = {
    "turn_on": _ON_DOMAINS,
    "turn_off": _OFF_DOMAINS,
    "set_light": ("light",),
    "set_cover": ("cover",),
    "set_temperature": ("climate",),
    "set_hvac_mode": ("climate",),
}

_ID = {"type": "string", "description": "entity_id, più id separati da virgola"}

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "turn_on",
        "description": "Accende/attiva: luci, prese, ventole, scene, script, tapparelle (apre).",
        "parameters": {"type": "object", "properties": {"entity_id": _ID}, "required": ["entity_id"]}}},
    {"type": "function", "function": {
        "name": "turn_off",
        "description": "Spegne/disattiva.",
        "parameters": {"type": "object", "properties": {"entity_id": _ID}, "required": ["entity_id"]}}},
    {"type": "function", "function": {
        "name": "set_light",
        "description": "Luminosità (0-100) e/o colore di una luce.",
        "parameters": {"type": "object", "properties": {
            "entity_id": _ID,
            "brightness": {"type": "integer", "description": "0-100"},
            "color": {"type": "string", "description": "es. rosso, blu, bianco caldo"}},
            "required": ["entity_id"]}}},
    {"type": "function", "function": {
        "name": "set_cover",
        "description": "Tapparelle/tende: apri, chiudi, ferma o posizione 0-100.",
        "parameters": {"type": "object", "properties": {
            "entity_id": _ID,
            "action": {"type": "string", "enum": ["open", "close", "stop"]},
            "position": {"type": "integer", "description": "0-100"}},
            "required": ["entity_id"]}}},
    {"type": "function", "function": {
        "name": "set_temperature",
        "description": "Temperatura del clima in gradi. Solo numeri.",
        "parameters": {"type": "object", "properties": {
            "entity_id": _ID, "temperature": {"type": "number"}},
            "required": ["entity_id", "temperature"]}}},
    {"type": "function", "function": {
        "name": "set_hvac_mode",
        "description": "Modalità clima.",
        "parameters": {"type": "object", "properties": {
            "entity_id": _ID,
            "hvac_mode": {"type": "string", "enum": ["heat", "cool", "auto", "heat_cool", "dry", "fan_only", "off"]}},
            "required": ["entity_id", "hvac_mode"]}}},
]

_TOOL_ALIASES = {
    "accendi": "turn_on", "spegni": "turn_off", "on": "turn_on", "off": "turn_off",
    "light_turn_on": "turn_on", "light_turn_off": "turn_off", "homeassistant.turn_on": "turn_on",
    "homeassistant.turn_off": "turn_off", "set_brightness": "set_light", "open_cover": "set_cover",
    "close_cover": "set_cover", "set_cover_position": "set_cover", "climate.set_temperature": "set_temperature",
}


@dataclass(slots=True)
class ToolCall:
    name: str
    args: dict[str, Any]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    getter = getattr(obj, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(obj, key, default)


def _coerce_call(name: Any, args: Any) -> ToolCall | None:
    if not isinstance(name, str):
        return None
    name = name.strip()
    name = _TOOL_ALIASES.get(name, name)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, Mapping):
        args = {}
    args = dict(args)
    if name == "set_cover" and "action" not in args and "position" not in args:
        args["action"] = "open"
    return ToolCall(name, args)


_TOOLCALL_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def extract_tool_calls(message: Any) -> list[ToolCall]:
    """Tool call native, oppure JSON scritto nel testo (capita coi modelli 1-3B)."""
    calls: list[ToolCall] = []
    for tc in _get(message, "tool_calls") or []:
        fn = _get(tc, "function")
        call = _coerce_call(_get(fn, "name"), _get(fn, "arguments"))
        if call:
            calls.append(call)
    if calls:
        return calls

    content = _THINK_RE.sub("", _get(message, "content") or "").strip()
    if not content:
        return []
    chunks = _TOOLCALL_TAG_RE.findall(content)
    if not chunks:
        stripped = content.strip("` \n")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        if stripped[:1] in "{[":
            chunks = [stripped]
    for chunk in chunks:
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, Mapping):
                continue
            fn = item.get("function", item)
            call = _coerce_call(fn.get("name"), fn.get("arguments", fn.get("parameters", {})))
            if call and call.name in TOOL_DOMAINS:
                calls.append(call)
    return calls


def split_targets(args: Mapping[str, Any]) -> list[str]:
    raw = args.get("entity_id", args.get("entity_ids", args.get("name")))
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out += [p.strip() for p in re.split(r"[,;]", item) if p.strip()]
    return list(dict.fromkeys(out))


_COLORS = {
    "rosso": "red", "verde": "green", "blu": "blue", "azzurro": "lightblue", "giallo": "yellow",
    "arancione": "orange", "viola": "purple", "rosa": "pink", "bianco": "white", "ciano": "cyan",
    "magenta": "magenta", "fucsia": "fuchsia", "oro": "gold", "turchese": "turquoise",
}


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("numero non valido")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:[.,]\d+)?", value)
        if m:
            return float(m.group().replace(",", "."))
    raise ValueError(f"numero non valido: {value!r}")


def build_service_call(
    call: ToolCall, info: EntityInfo, attrs: Mapping[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    """(dominio, servizio, dati). Solleva ValueError se gli argomenti non vanno."""
    eid = info.entity_id
    d = info.domain
    a = call.args

    if call.name in ("turn_on", "turn_off"):
        on = call.name == "turn_on"
        if d == "cover":
            return "cover", "open_cover" if on else "close_cover", {"entity_id": eid}
        if d == "valve":
            return "valve", "open_valve" if on else "close_valve", {"entity_id": eid}
        if d in ("scene", "script") and on:
            return d, "turn_on", {"entity_id": eid}
        return "homeassistant", "turn_on" if on else "turn_off", {"entity_id": eid}

    if call.name == "set_light":
        data: dict[str, Any] = {"entity_id": eid}
        if a.get("brightness") is not None:
            pct = max(0, min(100, round(_number(a["brightness"]))))
            if pct == 0:
                return "light", "turn_off", {"entity_id": eid}
            data["brightness_pct"] = pct
        if color := a.get("color"):
            c = normalize(str(color))
            if "caldo" in c or "warm" in c:
                data["color_temp_kelvin"] = 2700
            elif "freddo" in c or "cold" in c or "cool" in c:
                data["color_temp_kelvin"] = 6000
            else:
                first = c.split()[0] if c else c
                data["color_name"] = _COLORS.get(first, first)
        return "light", "turn_on", data

    if call.name == "set_cover":
        if a.get("position") is not None:
            pos = max(0, min(100, round(_number(a["position"]))))
            return "cover", "set_cover_position", {"entity_id": eid, "position": pos}
        action = str(a.get("action", "open")).lower()
        service = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover",
                   "apri": "open_cover", "chiudi": "close_cover", "ferma": "stop_cover"}.get(action)
        if not service:
            raise ValueError(f"azione tapparella non valida: {action}")
        return "cover", service, {"entity_id": eid}

    if call.name == "set_temperature":
        temp = _number(a.get("temperature"))
        lo, hi = attrs.get("min_temp", 5), attrs.get("max_temp", 35)
        if not lo <= temp <= hi:
            raise ValueError(f"temperatura fuori range ({lo}-{hi})")
        return "climate", "set_temperature", {"entity_id": eid, "temperature": temp}

    if call.name == "set_hvac_mode":
        mode = str(a.get("hvac_mode", "")).lower().strip()
        mode = {"caldo": "heat", "riscaldamento": "heat", "freddo": "cool", "raffrescamento": "cool",
                "spento": "off", "automatico": "auto", "deumidifica": "dry"}.get(mode, mode)
        supported = attrs.get("hvac_modes")
        if supported and mode not in supported:
            raise ValueError(f"modalità {mode} non supportata")
        return "climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": mode}

    raise ValueError(f"tool sconosciuto: {call.name}")


# ---------------------------------------------------------------------------
# Frasi di risposta
# ---------------------------------------------------------------------------

_TEXTS = {
    "it": {"done": "Fatto.", "partial": "Fatto, ma non ho trovato: {x}.", "notfound": "Non ho trovato: {x}.",
           "failed": "Non ci sono riuscito: {x}.", "nothing": "Non ho capito, puoi ripetere?",
           "error": "Ollama non risponde: {x}",
           "no_action": "Non ho eseguito nessun comando. Dimmi cosa vuoi accendere, spegnere o regolare."},
    "en": {"done": "Done.", "partial": "Done, but I couldn't find: {x}.", "notfound": "I couldn't find: {x}.",
           "failed": "That didn't work: {x}.", "nothing": "Sorry, can you repeat?",
           "error": "Ollama is not responding: {x}",
           "no_action": "I didn't run any command. Tell me what to turn on, off or adjust."},
}


_CLAIM_RE = re.compile(
    r"\b(ho|abbiamo|sono|e stat[oa]|sono stat[ei])\s+(gia\s+|appena\s+)?"
    r"(acces|spent|attivat|disattivat|apert|chius|impostat|alzat|abbassat|regolat|avviat|fermat|mess)"
    r"|\bi(\s+have|'ve)?\s+(turned|switched|set|opened|closed|activated|started)\b",
)


def claims_action(reply: str) -> bool:
    """Il modello dice di aver fatto qualcosa senza aver chiamato tool (allucinazione)."""
    return bool(_CLAIM_RE.search(normalize(reply).replace(" ve ", "'ve ")))


def text(language: str | None, key: str, **kw: Any) -> str:
    lang = "en" if (language or "").lower().startswith("en") else "it"
    return _TEXTS[lang][key].format(**kw)
