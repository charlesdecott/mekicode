---
title: "s08 · Context Compact"
session: 08
phase: "Contexte & mémoire"
fichier: "inspiration/learn-claude-code/s08_context_compact/code.py"
lignes: 525
tags: [compaction, contexte, pipeline, resume-llm, prompt-too-long]
prev: "s07-skill-loading"
next: "s09-memory"
---

# s08 · Context Compact

> **En une phrase** : un pipeline de compaction en quatre couches (+ un mode urgence), inséré avant chaque appel LLM, selon le principe « le bon marché d'abord, le coûteux en dernier ».

## Rôle dans le harness

Le README résume le symptôme : « l'agent tourne, puis se fige ». Il a tous les outils nécessaires, mais il a lu un fichier de 1 000 lignes (~4 000 tokens), puis 30 autres fichiers, lancé 20 commandes — et chaque sortie s'empile dans `messages`. La fenêtre de contexte est finie ; une fois pleine, l'API rejette l'appel avec `prompt_too_long`. « Sans compression, un agent ne peut tout simplement pas travailler sur de grands projets. »

La réponse de s08 : quatre couches, ordonnées par coût. **L1 `snip_compact`** coupe le milieu de la conversation quand il y a plus de 50 messages. **L2 `micro_compact`** remplace les vieux `tool_result` par des placeholders d'une ligne. **L3 `tool_result_budget`** persiste sur disque les résultats géants du dernier message. Ces trois couches sont purement textuelles/structurelles — **0 appel API**. **L4 `compact_history`** est le filet sémantique : un résumé LLM complet (1 appel API), déclenché seulement si le contexte dépasse encore le seuil. Et si malgré tout l'API renvoie `prompt_too_long`, **`reactive_compact`** fait un repli d'urgence (résumé + 5 derniers messages).

Détail d'ordre crucial (et contre-intuitif vu la numérotation) : le pipeline exécute **budget (L3) → snip (L1) → micro (L2) → auto (L4)**, comme le vrai code source de Claude Code (`query.ts` : `applyToolResultBudget` → `snipCompact` → `microcompact` → `contextCollapse` → `autoCompact`). Si micro passait avant budget, les gros contenus seraient écrasés en placeholders **avant** d'avoir été sauvegardés sur disque.

Le README documente les différences avec le vrai Claude Code : seuils précis en tokens (`contextWindow − maxOutputTokens − 13 000`), prompt de résumé à 9 sections avec balises `<analysis>`/`<summary>` et double garde-fou « TEXT ONLY », restauration post-compaction des fichiers récents (jusqu'à 5 fichiers, 50 K tokens), `readFileState` avec `FILE_UNCHANGED_STUB`, et deux mécanismes absents ici (`contextCollapse`, `sessionMemoryCompact` — ce dernier s'éclaire avec [[s09-memory]]).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–33 | Docstring | Schéma du pipeline L1–L4 + urgence, principe « cheap first » |
| 35–48 | Imports & env | + `time` ; `yaml` a disparu |
| 50–56 | Globals | + `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` |
| 58–117 | Skills s07 (modifié) | `_parse_frontmatter` **réécrit sans yaml**, registre, `load_skill`, `build_system`, `SUB_SYSTEM` |
| 120–203 | Outils s02–s07 | `safe_path` … `run_todo_write`, `extract_text` (mise en forme compactée) |
| 206–258 | Subagent s06–s07 | `SUB_TOOLS`, `SUB_HANDLERS`, `spawn_subagent` (paramètre renommé) |
| 261–391 | **NOUVEAU s08** | constantes, 4 helpers de structure, L1–L4, `reactive_compact` |
| 394–424 | Registre d'outils | `TOOLS` (9, + `compact`), `TOOL_HANDLERS` |
| 426–445 | Hooks (réduits) | `PreToolUse`/`PostToolUse` seulement |
| 448–509 | **agent_loop refondu** | pipeline avant l'appel, try/except réactif, outil `compact` |
| 512–524 | `__main__` | REPL (sans hooks `UserPromptSubmit`) |

## Constantes et configuration

- `TRANSCRIPT_DIR = WORKDIR / ".transcripts"` (ligne 52) — **nouveau** : où `write_transcript` archive la conversation complète en JSONL avant tout résumé.
- `TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"` (ligne 53) — **nouveau** : où L3 persiste les sorties d'outils géantes.
- `CONTEXT_LIMIT = 50000` (ligne 265) — seuil de déclenchement de L4, en **caractères** (`estimate_size`), pas en tokens (~12 K tokens).
- `KEEP_RECENT = 3` (ligne 266) — nombre de `tool_result` récents que L2 laisse intacts.
- `PERSIST_THRESHOLD = 30000` (ligne 267) — taille minimale (caractères) pour qu'un bloc soit persisté par L3.
- `MAX_REACTIVE_RETRIES = 1` (ligne 452) — une seule tentative de compaction réactive avant de relancer l'exception.
- `DENY_LIST = ["rm -rf /", "sudo", "shutdown"]` (ligne 434) — raccourcie vs s07 (qui listait aussi `reboot`, `mkfs`, `dd if=`).

## Les fonctions, une à une

### `_parse_frontmatter(text)` — lignes 59–70
**Modifiée** : la version s07 utilisait `yaml.safe_load` ; ici, le parsing YAML est remplacé par un découpage naïf `clé: valeur` ligne à ligne — la dépendance pyyaml disparaît.

```python
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, parts[2].strip()
```

Suffisant pour `name:` et `description:` sur une ligne ; les valeurs multilignes ou imbriquées ne sont plus gérées (régression assumée, hors sujet pour cette session).

### `_scan_skills()` — lignes 74–86, `list_skills()` — lignes 90–93, `load_skill(name)` — lignes 95–99, `build_system()` — lignes 102–110
Repris de [[s07-skill-loading]] sans modification de logique (`load_skill` a simplement été remonté à côté du registre). `SYSTEM = build_system()` ligne 110, `SUB_SYSTEM` lignes 113–117.

### `safe_path` (124–127), `run_bash` (129–134), `run_read` (136–141), `run_write` (143–147), `run_edit` (149–156), `run_glob` (158–166), `_normalize_todos` (168–186), `run_todo_write` (188–199), `extract_text` (201–203)
Repris de [[s02-tool-use]], [[s05-todo-write]] et [[s06-subagent]] sans modification de logique (mise en forme condensée : plusieurs `try/except` tiennent sur une ligne).

### `spawn_subagent(task)` — lignes 225–258
Reprise de [[s06-subagent]]… avec un **renommage de paramètre lourd de conséquences** : `description` devient `task` (ligne 225), mais le schéma de l'outil `task` (lignes 411–412) exige toujours une propriété `description` :

```python
def spawn_subagent(task: str) -> str:
```

```python
    {"name": "task", "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
     "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}},
```

Quand le modèle appelle `task` avec `{"description": "..."}`, le dispatch `handler(**block.input)` (ligne 500) lève `TypeError: spawn_subagent() got an unexpected keyword argument 'description'` — exception non rattrapée qui fait planter la boucle. **Bug réel** de cette session (la logique interne du sous-agent, elle, est inchangée).

### `estimate_size(msgs)` — ligne 269
Une ligne : `return len(str(msgs))`. L'estimation de tokens est un simple comptage de caractères de la représentation Python — grossier mais sans dépendance (le vrai CC utilise un tokenizer précis).

### `_block_type(block)` — lignes 271–272
Helper d'uniformisation : renvoie `block.get("type")` pour un dict, `getattr(block, "type", None)` pour un objet SDK. Nécessaire parce que les messages mélangent les deux représentations (contenu assistant = objets, tool_results = dicts).

### `_message_has_tool_use(msg)` — lignes 275–281
Vrai si `msg` est un message assistant dont le contenu (liste) contient au moins un bloc `tool_use`. Utilisé par les gardes de frontière de L1 et du mode réactif.

### `_is_tool_result_message(msg)` — lignes 284–291
Vrai si `msg` est un message user dont le contenu contient un bloc `tool_result` (test `isinstance(block, dict)` : seuls les dicts comptent). Pendant des deux gardes.

### `snip_compact(messages, max_messages=50)` — lignes 295–309 (L1)
Coupe le **milieu** de la conversation : garde 3 messages de tête (contexte initial) et 47 de queue (travail courant), remplace le reste par un placeholder.

```python
def snip_compact(messages, max_messages=50):
    if len(messages) <= max_messages: return messages
    keep_head, keep_tail = 3, max_messages - 3
    head_end, tail_start = keep_head, len(messages) - keep_tail
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    return messages[:head_end] + [{"role": "user", "content": f"[snipped {snipped} messages]"}] + messages[tail_start:]
```

- Lignes 299–301 : garde de tête — si le 3e message gardé est un assistant avec `tool_use`, on **étend** la tête pour inclure les `tool_result` qui suivent. L'API Anthropic exige que chaque `tool_use` soit immédiatement suivi de son `tool_result` : couper entre les deux provoquerait une erreur 400.
- Lignes 302–304 : garde de queue, symétrique — si la queue commence par un `tool_result`, on **recule** `tail_start` pour ré-inclure le `tool_use` correspondant.
- Lignes 305–306 : si les gardes font se croiser tête et queue, on renonce à couper plutôt que de produire une liste incohérente.
- Ligne 309 : le placeholder est un message **user** (`[snipped N messages]`) — le modèle sait qu'il manque quelque chose.

### `collect_tool_results(messages)` — lignes 313–320 (support de L2)
Parcourt tous les messages user et renvoie la liste des triplets `(index_message, index_bloc, bloc)` pour chaque `tool_result` (dicts uniquement). L'ordre de la liste est l'ordre chronologique — c'est ce qui permet à L2 de cibler « tous sauf les N derniers ».

### `micro_compact(messages)` — lignes 322–328 (L2)

```python
def micro_compact(messages):
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT: return messages
    for _, _, block in tool_results[:-KEEP_RECENT]:
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages
```

- Ligne 325 : `[:-KEEP_RECENT]` épargne les 3 résultats les plus récents — le travail en cours reste lisible.
- Ligne 326 : seuls les contenus de plus de 120 caractères sont remplacés — écraser un `"Edited foo.py"` de 14 caractères par un placeholder de 47 serait contre-productif.
- Mutation **en place** des blocs (les dicts sont partagés avec `messages`) ; le placeholder invite le modèle à ré-exécuter l'outil si besoin — le compromis assumé : un appel d'outil en plus plutôt qu'un état de cache de fichiers (le `readFileState` du vrai CC).

### `persist_large_output(tool_use_id, output)` — lignes 332–337 (support de L3)

```python
def persist_large_output(tool_use_id, output):
    if len(output) <= PERSIST_THRESHOLD: return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists(): path.write_text(output)
    return f"<persisted-output>\nFull output: {path}\nPreview:\n{output[:2000]}\n</persisted-output>"
```

Le fichier est nommé d'après le `tool_use_id` (unicité garantie par l'API) ; le `if not path.exists()` évite une réécriture. Le marqueur `<persisted-output>` donne au modèle le chemin complet **et** un aperçu de 2 000 caractères : il sait où relire l'intégralité avec `read_file`.

### `tool_result_budget(messages, max_bytes=200_000)` — lignes 339–353 (L3)
Budget appliqué au **dernier message seulement** (celui qui vient d'être produit par le tour d'outils).

```python
def tool_result_budget(messages, max_bytes=200_000):
    last = messages[-1] if messages else None
    if not last or last.get("role") != "user" or not isinstance(last.get("content"), list): return messages
    blocks = [(i, b) for i, b in enumerate(last["content"]) if isinstance(b, dict) and b.get("type") == "tool_result"]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes: return messages
    ranked = sorted(blocks, key=lambda p: len(str(p[1].get("content", ""))), reverse=True)
    for _, block in ranked:
        if total <= max_bytes: break
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD: continue
        tid = block.get("tool_use_id", "unknown")
        block["content"] = persist_large_output(tid, content)
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    return messages
```

- Ligne 343 : si le total des tool_results du dernier message ≤ 200 KB, rien à faire.
- Ligne 345 : tri décroissant par taille — on persiste d'abord les plus gros (gain maximal par opération).
- Ligne 349 : les blocs ≤ 30 KB (`PERSIST_THRESHOLD`) ne sont **jamais** persistés — conséquence : un message composé de nombreux blocs moyens peut rester au-dessus du budget sans recours (cas limite assumé, L2 s'en chargera au tour suivant).
- Ligne 352 : recalcul complet du total après chaque persistance (O(n²), négligeable ici).

### `write_transcript(messages)` — lignes 357–362 (support de L4)
Archive la conversation complète dans `.transcripts/transcript_<epoch>.jsonl`, un message JSON par ligne (`default=str` pour sérialiser les objets SDK). C'est la garantie « rien n'est vraiment perdu » — même si, comme le note le README, la version pédagogique n'offre **pas** d'outil de relecture du transcript.

### `summarize_history(messages)` — lignes 364–373 (support de L4)

```python
def summarize_history(messages):
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = ("Summarize this coding-agent conversation so work can continue.\n"
              "Preserve: 1. current goal, 2. key findings/decisions, 3. files read/changed, "
              "4. remaining work, 5. user constraints.\nBe compact but concrete.\n\n" + conversation)
    response = client.messages.create(model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=2000)
    return "\n".join(...).strip() or "(empty summary)"
```

- Ligne 365 : la conversation sérialisée est plafonnée à 80 000 caractères — l'appel de résumé ne doit pas lui-même exploser le contexte.
- Lignes 366–368 : le prompt impose 5 catégories à préserver (objectif courant, découvertes/décisions, fichiers lus/modifiés, travail restant, contraintes utilisateur) — la version CC en exige 9, avec analyse préalable en `<analysis>` et interdiction absolue d'appels d'outils.
- Ligne 369 : appel **sans** `tools` ni `system` — un pur appel de résumé, `max_tokens=2000`.
- Ligne 373 : repli `"(empty summary)"` si le modèle ne renvoie aucun texte.

### `compact_history(messages)` — lignes 375–379 (L4)

```python
def compact_history(messages):
    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = summarize_history(messages)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]
```

L'ordre est significatif : **archiver d'abord, résumer ensuite**. Le retour est radical — toute la conversation devient un unique message user `[Compacted]`. Le vrai CC ré-attache ensuite fichiers récents, plans et contexte agent/skill/outils ; ici, seul le résumé survit.

### `reactive_compact(messages)` — lignes 383–391 (urgence)

```python
def reactive_compact(messages):
    transcript = write_transcript(messages)
    summary = summarize_history(messages)
    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    return [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}, *messages[tail_start:]]
```

Différence avec L4 : on garde les **5 derniers messages** (le travail immédiat) après le résumé, avec la même garde de frontière `tool_use`/`tool_result` que `snip_compact` (lignes 387–390). Déclenchée seulement quand l'API a déjà refusé l'appel.

### `TOOLS` — lignes 398–418 et `TOOL_HANDLERS` — lignes 420–424
9 outils : les 8 de s07 + `compact` (lignes 416–417, paramètre optionnel `focus`). Particularité : `compact` est dans `TOOLS` mais **absent de `TOOL_HANDLERS`** — il est intercepté spécialement par `agent_loop` (ligne 488) car il doit muter `messages`, ce qu'un handler ordinaire (qui ne reçoit que `block.input`) ne peut pas faire.

### `trigger_hooks(event, *args)` — lignes 428–432, `permission_hook(block)` — lignes 435–439, `log_hook(block)` — lignes 440–442
Système de hooks **réduit** par rapport à [[s04-hooks]] : seuls `PreToolUse` et `PostToolUse` subsistent (ligne 427) ; `register_hook`, `UserPromptSubmit`, `Stop`, `context_inject_hook` et `summary_hook` ont disparu, l'enregistrement se fait par `append` direct (lignes 444–445). Le nag reminder de [[s05-todo-write]] (`rounds_since_todo`) a aussi été retiré de la boucle — élagage volontaire pour concentrer la session sur la compaction.

### `agent_loop(messages)` — lignes 454–509
**Refondue.** C'est ici que le pipeline s'insère.

```python
def agent_loop(messages: list):
    reactive_retries = 0
    while True:
        # s08 change: three preprocessors (0 API calls, cheap first)
        # Order matches CC source: budget → snip → micro
        messages[:] = tool_result_budget(messages)    # L3: persist large results first
        messages[:] = snip_compact(messages)          # L1: trim middle
        messages[:] = micro_compact(messages)         # L2: old result placeholders

        # s08 change: tokens still over threshold → LLM summary (1 API call)
        if estimate_size(messages) > CONTEXT_LIMIT:
            print("[auto compact]")
            messages[:] = compact_history(messages)
```

- Lignes 459–461 : `messages[:] = ...` — affectation **par tranche**, qui modifie la liste en place : l'appelant (`history` du REPL) voit la compaction, pas seulement la variable locale.
- Ordre budget → snip → micro : persister avant d'écraser (cf. « Rôle dans le harness »).

```python
        try:
            response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=8000)
            reactive_retries = 0  # reset on successful API call
        except Exception as e:
            if ("prompt_too_long" in str(e).lower() or "too many tokens" in str(e).lower()) and reactive_retries < MAX_REACTIVE_RETRIES:
                print("[reactive compact]")
                messages[:] = reactive_compact(messages)
                reactive_retries += 1
                continue
            raise
```

- Ligne 472 : détection par inspection du message d'erreur (deux variantes textuelles), faute de classe d'exception dédiée dans cette version.
- Lignes 470 et 475 : le compteur se réinitialise à chaque appel réussi et se borne à `MAX_REACTIVE_RETRIES = 1` — après quoi l'exception est relancée. La récupération d'erreurs complète arrive en [[s11-error-recovery]].

```python
        for block in response.content:
            if block.type != "tool_use": continue
            print(f"\033[36m> {block.name}\033[0m")

            # s08: compact tool triggers compact_history, not a no-op string
            if block.name == "compact":
                messages[:] = compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. Conversation history has been summarized.]"})
                messages.append({"role": "user", "content": results})
                break  # end current turn, start fresh with compacted context
            ...
        else:
            # normal path: no compact was called
            messages.append({"role": "user", "content": results})
            continue
        # compact was called: results already appended above
        continue
```

- Lignes 488–493 : l'outil `compact` court-circuite tout — résumé immédiat, accusé de réception en `tool_result`, puis `break`. Les `tool_use` restants de la même réponse sont **abandonnés** sans résultat.
- Lignes 504–509 : construction `for…else` — le `else` ne s'exécute que si la boucle s'est terminée **sans** `break` (chemin normal : on appende les résultats). Après un `break` (compact), on saute le `else` et on `continue` directement. Lecture piégeuse mais idiomatique.
- Subtilité problématique : après `compact_history`, `messages` ne contient plus le `tool_use` d'origine — le `tool_result` appendu ligne 492 référence donc un `tool_use_id` orphelin, ce que l'API Anthropic rejette normalement au tour suivant (cf. Pièges).

### Bloc `__main__` — lignes 512–524
REPL simplifié (plus de hook `UserPromptSubmit`). Anomalie cosmétique : la ligne 514 affiche du **chinois** non traduit (`"输入问题，回车发送。输入 q 退出。"` — « tapez une question, Entrée pour envoyer, q pour quitter »), vestige de la version originale du dépôt.

## Ce qui change par rapport à [[s07-skill-loading]]

- **Nouveau** : constantes `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` (52–53), `CONTEXT_LIMIT`/`KEEP_RECENT`/`PERSIST_THRESHOLD` (265–267), `MAX_REACTIVE_RETRIES` (452).
- **Nouveau** : helpers `estimate_size` (269), `_block_type` (271–272), `_message_has_tool_use` (275–281), `_is_tool_result_message` (284–291).
- **Nouveau** : pipeline `snip_compact` (295–309), `collect_tool_results` (313–320), `micro_compact` (322–328), `persist_large_output` (332–337), `tool_result_budget` (339–353), `write_transcript` (357–362), `summarize_history` (364–373), `compact_history` (375–379), `reactive_compact` (383–391).
- **Nouveau** : outil `compact` (416–417) — 8 outils deviennent 9 ; traité spécialement dans la boucle, pas dans `TOOL_HANDLERS`.
- **Modifié** : `agent_loop` (454–509) — préprocesseurs avant chaque appel, try/except réactif, interception de `compact` via `for…else`.
- **Modifié** : `_parse_frontmatter` (59–70) — parsing naïf, suppression de la dépendance pyyaml.
- **Modifié (bug)** : `spawn_subagent(task)` (225) — paramètre renommé, schéma de l'outil non mis à jour.
- **Supprimé** : hooks `UserPromptSubmit`/`Stop`, `register_hook`, `context_inject_hook`, `summary_hook` ; nag reminder et `rounds_since_todo` ; `DENY_LIST` raccourcie.

## Pièges et détails d'implémentation

- **Bug réel — l'outil `task` est cassé** : schéma `{"description": ...}` (lignes 411–412) vs signature `spawn_subagent(task)` (ligne 225) → `TypeError` non rattrapée au premier appel de `task` par le modèle.
- **Le `tool_result` orphelin de `compact`** : après remplacement de l'historique par `[Compacted]`, le `tool_result` appendu (lignes 490–492) référence un `tool_use` qui n'existe plus — l'API exige qu'un `tool_result` réponde à un `tool_use` du message assistant précédent, l'appel suivant risque donc un 400. De plus, les autres `tool_use` du même tour sont abandonnés par le `break`.
- **L'ordre du pipeline n'est pas la numérotation** : budget (L3) → snip (L1) → micro (L2). Inverser micro et budget détruirait les contenus avant leur sauvegarde sur disque — c'est exactement pourquoi le vrai CC exécute `applyToolResultBudget` en premier.
- **Tout est en caractères, rien n'est en tokens** : `estimate_size = len(str(msgs))`, seuils 50 000 / 200 000 / 30 000 caractères. Approximations volontaires (~4 caractères/token).
- **Les gardes de frontière sont le vrai sujet de L1** : couper une paire `tool_use`/`tool_result` rend l'historique invalide pour l'API. `snip_compact` et `reactive_compact` partagent la même précaution (extension de tête, recul de queue, abandon si croisement).
- **L3 ignore les blocs moyens** : `if len(content) <= PERSIST_THRESHOLD: continue` — vingt blocs de 25 KB (500 KB au total) passent au travers du budget ; seul L2 les rattrapera au tour suivant.

## Liens

- Session précédente : [[s07-skill-loading]]
- Session suivante : [[s09-memory]]
- Sessions liées : [[s11-error-recovery]] (gestion complète de `prompt_too_long` et des autres erreurs), [[s09-memory]] (ce qui doit survivre à la compaction), [[s10-system-prompt]] (ce qui vit hors de l'historique compactable)
