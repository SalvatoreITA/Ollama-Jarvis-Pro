# Ollama Jarvis Pro

[![it](https://img.shields.io/badge/lang-it-green.svg)](https://github.com/SalvatoreITA/ollama_jarvis_pro/blob/main/README_it.md)
[![en](https://img.shields.io/badge/lang-en-red.svg)](https://github.com/SalvatoreITA/ollama_jarvis_pro/blob/main/README.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![version](https://img.shields.io/badge/version-1.0.0-blue.svg)]()
[![maintainer](https://img.shields.io/badge/maintainer-Salvatore_Lentini_--_DomHouse.it-green.svg)](https://www.domhouse.it)

<div align="center">
  <img src="https://github.com/SalvatoreITA/ollama_jarvis_pro/blob/main/icon.png?raw=true" alt="Logo" width="150">
</div>

## 🇮🇹 Descrizione

**Ollama Jarvis Pro** è un componente personalizzato per **Home Assistant** progettato per integrare l'intelligenza artificiale locale (Ollama) con prestazioni reali da produzione.

A differenza delle integrazioni standard, questo componente è stato riscritto per eliminare la latenza, correggere gli errori di gestione climatica e velocizzare l'esecuzione dei comandi.

## 🚀 Perché scegliere Jarvis Pro?

Questa versione risolve i 4 problemi principali dell'integrazione Ollama classica:

### 1. Zero Latenza (Keep-Alive Configurabile)
Nell'integrazione standard, il modello viene spesso scaricato dalla memoria, causando ritardi di 5-10 secondi al comando successivo.
**Jarvis Pro** introduce un parametro **Keep Alive**:
* Imposta un timer (es. `5` minuti) o **`-1` per mantenere il modello sempre in RAM**.
* **Risultato:** Dopo la prima richiesta, le risposte sono **istantanee**.

### 2. Climate Guard (Anti-Crash)
Gli LLM spesso confondono i comandi numerici ("Metti 20 gradi") con le modalità ("Metti su Caldo"), causando errori API.
**Jarvis Pro** separa logicamente i tools:
* `set_temperature`: Accetta **solo numeri**.
* `set_hvac_mode`: Accetta **solo modalità** (heat, cool, auto, off).
Il sistema istruisce automaticamente il modello per non confonderli mai.

### 3. Modalità Turbo (Esecuzione Parallela)
Invece di accendere le luci una alla volta in sequenza, Jarvis Pro utilizza `asyncio.gather` per inviare tutti i comandi simultaneamente a Home Assistant.
* **Esempio:** "Spegni tutte le luci" -> Tutte le luci si spengono nello stesso istante.

### 4. Mute Mode (Feedback Sintetico)
Basta risposte verbose. Quando Jarvis esegue un'azione fisica (accendere/spegnere), risponde semplicemente **"Ok."**. Se ci sono più azioni, unisce le risposte per evitare ripetizioni fastidiose.

---

## 🚀 Installazione

### Metodo 1: Tramite HACS (Consigliato)
1.  Apri **HACS** nel tuo Home Assistant.
2.  Vai su **Integrazioni** > **Menu (3 puntini in alto a destra)** > **Repository personalizzati**.
3.  Incolla l'URL di questo repository GitHub. 
    https://github.com/SalvatoreITA/ollama_jarvis_pro
4.  Nella categoria seleziona **Integrazione**.
5.  Clicca su **Aggiungi** e poi su **Scarica**.
6.  **Riavvia Home Assistant**.

### Metodo 2: Manuale
1.  Scarica la cartella `custom_components/ollama_jarvis_pro` da questo repository.
2.  Copiala nella cartella `config/custom_components/` del tuo Home Assistant.
3.  Riavvia Home Assistant.

---

## 🛠 Configurazione

Vai su **Impostazioni** -> **Dispositivi e Servizi** -> **Aggiungi Integrazione** -> Cerca **"Ollama Jarvis Pro"**.

### Parametri Disponibili

| Parametro | Descrizione | Default |
| :--- | :--- | :--- |
| **URL** | Indirizzo del server Ollama (es. `http://192.168.1.X:11434`). | `http://...` |
| **Model** | Nome del modello (es. `llama3`, `qwen2.5:1.5b`). Deve essere già scaricato su Ollama (`ollama pull`). | `qwen2.5:1.5b` |
| **Keep Alive (min)** | **Esclusiva Pro:** Minuti di permanenza in RAM. Imposta **-1** per infinito (massima velocità). | `5` |
| **Max Tokens** | Lunghezza massima della risposta generata. | `500` |
| **Temperature** | Creatività del modello. Consigliato basso per comandi domotici precisi. | `0.1` |
| **Max Devices** | Limite massimo di dispositivi da inviare al contesto (per risparmiare token). | `60` |
| **System Prompt** | Istruzioni base per la personalità dell'assistente. | *Vedi sotto* |

---

## 💡 Come Funziona

### 1. Esposizione Dispositivi
Jarvis Pro rispetta la privacy e le impostazioni di Home Assistant. Vede solo i dispositivi che hai deciso di esporre.
* Vai nelle impostazioni di un'entità -> **Assistenti Vocali** -> Attiva **Assist**.

### 2. Logica Prompt
Il componente costruisce dinamicamente il prompt di sistema aggiungendo:
* La lista dei dispositivi con il loro stato attuale.
* Le regole di sicurezza per il clima.
* L'istruzione di usare i Tools per agire sul mondo reale.

### 3. Debug
Se qualcosa non va, controlla i log di Home Assistant. Jarvis Pro logga le chiamate ai tools:
```text
Jarvis Tools: [{'function': {'name': 'turn_on', 'arguments': {'entity_id': 'light.cucina'}}}]
```

## 📋 Requisiti
* Home Assistant 2024.x o superiore.
* Server Ollama funzionante e accessibile dalla rete locale.

## ⚠️ Disclaimer e Scarico di Responsabilità

Questo progetto (**Ollama Jarvis Pro**) è un componente personalizzato ("custom component") sviluppato in modo indipendente e **NON è affiliato, supportato, autorizzato o sponsorizzato da Ollama** né dai suoi creatori. "Ollama" è un marchio registrato dei rispettivi proprietari.

### 1. Nessuna Garanzia
Il software è fornito "così com'è", senza alcuna garanzia esplicita o implicita, inclusa ma non limitata alle garanzie di commerciabilità, idoneità per uno scopo particolare e non violazione. In nessun caso l'autore o i collaboratori saranno responsabili per qualsiasi reclamo, danno o altra responsabilità.

### 2. Utilizzo e Rischi
L'utente si assume la piena responsabilità per l'utilizzo di questo componente. Poiché questo software interagisce con dispositivi fisici (luci, elettrodomestici, termostati):
* **Non utilizzare** questo componente per sistemi critici (es. serrature, sistemi di allarme, controllo accessi).
* L'autore non è responsabile per comportamenti imprevisti dei modelli di intelligenza artificiale (allucinazioni, comandi errati) che potrebbero portare all'accensione o allo spegnimento involontario di dispositivi.
* Si raccomanda di testare sempre il funzionamento in un ambiente controllato prima di un utilizzo esteso.

## ❤️ Crediti
Sviluppato da [Salvatore Lentini - DomHouse.it](https://www.domhouse.it)
