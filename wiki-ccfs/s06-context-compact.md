---
title: "s06 · Context Compact"
session: 06
phase: "Connaissance & contexte"
fichier: "inspiration/claude-code-from-scratch/s06_context_compact.py"
lignes: 252
tags: [compression, contexte, memoire, summarization, persistance]
prev: "s05-skill-loading"
next: "s07-task-system"
---

# s06 · Context Compact

> **En une phrase** : quand l'historique dépasse ~40 000 caractères, les vieux tours sont condensés par le modèle lui-même en un résumé, persisté sur disque dans `.agent_memory.md`, et l'historique est reconstruit — 1 résumé + 6 messages récents verbatim — pour que le contexte respire et que la mémoire survive aux redémarrages.

## Rôle dans le harness

Le motto de la session : *« Context will fill up; you need a way to make room »*. Toute session longue finit par saturer la fenêtre de contexte : erreurs API, coût croissant, et surtout dégradation du raisonnement bien avant la limite dure — le README de la phase 2 parle de *« compressing conversation history before it degrades reasoning quality »*. C'est aussi le troisième principe du harness engineering énoncé en tête de README : *« Context is a managed resource — what the model sees at each turn is curated, compressed, and injected deliberately »*.

L'architecture est en **trois couches** (docstring, lignes 12–19) : couche 1, les `KEEP_RECENT` derniers messages gardés **verbatim** (mémoire de travail immédiate) ; couche 2, les messages plus anciens **résumés** par un appel LLM dédié (décisions techniques, chemins de fichiers, changements de code, tâches en attente) ; couche 3, le résumé **persisté** dans un fichier Markdown, relu au prochain démarrage — le contexte traverse les sessions. Le déclenchement est automatique, par estimation de taille en caractères après chaque tour complet.

L'analogue dans le vrai Claude Code, selon le tableau du README : le **« Compressor `wU2` at 92% »** — la compaction automatique qui se déclenche quand le contexte approche sa capacité (commande `/compact` en manuel). La couche 3 évoque les fichiers de mémoire persistante de CC. Le projet jumeau learn-claude-code répartit ces mécanismes sur deux sessions (compaction en s08, mémoire disque en s09) ; ici les deux sont fusionnés dans un seul fichier. Particularité notable : la session n'ajoute **aucun outil** — le mécanisme vit entièrement dans le harness, invisible du modèle, qui ne « voit » que son historique raccourci.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–24 | Shebang & docstring | Architecture 3 couches, déclencheur par seuil |
| 26–30 | Imports stdlib | `os`, `sys`, `Path`, typing |
| 32–39 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 41–50 | Configuration | `COMPRESS_THRESHOLD`, `KEEP_RECENT`, `MEMORY_FILE` |
| 54–81 | **Nouveau** | `_estimate_size()` : mesure du contexte |
| 84–120 | **Nouveau** | `_summarize()` : la couche 2 (appel LLM compresseur) |
| 123–181 | **Nouveau** | `maybe_compress()` : garde-fous, découpe, reconstruction |
| 184–196 | **Nouveau** | `agent_loop_with_compression()` : la boucle enveloppée |
| 199–247 | REPL | `main()` : restauration mémoire + boucle interactive |
| 250–252 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`COMPRESS_THRESHOLD = 40_000` (ligne 44)** : seuil de déclenchement en caractères — l'heuristique ~4 caractères/token donne ≈ 10 000 tokens. Le commentaire l'assume : c'est un proxy, pas un comptage de tokens réel.
- **`KEEP_RECENT = 6` (ligne 47)** : la taille de la couche 1 — six **messages** (pas six tours : un tour avec outils consomme plusieurs messages).
- **`MEMORY_FILE = Path(".agent_memory.md")` (ligne 50)** : la couche 3 — chemin **relatif au répertoire courant**, donc une mémoire par dossier de travail.

## Les fonctions, une à une

### `_estimate_size(messages)` — lignes 54–81

Additionne les longueurs de caractères de tout l'historique, en gérant les trois formes que peut prendre `content` :

```python
        if isinstance(content, str):
            total += len(content)
        # Handle structured list content (usually assistant or tool results)
        elif isinstance(content, list):
            for block in content:
                # Check for dictionary-style blocks
                if isinstance(block, dict):
                    total += len(str(block.get("text", "") or block.get("content", "")))
                # Check for Anthropic SDK block objects
                elif hasattr(block, "text"):
                    total += len(block.text or "")
```

- **Ligne 71** : chaîne simple — typiquement les messages utilisateur.
- **Ligne 77** : blocs dict — les `tool_result` fabriqués par le harness (`content`) ou des blocs texte sérialisés (`text`).
- **Ligne 80** : objets du SDK — les messages assistant stockent `response.content` tel quel, donc des `TextBlock` (qui ont `.text`). Les `ToolUseBlock`, eux, n'ont pas d'attribut `.text` : **ils comptent pour zéro**. L'estimation sous-évalue donc systématiquement — acceptable pour un déclencheur, pas pour de la facturation.

### `_summarize(messages)` — lignes 84–120

La couche 2 : confie au modèle la condensation des vieux messages. D'abord un aplatissement textuel `[role]: texte` (lignes 95–104 — même logique d'extraction que `_estimate_size`, les blocs sans `.text` produisant des chaînes vides), puis l'appel :

```python
    response = client.messages.create(
        model=MODEL,
        system=(
            "You are a context compressor. Summarize the provided conversation history "
            "concisely. Retain all critical technical decisions, file paths mentioned, "
            "code changes made, and pending tasks. Ignore trivial back-and-forth."
        ),
        messages=[{"role": "user", "content": f"Summarize this history:\n\n{text_to_summarize[:20000]}"}],
        max_tokens=2000,
    )
```

- C'est un **appel one-shot direct** (`client.messages.create`), pas `stream_loop` : le compresseur n'a pas d'outils, pas de boucle — un sous-programme LLM à rôle unique, comme le subagent de [[s04-subagent]] mais réduit à un seul échange.
- Le prompt système énumère ce qu'il faut **préserver** : décisions techniques, chemins de fichiers, changements de code, tâches en attente — la définition opérationnelle de « l'important » pour un agent de code. Le reste (*« trivial back-and-forth »*) est sacrifié.
- **Ligne 115** : la tranche `[:20000]` protège l'appel de résumé lui-même d'un dépassement — mais tout ce qui se trouve au-delà de 20 000 caractères est **perdu sans avertissement** (voir Pièges).
- **`max_tokens=2000`** borne le résumé : la compression a un taux plancher garanti.
- **Ligne 120** : reconstruction du texte en ne gardant que les blocs ayant `.text`.

### `maybe_compress(messages)` — lignes 123–181

L'orchestrateur : évalue, découpe, résume, persiste, reconstruit — **en place**.

```python
    old_messages = messages[:-KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]

    # Layer 2: Generate the textual summary
    summary = _summarize(old_messages)

    # Layer 3: Persist summary to a Markdown file on disk
    try:
        MEMORY_FILE.write_text(
            f"# Agent Context Memory\n*Last updated: {os.getcwd()}*\n\n{summary}\n",
            encoding="utf-8",
        )
```

- **Deux gardes en amont** (lignes 137–142) : taille sous le seuil → `False` ; et `len(messages) <= KEEP_RECENT` → `False` (rien d'« ancien » à compresser, même si les 6 messages sont énormes).
- **Lignes 148–149** : la découpe au couteau `[-KEEP_RECENT:]` — simple, mais aveugle à la structure des tours (voir Pièges : risque de `tool_result` orphelin).
- **Ligne 157** : le bug cocasse de l'en-tête — `*Last updated: {os.getcwd()}*` écrit le **répertoire courant**, pas une date. L'intention était manifestement un timestamp.
- **Lignes 160–161** : l'échec d'écriture disque est signalé en rouge mais **non fatal** — la compression en mémoire continue (couche 3 perdue, couches 1–2 intactes).

La reconstruction (lignes 164–177) :

```python
    messages.clear()
    
    # 1. Inject the summary as the new "starting context"
    messages.append({
        "role": "user",
        "content": f"[Context summary of previous turns]:\n\n{summary}",
    })
    # 2. Add an assistant acknowledgement to maintain the user/assistant turn alternating rule
    messages.append({
        "role": "assistant",
        "content": "Understood. I have integrated the summary of our previous progress into my current context.",
    })
    # 3. Restore the most recent verbatim messages
    messages.extend(recent_messages)
```

- **`messages.clear()` puis `append`/`extend`** : la mutation **en place** est indispensable — `main()` détient la même référence de liste ; un `messages = [...]` local serait invisible de l'appelant.
- **Le faux accusé de réception assistant** (lignes 172–175) : l'API exige l'alternance stricte user/assistant ; le résumé étant injecté comme message user, il faut un message assistant entre lui et le premier message récent (souvent un user). Petit théâtre de marionnettes structurel — le modèle n'a jamais prononcé cette phrase.
- Le rapport de compression (ligne 180) affiche le bilan : N messages → 1 résumé, chemin du fichier mémoire.

### `agent_loop_with_compression(messages)` — lignes 184–196

L'enveloppe minimaliste — c'est le pattern central de la session :

```python
    # 1. Execute the standard autonomous agent loop
    stream_loop(messages, EXTENDED_TOOLS, EXTENDED_DISPATCH)
    
    # 2. Evaluate if the history now needs compression
    maybe_compress(messages)
```

La compression a lieu **après** le tour complet, jamais pendant : `stream_loop` court jusqu'au `stop_reason != "tool_use"`, puis on mesure. Un tour unique très bavard (gros `tool_result` en série) peut donc dépasser largement le seuil avant que la soupape ne s'ouvre — le vrai Claude Code, lui, surveille en continu et compacte à 92 % de la fenêtre. Noter aussi : `stream_loop` est appelée **sans** argument `system` — voir Pièges.

### `main()` — lignes 201–247

Avant le REPL, la restauration de la couche 3 :

```python
    if MEMORY_FILE.exists():
        try:
            mem_content = MEMORY_FILE.read_text(encoding="utf-8")
            print(f"\033[90m  [memory] Restoring context from {MEMORY_FILE}...\033[0m")
            # Seed the history with the saved memory
            history = [
                {"role": "user",      "content": f"[Previous Session Memory]:\n\n{mem_content}"},
                {"role": "assistant", "content": "Memory loaded. I am ready to continue where we left off."},
            ]
```

Même technique que dans `maybe_compress` : la mémoire entre comme message user étiqueté `[Previous Session Memory]`, suivie d'un faux accusé assistant pour préserver l'alternance. L'agent « se souvient » de la session précédente dès le premier prompt. Le reste (lignes 228–247) est le REPL standard : prompt cyan `s06 >> `, sortie sur `EOFError`/`KeyboardInterrupt`, mots de sortie, puis `agent_loop_with_compression(history)` à chaque requête. Le point d'entrée (lignes 250–252) appelle `main()`.

## Ce qui vient de [[core-py]]

- **`client`, `MODEL`** : utilisés directement par `_summarize()` pour l'appel one-shot du compresseur — la seule session de la phase qui parle à l'API en dehors de `stream_loop`.
- **`EXTENDED_TOOLS` / `EXTENDED_DISPATCH`** : la palette standard, passée telle quelle — s06 n'ajoute aucun outil.
- **`stream_loop`** : la boucle de base, enveloppée par `agent_loop_with_compression()` ; faute d'argument `system`, c'est son `DEFAULT_SYSTEM` qui s'applique.

## Pièges et détails d'implémentation

- **`system_prompt` est du code mort** : défini ligne 206 dans `main()`, il n'est jamais passé à quoi que ce soit — `stream_loop` retombe sur le `DEFAULT_SYSTEM` de core.py (quasi identique, avec « Act, don't explain. » en plus). Vestige trompeur à la première lecture.
- **`*Last updated: {os.getcwd()}*`** (ligne 157) : le fichier mémoire estampille un chemin de répertoire là où on attend une date.
- **La découpe `[-KEEP_RECENT:]` ignore les frontières de tours** : si `messages[-6]` est un message user de `tool_result` dont le `tool_use` assistant vient d'être compressé, l'API rejettera l'historique (tool_result orphelin). Avec `KEEP_RECENT` pair et des tours outillés, le cas finit par arriver — le compacteur du vrai CC coupe aux frontières de tours complets.
- **Double troncature silencieuse** : `_estimate_size` ne compte pas les blocs `tool_use` (sous-estimation du déclencheur), et `_summarize` tranche à 20 000 caractères (au-delà, l'historique ancien n'est même pas montré au compresseur).
- **Compression inter-tours seulement** : rien ne protège pendant un long tour multi-outils ; le seuil n'est vérifié qu'au retour de `stream_loop`.
- **Résumé de résumé** : `MEMORY_FILE` est écrasé à chaque compression, et le résumé restauré au démarrage sera lui-même re-résumé au cycle suivant — dégradation générationnelle de la mémoire au fil des sessions longues (le README suggère d'ailleurs en amélioration n°2 un store vectoriel ChromaDB à la place du fichier plat).

## Lancer la démo

```bash
python s06_context_compact.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM, cf. README). Aucun fichier de config supplémentaire — `.agent_memory.md` est créé dans le répertoire courant à la première compression.

Ce qu'on observe : en conversation normale, rien — le mécanisme est invisible. Après assez de tours chargés (ou en abaissant `COMPRESS_THRESHOLD` à quelques milliers pour la démo), apparaissent les messages gris `[compress] Context large — condensing older history...` puis `[compress] Done. Collapsed N messages into 1 summary. Saved to .agent_memory.md`. Quitter, relancer : `[memory] Restoring context from .agent_memory.md...` — et l'agent répond en connaissant les décisions de la session précédente. Le fichier `.agent_memory.md` est lisible à l'œil : on peut auditer ce que l'agent a retenu.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s05-skill-loading]]
- Session suivante : [[s07-task-system]]
- Sessions liées : [[s04-subagent]] (l'autre stratégie anti-débordement : isoler le travail dans un contexte enfant plutôt que compresser le sien), [[s17-session-management]] (persistance intégrale des sessions — resume/fork — là où s06 ne garde qu'un résumé), [[s20-cache-optimization]] (l'autre économie de tokens : réutiliser le préfixe au lieu de le raccourcir)
