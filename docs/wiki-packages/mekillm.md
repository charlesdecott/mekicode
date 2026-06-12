# `packages/mekillm/` — provider LLM généraliste

Provider réutilisable basé sur le SDK `openai`, pointé sur OpenRouter par défaut (compatible
ollama / litellm). Rend une réponse **normalisée** et émet une trace d'observabilité par appel.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
__init__.py  ── expose ──▶ client.LLM / LLMResponse / ToolCall / Usage
     │                     observability (alias « observe »)
     │  complete()  ── singleton paresseux ──▶ LLM.complete()
     ▼
client.py    ── LLM.__init__ ── appelle ──▶ config.resolve()
     │         LLM.complete() ── appelle ──▶ _normalize() ──▶ ToolCall/Usage/LLMResponse
     │         LLM.stream()   ── yield tokens, ──▶ _consume_stream() ──▶ LLMResponse final (réassemblé)
     │                        └─ finally ──▶ observability.emit(CallRecord)  (complete ET stream)
     ▼
observability.py  ── emit() ──▶ logging + _append_jsonl() (JSONL) + _HOOKS
config.py    ── resolve() : args explicites > variables .env > défauts
```

## `config.py` — résolution de la configuration
- `DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"`, `DEFAULT_MODEL = "openai/gpt-4o-mini"` (l.10-11).
- `load_dotenv(override=True)` à l'import (l.8) : charge le `.env` racine.
- `resolve(api_key=None, base_url=None, model=None) -> dict` (l.14) : fusionne par priorité
  **arguments explicites > env > défauts**. Renvoie `{"api_key", "base_url", "model"}`.
- **Variables d'environnement lues** :
  - `OPENROUTER_API_KEY` puis `MEKILLM_API_KEY` (clé)
  - `MEKILLM_BASE_URL` (URL du backend)
  - `MEKILLM_MODEL` (modèle)

Consommé par `client.LLM.__init__`.

## `client.py` — le provider et la normalisation

### Types normalisés (dataclasses, agnostiques du provider)
- `ToolCall{ id, name, arguments }` (l.19) — `arguments` est **déjà un dict** (parsé depuis le JSON
  d'OpenAI ; `{}` si JSON invalide).
- `Usage{ prompt_tokens, completion_tokens, total_tokens }` (l.28) — `0` si le backend n'envoie rien.
- `LLMResponse{ text, tool_calls, finish_reason, usage, message, raw }` (l.37) :
  - `text` : texte assistant (`""` si seulement des `tool_calls`).
  - `tool_calls` : `list[ToolCall]`.
  - `message` : **dict assistant prêt à réinjecter** dans l'historique (format OpenAI).
  - `raw` : réponse SDK brute (échappatoire ; sert aussi à lire `raw.model`).

### Fonctions
- `_message_dict(msg) -> dict` (l.49) : convertit le message assistant du SDK en **dict simple**
  `{"role":"assistant","content":..., "tool_calls":[...]}` (sérialisable, réinjectable au tour suivant).
- `_normalize(resp) -> LLMResponse` (l.64) : extrait `choices[0].message`, parse les `tool_calls`
  (avec repli `{}` sur JSON invalide + warning), tolère `usage=None` → `Usage()`, et assemble le
  `LLMResponse`. **C'est le cœur testé** par le smoke.
- `_consume_stream(chunks) -> générateur` : l'équivalent de `_normalize` pour le **streaming**. Itère
  les chunks SDK, **yield chaque token** de texte au fil de l'eau, **réassemble** les `tool_calls`
  fragmentés (par `index` ; `id`/`name` au 1er fragment, `arguments` concaténés), tracke
  `finish_reason`, et **`return`** le `LLMResponse` final. Robuste multi-backend (gardes `delta`/`index`
  pour ollama/litellm). Testé par le smoke (texte, outil, flux vide, texte+outil).
- `class LLM` (l.96) :
  - `__init__(model, api_key, base_url)` (l.99) : `config.resolve(...)` puis instancie
    `OpenAI(api_key, base_url)`. (Lève `OpenAIError` immédiatement si aucune clé — échec explicite.)
  - `complete(messages, tools=None, system=None, max_tokens=8000, **kwargs) -> LLMResponse` (l.105) :
    1. construit `sent` (insère un message `system` en tête si fourni) ;
    2. n'ajoute `tools` à l'appel **que s'ils sont non vides** (évite `tools=null`) ;
    3. appelle `self._client.chat.completions.create(**params)` puis `_normalize` ;
    4. **`finally`** : émet toujours un `CallRecord` via `observability.emit` (succès comme
       exception — l'exception est re-`raise`d après émission).
  - `stream(messages, tools=None, system=None, max_tokens=8000, **kwargs)` : variante **streaming**.
    Appelle l'API en `stream=True`, **délègue à `_consume_stream` via `yield from`** (re-yield les
    tokens et capture le `LLMResponse` final retourné), même `CallRecord` en `finally` (l'`usage`
    reste `0` en streaming, sans `stream_options`). Consommé par `mekicore.run_agent(stream=True)`.

## `observability.py` — monitor / profile / log
- `log = logging.getLogger("mekillm")` (l.16) — la lib ne configure **aucun** handler (à la charge
  du consommateur).
- `_DEFAULT_LOG = parents[2] / ".logs" / "mekillm.jsonl"` (l.21) : JSONL **à la racine du projet**.
- `CallRecord{ ts, provider, model, latency_ms, prompt_tokens, completion_tokens, total_tokens,
  finish_reason, status, error, n_messages, n_tools, cost_usd }` (l.25) — `cost_usd` reste `None`
  pour l'instant.
- `now_iso()` (l.44) : horodatage ISO 8601 UTC.
- `add_hook(fn)` (l.49) : enregistre `fn(record)` dans `_HOOKS` (appelé après chaque appel).
- `_log_file() -> Path | None` (l.54) : lit `MEKILLM_LOG_FILE` ; chaîne vide ⇒ `None` ⇒ JSONL désactivé.
- `_append_jsonl(record)` (l.60) : crée le dossier au besoin, écrit une ligne JSON.
- `emit(record)` (l.70) : **diffuse vers les 3 canaux** — `log.info` (résumé une ligne), JSONL,
  puis chaque hook (un hook qui lève est loggé en `warning`, sans casser le flux).

## `__init__.py` — API publique
- Ré-exporte `LLM, LLMResponse, ToolCall, Usage` et `observe` (alias d'`observability`).
- `complete(messages, **kwargs)` (l.14) : raccourci via un **singleton `LLM` paresseux** (`_default`),
  pour appeler le LLM sans instancier soi-même.

```python
import mekillm
llm = mekillm.LLM()                          # ou mekillm.complete(messages, ...)
resp = llm.complete(messages, tools=TOOLS)
mekillm.observe.add_hook(lambda r: ...)      # monitoring maison
```

## Relations sortantes
- Consommé par [`mekicore`](mekicore.md) via `mekillm.LLM` (`complete`/`stream`) et les types
  `LLMResponse`/`ToolCall` ; et par [`mekichat`](mekichat.md) (front web), qui utilise `run_agent`.
- Vue d'ensemble du flux : [architecture.md](architecture.md).
