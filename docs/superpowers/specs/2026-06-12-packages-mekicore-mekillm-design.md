# Spec — `packages/` : mekicore + mekillm

Date : 2026-06-12
Statut : validé (design approuvé), prêt pour plan d'implémentation

## Objectif

Créer un dossier `packages/` contenant deux paquets sœurs, indépendants de `src/` et
`src_scratch/` :

- **mekillm** — un provider LLM généraliste, importable n'importe où, branché sur OpenRouter
  via le SDK `openai` (compatible plus tard avec ollama / litellm-proxy sans changement de
  code), avec une couche d'observabilité de premier plan (monitor / profile / log).
- **mekicore** — un mini-harness = le s01 (perception-action loop) de claude-code-from-scratch
  **adapté** : on retire l'appel Anthropic natif et on branche mekillm à la place.

Aucune modification de `inspiration/` (gitignoré, matériel d'étude) ni de `src_scratch/`.

## Décisions actées (brainstorming)

1. **Transport mekillm** : wrapper du SDK `openai` pointé sur `base_url` OpenRouter.
   Choisi pour la robustesse (tool_calls, streaming, gestion d'erreurs) et parce qu'OpenRouter,
   ollama (`localhost:11434/v1`) et un proxy litellm sont tous compatibles API OpenAI.
2. **Packaging** : import par chemin (comme `src_scratch`), pas de `pyproject.toml` pour l'instant.
   mekicore ajoute `packages/` au `sys.path` pour pouvoir faire `import mekillm`.
3. **Observabilité** : logging standard + JSONL append-only + hook/callback optionnel.
4. **Lingua franca = format OpenAI** (`messages`, `tools:[{type:"function",...}]`, `tool_calls`,
   messages `role:"tool"`). mekicore travaille directement dans ce format ; pas d'abstraction-maison
   de messages.

## Arborescence

```
packages/
├── mekillm/                  # provider LLM généraliste
│   ├── __init__.py           # API publique : LLM, complete(), LLMResponse, ToolCall, Usage, observe
│   ├── client.py             # wrapper SDK openai + normalisation de la réponse
│   ├── observability.py      # CallRecord + logging + JSONL append + registre de hooks
│   └── config.py             # lecture .env (clé, base_url, modèle, provider)
└── mekicore/                 # mini-harness = s01 adapté, branché sur mekillm
    ├── main.py               # REPL + bootstrap sys.path (ajoute packages/ → import mekillm)
    ├── base.py               # agent_loop + dispatch_tools (format OpenAI tool_calls)
    └── tools.py              # run_bash + schéma OpenAI de l'outil + table de dispatch
```

## mekillm — interface publique

```python
import mekillm
llm = mekillm.LLM()                       # lit .env (clé/base_url/modèle) ; surchargeable par args
resp = llm.complete(messages, tools=TOOLS, system="...", max_tokens=8000)

resp.text           # str — texte assistant ("" si seulement des tool_calls)
resp.tool_calls     # list[ToolCall] : champs .id, .name, .arguments (dict déjà parsé depuis le JSON)
resp.finish_reason  # "stop" | "tool_calls" | "length" | ...
resp.usage          # Usage : .prompt_tokens / .completion_tokens / .total_tokens
resp.message        # dict assistant prêt à append à l'historique (role/content/tool_calls)
resp.raw            # réponse SDK brute (échappatoire)
```

- Raccourci module : `mekillm.complete(...)` utilisant un singleton `LLM` paresseux.
- `LLM(model=..., api_key=..., base_url=...)` : tout argument explicite surcharge le `.env`.
- Bascule ollama / autre backend = uniquement `.env` (`MEKILLM_BASE_URL`, `MEKILLM_MODEL`),
  **zéro changement de code**.

### Normalisation

- `ToolCall` : dataclass `{ id: str, name: str, arguments: dict }`. `arguments` est le résultat
  de `json.loads` sur la chaîne d'arguments OpenAI ; en cas de JSON invalide, `arguments={}` et un
  warning est loggé (le record passe quand même).
- `resp.message` est un **dict simple** (pas l'objet pydantic du SDK) pour rester agnostique du
  provider et facilement sérialisable dans l'historique.
- `Usage` tolère un `usage` absent (certains backends ollama ne le renvoient pas) → champs à 0.

## mekillm — observabilité

Chaque appel `complete()` est encapsulé (try/finally autour de l'appel SDK) et produit un
`CallRecord` (dataclass) :

```
ts (ISO 8601, UTC), provider, model, latency_ms,
prompt_tokens, completion_tokens, total_tokens,
finish_reason, status ("ok" | "error"), error (str | None),
n_messages (taille de l'historique envoyé), n_tools (nb d'outils exposés),
cost_usd (optionnel, None pour l'instant)
```

Trois canaux, indépendants et activables séparément :

1. **logging** : logger nommé `mekillm`.
   - `INFO` : résumé une ligne — ex. `model · 1.2s · 540→128 tok · stop`.
   - `DEBUG` : payloads complets (messages envoyés + réponse brute).
   - Aucun `basicConfig` imposé par la lib : c'est au consommateur de configurer le handler.
2. **JSONL** : append-only vers `MEKILLM_LOG_FILE` (défaut `packages/mekillm/.logs/calls.jsonl`).
   - Créé à la volée (dossier inclus). Désactivable (env vide / `None`).
   - Un record = une ligne JSON (le `CallRecord` sérialisé).
3. **hook** : `mekillm.observe.add_hook(fn)` enregistre `fn(record: CallRecord)`, appelé après
   chaque call (succès comme erreur). Plusieurs hooks possibles. Une exception dans un hook est
   loggée (`mekillm` logger) et n'interrompt pas le flux.

`latency_ms` couvre le besoin « profile ». Le coût `$` est laissé best-effort (champ `cost_usd`
à `None` pour l'instant — pas de table de prix codée en dur : YAGNI ; on pourra le remplir plus
tard si OpenRouter renvoie le coût ou via une table optionnelle).

## mekicore — s01 adapté (format OpenAI)

### `tools.py`

- `run_bash(command) -> str` : repris du `core.py` de s01 — `subprocess.run(shell=True)`, timeout
  120 s, sortie tronquée à 50k, garde-fous `_ALWAYS_BLOCK` (`rm -rf /`, `sudo`, fork bomb, …).
- `TOOLS` : liste au **format function-calling OpenAI** :
  `[{"type": "function", "function": {"name": "bash", "description": ..., "parameters": {json schema}}}]`.
- `DISPATCH = {"bash": lambda args: run_bash(args["command"])}`.

### `base.py`

- `dispatch_tools(tool_calls, dispatch) -> list[dict]` : pour chaque `ToolCall`, exécute le handler
  et renvoie un message `{"role": "tool", "tool_call_id": tc.id, "content": str(output)}`. Outil
  inconnu / exception handler → message d'erreur en `content` (jamais de crash). Affichage terminal
  du call et d'un extrait de sortie (esprit s01).
- `agent_loop(messages, llm, tools, dispatch) -> None` : boucle `while True` —
  `resp = llm.complete(messages, tools=tools)` ; `messages.append(resp.message)` ; si
  `resp.finish_reason != "tool_calls"` → `break` ; sinon `messages += dispatch_tools(resp.tool_calls, dispatch)`.

### `main.py`

- Bootstrap : `sys.path.insert(0, <packages/>)` (parent du dossier mekicore) pour rendre
  `import mekillm` résoluble en lancement direct (`python packages/mekicore/main.py`).
- REPL d'esprit s01 : prompt `mekicore >>`, historique `messages` (commence éventuellement par un
  message system), `agent_loop` par requête, affichage de la réponse finale, gestion propre de
  `EOFError` / `KeyboardInterrupt` et des commandes `q`/`exit`/`quit`.
- Instancie `mekillm.LLM()` une fois.

## Config, dépendances & non-régression

- **`requirements.txt`** : ajouter `openai>=1.0` (commentaire fr). `anthropic` reste (utilisé par
  `src/` et `src_scratch/`).
- **`.env.example`** : ajouter
  - `OPENROUTER_API_KEY=` (clé OpenRouter)
  - `MEKILLM_BASE_URL=https://openrouter.ai/api/v1`
  - `MEKILLM_MODEL=openai/gpt-4o-mini` (défaut concret : économique et compatible tool-calling ;
    surchargeable — ex. `anthropic/claude-3.5-sonnet` pour du coding plus exigeant)
  - (optionnel) `MEKILLM_LOG_FILE=`
- **`.gitignore`** : ajouter `packages/mekillm/.logs/`.
- **Vérification** (règle 4 du CLAUDE.md) : `python -m py_compile` sur chaque nouveau fichier `.py`,
  plus un smoke d'import : `import mekillm` et `import mekicore.base` / `import mekicore.tools`
  (sans appel réseau).
- **Wiki** : la règle 1 du CLAUDE.md (skill `wiki-update`) cible `src/` → `wiki-src/` et
  `src_scratch/` → `wiki-src-scratch/` uniquement. `packages/` est une nouvelle arborescence non
  couverte ; **pas** de régénération de wiki dans ce chantier. À signaler à l'utilisateur, libre à
  lui d'étendre la convention plus tard.

## Hors périmètre (YAGNI)

- Streaming (s01 n'en a pas besoin ; `complete()` est synchrone). Pourra être ajouté plus tard.
- Estimation de coût `$` chiffrée (champ présent mais `None`).
- Outils étendus (read/write/grep/glob/revert) : mekicore reste au seul outil `bash` du s01.
- `pyproject.toml` / install pip (import par chemin pour l'instant).
- Backend ollama/litellm effectivement testé (l'architecture le permet via `.env`, mais on ne
  le valide pas dans ce chantier).

## Critères de succès

1. `python packages/mekicore/main.py` lance un REPL qui, avec une clé OpenRouter valide dans `.env`,
   répond et sait exécuter une commande `bash` via tool-calling.
2. `import mekillm` fonctionne depuis n'importe quel script du repo (après bootstrap sys.path) et
   `mekillm.complete(...)` renvoie un `LLMResponse` normalisé.
3. Chaque appel LLM produit un `CallRecord` visible via les trois canaux (log INFO, ligne JSONL,
   hook) ; un hook utilisateur reçoit bien le record.
4. `py_compile` + smoke d'import passent sur tous les fichiers de `packages/`.
