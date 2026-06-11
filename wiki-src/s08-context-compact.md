---
title: "s08 · Context Compact"
session: 08
phase: "Contexte & mémoire"
fichier: "src/s08.py"
lignes: 129
tags: [compaction, contexte, pipeline, seuils, resume-llm]
prev: "s07-skill-loading"
next: "s09-memory"
---

# s08 · Context Compact

> **En une phrase** : le pipeline de compaction de shared (budget → snip → micro → compact, + reactive en urgence) rendu observable en démo grâce à des seuils abaissés et à une démo « à sec » sans appel API.

## Rôle dans le harness

La fenêtre de contexte est finie : sans compression, chaque sortie d'outil s'empile dans `messages` jusqu'au rejet `prompt_too_long`. La réponse de [[shared-py]] est un pipeline en couches, du moins destructif au plus destructif, appliqué par `prepare_context()` avant **chaque** appel LLM : `tool_result_budget` (persiste sur disque les sorties géantes du dernier message), `snip_compact` (coupe le milieu sans jamais casser une paire tool_use/tool_result), `micro_compact` (placeholders sur les vieux tool_result), puis `compact_history` (résumé LLM — 1 appel API — seulement si `estimate_size` dépasse `CONTEXT_LIMIT`). En dernier recours, `reactive_compact` répare après une erreur « prompt too long ». Tous les seuils sont en **caractères JSON**, pas en tokens.

Avec les valeurs de production (50 000 caractères), il faudrait de longues sessions pour voir le pipeline travailler. Le délta de ce fichier : **abaisser les globales de shared** (`CONTEXT_LIMIT` 50 000 → 6 000, `KEEP_RECENT_TOOL_RESULTS` 3 → 1, `PERSIST_THRESHOLD` 30 000 → 1 000) pour que la compaction se déclenche en quelques tours, et rejouer les couches structurelles sur un historique synthétique (`:sec`, 0 appel API) en affichant la taille après chacune.

## Ce que fait ce fichier

### pick() — lignes 26–28

Le helper commun. Pool de la session (lignes 34–37) : `bash`, `read_file`, `glob`, `compact` — avec une subtilité :

```python
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES
            if n in BUILTIN_HANDLERS}
```

`compact` est un outil **méta** : présent dans `TOOLS` (le modèle peut le demander) mais absent de `BUILTIN_HANDLERS` — `agent_loop` l'intercepte avant le dispatch, car il doit réécrire `messages`, ce qu'un handler ordinaire (qui ne voit que ses arguments) ne peut pas faire. D'où le garde `if n in BUILTIN_HANDLERS`.

### Seuils abaissés — lignes 42–44

```python
shared.CONTEXT_LIMIT = 6000
shared.KEEP_RECENT_TOOL_RESULTS = 1
shared.PERSIST_THRESHOLD = 1000
```

Les trois constantes sont des globales module-level de shared, lues à chaque appel par `prepare_context`, `micro_compact` et `persist_large_output` : les réaffecter depuis la session suffit. C'est pour ces trois noms que le fichier garde `import shared` et l'accès qualifié `shared.X` (affectation **et** lectures) — une affectation sur un nom from-importé ne toucherait pas le module, et les fonctions de shared liraient toujours les anciennes valeurs. `SYSTEM` (46–50) est un system figé qui autorise explicitement l'appel de `compact`.

### fake_history() — lignes 53–65

Fabrique un historique synthétique : `pairs` (12) paires tool_use/tool_result **en dicts** (le format harness — les couches structurelles n'exigent pas d'objets SDK), la dernière sortie étant volontairement géante (`"x" * 5000`, les autres 150) pour donner du grain à moudre à `tool_result_budget`, qui ne regarde que le dernier message.

### demo_a_sec() — lignes 68–84

Rejoue les trois couches structurelles — **0 appel API** — en montrant `estimate_size` après chacune :

```python
    msgs = tool_result_budget(msgs, max_bytes=3000)
    print(f"1. tool_result_budget   : {estimate_size(msgs)} caractères "
          f"(la sortie géante est persistée sous {TOOL_RESULTS_DIR})")
    msgs = snip_compact(msgs, max_messages=8)
    print(f"2. snip_compact(max=8)  : {len(msgs)} messages, "
          f"{estimate_size(msgs)} caractères")
    print(f"   placeholder inséré   : {msgs[3]['content']!r}")
    msgs = micro_compact(msgs)
```

Sur les 25 messages synthétiques : le budget persiste la sortie de 5 000 caractères dans `.task_outputs/tool-results/` (remplacée par un `<persisted-output>` avec chemin + aperçu) ; le snip ramène à 10 messages avec `[snipped 16 messages]` en position 3 — la garde de queue a reculé `tail_start` pour ré-inclure le `tool_use` apparié ; le micro écrase tous les vieux tool_result sauf le dernier (`KEEP_RECENT_TOOL_RESULTS = 1`). Les couches à appel API (`compact_history`, `reactive_compact`) se testent dans la boucle interactive.

### main() — lignes 87–124

Boucle interactive (`q` pour quitter) à cinq chemins :

- `:sec` (102–104) — la démo à sec ci-dessus.
- `:taille` (105–108) — `estimate_size(history)` face au seuil `CONTEXT_LIMIT` courant.
- `:compact` (109–114) — couche 4 à la demande : `history[:] = compact_history(history)` — transcript JSONL d'abord, résumé LLM ensuite, tout l'historique devient UN message `[Compacted]`.
- `:reactive` (115–120) — `history[:] = reactive_compact(history)` : résumé + ~5 derniers messages bruts (garde de frontière incluse) ; si même le résumé échoue, texte de repli sans API.
- Texte libre (121–124) — tour d'`agent_loop` : `prepare_context` y applique le pipeline avant chaque appel ; avec `CONTEXT_LIMIT = 6000`, deux ou trois lectures de fichiers suffisent à déclencher `[compact] transcript saved: ...`.

## Ce qui vient de [[shared-py]]

- `tool_result_budget(messages, max_bytes)` / `persist_large_output` — couche 1, persistance disque des sorties géantes.
- `snip_compact(messages, max_messages)` — couche 2, coupe du milieu avec gardes de paires tool_use/tool_result.
- `micro_compact(messages)` — couche 3, placeholders sur les vieux tool_result (pilotée par `KEEP_RECENT_TOOL_RESULTS`).
- `compact_history(messages)` / `summarize_history` / `write_transcript` — couche 4, résumé LLM précédé de l'archivage JSONL.
- `reactive_compact(messages)` — l'urgence post « prompt too long » (utilisée aussi en interne par `agent_loop`).
- `estimate_size` / `TOOL_RESULTS_DIR` — la métrique et le dossier de persistance (from-importés) ; `CONTEXT_LIMIT`, `KEEP_RECENT_TOOL_RESULTS`, `PERSIST_THRESHOLD` — les seuils, **réaffectés ici** donc accédés en `shared.X` qualifié.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop` (qui exécute `prepare_context` et intercepte `compact`), `print_turn_assistants`, `PROMPT`, `WORKDIR`.

## Différences avec l'original learn-claude-code

- L'original (`s08_context_compact/code.py`, 525 lignes) insérait le pipeline dans une `agent_loop` refondue ; ici la boucle de shared le fait déjà (`prepare_context`), le fichier ne fait qu'abaisser les seuils et instrumenter.
- Le bug de l'original — outil `task` au schéma `description` face à `spawn_subagent(task)`, `TypeError` au premier appel — n'existe plus : signatures alignées dans shared.py (et `task` n'est de toute façon pas dans le pool de cette démo).
- L'interception de `compact` dans l'original laissait un `tool_result` orphelin (référant un `tool_use` détruit par la compaction) ; l'`agent_loop` de shared appende un simple message user `[Compacted. Continue with summarized context.]` — plus d'orphelin.
- La démo à sec (`fake_history` + `:sec`) est nouvelle : l'original n'offrait aucun moyen d'observer les couches sans brûler des appels API.
- `estimate_size` de shared mesure `len(json.dumps(messages))` — l'original mesurait `len(str(msgs))` ; même ordre de grandeur, mesure plus honnête du payload réel.

## Lancer la démo

```
python src/s08.py
```

`:sec` montre la cascade des tailles (et crée réellement un fichier sous `.task_outputs/tool-results/`). Puis en texte libre, faire lire deux ou trois fichiers : `:taille` montre l'historique gonfler, et dès 6 000 caractères le tour suivant affiche `[compact] transcript saved: ...` — l'historique est devenu un seul message `[Compacted]`. `:reactive` montre la variante d'urgence qui garde les derniers messages bruts.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s07-skill-loading]]
- Session suivante : [[s09-memory]]
- Sessions liées : [[s11-error-recovery]] (qui déclenche `reactive_compact` sur l'erreur réelle), [[s09-memory]] (la couche qui survit à la compaction)
