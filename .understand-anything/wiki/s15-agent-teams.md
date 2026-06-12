---
title: "s15 · Agent Teams"
session: 15
phase: "Multi-agents"
fichier: "inspiration/learn-claude-code/s15_agent_teams/code.py"
lignes: 929
tags: [multi-agents, message-bus, mailbox, jsonl, threads]
prev: "s14-cron-scheduler"
next: "s16-team-protocols"
---

# s15 · Agent Teams

> **En une phrase** : le Lead peut engendrer des *teammates* persistants — chacun un thread démon avec sa propre boucle LLM et ses propres outils — qui communiquent par boîtes aux lettres JSONL sur disque (`MessageBus`), leurs messages étant réinjectés dans l'historique du Lead.

## Rôle dans le harness

« Refactorer tout le backend » touche l'authentification, la couche base de données, les routes API et les tests. Le README pose le problème frontalement : un agent seul qui travaille sur les routes API n'a plus les détails du module auth dans son contexte — **la fenêtre de contexte est limitée, un agent unique ne peut pas couvrir tous les modules**. Les sub-agents de [[s06-subagent]] ne suffisent pas : ce sont des intérimaires, appelés pour une mission, détruits ensuite, qui ne savent que retourner une conclusion. Certaines tâches exigent des coéquipiers qui durent et qui se parlent.

La session ajoute trois mécanismes : un **MessageBus** à boîtes aux lettres fichiers (un `.jsonl` par agent dans `.mailboxes/`, envoi = append d'une ligne JSON, lecture = lecture + suppression du fichier), **`spawn_teammate_thread`** (le teammate tourne dans son thread démon, avec son propre prompt système, son propre historique et un jeu d'outils réduit), et l'**injection d'inbox** : les messages des teammates ne sont pas seulement affichés, ils entrent dans l'historique du Lead comme messages utilisateur, pour que le LLM puisse y réagir.

Le vrai Claude Code n'a pas de classe « bus » centrale : c'est directement le filesystem. Chaque agent écrit dans les fichiers inbox des autres (`~/.claude/teams/{team}/inboxes/{agent}.json`), protégés par `proper-lockfile` (jusqu'à 10 tentatives). La communication d'équipe y compte une quinzaine de types de messages structurés (`idle_notification`, `permission_request/response`, `shutdown_request/approved/rejected`, `task_assignment`…), un *inbox poller* côté Lead qui vérifie chaque seconde, et un mécanisme de **remontée de permissions** (le teammate demande une approbation au Lead, qui la montre à l'utilisateur, puis renvoie la réponse). La version pédagogique omet tout cela — pas de verrou fichier, pas de types de protocole, pas de permissions — et limite chaque teammate à 10 tours là où le vrai CC utilise une boucle d'attente (*idle loop*). [[s16-team-protocols]] comblera une partie de l'écart.

## Vue d'ensemble du fichier

Le fichier compte 928 lignes physiques (numérotation utilisée ci-dessous) ; la carte du wiki indique 774 lignes hors lignes vides.

| Lignes | Zone | Contenu |
|---|---|---|
| 1–21 | Docstring | Changements vs s14, schéma ASCII des flux Lead/teammate |
| 23–45 | Imports & init | Identique à s14 |
| 47–138 | Task system | Repris de [[s12-task-system]] |
| 141–174 | Prompt assembly | Repris de [[s10-system-prompt]] ; liste d'outils étendue |
| 177–214 | Outils de base | `safe_path`, `run_bash`, `run_read`, `run_write` |
| 217–254 | Handlers d'outils tâches | `run_create_task` … `run_complete_task` |
| 257–344 | Background tasks | Repris de [[s13-background-tasks]] ; `execute_tool` +3 outils |
| 347–584 | Cron scheduler | Repris de [[s14-cron-scheduler]], **amputé du queue processor** |
| 587–624 | **MessageBus (nouveau)** | Boîtes `.mailboxes/*.jsonl`, `BUS`, `active_teammates` |
| 627–712 | **Thread teammate (nouveau)** | `spawn_teammate_thread` et sa boucle interne |
| 715–733 | **Handlers d'outils équipe (nouveau)** | `run_spawn_teammate`, `run_send_message`, `run_check_inbox` |
| 736–823 | `TOOLS` | 14 définitions (11 de s14 + 3 équipe) |
| 826–839 | Contexte | `update_context` |
| 842–898 | `agent_loop` | Identique à s14 (consommation cron comprise) |
| 901–928 | REPL `__main__` | **Modifié** : injection de l'inbox du Lead dans `history` |

## Constantes et configuration

- **Lignes 37–45** : env, client, `MODEL` — identiques à [[s14-cron-scheduler]].
- **Lignes 143–151** : `PROMPT_SECTIONS` — la section `tools` ajoute `spawn_teammate, send_message, check_inbox`.
- **Lignes 259–262** : état background (repris de [[s13-background-tasks]]).
- **Lignes 349–364** : état cron repris de [[s14-cron-scheduler]] — **sans `agent_lock`** (le queue processor de s14 a disparu, voir « Ce qui change »).
- **Lignes 553–556** : bloc de démarrage — `load_durable_jobs()` + thread `cron_scheduler_loop`.
- **Lignes 591–592** : `MAILBOX_DIR = WORKDIR / ".mailboxes"`, créé immédiatement. C'est le répertoire des boîtes aux lettres (équivalent pédagogique de `~/.claude/teams/{team}/inboxes/`).
- **Ligne 621** : `BUS = MessageBus()` — instance unique, partagée par le Lead et tous les threads teammates.
- **Ligne 624** : `active_teammates: dict[str, bool] = {}` — registre des teammates vivants, utilisé pour refuser les doublons de nom (pas de verrou : simple dict, voir Pièges).
- **Lignes 738–823** : `TOOLS` — 14 outils ; les trois nouveaux : `spawn_teammate` (805–812, paramètres `name`, `role`, `prompt`), `send_message` (813–818), `check_inbox` (819–822).

## Les fonctions, une à une

### `Task` (dataclass) — lignes 53–60
Reprise de [[s12-task-system]] sans modification.

### `_task_path(task_id)` — lignes 63–64
Reprise de [[s12-task-system]] sans modification.

### `create_task(subject, description, blockedBy)` — lignes 67–76
Reprise de [[s12-task-system]] sans modification.

### `save_task(task)` / `load_task(task_id)` — lignes 79–80 / 83–84
Reprises de [[s12-task-system]] sans modification.

### `list_tasks()` — lignes 87–89
Reprise de [[s12-task-system]] sans modification.

### `get_task(task_id)` — lignes 92–95
Reprise de [[s12-task-system]] sans modification.

### `can_start(task_id)` — lignes 98–107
Reprise de [[s12-task-system]] sans modification.

### `claim_task(task_id, owner)` — lignes 110–122
Reprise de [[s12-task-system]] sans modification.

### `complete_task(task_id)` — lignes 125–138
Reprise de [[s12-task-system]] sans modification.

### `assemble_system_prompt(context)` — lignes 154–161
Reprise de [[s10-system-prompt]] sans modification.

### `get_system_prompt(context)` — lignes 167–174
Reprise de [[s10-system-prompt]] sans modification (cache sur clé JSON du contexte).

### `safe_path(p)` — lignes 179–183
Reprise des sessions fondamentales (voir [[s03-permission]]) sans modification.

### `run_bash(command, run_in_background)` — lignes 186–194
Reprise de [[s13-background-tasks]] sans modification. Notons qu'elle sert **aussi** aux teammates (table `sub_handlers`, ligne 665) : tous les agents partagent le même `WORKDIR` et le même timeout de 120 s.

### `run_read(path, limit)` — lignes 197–204
Reprise de [[s02-tool-use]] sans modification.

### `run_write(path, content)` — lignes 207–214
Reprise de [[s02-tool-use]] sans modification.

### `run_create_task` … `run_complete_task` — lignes 219–254
Handlers repris de [[s12-task-system]] sans modification : `run_create_task` (219–224), `run_list_tasks` (227–239), `run_get_task` (242–246), `run_claim_task` (249–250), `run_complete_task` (253–254).

### `is_slow_operation` / `should_run_background` — lignes 265–273 / 276–280
Reprises de [[s13-background-tasks]] sans modification.

### `execute_tool(block)` — lignes 283–297
Reprise de s14, **modifiée** : la table de dispatch gagne `spawn_teammate`, `send_message`, `check_inbox` (lignes 292–293). Cette table sert au **Lead uniquement** — les teammates ont leur propre table `sub_handlers` dans `spawn_teammate_thread`.

### `start_background_task(block)` — lignes 300–321
Reprise de [[s13-background-tasks]] sans modification.

### `collect_background_results()` — lignes 324–344
Reprise de [[s13-background-tasks]] sans modification.

### Bloc cron — lignes 347–584
Repris de [[s14-cron-scheduler]] sans modification de logique : `CronJob` (352–358), `_cron_field_matches` (367–380), `cron_matches` (383–410), `_validate_cron_field` (413–445), `validate_cron` (448–459), `save_durable_jobs` (462–465), `load_durable_jobs` (468–485), `schedule_job` (488–504), `cancel_job` (507–516), `cron_scheduler_loop` (519–542), `consume_cron_queue` (545–550), puis les handlers `run_schedule_cron` (561–566), `run_list_crons` (569–580), `run_cancel_cron` (583–584). **Différence structurelle** : `agent_lock`, `has_cron_queue`, `queue_processor_loop` et `run_agent_turn_locked` de s14 ont disparu — voir « Ce qui change ».

### `MessageBus` (classe) — lignes 595–618 — NOUVEAU

Le mécanisme de communication inter-agents. Docstring honnête (596–598) : « Read is destructive: read_text + unlink (consumes messages). Teaching version: no file locking; real CC uses proper-lockfile. »

#### `MessageBus.send(from_agent, to_agent, content, msg_type)` — lignes 600–609

```python
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message"):
        msg = {"from": from_agent, "to": to_agent,
               "content": content, "type": msg_type,
               "ts": time.time()}
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a") as f:
            f.write(json.dumps(msg) + "\n")
```

- **602–604** : l'enveloppe du message — expéditeur, destinataire, contenu, type (par défaut `"message"` ; le seul autre type utilisé en s15 est `"result"`, le résumé final d'un teammate) et timestamp Unix. Pas encore de `metadata` ni de `request_id` : c'est [[s16-team-protocols]] qui les ajoutera.
- **605–607** : **envoyer = append d'une ligne JSON** dans `{destinataire}.jsonl`. Le format JSONL (un objet JSON par ligne) rend l'append trivial et le fichier lisible à l'œil nu — on peut faire `cat .mailboxes/lead.jsonl` pendant que les agents tournent. Le mode `"a"` crée le fichier s'il n'existe pas.
- Pourquoi des fichiers plutôt qu'une `queue.Queue` en mémoire ? Le README répond : c'est intuitif, observable entre threads, et c'est aussi ce que fait le vrai CC (qui doit, lui, traverser des **process** tmux séparés, d'où le verrou fichier indispensable).

#### `MessageBus.read_inbox(agent)` — lignes 611–618

```python
    def read_inbox(self, agent: str) -> list[dict]:
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line in inbox.read_text().splitlines()
                if line.strip()]
        inbox.unlink()  # consume: read + delete
        return msgs
```

- **613–614** : pas de fichier = pas de messages, liste vide.
- **615–616** : parse chaque ligne non vide en dict (le `if line.strip()` tolère les lignes vides parasites).
- **617** : **la lecture est destructive** — `unlink()` supprime le fichier entier. Lire, c'est consommer. Conséquence assumée : entre le `read_text()` et le `unlink()`, un autre thread peut faire `send()` (append) sur le même fichier ; ce message est alors supprimé sans avoir été lu. Le README le reconnaît explicitement : « concurrent reads could lose messages, acceptable for teaching purposes ». Le vrai CC évite ce trou avec `proper-lockfile`.

### `spawn_teammate_thread(name, role, prompt)` — lignes 629–712 — NOUVEAU

La deuxième pièce maîtresse : créer un agent coéquipier complet dans un thread.

```python
def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    if name in active_teammates:
        return f"Teammate '{name}' already exists"

    system = (f"You are '{name}', a {role}. "
              f"Use tools to complete tasks. "
              f"Send results via send_message to 'lead'.")
```

- **635–636** : garde anti-doublon — deux teammates de même nom partageraient la même boîte `.jsonl`, ce serait le chaos.
- **638–640** : le prompt système du teammate est **construit dynamiquement** à partir de `name` et `role`. Il intègre l'instruction de reporter au Lead via `send_message` — la coopération est câblée dans l'identité.

La fermeture `run()` (lignes 641–707) contient toute la vie du teammate :

```python
    def run():
        messages = [{"role": "user", "content": prompt}]
        sub_tools = [ ... bash, read_file, write_file, send_message ... ]
        sub_handlers = {
            "bash": run_bash, "read_file": run_read, "write_file": run_write,
            "send_message": lambda to, content: (BUS.send(name, to, content),
                                                  "Sent")[1],
        }

        for _ in range(10):
            inbox = BUS.read_inbox(name)
            if inbox:
                messages.append({"role": "user",
                                 "content": f"<inbox>{json.dumps(inbox)}</inbox>"})
            try:
                response = client.messages.create(
                    model=MODEL, system=system, messages=messages[-20:],
                    tools=sub_tools, max_tokens=8000)
            except Exception:
                break
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    handler = sub_handlers.get(block.name)
                    output = handler(**block.input) if handler else "Unknown"
                    results.append({"type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": str(output)})
            messages.append({"role": "user", "content": results})
```

Ligne par ligne :
- **642** : l'historique du teammate démarre avec le `prompt` de mission comme premier message utilisateur — contexte **totalement séparé** de celui du Lead.
- **643–663** : `sub_tools` — un jeu d'outils **réduit** : `bash`, `read_file`, `write_file`, `send_message`. Pas de tâches, pas de cron, pas de `spawn_teammate` (donc pas de teammates imbriqués — le vrai CC l'interdit aussi explicitement). Le README précise que dans le vrai CC les teammates ont en plus les outils de tâches, le tableau de tâches étant partagé par l'équipe.
- **664–668** : `sub_handlers` — les handlers réutilisent les fonctions du module. Le lambda de `send_message` mérite une pause : `(BUS.send(name, to, content), "Sent")[1]` évalue le tuple (donc envoie le message, `BUS.send` retournant `None`) puis en retourne l'élément `[1]`, la chaîne `"Sent"` — l'astuce idiomatique pour « faire un effet de bord et retourner une constante » dans un lambda. La fermeture capture `name` : l'expéditeur est toujours le teammate lui-même.
- **670** : `for _ in range(10)` — **10 tours maximum**, le garde-fou pédagogique contre les boucles infinies. Le vrai CC remplace cette borne par une *idle loop* : à chaque fin de tour, le teammate envoie `idle_notification` au Lead et attend des messages, ne sortant que sur `shutdown_request` ([[s16-team-protocols]] implémente cette boucle).
- **671–674** : en début de chaque tour, le teammate **lit sa propre inbox** : les messages reçus (du Lead, ou d'un autre teammate) sont injectés bruts, sérialisés en JSON entre balises `<inbox>...</inbox>`. C'est le canal d'entrée du teammate.
- **676–680** : l'appel API n'envoie que `messages[-20:]` — une fenêtre glissante des 20 derniers messages pour borner le contexte du teammate. Toute exception (`except Exception: break`) sort silencieusement de la boucle : un teammate qui plante ne fait pas tomber le processus, mais ne loggue rien non plus.
- **682–683** : si le modèle ne demande plus d'outil, le travail est fini — sortie de boucle.
- **684–692** : exécution séquentielle des tool calls avec la mini-table `sub_handlers` — une version condensée de `agent_loop`, sans background ni notifications.

Épilogue (lignes 694–707) — le rapport final :

```python
        # Send final summary to Lead
        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant" and isinstance(msg["content"], list):
                for b in msg["content"]:
                    if getattr(b, "type", None) == "text":
                        summary = b.text
                        break
                else:
                    continue
                break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)
```

- **696–704** : remonte l'historique à l'envers pour trouver le **dernier bloc de texte assistant** — c'est le résumé. La construction `for/else` imbriquée est subtile : le `else` du `for` intérieur (ligne 702) ne s'exécute que si aucun bloc texte n'a été trouvé dans ce message → `continue` vers le message précédent ; si un texte a été trouvé, le `break` intérieur saute le `else` et le `break` extérieur (704) termine la recherche.
- **705** : quoi qu'il arrive (même après un crash silencieux), le teammate envoie son résumé au Lead avec le type `"result"` — l'équivalent du compte rendu de fin de mission.
- **706** : auto-désinscription de `active_teammates` ; le nom redevient disponible.

Enfin (709–712), le thread est lancé en démon et la fonction retourne immédiatement `"Teammate '{name}' spawned as {role}"` : **spawn est non bloquant**, le Lead continue son tour pendant que le teammate travaille.

### `run_spawn_teammate(name, role, prompt)` — lignes 717–718 — NOUVEAU
Handler d'outil : délègue à `spawn_teammate_thread`.

### `run_send_message(to, content)` — lignes 721–723 — NOUVEAU
Handler d'outil du Lead : `BUS.send("lead", to, content)` — l'expéditeur est codé en dur, le LLM ne peut pas usurper une identité.

### `run_check_inbox()` — lignes 726–733 — NOUVEAU
Handler d'outil du Lead : lit (et consomme) `lead.jsonl`, formate chaque message `[expéditeur] contenu` tronqué à 200 caractères, ou `"(inbox empty)"`. Donne au Lead un moyen **actif** de consulter ses messages en milieu de tour — le second canal, passif, étant l'injection en fin de tour dans `__main__`.

### `TOOLS` — lignes 738–823
Les 11 définitions de s14 plus `spawn_teammate`, `send_message`, `check_inbox`. Voir « Constantes et configuration ».

### `update_context(context, messages)` — lignes 828–839
Reprise de s14 sans modification.

### `agent_loop(messages, context)` — lignes 847–898
Reprise de [[s14-cron-scheduler]] dans sa logique (consommation `cron_queue` en tête de boucle, dispatch background, fusion des notifications), mais **revenue à une signature sans valeur de retour** : s14 retournait `context` pour le queue processor ; celui-ci ayant disparu, la fonction ne retourne rien (lignes 865, 869). Le commentaire de tête (843–845) assume : « Cron queue is consumed when agent_loop is called; real CC auto-wakes via queue processor (useQueueProcessor.ts) when items arrive. »

### Bloc `__main__` — lignes 901–928

REPL repris des sessions précédentes, avec la nouveauté de la session en fin de tour (lignes 920–927) :

```python
        # Check inbox for teammate results → inject into history
        inbox = BUS.read_inbox("lead")
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']}: {m['content'][:200]}" for m in inbox)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
            print(f"\n\033[33m[Inbox: {len(inbox)} messages injected]\033[0m")
```

Après chaque tour du Lead, son inbox est lue et, si elle contient des messages, ils sont **injectés dans `history` comme message utilisateur** préfixé `[Inbox]`. C'est le point que le README souligne : ne pas seulement *afficher* les messages, mais les mettre dans l'historique pour que le LLM les voie au tour suivant et puisse y réagir (« Alice a fini le schéma → je lance Bob sur l'API »). Limite assumée : l'injection n'a lieu qu'après un tour, donc il faut une saisie utilisateur pour que le Lead « voie » les résultats arrivés entre-temps — le vrai CC a un `useInboxPoller` qui vérifie chaque seconde et soumet les messages comme nouveaux tours sans attendre l'humain.

## Ce qui change par rapport à [[s14-cron-scheduler]]

- **Nouvelle classe `MessageBus`** (595–618) + répertoire `.mailboxes/` (591–592) + instance `BUS` (621) : envoi par append JSONL, lecture destructive.
- **Nouveau registre `active_teammates`** (624) : anti-doublons de noms, nettoyé à la fin de chaque teammate.
- **Nouvelle fonction `spawn_teammate_thread`** (629–712) : thread démon par teammate, prompt système dédié, historique isolé, 4 outils, 10 tours max, fenêtre `messages[-20:]`, rapport final de type `result`.
- **3 nouveaux outils Lead** : `spawn_teammate`, `send_message`, `check_inbox` (11 → 14) ; `PROMPT_SECTIONS`, `execute_tool` et `TOOLS` mis à jour.
- **Injection d'inbox dans `__main__`** (920–927) : les messages des teammates entrent dans l'historique du Lead.
- **Régression assumée vs s14** : le *queue processor* disparaît — plus de `agent_lock`, `has_cron_queue()`, `queue_processor_loop()`, `run_agent_turn_locked()` ni `print_latest_assistant_text()`. Les jobs cron continuent de tirer (thread scheduler conservé) mais ne sont **livrés que lorsqu'un tour d'agent s'exécute**, c'est-à-dire après une saisie humaine. Le code pédagogique simplifie pour se concentrer sur le mécanisme d'équipe ; `agent_loop` perd au passage son `return context`.
- **Toujours omis** : récupération d'erreurs ([[s11-error-recovery]]), mémoire, skills, et — listé par le README — la remontée de permissions des teammates vers le Lead.

## Pièges et détails d'implémentation

- **La course lecture/suppression de `read_inbox`** : un `send()` qui s'intercale entre `read_text()` et `unlink()` est perdu. Avec un Lead, plusieurs teammates et des envois croisés, c'est une vraie fenêtre — assumée pour la pédagogie, fermée par `proper-lockfile` dans le vrai CC.
- **`messages[-20:]` peut casser l'appariement tool_use/tool_result** : si la fenêtre glissante coupe entre un message assistant contenant un `tool_use` et le message user contenant son `tool_result` (ou l'inverse), l'API rejette la requête ; l'`except Exception: break` masque alors l'erreur et le teammate meurt en envoyant quand même son `"Done."` — un échec qui ressemble à un succès.
- **Les erreurs des teammates sont invisibles** : `except Exception: break` sans log (ligne 679–680). Si la clé API expire en cours de route, le seul symptôme est un résumé prématuré dans l'inbox du Lead.
- **Le lambda `(BUS.send(...), "Sent")[1]`** (666–667) : effet de bord + valeur de retour dans une seule expression — élégant mais facile à mal lire ; le `[1]` retourne `"Sent"` au modèle comme `tool_result`.
- **L'inbox du teammate n'est lue qu'en début de tour** (671) : un message envoyé pendant que le teammate est au tour 10 (ou déjà sorti de boucle) ne sera jamais lu — le fichier `.jsonl` restera orphelin jusqu'à ce qu'un futur teammate du même nom le consomme. Pas d'idle loop avant [[s16-team-protocols]].
- **`active_teammates` n'est pas verrouillé** : deux `spawn_teammate` simultanés du même nom (théoriquement possibles via deux tool calls d'un même tour) passeraient tous deux la garde. En pratique, l'exécution séquentielle des tool calls dans `agent_loop` protège.
- **Tous les agents partagent `WORKDIR`** : deux teammates qui écrivent le même fichier se marchent dessus sans arbitrage — la session [[s18-worktree-isolation]] traitera l'isolation.

## Liens

- Session précédente : [[s14-cron-scheduler]]
- Session suivante : [[s16-team-protocols]]
- Sessions liées : [[s06-subagent]] (le contraste intérimaire vs coéquipier), [[s12-task-system]] (le tableau de tâches partageable), [[s17-autonomous-agents]] (teammates auto-organisés), [[s18-worktree-isolation]] (isolation des espaces de travail)
