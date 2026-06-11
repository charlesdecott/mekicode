---
title: "s09 · Mémoire persistante"
session: 09
phase: "Contexte & mémoire"
fichier: "inspiration/learn-claude-code/s09_memory/code.py"
lignes: 656
tags: [memoire, frontmatter, compaction, llm-side-query, consolidation]
prev: "s08-context-compact"
next: "s10-system-prompt"
---

# s09 · Mémoire persistante

> **En une phrase** : un magasin de fichiers Markdown (`.memory/`) avec index, sélection à la demande, extraction automatique après chaque tour et consolidation périodique — une couche de connaissance qui survit à la compaction et aux sessions.

## Rôle dans le harness

La session [[s08-context-compact]] a appris à l'agent à compresser son contexte quand il déborde. Mais la compression est **avec perte** : « utilise des tabs, pas des espaces » peut devenir « l'utilisateur a des préférences de style » dans le résumé, et au lancement d'une nouvelle session, même le résumé a disparu. Le README le formule ainsi : *« Compression loses details, keep a layer that doesn't »* — il faut une couche de stockage qui ne participe pas à la compression et persiste entre les sessions.

La solution est un répertoire `.memory/` où chaque souvenir est un fichier `.md` avec frontmatter YAML (`name` / `description` / `type`), plus un index `MEMORY.md` (une ligne par souvenir). Le design clé, souligné par le README : **l'index vit dans le prompt SYSTEM** (peu coûteux, compatible prompt caching), tandis que **le contenu des fichiers est injecté à la demande**, sélectionné par une side-query LLM qui compare la conversation récente au catalogue nom + description. L'écriture a deux chemins : l'utilisateur dit explicitement « remember », ou l'extraction tourne en arrière-plan à la fin de chaque tour. Quand les fichiers s'accumulent, une consolidation déduplique.

Dans le vrai Claude Code, ce mécanisme existe sous une forme plus riche : la sélection est faite par une side-query Sonnet (pas par embeddings), l'extraction est déclenchée par un *stop hook* en fire-and-forget via un agent forké à permissions restreintes, et la consolidation s'appelle **Dream**, gardée par quatre verrous (intervalle de temps, throttle de scan, nombre de sessions, fichier de lock). La version pédagogique simplifie en un seuil de comptage de fichiers, mais la direction est identique. Quatre types de mémoire répondent chacun à une question : `user` (qui tu es), `feedback` (comment travailler), `project` (ce qui se passe), `reference` (où trouver les choses).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–25 | Docstring | Layout de `.memory/`, flux en 5 étapes dans `agent_loop` |
| 27–49 | Imports & configuration | readline, dotenv, chemins (`.memory/`, `.transcripts/`, `.task_outputs/`), client, `MODEL` |
| 52–351 | **NOUVEAU : système de mémoire** | frontmatter, CRUD fichiers, index, sélection LLM, extraction, consolidation, `build_system` |
| 354–441 | Repris de s02–s07 | outils de base (`run_bash`…), `extract_text`, subagent |
| 444–549 | Repris de [[s08-context-compact]] | pipeline de compaction complet (snip, micro, budget, compact, reactive) |
| 552–574 | Définitions d'outils | 6 outils (squelette réduit pour se concentrer sur la mémoire) |
| 577–640 | `agent_loop` | injection mémoire + pipeline s08 + extraction post-tour |
| 643–655 | REPL | boucle interactive |

## Constantes et configuration

- `MEMORY_DIR = WORKDIR / ".memory"` — ligne 43, créé immédiatement (`mkdir(exist_ok=True)`).
- `MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"` — ligne 44, l'index injecté dans SYSTEM.
- `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` — lignes 46–47, hérités de s08 (transcripts avant compaction, sorties d'outils persistées).
- `MEMORY_TYPES = ["user", "feedback", "project", "reference"]` — ligne 56. Déclaré mais jamais utilisé pour valider le champ `type` (voir Pièges).
- `CONSOLIDATE_THRESHOLD = 10` — ligne 285 : la consolidation se déclenche à partir de 10 fichiers mémoire.
- `CONTEXT_LIMIT = 50000; KEEP_RECENT = 3; PERSIST_THRESHOLD = 30000` — ligne 448, seuils du pipeline s08 (taille en caractères, pas en tokens).
- `MAX_REACTIVE_RETRIES = 1` — ligne 581 : un seul compact réactif par appel d'`agent_loop`.
- `SUB_SYSTEM` — lignes 347–351 : prompt système du subagent (« Complete the task… Do not delegate further »).
- `TOOLS` / `TOOL_HANDLERS` — lignes 556–569 / 571–574 : 6 outils (`bash`, `read_file`, `write_file`, `edit_file`, `glob`, `task`). Le README note que s09 réduit volontairement la palette (s08 en avait 9) pour se concentrer sur la mémoire.
- `SUB_TOOLS` / `SUB_HANDLERS` — lignes 407–414 / 415 : les 3 outils du subagent.

## Les fonctions, une à une

### `_parse_frontmatter(text)` — lignes 58–69

Parseur YAML minimaliste : sépare le frontmatter du corps d'un fichier mémoire et retourne `(meta: dict, body: str)`.

```python
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, parts[2].strip()
```

- Ligne 61 : `split("---", 2)` coupe au plus en 3 morceaux — `parts[1]` est le bloc YAML, `parts[2]` le corps (qui peut donc contenir des `---` sans casser le parsing).
- Lignes 65–68 : pas de vraie librairie YAML — chaque ligne `clé: valeur` est coupée au premier `:`, puis les guillemets simples/doubles sont retirés. Suffisant pour 3 champs plats, et zéro dépendance.
- Cas limites gérés : texte sans frontmatter (ligne 59) et frontmatter non fermé (ligne 62) retournent `({}, text)` intact.

### `write_memory_file(name, mem_type, description, body)` — lignes 72–81

L'unique point d'écriture d'un souvenir. Slugifie le nom, écrit le fichier avec frontmatter, puis **reconstruit l'index**.

```python
    slug = name.lower().replace(" ", "-").replace("/", "-")
    filename = f"{slug}.md"
    filepath = MEMORY_DIR / filename
    filepath.write_text(
        f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n"
    )
    _rebuild_index()
```

- Ligne 74 : la slugification remplace espaces et `/` (qui ferait sortir du répertoire) par des tirets. Deux souvenirs de même nom écrasent le même fichier — c'est la déduplication par construction.
- Ligne 80 : l'invariant « index toujours synchronisé » est garanti car toute écriture passe par ici.

### `_rebuild_index()` — lignes 84–95

Régénère `MEMORY.md` à partir de tous les `*.md` du répertoire (en excluant `MEMORY.md` lui-même, ligne 88). Pour chaque fichier : une ligne `- [name](fichier.md) — description`. Ligne 93 : si la description manque, repli sur la première ligne du corps tronquée à 80 caractères. Ligne 95 : l'expression `"\n".join(lines) + "\n" if lines else ""` écrit un fichier vide quand il n'y a aucun souvenir.

### `read_memory_index()` — lignes 98–103

Lit `MEMORY.md` (retourne `""` si absent ou vide). Appelée par `build_system()` : c'est le chemin « index dans SYSTEM », toujours présent et bon marché.

### `read_memory_file(filename)` — lignes 106–111

Lit le contenu intégral d'un fichier mémoire, `None` si inexistant. Utilisée par `load_memories` pour le chemin « contenu à la demande ».

### `list_memory_files()` — lignes 114–129

Scanne `.memory/*.md` (hors index) et retourne une liste de dicts `{filename, name, description, type, body}` en réutilisant `_parse_frontmatter`. C'est le catalogue qui alimente la sélection, l'extraction (anti-doublons) et la consolidation.

### `select_relevant_memories(messages, max_items=5)` — lignes 132–204

Le cœur du chargement à la demande : choisit jusqu'à 5 fichiers mémoire pertinents pour la conversation courante, via une side-query LLM avec repli sur du matching par mots-clés.

```python
    recent_texts = []
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(getattr(b, "text", "")) for b in content
                    if getattr(b, "type", None) == "text"
                )
            if isinstance(content, str):
                recent_texts.append(content)
            if len(recent_texts) >= 3:
                break
    recent = " ".join(reversed(recent_texts))[:2000]
```

- Lignes 142–154 : collecte les 3 derniers messages `user` en remontant l'historique (d'où le `reversed` ligne 143, puis le re-`reversed` ligne 154 pour rétablir l'ordre chronologique), plafonné à 2000 caractères. Les contenus en liste (tool_results) ne produisent que leurs blocs texte.
- Lignes 160–172 : construit un catalogue indexé `"0: nom — description"` et un prompt qui demande **uniquement un tableau JSON d'entiers** (`[0, 3]`).

```python
        text = extract_text(response.content).strip()
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            indices = json.loads(match.group())
            selected = []
            for idx in indices:
                if isinstance(idx, int) and 0 <= idx < len(files):
                    selected.append(files[idx]["filename"])
```

- Ligne 182 : la regex **non gourmande** `\[.*?\]` capture le premier tableau JSON même si le modèle bavarde autour. (Comparer avec `extract_memories` qui utilise la version gourmande — voir Pièges.)
- Lignes 186–191 : validation défensive de chaque indice (type entier, bornes) et plafond `max_items`.
- Lignes 195–204 : **repli sans LLM** si l'appel échoue (exception avalée lignes 192–193) — tout mot de plus de 3 lettres de la conversation récente est cherché dans `name + description` de chaque souvenir. C'est exactement la simplification que le README revendique : « LLM side-query + keyword fallback ».

### `load_memories(messages)` — lignes 207–219

Assemble le bloc à injecter : appelle `select_relevant_memories`, lit chaque fichier retenu et enveloppe le tout dans `<relevant_memories>…</relevant_memories>`. Retourne `""` s'il n'y a rien — l'appelant peut alors ne rien injecter du tout.

### `extract_memories(messages)` — lignes 222–282

L'écriture automatique : après chaque tour, une side-query LLM fouille le dialogue récent à la recherche de préférences, contraintes ou faits de projet.

```python
    for msg in messages[-10:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        ...
        if isinstance(content, str) and content.strip():
            dialogue_parts.append(f"{role}: {content}")
```

- Lignes 225–236 : sérialise les 10 derniers messages en `role: texte` (les blocs non textuels sont ignorés).
- Lignes 242–243 : les souvenirs **existants** sont listés dans le prompt (`Existing memories:`) — c'est l'anti-doublon : « If nothing new or already covered by existing memories, return [] ».
- Lignes 245–256 : le prompt impose un schéma `{name, type, description, body}` avec `name` en kebab-case et `type` parmi les 4 valeurs, et tronque le dialogue à 4000 caractères.

```python
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return
        items = json.loads(match.group())
        ...
        for mem in items:
            name = mem.get("name", f"memory_{int(time.time())}")
            ...
            if desc and body:
                write_memory_file(name, mem_type, desc, body)
                count += 1
```

- Ligne 264 : ici la regex est **gourmande** (`\[.*\]`) : les objets JSON contiennent eux-mêmes des crochets potentiels, il faut capturer jusqu'au dernier `]`.
- Lignes 271–277 : chaque item valide (description ET corps non vides) devient un fichier ; les champs manquants ont des défauts (`memory_<timestamp>`, type `user`).
- Lignes 281–282 : `except Exception: pass` — un échec d'extraction est totalement silencieux, l'agent continue.

### `consolidate_memories()` — lignes 287–333

Le « Dream » pédagogique : quand `list_memory_files()` atteint `CONSOLIDATE_THRESHOLD` (10), tous les souvenirs sont envoyés au LLM avec 4 règles (fusionner les doublons, supprimer l'obsolète, rester sous 30 souvenirs, préserver les préférences utilisateur), qui renvoie la liste consolidée.

```python
        items = json.loads(match.group())

        # Remove old memory files (keep MEMORY.md)
        for f in MEMORY_DIR.glob("*.md"):
            if f.name != "MEMORY.md":
                f.unlink()

        for mem in items:
            ...
            if desc and body:
                write_memory_file(name, mem_type, desc, body)
```

- Ordre décisif : le JSON est parsé **avant** la suppression (ligne 316 vs lignes 319–321) — si la réponse est malformée, l'exception part avant tout `unlink()` et les fichiers sont intacts.
- Le catalogue envoyé est tronqué à 16000 caractères (ligne 305) et la réponse plafonnée à 3000 tokens : une consolidation très volumineuse peut donc être tronquée (voir Pièges).
- Le README détaille la version réelle : CC utilise quatre verrous (≥ 24 h depuis la dernière consolidation, throttle de scan, ≥ 5 transcripts modifiés, fichier `.consolidate-lock` avec expiration 1 h) et un agent forké pour fusionner.

### `build_system()` — lignes 337–345

Construit le prompt SYSTEM **avec l'index** :

```python
    index = read_memory_index()
    memories_section = f"\n\nMemories available:\n{index}" if index else ""
    return (
        f"You are a coding agent at {WORKDIR}."
        f"{memories_section}\n"
        "Relevant memories are injected below. Respect user preferences from memory.\n"
        "When the user says 'remember' or expresses a clear preference, extract it as a memory."
    )
```

C'est une fonction (et plus une constante comme `SYSTEM` en s08) car l'index change entre les tours. Elle est appelée **une fois par tour utilisateur** (ligne 589) : le README insiste — extraction et consolidation ne tournent qu'en fin de tour, donc SYSTEM reste stable pendant tout le tour, ce qui ménage le prompt cache.

### Helpers outils — lignes 358–404 (repris de [[s02-tool-use]]/[[s03-permission]])

`safe_path` (358–361), `run_bash` (363–368), `run_read` (370–375), `run_write` (377–381), `run_edit` (383–390), `run_glob` (392–400) et `extract_text` (402–404) : repris des sessions Fondamentaux sans modification (sandbox de chemin, timeout 120 s, troncature à 50000 caractères, etc.).

### `SUB_TOOLS`, `SUB_HANDLERS`, `spawn_subagent(task)` — lignes 407–441 (repris de [[s06-subagent]])

Subagent simplifié repris de s06–s07 : boucle de 30 tours max avec 3 outils, et récupération du dernier texte assistant si la boucle s'épuise (lignes 433–439). Aucun changement lié à la mémoire — le subagent n'écrit ni ne lit `.memory/`.

### Pipeline de compaction — lignes 448–549 (repris de [[s08-context-compact]] sans modification)

- `estimate_size` (450) : taille = `len(str(msgs))`, en caractères.
- `_block_type` (452–453), `_message_has_tool_use` (455–461), `_is_tool_result_message` (463–469) : prédicats de structure de message.
- `snip_compact(msgs, mx=50)` (471–483) : coupe le milieu en gardant 3 messages de tête et la queue, avec ajustement des bornes pour ne jamais séparer un `tool_use` de son `tool_result`.
- `collect_tool_results` (485–491), `micro_compact` (493–498) : remplace les vieux tool_results (> 120 caractères, hors les 3 plus récents) par `"[Earlier tool result compacted.]"`.
- `persist_large` (500–505), `tool_result_budget` (507–519) : les sorties > 30000 caractères du dernier message sont déchargées sur disque avec un aperçu de 2000 caractères.
- `write_transcript` (521–526), `summarize_history` (528–534), `compact_history` (536–539), `reactive_compact` (541–549) : sauvegarde JSONL puis résumé LLM en 5 points ; la variante réactive garde les ~5 derniers messages derrière le résumé.

Tous expliqués en détail dans [[s08-context-compact]].

### `agent_loop(messages)` — lignes 583–640

La boucle s08 augmentée de trois moments mémoire : **injection** au début du tour, **snapshot** avant compression, **extraction + consolidation** à la fin du tour.

```python
def agent_loop(messages: list):
    reactive_retries = 0
    # s09: inject relevant memory content into the current user turn
    memories_content = load_memories(messages)
    memory_turn = len(messages) - 1 if messages and isinstance(messages[-1].get("content"), str) else None
    # s09: build system once per user turn; memory is updated after the loop returns
    system = build_system()
```

- Ligne 586 : **une seule** side-query de sélection par tour utilisateur, pas à chaque itération de la boucle.
- Ligne 587 : `memory_turn` mémorise l'indice du message où injecter — uniquement si le dernier message a un contenu `str` (un vrai tour utilisateur tapé au clavier, pas une liste de tool_results).
- Ligne 589 : SYSTEM figé pour tout le tour (voir `build_system`).

```python
        # s09: save pre-compression snapshot for accurate memory extraction
        pre_compress = [m if isinstance(m, dict) else {"role": m.get("role",""),
            "content": str(m.get("content",""))} for m in messages]

        # s08: compression pipeline (budget → snip → micro)
        messages[:] = tool_result_budget(messages)
        messages[:] = snip_compact(messages)
        messages[:] = micro_compact(messages)
```

- Lignes 593–594 : le snapshot `pre_compress` est repris à **chaque itération**, avant que le pipeline ne mutile les messages. C'est lui (et pas `messages`) qui sera donné à `extract_memories` : on extrait depuis le texte original, pas depuis `"[Earlier tool result compacted.]"`.
- Lignes 597–599 : l'affectation par tranche `messages[:] = ...` mute la liste en place, pour que l'historique de l'appelant (le REPL) voie les compactions.

```python
            request_messages = messages
            if memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {
                    **messages[memory_turn],
                    "content": memories_content + "\n\n" + messages[memory_turn]["content"],
                }
```

- Lignes 606–612 : l'injection est **non destructive** — on copie la liste (copie superficielle) et on remplace seulement l'élément `memory_turn` par un nouveau dict dont le contenu est préfixé par `<relevant_memories>…`. L'historique persistant ne contient jamais le texte des souvenirs : pas de duplication au tour suivant, pas de pollution des transcripts.
- Le garde `memory_turn < len(messages)` protège contre le rétrécissement de la liste par `compact_history` (sinon `IndexError`).
- Lignes 617–623 : repli `reactive_compact` (1 essai, `MAX_REACTIVE_RETRIES`) sur erreur `prompt_too_long` — repris de s08.

```python
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            # s09: extract from pre-compression snapshot for full fidelity
            extract_memories(pre_compress)
            consolidate_memories()
            return
```

- Lignes 626–630 : le déclencheur d'écriture est `stop_reason != "tool_use"` — la fin naturelle du tour. Le README rapproche cela du *stop hook* de CC (`stopHooks.ts`), qui déclenche extraction et Dream en fire-and-forget.
- Lignes 632–640 : exécution d'outils inchangée par rapport à s08.

### REPL — lignes 643–655

Boucle interactive standard : `input()`, ajout du tour à `history`, `agent_loop(history)`, affichage des blocs texte de la dernière réponse. Particularité : la ligne 645 affiche les instructions **en chinois** (`输入问题，回车发送。输入 q 退出。`) — vestige du dépôt d'origine, les sessions suivantes sont en anglais.

## Ce qui change par rapport à [[s08-context-compact]]

- **Nouveau bloc complet « Memory System »** (lignes 52–351) : `_parse_frontmatter`, `write_memory_file`, `_rebuild_index`, `read_memory_index`, `read_memory_file`, `list_memory_files`, `select_relevant_memories`, `load_memories`, `extract_memories`, `consolidate_memories`, plus `MEMORY_TYPES` et `CONSOLIDATE_THRESHOLD`.
- **`SYSTEM` (constante) → `build_system()` (fonction)** : le prompt système embarque désormais l'index `MEMORY.md` et des consignes mémoire, et est reconstruit une fois par tour utilisateur.
- **`agent_loop` enrichie** : sélection/injection des souvenirs dans le tour utilisateur courant (lignes 586–587, 606–612), snapshot pré-compression (593–594), extraction + consolidation en fin de tour (627–629). Le pipeline de compression s08 (budget → snip → micro → auto compact → reactive compact) est conservé tel quel.
- **Palette d'outils réduite** : s08 exposait 9 outils (dont `todo_write`, `load_skill`, `compact`) ; s09 n'en garde que 6 (`bash`, `read_file`, `write_file`, `edit_file`, `glob`, `task`) pour focaliser la session — c'est documenté dans le tableau « Changes From s08 » du README.
- **Nouveaux répertoires** : `.memory/` (créé au chargement du module, ligne 43) en plus de `.transcripts/` et `.task_outputs/` hérités.

## Pièges et détails d'implémentation

- **Deux regex différentes pour le même travail** : `select_relevant_memories` utilise `\[.*?\]` (non gourmand — un tableau d'entiers ne contient pas de `]` interne), `extract_memories` et `consolidate_memories` utilisent `\[.*\]` (gourmand — les objets `{...}` du tableau peuvent contenir des crochets). Inverser les deux casserait le parsing.
- **`MEMORY_TYPES` n'est jamais consulté** : la liste de la ligne 56 documente les 4 types mais aucun code ne valide que `mem_type` en fait partie — un LLM qui renvoie `type: "misc"` sera écrit tel quel.
- **L'injection mémoire survit mal à une compaction en plein tour** : si `compact_history` réduit l'historique à 1 message, `memory_turn` (capturé avant la boucle) pointe sur l'indice 0… qui est désormais le résumé `[Compacted]`. Le garde `memory_turn < len(messages)` évite le crash, mais les souvenirs se retrouvent préfixés au résumé — inoffensif mais inattendu.
- **Échecs 100 % silencieux** : `extract_memories` et `consolidate_memories` avalent toute exception (`except Exception: pass`). Si `MODEL_ID` pointe vers un modèle indisponible, la mémoire ne se remplit jamais et rien ne le signale.
- **Consolidation = remplacement total** : tous les fichiers sont supprimés puis réécrits depuis la réponse LLM. Le parsing a lieu avant la suppression (sécurité), mais une réponse tronquée par `max_tokens=3000` qui reste un JSON valide peut silencieusement perdre des souvenirs.
- **Le snapshot `pre_compress` n'est fidèle que pour l'itération courante** : il est refait à chaque tour de boucle, donc les détails déjà détruits par `micro_compact` aux itérations précédentes sont perdus pour l'extraction. « Full fidelity » (commentaire ligne 627) est relatif.

## Liens

- Session précédente : [[s08-context-compact]]
- Session suivante : [[s10-system-prompt]]
- Sessions liées : [[s07-skill-loading]] (même patron « index léger + chargement à la demande » pour les skills), [[s06-subagent]] (le subagent repris ici), [[s10-system-prompt]] (la section mémoire devient un segment du prompt assemblé), [[s14-cron-scheduler]] (autre mécanisme déclenché périodiquement)
