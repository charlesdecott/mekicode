---
title: "core.py · Le socle commun"
phase: "Socle"
fichier: "inspiration/claude-code-from-scratch/core.py"
lignes: 626
tags: [socle, tools, dispatch, streaming, permissions, snapshots, async]
---

# core.py · Le socle commun

> **En une phrase** : la bibliothèque unique que les 23 sessions importent — client Anthropic configuré, 6 outils synchrones + 5 wrappers async, schémas JSON, 3 tables de dispatch, gouvernance YAML et deux briques de boucle (`dispatch_tools`, `stream_loop`) — pour que chaque `sNN_*.py` ne contienne QUE son mécanisme delta.

## Rôle dans le harness

Le README pose le contrat : *« Every session file imports from core.py. Nothing is duplicated across files. »* Là où learn-claude-code (l'autre repo d'inspiration) est **cumulatif** — chaque session recopie et étend le code de la précédente —, claude-code-from-scratch factorise tout le code récurrent dans ce module. Conséquence directe sur la lecture : ouvrir `s09_agent_teams.py`, c'est lire *uniquement* les mailboxes JSONL ; la boucle, les outils et le client sont ici. Le fichier est la matérialisation du premier principe du harness engineering énoncé par le README : *« The model is the only source of decisions — the harness never branches on model output, it only executes what the model requests. »* `dispatch_tools()` et `stream_loop()` ne contiennent en effet aucun `if` sur le *contenu* des réponses du modèle, seulement sur leur *type* (`tool_use` ou non).

Le module est organisé en couches qui recoupent les trois autres principes du README : les outils (*« Tools are the only interface between the model and the world »*) existent en version synchrone pour les sessions à boucle simple et en version asynchrone pour le runtime `asyncio` de [[s18-parallel-tools]] à [[s21-mcp-runtime]] ; la gouvernance (*« Permissions are declarative, not procedural »*) vit dans `config/permissions.yaml` lu par `load_rules()`, pas dans le code ; et la gestion du contexte est laissée aux sessions ([[s06-context-compact]]) — core.py se contente de plafonner les sorties d'outils (50 000 caractères pour bash/read, 10 000 pour grep, 200 résultats pour glob) pour protéger la fenêtre.

Deux choses à savoir avant de lire : le docstring (ligne 2) annonce `agents/core.py` alors que le fichier vit à la racine du repo — trace d'un ancien emplacement qui a un effet de bord réel sur `_PERM_CONFIG` (voir Pièges) ; et le README affirme *« core.py is 392 lines »* alors que le fichier réel en compte 626 — le module a grossi après la rédaction du README (commentaires ligne à ligne systématiques).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–20 | Docstring module | Inventaire complet des exports, groupe par groupe |
| 22–29 | Imports stdlib | `os`, `re`, `asyncio`, `subprocess`, `glob as _glob`, `pathlib`, `typing` |
| 31–54 | Dépendances optionnelles | `readline` (édition de ligne Unix), `colorama` (ANSI Windows) — les deux en `try/except ImportError` silencieux |
| 56–59 | Imports tiers | `yaml`, `anthropic.Anthropic`, `dotenv.load_dotenv` |
| 61–78 | Configuration | `load_dotenv`, gestion `ANTHROPIC_BASE_URL`, `client`, `MODEL`, `DEFAULT_SYSTEM` |
| 80–96 | État global & sécurité | `SNAPSHOTS` (undo), `_ALWAYS_BLOCK` (blocklist bash) |
| 98–292 | Outils synchrones | `run_bash`, `run_read`, `run_write`, `run_grep`, `run_glob`, `run_revert` |
| 295–350 | Outils asynchrones | `async_bash` (vrai async) + 4 wrappers `run_in_executor` |
| 353–426 | Schémas d'outils | `BASIC_TOOLS` (bash seul), `EXTENDED_TOOLS` (6 outils) |
| 428–452 | Tables de dispatch | `BASIC_DISPATCH`, `EXTENDED_DISPATCH`, `ASYNC_DISPATCH` |
| 454–519 | Gouvernance | `_PERM_CONFIG`, `load_rules()`, `check_permission()` |
| 522–626 | Logique d'agent partagée | `dispatch_tools()`, `stream_loop()` |

## Constantes et configuration

### `client` — ligne 72 (et lignes 61–69)

```python
# Load environment variables from a .env file, allowing local overrides of system vars
load_dotenv(override=True)

# Check if a custom base URL is set (useful for local proxies or specific API gateways)
if os.getenv("ANTHROPIC_BASE_URL"):
    # Remove the standard auth token to prevent conflicts with custom gateways
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# Initialize the global Anthropic client using the base URL from environment
client: Anthropic = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
```

- **Ligne 64** : `load_dotenv(override=True)` — le `.env` du repo *écrase* les variables d'environnement système. Choix inverse du défaut de `python-dotenv` : la config locale du repo prime toujours.
- **Lignes 67–69** : si `ANTHROPIC_BASE_URL` est défini (cas du proxy LiteLLM, option B du README), on purge `ANTHROPIC_AUTH_TOKEN` pour éviter qu'un token Anthropic résiduel ne parte vers un gateway tiers.
- **Ligne 72** : `base_url=None` quand la variable est absente — le SDK retombe alors sur `api.anthropic.com`. Un seul client, construit **à l'import du module**, partagé par toutes les sessions.

### `MODEL` — ligne 75

`os.environ.get("MODEL_ID", "claude-3-5-sonnet-20240620")` : l'ID du modèle vient du `.env` ; le défaut est une version datée de Sonnet 3.5. Avec LiteLLM, `MODEL_ID=my-model` désigne l'alias déclaré dans `litellm_config.yaml`.

### `DEFAULT_SYSTEM` — ligne 78

```python
DEFAULT_SYSTEM: str = f"You are a coding agent at {os.getcwd()}. Use tools to solve tasks. Act, don't explain."
```

Trois informations en une phrase : le rôle, l'ancrage (`os.getcwd()` capturé **à l'import** — un `os.chdir()` ultérieur ne le mettra pas à jour), et la consigne comportementale *« Act, don't explain »* qui pousse le modèle vers les tool calls plutôt que la paraphrase. Les sessions qui veulent un persona spécifique (ex. [[s15-permissions]]) passent leur propre `system` à `stream_loop`.

### `SNAPSHOTS` — ligne 84

```python
SNAPSHOTS: Dict[str, Optional[str]] = {}
```

Registre d'undo en mémoire : chemin → contenu *avant* la dernière écriture, ou `None` si le fichier n'existait pas (alors `revert` = suppression). Rempli par `run_write`, consommé (et vidé) par `run_revert`. C'est l'analogue minimal des *file snapshots* du vrai Claude Code, mis en avant par [[s14-tools-extended]]. Aucune session ne l'importe directement : il vit entièrement derrière les deux fonctions.

### `_ALWAYS_BLOCK` — lignes 89–96

```python
_ALWAYS_BLOCK: List[str] = [
    "rm -rf /",      # Prevent root filesystem deletion
    "sudo",          # Prevent privilege escalation
    "shutdown",      # Prevent system termination
    "reboot",        # Prevent system restart
    "> /dev/",       # Prevent direct hardware or system device writing
    ":(){ :|:& };:"  # Prevent fork bombs
]
```

Blocklist de fragments testée par **sous-chaîne** (`blocked in command`) dans `run_bash` et `async_bash`. C'est un filet grossier, pas une politique : la vraie gouvernance, à motifs regex et à trois niveaux, est dans `check_permission()` ([[s15-permissions]]). Préfixe `_` : non exporté, non listé dans le docstring.

### `_PERM_CONFIG` — ligne 457

```python
_PERM_CONFIG: Path = Path(__file__).parent.parent / "config" / "permissions.yaml"
```

Chemin du fichier de règles. **Attention** : `parent.parent` remonte d'un niveau *au-dessus* du dossier contenant `core.py`. Le docstring (`agents/core.py`) révèle que le fichier était prévu dans un sous-dossier `agents/` ; à la racine du repo cloné, ce chemin pointe **hors du repo** et `config/permissions.yaml` (qui est à la racine) n'est jamais trouvé — voir Pièges.

## Les fonctions, une à une

### `run_bash(command)` — lignes 100–129

L'outil fondamental, identique dans l'esprit au `run_bash` de learn-claude-code.

```python
    # Security check: verify the command doesn't contain blacklisted patterns
    if any(blocked in command for blocked in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    
    try:
        # Execute command in the current working directory using the system shell
        result = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=120
        )
        # Combine standard output and error output, then strip whitespace
        output = (result.stdout + result.stderr).strip()
        # Return output or a placeholder, capped at 50k chars to protect context window
        return output[:50000] if output else "(no output)"
```

- **Lignes 111–112** : la blocklist d'abord, par sous-chaîne — un commande bloquée renvoie une *chaîne* d'erreur au modèle, jamais une exception.
- **Lignes 116–119** : `shell=True` (le modèle peut utiliser pipes et redirections), `timeout=120`, `cwd=os.getcwd()` réévalué à chaque appel (contrairement à `DEFAULT_SYSTEM`).
- **Ligne 121** : stdout et stderr concaténés — le modèle voit les erreurs de compilation comme la sortie normale, dans un seul flux.
- **Ligne 123** : cap à 50 000 caractères et placeholder `"(no output)"` — ne jamais renvoyer du vide ambigu au modèle.
- **Lignes 124–129** : `TimeoutExpired` et `Exception` génériques convertis en `"Error: ..."` — une erreur d'outil est une donnée pour le modèle, pas un crash du harness.

### `run_read(path, start_line=None, end_line=None)` — lignes 132–166

Lecture avec tranche optionnelle et **numérotation des lignes** — c'est le format que le vrai Claude Code utilise pour son outil Read.

```python
        # Convert 1-based human/AI indexing to 0-based Python indexing
        start_index = (start_line or 1) - 1
        # Set end index to requested line or default to end of file
        end_index = end_line or len(lines)
        
        # Build a string where every line is prefixed by its line number
        numbered_lines = "".join(
            f"{start_index + 1 + i:4d}\t{line}" 
            for i, line in enumerate(lines[start_index:end_index])
        )
        # Return formatted text, capped at 50k chars
        return numbered_lines[:50000] or "(empty file)"
```

- **Lignes 150–152** : conversion 1-indexé (humain/modèle) → 0-indexé (Python) ; le slicing tolère un `end_line` au-delà du fichier.
- **Lignes 155–158** : chaque ligne est préfixée `numéro<TAB>` ; la numérotation **continue depuis `start_line`**, pas depuis 1 — le modèle peut donc citer des numéros absolus pour un `edit` ultérieur.
- **Ligne 146** : `encoding="utf-8", errors="replace"` — lecture déterministe sur toutes plateformes (crucial sous Windows où le défaut est cp1252).
- **Lignes 161–166** : `FileNotFoundError` a son message dédié ; le reste tombe dans le générique.

### `run_write(path, content)` — lignes 169–201

Écriture avec **snapshot automatique** avant modification.

```python
        # Check if file exists to determine if we update or create
        if os.path.exists(path):
            # Read and store current content for 'revert' functionality
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                SNAPSHOTS[path] = f.read()
            action = "updated"
        else:
            # Mark as None in snapshots so 'revert' knows to delete the file
            SNAPSHOTS[path] = None
            action = "created"
        
        # Ensure the directory structure exists before writing the file
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
```

- **Lignes 182–190** : la distinction `updated`/`created` est encodée dans le snapshot lui-même — contenu pour un fichier existant, `None` pour une création. `run_revert` saura ainsi s'il doit réécrire ou supprimer.
- **Ligne 193** : `os.makedirs(..., exist_ok=True)` sur le chemin *absolu* — le modèle peut écrire `src/utils/x.py` sans créer les dossiers d'abord.
- **Ligne 198** : le retour annonce explicitement le mécanisme au modèle : `"(snapshot saved — use revert to undo)"` — le message d'outil sert de documentation in-band.
- Subtilité : chaque écriture **écrase** le snapshot précédent du même chemin — l'undo n'a qu'un niveau de profondeur (voir Pièges).

### `run_grep(pattern, path=".", recursive=True)` — lignes 204–240

Recherche regex déléguée au binaire système, avec fallback Windows.

```python
        result = subprocess.run(
            ["grep", "-n", *flags, pattern, path],
            capture_output=True, text=True, timeout=30
        )
        # Return results truncated to 10k chars to keep context lean
        return ((result.stdout + result.stderr).strip() or "(no matches)")[:10000]
    except FileNotFoundError:
        # Fallback mechanism for Windows environments without grep installed
        try:
            # Construct findstr command for common code file extensions
            command = f'findstr /S /N "{pattern}" "{path}\\*.py" "{path}\\*.js" "{path}\\*.md"'
```

- **Ligne 221** : forme *liste* (pas `shell=True`) — c'est précisément ce qui fait lever `FileNotFoundError` quand le binaire `grep` n'existe pas (Windows nu), déclenchant le fallback.
- **Lignes 226–234** : le fallback `findstr /S /N` ne cherche que dans `*.py`, `*.js`, `*.md` et avec la syntaxe regex limitée de findstr — les résultats Windows et Unix ne sont **pas** équivalents.
- **Ligne 225** : cap à 10 000 caractères (5× plus serré que bash/read) — une recherche est par nature plus bruyante qu'une lecture ciblée.

### `run_glob(pattern)` — lignes 243–258

```python
    # Perform recursive glob search using the standard library
    matches = _glob.glob(pattern, recursive=True)
    if not matches:
        return "(no matches)"
    # Sort for consistency and limit count to prevent massive context inflation
    return "\n".join(sorted(matches)[:200])
```

- **Ligne 254** : `recursive=True` en dur — `**` fonctionne toujours. Pas de `root_dir` : le motif est relatif au cwd du process (ou absolu si le modèle en passe un).
- **Ligne 258** : tri pour la stabilité, cap à 200 chemins. Seul outil sans `try/except` : `glob.glob` ne lève quasiment jamais.

### `run_revert(path)` — lignes 261–292

La contrepartie de `run_write` : restaure l'état pré-écriture.

```python
    # Retrieve and remove the snapshot from memory
    original_content = SNAPSHOTS.pop(path)
    
    if original_content is None:
        # If original_content was None, the file didn't exist before 'write'
        try:
            os.remove(path) # Revert by deleting the new file
            return f"reverted: deleted {path} (it was a new file)"
```

- **Ligne 276** : `pop()` — le snapshot est consommé. Deux `revert` successifs sur le même chemin échouent au second (`"Error: no snapshot for ..."`).
- **Lignes 278–284** : la convention `None` posée par `run_write` se déplie ici : fichier créé → on le supprime ; fichier modifié → on réécrit l'ancien contenu (lignes 285–292).

### `async_bash(command)` — lignes 297–326

Le seul outil async **natif** (les quatre autres sont des wrappers de thread).

```python
        # Create an async subprocess
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
        # Wait for the process to complete or timeout
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
```

- **Lignes 308–309** : la blocklist `_ALWAYS_BLOCK` est revérifiée — la sécurité n'est pas déléguée à la version sync.
- **Ligne 312** : `create_subprocess_shell` rend l'attente non bloquante : pendant qu'une commande tourne, l'event loop peut exécuter d'autres outils — c'est la condition du `asyncio.gather` de [[s18-parallel-tools]].
- **Ligne 319** : le timeout passe par `asyncio.wait_for` (l'API async n'a pas de paramètre `timeout=`), et l'exception correspondante est `asyncio.TimeoutError` (ligne 323), pas `subprocess.TimeoutExpired`.

### `async_read(path, start_line=None, end_line=None)` — lignes 329–332

```python
async def async_read(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Runs run_read in a separate thread to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_read, path, start_line, end_line)
```

Le motif des quatre wrappers suivants : pas de réimplémentation async, on pousse la fonction sync dans le thread pool par défaut (`run_in_executor(None, ...)`). L'I/O fichier bloquante sort de l'event loop ; la logique reste écrite une seule fois.

### `async_write(path, content)` — lignes 335–338

Même motif : `run_write` en executor. Les snapshots `SNAPSHOTS` restent partagés — deux écritures parallèles sur le même chemin se disputeraient le snapshot sans verrou.

### `async_grep(pattern, path=".", recursive=True)` — lignes 341–344

Même motif : `run_grep` en executor (le sous-processus grep bloque un thread du pool, pas l'event loop).

### `async_glob(pattern)` — lignes 347–350

Même motif : `run_glob` en executor. Notez qu'aucun de ces quatre wrappers n'est importé directement par une session — ils ne sont consommés que via `ASYNC_DISPATCH`.

### `BASIC_TOOLS` — lignes 356–366

```python
BASIC_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]
```

Le schéma minimal : bash seul. Sert exclusivement à [[s01-perception-action-loop]], dont tout le propos est de montrer qu'une boucle + un outil suffisent.

### `EXTENDED_TOOLS` — lignes 369–426

`BASIC_TOOLS + [...]` : concaténation de listes, donc **6 schémas** — `bash`, `read`, `write`, `grep`, `glob`, `revert` (le dict bash est *partagé* entre les deux listes, pas copié). Points notables des schémas :

- `read` (lignes 370–382) expose `start_line`/`end_line` optionnels — le modèle apprend depuis le schéma qu'il peut lire des tranches (1-indexées, dit la description).
- `write` (lignes 383–394) annonce dans sa description : *« Snapshots previous content automatically. »* — le mécanisme d'undo est contractualisé côté modèle.
- `grep` (lignes 395–407) déclare des `default` (`path: "."`, `recursive: true`) ; seul `pattern` est `required`.
- `revert` (lignes 417–425) : *« Restore a file to its state before the last write. »* — « last » est précis : un seul niveau.

### `BASIC_DISPATCH` — lignes 431–433

```python
BASIC_DISPATCH: Dict[str, Any] = {
    "bash": lambda inp: run_bash(inp["command"]),
}
```

Première des trois tables nom → handler. La convention de tout le repo est posée ici : un handler prend **le dict `input` entier** et la lambda fait l'adaptation vers les arguments nommés (là où learn-claude-code déballe avec `handler(**block.input)`). Avantage : une clé inattendue envoyée par le modèle est simplement ignorée au lieu de lever un `TypeError`.

### `EXTENDED_DISPATCH` — lignes 436–443

```python
EXTENDED_DISPATCH: Dict[str, Any] = {
    "bash":   lambda inp: run_bash(inp["command"]),
    "read":   lambda inp: run_read(inp["path"], inp.get("start_line"), inp.get("end_line")),
    "write":  lambda inp: run_write(inp["path"], inp["content"]),
    "grep":   lambda inp: run_grep(inp["pattern"], inp.get("path", "."), inp.get("recursive", True)),
    "glob":   lambda inp: run_glob(inp["pattern"]),
    "revert": lambda inp: run_revert(inp["path"]),
}
```

La table de référence, miroir exact d'`EXTENDED_TOOLS`. Les paramètres optionnels passent par `inp.get(...)` avec les mêmes défauts que les schémas — la cohérence schéma/handler est maintenue à la main, dans deux structures distinctes (le piège classique du dispatch par table, déjà présent dans learn-claude-code).

### `ASYNC_DISPATCH` — lignes 446–452

Même structure, branchée sur les coroutines : les lambdas renvoient des **coroutines non attendues**, que l'appelant doit `await` (ou rassembler via `asyncio.gather` — [[s18-parallel-tools]]). **Cinq entrées seulement** : `revert` est absent, alors que les sessions async exposent `EXTENDED_TOOLS` qui l'annonce au modèle (voir Pièges).

### `load_rules()` — lignes 459–472

```python
    try:
        # Attempt to read the permission YAML
        with open(_PERM_CONFIG, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Return a restrictive default if config is missing
        return {"always_deny": [], "always_allow": [], "ask_user": []}
```

Charge `config/permissions.yaml` (trois listes de règles `{pattern, reason}`). Le commentaire ligne 471 dit *« restrictive default »* mais c'est l'inverse : trois listes vides + le défaut « allow » de `check_permission` = **tout est autorisé** quand le fichier manque. Combiné au chemin `_PERM_CONFIG` erroné (ligne 457), ce fallback s'active silencieusement sur un clone standard.

### `check_permission(tool_name, input_str, rules=None)` — lignes 475–519

Le moteur de gouvernance à trois niveaux, consommé par [[s15-permissions]] et [[s16-event-bus]].

```python
    # Priority 1: Check if the input matches any 'always_deny' pattern
    for rule in rules.get("always_deny", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "blocked by policy")
            # Print feedback in Red
            print(f"\033[31m[DENIED] {reason}\033[0m")
            return False, f"Denied: {reason}"

    # Priority 2: Check if the input matches any 'always_allow' pattern
    for rule in rules.get("always_allow", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            return True, "allowed by policy"
```

- **Ordre strict deny → allow → ask** : une règle `always_deny` ne peut jamais être contournée par une règle `always_allow` plus permissive — l'ordre des priorités est l'architecture.
- **Ligne 493** : `re.search` + `re.IGNORECASE` sur `input_str`, la représentation *chaîne* des paramètres — c'est l'appelant (ex. `_guarded` dans s15) qui décide comment sérialiser l'input en chaîne.
- **Lignes 509–516** : le niveau `ask_user` fait un `input("  Allow? [y/N] ")` **bloquant dans le terminal** ; `EOFError`/`KeyboardInterrupt` → réponse `"n"` (refus par défaut sur interruption — le seul endroit du fichier qui choisit la fermeture).
- **Ligne 519** : priorité 4 — *aucune règle ne matche* → `True, "allowed by default (no rule matched)"`. Politique **ouverte par défaut**, l'inverse du vrai Claude Code qui demande confirmation pour tout ce qui n'est pas explicitement autorisé.
- Retour `Tuple[bool, str]` : la raison accompagne toujours la décision, pour le log et pour le message renvoyé au modèle.

### `dispatch_tools(response_content, dispatch)` — lignes 524–570

La moitié « action » de la boucle : transforme les blocs `tool_use` d'une réponse en liste de `tool_result`.

```python
    results = [] # To hold tool_result items
    for block in response_content:
        # Ignore text blocks, only process tool_use blocks
        if block.type != "tool_use":
            continue

        tool_name = block.name # Name of the tool requested
        tool_input = block.input # Params provided by the model
        tool_use_id = block.id # ID required for returning results
        handler = dispatch.get(tool_name) # Fetch handler from map
        
        # UI: Print the tool call in Yellow
        first_val = str(list(tool_input.values())[0])[:80] if tool_input else ""
        print(f"\033[33m[{tool_name}] {first_val}...\033[0m")

        if handler:
            try:
                # Call the mapped function with input dict
                output = handler(tool_input)
            except Exception as e:
                # Catch internal handler errors
                output = f"Error during tool execution: {e}"
        else:
            # Handle cases where the model hallucinates a tool name
            output = f"Error: Unknown tool '{tool_name}'"
```

- **Ligne 544** : `dispatch.get(tool_name)` — `.get()` et non `[...]` : un nom d'outil halluciné par le modèle produit le message `"Error: Unknown tool '...'"` renvoyé au modèle (ligne 559), jamais un `KeyError`.
- **Lignes 550–556** : double filet — le handler lui-même est entouré d'un `try/except` ; même un bug dans un outil devient un `tool_result` textuel. Le harness ne crashe sur aucune sortie du modèle.
- **Ligne 568** : `"content": str(output)` — coercition systématique en chaîne, le format que l'API attend.
- **Lignes 565–569** : chaque résultat porte le `tool_use_id` du bloc d'origine — l'appariement obligatoire de l'API Anthropic.
- La fonction est **paramétrée par la table** `dispatch` : c'est ce qui permet à [[s15-permissions]] de lui passer un `PERM_DISPATCH` où chaque handler est enveloppé d'un garde, sans toucher à cette fonction. Exécution **séquentielle**, dans l'ordre de `response_content` — la parallélisation est précisément l'apport de [[s18-parallel-tools]], qui réécrit cette brique en async.

### `stream_loop(messages, tools, dispatch, system=None, extra_kwargs=None)` — lignes 573–626

La boucle d'agent complète, version streaming — le `nO` master loop du vrai Claude Code, en 30 lignes utiles.

```python
    while True:
        # Indicate the thinking phase in Cyan
        print("\n\033[36m> Thinking...\033[0m")
        
        # Open a streaming connection to the Anthropic API
        with client.messages.stream(
            model=MODEL,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=8000,
            **extra_kwargs,
        ) as stream:
            # Print text chunks as they arrive for a responsive UI
            for text in stream.text_stream:
                print(text, end="", flush=True)
            # Finalize the message once streaming is complete
            response = stream.get_final_message()
        
        # Print a newline for visual separation
        print()
        # Record the assistant's message in the history
        messages.append({"role": "assistant", "content": response.content})
        
        # Break the loop if the model stopped for any reason other than calling tools
        if response.stop_reason != "tool_use":
            return response
            
        # Execute tool calls and gather results
        results = dispatch_tools(response.content, dispatch)
        # Append tool results to history for the model to see in the next iteration
        messages.append({"role": "user", "content": results})
```

- **Lignes 600–607** : `client.messages.stream(...)` en context manager — le streaming est *toujours actif* dans ce socle (pas d'opt-in comme la session dédiée [[s13-streaming]] le détaille). `**extra_kwargs` est le point d'extension générique : une session peut injecter n'importe quel paramètre API sans modifier la signature.
- **Lignes 609–612** : `stream.text_stream` n'émet que le texte ; les blocs `tool_use` sont reconstitués d'un coup par `get_final_message()` — l'UI est temps réel, la logique d'outils reste sur le message final complet.
- **Ligne 617** : `messages.append(...)` — la liste est **mutée en place**. C'est un choix d'API : l'appelant garde la main sur l'historique complet après le retour, ce que [[s17-session-management]] exploite pour persister et rejouer les sessions.
- **Lignes 620–621** : l'unique condition de sortie — `stop_reason != "tool_use"` (fin naturelle, `max_tokens`…) → on retourne la réponse finale. Sinon, tour suivant.
- **Lignes 624–626** : les `tool_result` repartent dans un message de rôle `"user"` — la convention de l'API : les résultats d'outils sont de la « perception », pas de la parole d'assistant. La boucle perception → décision → action → perception est bouclée.
- **Ligne 605** : `max_tokens=8000` est en dur — non surchargeable par `extra_kwargs` (le passer en double lèverait un `TypeError` de l'API Python pour argument dupliqué).

## Qui importe quoi

Vérifié par grep sur les `from core import (...)` des 23 sessions :

| Groupe d'exports | Sessions consommatrices |
|---|---|
| `client`, `MODEL` | [[s01-perception-action-loop]], [[s04-subagent]], [[s06-context-compact]], [[s08-background-tasks]], [[s09-agent-teams]], [[s10-team-protocols]], [[s11-autonomous-agents]], [[s12-worktree-task-isolation]], [[s13-streaming]], [[s16-event-bus]], [[s18-parallel-tools]], [[s19-interrupts]], [[s20-cache-optimization]], [[s21-mcp-runtime]], [[s22-production-mailbox]], [[s23-worktree-advanced]] — toutes celles qui écrivent leur propre boucle ou appellent l'API directement |
| `DEFAULT_SYSTEM` | [[s01-perception-action-loop]], [[s13-streaming]] (les autres définissent leur persona) |
| `BASIC_TOOLS`, `BASIC_DISPATCH` | [[s01-perception-action-loop]] uniquement |
| `EXTENDED_TOOLS` | toutes les sessions de s02 à s23 (22 sessions — seule s01 reste au bash seul) |
| `EXTENDED_DISPATCH` | s02–s14, s16, s17, s22, s23 — **pas** [[s15-permissions]] (qui reconstruit un `PERM_DISPATCH` gardé), **pas** s18–s21 (qui passent à l'async) |
| `ASYNC_DISPATCH` | [[s18-parallel-tools]], [[s19-interrupts]], [[s20-cache-optimization]], [[s21-mcp-runtime]] |
| `stream_loop` | [[s02-tool-use]], [[s03-todo-write]], [[s04-subagent]], [[s05-skill-loading]], [[s06-context-compact]], [[s07-task-system]], s08–s11, [[s14-tools-extended]], [[s15-permissions]], [[s16-event-bus]], [[s17-session-management]] — les sessions sync qui délèguent la boucle |
| `dispatch_tools` | [[s01-perception-action-loop]], [[s04-subagent]], [[s08-background-tasks]], [[s09-agent-teams]], [[s10-team-protocols]], [[s11-autonomous-agents]], [[s13-streaming]], [[s23-worktree-advanced]] — celles qui écrivent leur boucle mais réutilisent l'exécution d'outils |
| `run_bash` | [[s12-worktree-task-isolation]] (commandes git), [[s15-permissions]] |
| `run_read`, `run_write`, `run_grep`, `run_glob`, `run_revert` | [[s15-permissions]] uniquement (pour les envelopper une à une dans le garde) |
| `load_rules`, `check_permission` | [[s15-permissions]], [[s16-event-bus]] |
| `async_bash` | [[s22-production-mailbox]] uniquement |
| Jamais importés directement | `SNAPSHOTS` (encapsulé derrière write/revert), `async_read`/`async_write`/`async_grep`/`async_glob` (consommés via `ASYNC_DISPATCH`) |

Le motif d'ensemble : les sessions à boucle simple importent le trio `EXTENDED_TOOLS` + `EXTENDED_DISPATCH` + `stream_loop` ; les sessions multi-agents (s04, s08–s11, s13, s23) descendent d'un cran et prennent `client` + `MODEL` + `dispatch_tools` pour écrire leur propre boucle ; les sessions du runtime async (s18–s21) prennent `ASYNC_DISPATCH` et réécrivent tout le reste en `asyncio`.

## Pièges et détails d'implémentation

- **`_PERM_CONFIG` pointe hors du repo** (ligne 457) : `Path(__file__).parent.parent / "config"` suppose que core.py vit dans un sous-dossier (`agents/`, dit le docstring ligne 2) — à la racine d'un clone standard, le chemin remonte *au-dessus* du repo, `permissions.yaml` n'est jamais trouvé, `load_rules()` renvoie ses listes vides et `check_permission` autorise **tout** par défaut. [[s15-permissions]] et [[s16-event-bus]] tournent alors sans aucune règle, silencieusement.
- **Politique ouverte par défaut + blocklist par sous-chaîne** : la priorité 4 de `check_permission` (ligne 519) est « allow » ; et `_ALWAYS_BLOCK` matche par sous-chaîne — `"sudo"` bloque aussi `visudo --help`, tandis que `rm -rf ~` passe sans encombre. Filet pédagogique, pas sécurité.
- **`ASYNC_DISPATCH` n'a pas `revert`** (lignes 446–452) : les sessions s18–s21 annoncent pourtant `EXTENDED_TOOLS` (qui contient `revert`) au modèle ; s'il l'appelle, `dispatch.get` renvoie `None` et le modèle reçoit `"Error: Unknown tool 'revert'"`. Désalignement schémas/handlers typique du dispatch à deux structures.
- **Undo à un seul niveau** : `run_write` écrase le snapshot précédent du même chemin, et `run_revert` fait `SNAPSHOTS.pop()` — après deux écritures, `revert` ne restaure que l'avant-*dernière* version, et un second `revert` échoue. `SNAPSHOTS` est aussi purement en mémoire : tout est perdu au redémarrage.
- **Aucun ancrage de chemins** : contrairement au `safe_path` de learn-claude-code, `run_read`/`run_write` acceptent n'importe quel chemin absolu ou `../` — la seule défense est la gouvernance YAML, qui (cf. premier piège) ne se charge pas.
- **Les chiffres du README sont périmés** : *« core.py is 392 lines »* — le fichier réel en compte 626. L'exemple d'import du README cite aussi `run_grep`/`async_grep` sous le nom des groupes mais l'essentiel reste exact : tout passe par ce module.

## Utilisation

core.py ne se lance pas seul — c'est un module importé. Mais il a des **effets de bord à l'import** qu'il faut connaître : `load_dotenv(override=True)`, la purge éventuelle d'`ANTHROPIC_AUTH_TOKEN`, et la construction du client Anthropic. Prérequis : un `.env` à la racine du repo avec au minimum :

```env
ANTHROPIC_API_KEY=sk-ant-...
MODEL_ID=claude-sonnet-4-20250514
```

et, pour un modèle non-Anthropic via le proxy LiteLLM (option B du README) : `ANTHROPIC_BASE_URL=http://localhost:4000` + `litellm --config litellm_config.yaml --port 4000`. L'import type d'une session, tel que le README le présente :

```python
from core import (
    client, MODEL, DEFAULT_SYSTEM,          # Anthropic client + config
    EXTENDED_TOOLS, EXTENDED_DISPATCH,      # Tool definitions + handlers
    run_bash, run_read, run_write,          # Sync tool implementations
    async_bash, async_read, async_write,    # Async tool implementations
    load_rules, check_permission,           # Permission governance
    stream_loop, dispatch_tools,            # Core loop helpers
)
```

Pour vérifier que le socle est sain sans lancer de session : `python -c "import core; print(core.MODEL)"` depuis la racine du repo (le client se construit à l'import ; une clé manquante ne casse qu'au premier appel API).

## Liens

- Accueil : [[Accueil]]
- Première consommatrice : [[s01-perception-action-loop]] (`BASIC_TOOLS` + `dispatch_tools`)
- La boucle déléguée : [[s02-tool-use]] (premier usage du trio `EXTENDED_TOOLS`/`EXTENDED_DISPATCH`/`stream_loop`)
- Les outils en vitrine : [[s14-tools-extended]] (read/write/grep/glob/revert et les snapshots)
- La gouvernance en action : [[s15-permissions]] (`load_rules` + `check_permission` + dispatch gardé)
- Le streaming expliqué : [[s13-streaming]] (ce que `stream_loop` fait en interne)
- Le passage à l'async : [[s18-parallel-tools]] (`ASYNC_DISPATCH` + `asyncio.gather`)
