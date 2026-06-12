---
title: "s09 · Agent Teams"
session: 09
phase: "Async & multi-agents"
fichier: "inspiration/claude-code-from-scratch/s09_agent_teams.py"
lignes: 317
tags: [agent-teams, lead-specialist, mailbox, jsonl, threads, delegation]
prev: "s08-background-tasks"
next: "s10-team-protocols"
---

# s09 · Agent Teams

> **En une phrase** : deux spécialistes persistants (`explorer`, `writer`) tournent en threads daemon et dialoguent avec un agent lead par des boîtes aux lettres JSONL ; le lead délègue via l'outil `send_to_teammate`, qui bloque jusqu'à la réponse, puis synthétise.

## Rôle dans le harness

Le subagent de [[s04-subagent]] est **éphémère** : créé pour une tâche, détruit après. À chaque délégation, on paie le démarrage, et deux délégations successives au « même » spécialiste n'ont aucun lien. s09 introduit l'architecture **lead-specialist** : des équipiers à rôle fixe (un explorateur du code, un rédacteur) vivent en threads d'arrière-plan pendant toute la session, prêts à recevoir du travail. La devise : *« When the task is too big for one, delegate to teammates »*.

Le deuxième apport est le **médium de communication** : des mailboxes JSONL sur disque (`.mailboxes/<agent>.jsonl`). Chaque agent a son fichier-inbox ; envoyer = appendre une ligne JSON chez le destinataire ; recevoir = lire tout son fichier et le vider. Ce découplage par le système de fichiers est volontairement low-tech — la docstring l'assume (*« This version uses JSONL for simplicity and visibility »*) : on peut ouvrir les fichiers et regarder les agents se parler. La version production, annoncée dès la docstring, est [[s22-production-mailbox]] (Redis pub/sub).

Le README range cette session face aux **« Parallel subagents »** du vrai Claude Code — son outil Agent/Task qui lance des sous-agents spécialisés (Explore, Plan…) avec leur propre contexte, et son mode teams où des agents nommés s'échangent des messages (`SendMessage`). La grande idée commune : la spécialisation par prompt système (un agent « explorer » cherche mieux qu'un généraliste) et la **synthèse par le lead**, qui reçoit des résultats bruts et les fond en réponse cohérente. Dans learn-claude-code, l'équivalent direct est la session s15 (agent teams), avec le même trio threads + mailboxes + délégation bloquante.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | Devise, 4 concepts (rôles, mailboxes, concurrence, synthèse), note pédagogique JSONL→Redis |
| 29–36 | Imports stdlib | `json`, `threading`, `time`, `Path`, typing |
| 38–46 | Imports core | 6 symboles du socle |
| 48–74 | Configuration | `MAILBOX_DIR`, `TEAMMATES`, `SYSTEM` du lead |
| 76–125 | **Nouveau** | Couche messagerie : `_get_mailbox_path`, `_send_message`, `_receive_messages` |
| 128–187 | **Nouveau** | `_run_teammate_loop()` : la boucle de vie d'un spécialiste |
| 190–222 | **Nouveau** | `run_send_to_teammate()` : l'outil de délégation du lead |
| 225–251 | Schémas & dispatch | `TEAM_TOOLS` (+2 outils), `TEAM_DISPATCH` |
| 254–312 | Point d'entrée | `main()` : spawn des threads, REPL du lead, nettoyage `finally` |
| 315–317 | Lancement | `if __name__ == "__main__"` |

## Constantes et configuration

- **`MAILBOX_DIR` (lignes 51–52)** : `Path(".mailboxes")`, créé dès l'import (`mkdir(exist_ok=True)`) — le « bureau de poste » de l'équipe, visible dans le répertoire courant.
- **`TEAMMATES` (lignes 55–66)** : dict `nom → prompt système`. C'est **toute** la définition d'un équipier : `explorer` (*« find relevant files, explain logic, and map dependencies. Use bash, read, glob, and grep »*) et `writer` (*« implement features, fix bugs, and document code. Use write, read, and bash »*). La spécialisation est purement déclarative — ajouter un troisième équipier = une entrée de dict, le reste (thread, mailbox, schéma d'outil) suit automatiquement.
- **`SYSTEM` (lignes 69–74)** : le persona du lead, qui interpole dynamiquement `', '.join(TEAMMATES.keys())` — le prompt reste juste si on modifie l'équipe. Consigne clé : *« Once they reply, synthesize their findings into a cohesive final response »*.
- **`TEAM_TOOLS` (lignes 227–245)** : `EXTENDED_TOOLS` + 2 outils. Détail important ligne 234 : `"enum": list(TEAMMATES.keys())` — le schéma JSON **contraint** les destinataires valides, le modèle ne peut pas halluciner un équipier. La description de `send_to_teammate` annonce le contrat : *« This blocks until they reply. »*
- **`TEAM_DISPATCH` (lignes 247–251)** : extension par dépliage `**EXTENDED_DISPATCH` ; `list_teammates` est traité par une lambda inline (ligne 250) qui formate le dict `TEAMMATES` — pas besoin de fonction dédiée pour un outil en lecture seule.

## Les fonctions, une à une

### `_get_mailbox_path(agent_name)` — lignes 78–80

Helper d'une ligne : `MAILBOX_DIR / f"{agent_name}.jsonl"`. Centraliser la convention de nommage évite qu'un renommage casse silencieusement l'adressage.

### `_send_message(to_agent, from_agent, body)` — lignes 83–99

```python
    message_data = {
        "from": from_agent,
        "body": body,
        "timestamp": time.time()
    }
    # Open in append mode ('a') to handle multiple incoming messages
    with open(_get_mailbox_path(to_agent), "a", encoding="utf-8") as f:
        f.write(json.dumps(message_data) + "\n")
```

- **Lignes 92–96** : l'enveloppe minimale d'un protocole de messagerie — expéditeur, corps, horodatage. Pas de destinataire dans le message : il est implicite (c'est le fichier dans lequel on écrit).
- **Lignes 98–99** : mode **append** (`"a"`) — plusieurs expéditeurs peuvent empiler des messages sans s'écraser, c'est tout l'intérêt du format JSONL (un objet JSON par ligne, append-only).

### `_receive_messages(agent_name)` — lignes 102–125

```python
    try:
        # Read all lines, parse JSON, and filter out empty lines
        lines = path.read_text(encoding="utf-8").splitlines()
        messages = [json.loads(line) for line in lines if line.strip()]
        # Clear the mailbox after reading (Atomic 'pop all' simulation)
        path.write_text("", encoding="utf-8")
        return messages
    except (json.JSONDecodeError, IOError) as e:
        print(f"\033[31m  [error] Mailbox read failed for {agent_name}: {e}\033[0m")
        return []
```

- **Lignes 118–121** : la sémantique est un **pop-all** — tout lire, tout effacer. Le commentaire dit *« Atomic 'pop all' simulation »* : le mot *simulation* est honnête, car rien n'est atomique ici. Entre `read_text` (118) et `write_text("")` (121), un autre thread peut appendre un message… qui sera effacé sans avoir été lu. C'est le **lost update** que la docstring de [[s10-team-protocols]] cite nommément et corrige avec un `threading.Lock`.
- **Lignes 123–125** : sur erreur de parsing, on log en rouge et on renvoie `[]` — mais comme l'exception jaillit **avant** la ligne de nettoyage (121), le fichier garde sa ligne corrompue (voir pièges).

### `_run_teammate_loop(name, specialist_prompt, stop_event)` — lignes 130–187

La boucle de vie d'un spécialiste : sondage du courrier, exécution autonome, réponse.

```python
            # Create a fresh context for this specific delegated task
            sub_history: List[Dict[str, Any]] = [{"role": "user", "content": task_body}]
            
            # Autonomous turn-taking for the specialist
            while True:
                response = client.messages.create(
                    model=MODEL,
                    system=specialist_prompt,
                    messages=sub_history,
                    tools=EXTENDED_TOOLS, # Specialists have standard file tools
                    max_tokens=4000,
                )
                sub_history.append({"role": "assistant", "content": response.content})
                
                # Exit turn if the model is done (no more tool calls)
                if response.stop_reason != "tool_use":
                    break
                
                # Execute tool calls requested by the specialist
                results = dispatch_tools(response.content, EXTENDED_DISPATCH)
                sub_history.append({"role": "user", "content": results})
```

- **Ligne 144** : `while not stop_event.is_set()` — la boucle externe vit tant que `main()` n'a pas signalé l'arrêt.
- **Ligne 155** : `sub_history` **vierge à chaque tâche**. C'est l'isolement de contexte de [[s04-subagent]], conservé : le thread est persistant, mais la mémoire ne l'est pas — deux délégations successives à `explorer` ne partagent rien (voir pièges).
- **Lignes 159–165** : `client.messages.create` **sans streaming**, contrairement au lead qui passe par `stream_loop`. Choix pragmatique : deux threads qui streament dans le même terminal produiraient un mélange illisible ; les spécialistes travaillent en silence (à part les logs magenta) et seul le lead streame.
- **Lignes 169–174** : la boucle think-act canonique du repo — c'est une ré-implémentation locale du cœur de `stream_loop`, en version non-streamée, avec `dispatch_tools` de [[core-py]] pour l'exécution.
- **Lignes 177–183** : extraction du texte final (`hasattr(block, "text")` filtre les blocs non textuels) puis `_send_message(to_agent=sender, ...)` — la réponse part dans la mailbox de **l'expéditeur d'origine**, pas dans une boîte codée en dur : le protocole est symétrique.
- **Ligne 187** : `stop_event.wait(timeout=0.5)` — l'astuce du fichier : ça dort 0,5 s **ou** se réveille immédiatement si l'événement d'arrêt est levé. Un `time.sleep(0.5)` ferait attendre la fin du somme avant de voir le signal.

### `run_send_to_teammate(name, message)` — lignes 192–222

L'outil du lead : envoyer, puis **attendre activement** la réponse.

```python
    # Send the task to the teammate
    _send_message(to_agent=name, from_agent="lead", body=message)
    
    # Synchronous Polling (The Lead blocks until the teammate finishes)
    # In a production system, this could be made async.
    print(f"\033[90m  [lead] waiting for {name} to reply...\033[0m")
    for attempt in range(60): # 60-second total timeout
        time.sleep(1)
        replies = _receive_messages("lead")
        if replies:
            # Aggregate all messages received (usually just one)
            return "\n\n".join(f"Response from {r['from']}:\n{r['body']}" for r in replies)
            
    return f"Timeout: Teammate '{name}' did not respond within 60 seconds."
```

- **Lignes 206–207** : validation `name not in TEAMMATES` — défense en profondeur derrière l'`enum` du schéma (les deux peuvent diverger si on édite l'un sans l'autre).
- **Ligne 210** : le lead signe `from_agent="lead"` — c'est ce champ que le spécialiste utilisera pour router sa réponse.
- **Lignes 215–220** : sondage 60 × 1 s de la mailbox `"lead"`. Le commentaire du code assume la limite : *« In a production system, this could be made async »*. Pendant ces 60 s, le lead est gelé — la délégation est concurrente côté spécialiste, mais bloquante côté lead.
- **Ligne 220** : on agrège **tout** ce qui traîne dans la boîte du lead, pas seulement la réponse attendue — le préfixe `Response from {r['from']}` permet au modèle de trier, mais l'attribution reste fragile (voir pièges).
- **Ligne 222** : le timeout est un résultat d'outil comme un autre : le modèle peut décider de réessayer, de relancer plus petit, ou d'expliquer l'échec.

### `main()` — lignes 256–312

Cycle de vie complet de l'équipe autour du REPL.

```python
    # 2. Spawn Teammate Background Threads
    for agent_name, agent_prompt in TEAMMATES.items():
        thread = threading.Thread(
            target=_run_teammate_loop, 
            args=(agent_name, agent_prompt, stop_signal),
            daemon=True # Ensures threads exit when the main program closes
        )
        thread.start()
        teammate_threads.append(thread)
```

- **Lignes 261–272** : un `threading.Event` partagé (`stop_signal`) + un thread daemon par équipier, démarrés **avant** le REPL — l'équipe est au travail dès la bannière.
- **Lignes 280–302** : REPL du lead, qui tourne sur `stream_loop` de [[core-py]] avec `TEAM_TOOLS`/`TEAM_DISPATCH`. Sur `Ctrl+C` : `break` (et non `sys.exit`) — indispensable pour que le `finally` s'exécute.
- **Lignes 304–312** : l'arrêt propre — `stop_signal.set()` réveille les boucles spécialistes (via leur `wait`), puis suppression des fichiers mailbox de tous les équipiers **plus** celle du lead :

```python
    finally:
        # 4. Clean Shutdown: Signal threads to stop and clear mailboxes
        print("\033[90m  [system] shutting down team...\033[0m")
        stop_signal.set()
        # Optionally cleanup mailbox files
        for agent in list(TEAMMATES.keys()) + ["lead"]:
            path = _get_mailbox_path(agent)
            if path.exists():
                path.unlink()
```

## Ce qui vient de [[core-py]]

Import en lignes 39–46 ; contrairement à [[s08-background-tasks]], les six symboles servent tous :

- **`client`, `MODEL`** — la boucle interne des spécialistes appelle l'API en direct (`client.messages.create`, lignes 159–160), sans streaming.
- **`EXTENDED_TOOLS`** — outils standards des spécialistes (ligne 163) et base de `TEAM_TOOLS` (ligne 227).
- **`EXTENDED_DISPATCH`** — exécution des outils des spécialistes (ligne 173) et base de `TEAM_DISPATCH` (ligne 248).
- **`dispatch_tools`** — le moteur d'exécution des `tool_use` dans la boucle spécialiste (ligne 173).
- **`stream_loop`** — la boucle du lead, streaming compris (ligne 296).

## Pièges et détails d'implémentation

- **« Persistant » ne veut pas dire « avec mémoire »** : le thread survit entre les tâches, mais `sub_history` repart de zéro à chaque message (ligne 155). `explorer` ne se souvient pas de sa précédente exploration — la persistance porte sur le processus et le rôle, pas sur le contexte.
- **Le pop-all n'est pas atomique** : aucun verrou autour de `read_text` → `write_text("")` (lignes 118–121). Un message appendu entre les deux est silencieusement détruit. C'est exactement le « lost update » que [[s10-team-protocols]] introduit un `threading.Lock` pour traiter.
- **Réponse tardive = réponse mal attribuée** : si un spécialiste dépasse les 60 s, le lead reçoit `Timeout`, mais le spécialiste, lui, continue et finira par écrire dans la boîte du lead. Sa réponse sera drainée par le **prochain** `run_send_to_teammate` et présentée comme la réponse à une autre question (le préfixe `Response from ...` est le seul indice).
- **Une ligne corrompue empoisonne la boîte** : `json.loads` échoue (ligne 119) avant le nettoyage (ligne 121), donc la ligne fautive reste dans le fichier — et le thread du spécialiste réessaie toutes les 0,5 s, imprimant l'erreur en boucle jusqu'à suppression manuelle du fichier.
- **Les rôles ne sont que des prompts** : `explorer` reçoit le même `EXTENDED_TOOLS` que tout le monde, `write` et `revert` compris. Rien ne l'empêche techniquement de modifier des fichiers — la restriction est rhétorique, pas mécanique (les permissions déclaratives arrivent en [[s15-permissions]]).
- **Pas de parallélisme réel côté lead** : `dispatch_tools` exécute les appels d'outils séquentiellement, et `send_to_teammate` bloque — même si le modèle demandait deux délégations dans le même tour, elles s'enchaîneraient l'une après l'autre. Les threads donnent la *réactivité* (l'équipier écoute en permanence), pas la *simultanéité* des délégations.
- **`Union` importé, jamais utilisé** (ligne 36) — bruit d'en-tête standardisé, comme dans la plupart des sessions du repo.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s09_agent_teams.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM). Le répertoire `.mailboxes/` est créé automatiquement.

Au lancement : `[explorer] thread initialized and ready` et `[writer] thread initialized and ready` en gris, puis la bannière `s09: agent teams | teammates: explorer, writer | mailboxes in .mailboxes`. Essayer : `demande à explorer de cartographier core.py, puis fais rédiger un résumé par writer`. On observe la chaîne complète : le lead appelle `send_to_teammate` → `[lead] waiting for explorer to reply...` → logs magenta `[explorer] processing task from lead: ...` puis `[explorer] result sent back to lead` → le lead streame sa synthèse. Pendant l'exécution, `cat .mailboxes/explorer.jsonl` montre les messages en transit ; à la sortie (`q`), `[system] shutting down team...` et les fichiers disparaissent.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s08-background-tasks]]
- Session suivante : [[s10-team-protocols]]
- Sessions liées : [[s04-subagent]] (la délégation éphémère dont s09 est la version persistante), [[s11-autonomous-agents]] (les équipiers cessent d'attendre des ordres et s'auto-affectent), [[s22-production-mailbox]] (le même protocole sur Redis pub/sub, durable et inter-processus)
