---
title: "s10 · System Prompt"
session: 10
phase: "Contexte & mémoire"
fichier: "inspiration/learn-claude-code/s10_system_prompt/code.py"
lignes: 219
tags: [system-prompt, assemblage, cache, sections]
prev: "s09-memory"
next: "s11-error-recovery"
---

# s10 · System Prompt

> **En une phrase** : le prompt système cesse d'être une chaîne codée en dur — il est découpé en sections, assemblé à l'exécution d'après l'état réel (outils enregistrés, fichiers de mémoire présents) et mis en cache.

## Rôle dans le harness

De s01 à s09, le prompt système était une ligne codée en dur (`SYSTEM = f"You are a coding agent at {WORKDIR}..."`), enrichie au fil des sessions par concaténation. Le README identifie trois problèmes de cette approche : changer de projet oblige à réécrire tout le prompt (impossible de savoir quoi garder), une modification peut en casser une autre (une description d'outil peut contredire une instruction antérieure), et chaque requête transporte tout — même les sections inutiles à la conversation en cours, gaspillant des tokens à chaque tour.

La thèse de la session : *« prompt is assembled, not hardcoded »*. Le prompt système doit être une **configuration assemblée à l'exécution** selon l'état courant : quels outils sont activés, quel contexte est visible, quelles mémoires sont pertinentes — et quelles parties doivent rester stables pour bénéficier du prompt caching. Le mécanisme tient en trois pièces : `PROMPT_SECTIONS` (fragments indexés par thème), `assemble_system_prompt(context)` (sélection + jointure selon l'état réel), `get_system_prompt(context)` (cache à clé déterministe via `json.dumps`). Le critère de chargement est martelé par le README : **l'état réel** (le fichier `.memory/MEMORY.md` existe-t-il ?), jamais des mots-clés devinés dans les messages.

Attention à une particularité structurelle : contrairement aux sessions précédentes, **s10 n'est pas cumulative**. Le fichier retombe à 174 lignes et 3 outils (`bash`, `read_file`, `write_file`) ; hooks, todos, subagent, skills et compaction ont disparu. Le README l'assume : « s10 se concentre sur l'assemblage du prompt. Il s'appuie sur les capacités de s08–s09 mais ne ré-implémente ni la compression ni la mémoire. »

Dans le vrai Claude Code (détail du README) : des dizaines de sections statiques (identity, doing_tasks, tone_style…) et dynamiques (memory, output_style, mcp_instructions…), un assemblage `getSystemPrompt()` qui renvoie un `string[]` séparé par `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` pour que les sections statiques touchent le cache API global, et trois couches de cache (memoize par session, registre de sections, cache API). Le cache pédagogique de s10, lui, n'évite que le réassemblage de chaîne dans le processus.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–15 | Docstring | Changements vs s09, critère « état réel, pas mots-clés » |
| 17–31 | Imports & env | `readline`, `anthropic`, `dotenv` |
| 33–37 | Globals | `WORKDIR`, `MEMORY_DIR`, `MEMORY_INDEX`, `client`, `MODEL` |
| 40–47 | **NOUVEAU** | `PROMPT_SECTIONS` — fragments de prompt par thème |
| 50–64 | **NOUVEAU** | `assemble_system_prompt` — sélection + jointure |
| 67–93 | **NOUVEAU** | `_last_context_key`/`_last_prompt`, `get_system_prompt` (cache) |
| 95–151 | Outils (3) | `safe_path`, `run_bash`, `run_read`, `run_write`, `TOOLS`, `TOOL_HANDLERS` |
| 154–167 | **NOUVEAU** | `update_context` — dérive le contexte de l'état réel |
| 170–197 | Boucle | `agent_loop(messages, context)` — prompt réévalué à chaque tour d'outils |
| 200–218 | `__main__` | REPL avec `update_context` initial et après chaque tour |

## Constantes et configuration

- `MEMORY_DIR = WORKDIR / ".memory"` (ligne 34) et `MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"` (ligne 35) — chemins hérités de [[s09-memory]], mais en **lecture seule** ici : contrairement à s09, le dossier n'est jamais créé (`mkdir` absent), seul `MEMORY_INDEX.exists()` est testé.
- `PROMPT_SECTIONS` (lignes 42–47) — le cœur déclaratif :

```python
PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: bash, read_file, write_file.",
    "workspace": f"Working directory: {WORKDIR}",
    "memory": "Relevant memories are injected below when available.",
}
```

  Chaque clé est un thème maintenu indépendamment : modifier `tools` ne touche pas `identity`. Curiosité : l'entrée `"memory"` n'est **jamais lue** par `assemble_system_prompt`, qui construit sa propre chaîne — clé morte (cf. Pièges).
- `_last_context_key = None` / `_last_prompt = None` (lignes 67–68) — le cache à un seul emplacement de `get_system_prompt`.
- `TOOLS` (lignes 134–149) et `TOOL_HANDLERS` (ligne 151) — retour aux 3 outils de [[s01-agent-loop]]/[[s02-tool-use]].

## Les fonctions, une à une

### `assemble_system_prompt(context)` — lignes 50–64
**Nouvelle** : la fonction d'assemblage, avec deux stratégies de chargement.

```python
def assemble_system_prompt(context: dict) -> str:
    """Select and join prompt sections based on current context."""
    sections = []

    # Always loaded — identity, tools, workspace
    sections.append(PROMPT_SECTIONS["identity"])
    sections.append(PROMPT_SECTIONS["tools"])
    sections.append(PROMPT_SECTIONS["workspace"])

    # Conditional — memory loaded when MEMORY.md exists and has content
    memories = context.get("memories", "")
    if memories:
        sections.append(f"Relevant memories:\n{memories}")

    return "\n\n".join(sections)
```

- Lignes 55–57 : trois sections **toujours chargées** — qui je suis, ce que je sais faire, où je travaille. Leur ordre est fixe, condition de stabilité du préfixe (et donc d'un éventuel prompt caching côté API).
- Lignes 60–62 : la section mémoire est **conditionnelle** — elle n'apparaît que si `context["memories"]` est non vide, c'est-à-dire si `.memory/MEMORY.md` existe et a du contenu. Le README justifie : pourquoi ne pas tout charger ? Les tokens coûtent (le prompt système est facturé à chaque tour) et moins d'instructions = sortie plus ciblée (les instructions hors sujet sont du bruit).
- Ligne 64 : jointure par double saut de ligne — chaque section reste un paragraphe distinct lisible par le modèle.

### `get_system_prompt(context)` — lignes 71–93
**Nouvelle** : l'enveloppe de cache.

```python
def get_system_prompt(context: dict) -> str:
    global _last_context_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_context_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt unchanged\033[0m")
        return _last_prompt
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)

    loaded = ["identity", "tools", "workspace"]
    if context.get("memories"):
        loaded.append("memory")
    print(f"  \033[32m[assembled] sections: {', '.join(loaded)}\033[0m")
    return _last_prompt
```

- Ligne 81 : la clé de cache est le contexte sérialisé en JSON **déterministe** : `sort_keys=True` neutralise l'ordre d'insertion des dicts, `default=str` absorbe les types non sérialisables. La docstring (lignes 72–79) explique le choix contre `hash()` : le hash Python est randomisé par processus (`PYTHONHASHSEED`) — inutilisable comme clé stable — et échoue (`unhashable type`) sur les dicts/listes imbriqués.
- Lignes 82–84 : hit — même contexte, on renvoie la chaîne mémorisée sans réassembler, avec trace `[cache hit]`.
- Lignes 85–86 : miss — on mémorise la nouvelle clé et le nouveau prompt (cache à un seul slot : seule la dernière valeur survit).
- Lignes 88–92 : la trace `[assembled] sections: ...` recalcule la liste des sections chargées pour l'affichage — c'est l'observabilité demandée par le README (« regardez quelles sections sont chargées »).
- La docstring précise les limites : ce cache n'économise que l'assemblage de chaîne **dans le processus**. Le vrai CC protège en plus le prompt cache **API** via l'ordre stable des sections et `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` (les parties statiques restent en cache même quand les dynamiques changent).

### `safe_path(p)` — lignes 97–101
### `run_bash(command)` — lignes 104–111
### `run_read(path, limit=None)` — lignes 114–121
### `run_write(path, content)` — lignes 124–131
Repris de [[s02-tool-use]] sans modification. Les outils `edit_file`, `glob`, `todo_write`, `task`, `load_skill`, `compact` et les outils mémoire de [[s09-memory]] ne sont **pas** repris — jeu minimal pour isoler le sujet de la session.

### `update_context(context, messages)` — lignes 156–167
**Nouvelle** : la source de vérité du contexte.

```python
def update_context(context: dict, messages: list) -> dict:
    """Derive context from real state: which tools exist, whether memory files exist."""
    memories = ""
    if MEMORY_INDEX.exists():
        content = MEMORY_INDEX.read_text().strip()
        if content:
            memories = content
    return {
        "enabled_tools": list(TOOL_HANDLERS.keys()),
        "workspace": str(WORKDIR),
        "memories": memories,
    }
```

- Lignes 159–162 : la mémoire est chargée si et seulement si `.memory/MEMORY.md` **existe et n'est pas vide** — un fichier vide ne déclenche pas la section. C'est le « real state, not keywords » du README : aucune heuristique sur le texte de la conversation.
- Lignes 163–167 : le contexte renvoyé est reconstruit **de zéro** — les paramètres `context` et `messages` sont en réalité ignorés (signature conservée pour la symétrie pédagogique et les évolutions futures). `enabled_tools` reflète la table de dispatch réelle ; toute valeur qui change ici invalide la clé de cache de `get_system_prompt`.

### `agent_loop(messages, context)` — lignes 172–197
**Modifiée** : la boucle de [[s01-agent-loop]], avec le prompt assemblé au lieu du `SYSTEM` fixe.

```python
def agent_loop(messages: list, context: dict):
    """Main loop — uses assembled system prompt instead of hardcoded SYSTEM."""
    system = get_system_prompt(context)
    while True:
        response = client.messages.create(
            model=MODEL, system=system, messages=messages,
            tools=TOOLS, max_tokens=8000)
        ...
        messages.append({"role": "user", "content": results})

        # Re-evaluate context and prompt after each tool round
        context = update_context(context, messages)
        system = get_system_prompt(context)
```

- Ligne 174 : le prompt est calculé **avant** la boucle pour le premier appel.
- Lignes 195–197 : après chaque tour d'outils, le contexte est re-dérivé et le prompt réévalué. Conséquence concrète : si le modèle vient de créer `.memory/MEMORY.md` via `write_file`, l'appel LLM **suivant** inclut déjà la section mémoire — c'est le scénario d'essai n° 2 du README. Si rien n'a changé, `get_system_prompt` renvoie le cache (`[cache hit]`).
- Le reste (dispatch, `tool_result`) est la boucle minimale de s01/s02 — sans hooks ni todo.

### Bloc `__main__` — lignes 200–218
REPL avec gestion du contexte de bout en bout : `context = update_context({}, [])` initial (ligne 204) — le contexte existe avant la première requête —, puis après chaque `agent_loop`, `context = update_context(context, history)` (ligne 214) rafraîchit l'état pour le tour suivant (un `MEMORY.md` créé à la main entre deux prompts sera détecté).

## Ce qui change par rapport à [[s09-memory]]

- **Nouveau** : `PROMPT_SECTIONS` (42–47) — le prompt éclaté en fragments thématiques.
- **Nouveau** : `assemble_system_prompt()` (50–64) — sections toujours chargées vs conditionnelles, pilotées par l'état réel.
- **Nouveau** : `get_system_prompt()` (71–93) avec `_last_context_key`/`_last_prompt` (67–68) — cache à clé `json.dumps` déterministe.
- **Nouveau** : `update_context()` (156–167) — dérivation du contexte depuis l'état réel (outils enregistrés, présence/contenu de `MEMORY.md`).
- **Modifié** : `agent_loop` (172–197) prend `context` en paramètre et réévalue le prompt après chaque tour d'outils ; `build_system()` de s07–s09 disparaît au profit du couple assemblage + cache.
- **Rupture du cumul (volontaire)** : tout le reste de s09 est retiré — outils mémoire, `select_relevant_memories`/`extract_memories`/`consolidate_memories`, pipeline de compaction de [[s08-context-compact]], subagent, skills, hooks, todos. Le fichier garde 3 outils et la boucle nue. Seuls les chemins `.memory/` relient encore s10 à s09.

## Pièges et détails d'implémentation

- **s10 casse la chaîne cumulative** : c'est une maquette focalisée, pas « s09 + un mécanisme ». Ne pas chercher la compaction ou la mémoire active dans ce fichier — il ne fait que **lire** `MEMORY.md` produit (conceptuellement) par s09.
- **`PROMPT_SECTIONS["memory"]` est une clé morte** : `assemble_system_prompt` fabrique `f"Relevant memories:\n{memories}"` au lieu d'utiliser le fragment déclaré ligne 46. Le dict documente l'intention, le code ne s'en sert pas.
- **`update_context` ignore ses deux paramètres** : tout est recalculé depuis `TOOL_HANDLERS` et le disque. La signature `(context, messages)` n'est là que pour le motif d'API.
- **Pourquoi `json.dumps` et pas `hash()`** : randomisation du hash entre processus (PYTHONHASHSEED) et `TypeError: unhashable type` sur les structures imbriquées. La sérialisation triée est lente mais stable et totale.
- **Deux caches très différents** : celui de s10 économise un réassemblage de chaîne local ; le prompt caching de l'API Anthropic économise du **prétraitement de tokens** côté serveur et exige un préfixe byte-identique — d'où, dans le vrai CC, l'ordre stable des sections et la frontière statique/dynamique.
- **Le prompt en vol n'est pas réécrit** : `system` est capturé avant `client.messages.create` ; un changement d'état pendant un tour ne s'applique qu'à l'appel suivant (lignes 195–197) — jamais rétroactivement.

## Liens

- Session précédente : [[s09-memory]]
- Session suivante : [[s11-error-recovery]]
- Sessions liées : [[s07-skill-loading]] (première injection dynamique dans `SYSTEM` via `build_system`), [[s09-memory]] (produit le `MEMORY.md` que s10 consomme), [[s01-agent-loop]] (la boucle minimale reprise ici)
