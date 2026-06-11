---
title: "s15 · Agent Teams"
session: 15
phase: "Multi-agents"
fichier: "src/sessions/s15.py"
lignes: 103
tags: [multi-agents, message-bus, mailbox, jsonl, threads]
prev: "s14-cron-scheduler"
next: "s16-team-protocols"
---

# s15 · Agent Teams

> **En une phrase** : le Lead engendre des *teammates* persistants — chacun un thread démon avec sa propre boucle LLM — et leur parle par boîtes aux lettres JSONL sur disque ; ce fichier câble les trois outils du Lead et le canal passif qui injecte l'inbox dans son historique.

## Rôle dans le harness

Les sub-agents de [[s06-subagent]] sont des intérimaires : une mission, une conclusion, destruction. Certains travaux exigent des coéquipiers qui durent et qui se parlent — refactorer un backend touche l'auth, la base, l'API : aucune fenêtre de contexte ne couvre tout. Trois mécanismes de [[shared-py]] répondent : le **MessageBus** (un `.jsonl` par agent sous `.mailboxes/`, envoi = append d'une ligne JSON, lecture = consommation destructive), **`spawn_teammate_thread`** (un mini-harness complet par teammate : 8 outils, fenêtre `messages[-20:]`, gate d'approbation de plan, bascule worktree, `idle_poll` entre les rafales), et l'**injection d'inbox** : les messages des teammates n'arrivent pas seulement à l'écran, ils entrent dans l'historique du Lead pour que le LLM y réagisse.

Ce fichier est le poste de pilotage du Lead : trois outils d'équipe (`spawn_teammate`, `send_message`, `check_inbox`) plus les tâches partagées de [[s12-task-system]] (`create_task`/`list_tasks` — les teammates de shared.py savent les revendiquer), une démo hors-ligne du bus, et le drainage passif de l'inbox en fin de tour.

## Ce que fait ce fichier

### pick() — lignes 28–29

Filtre `BUILTIN_TOOLS` par nom.

### Câblage module — lignes 32–40

`TOOL_NAMES = ("spawn_teammate", "send_message", "check_inbox", "create_task", "list_tasks", "bash")`. `SYSTEM` (lignes 36–40) installe l'identité `lead` et le contrat : les résultats des teammates arrivent dans l'inbox, les tâches créées via `create_task` sont revendicables par l'équipe.

### demo_bus() — lignes 43–55

La démo hors-ligne du MessageBus :

```python
    BUS.send("alice", "lead", "Schéma terminé : tables users+sessions")
    BUS.send("bob", "lead", "Tests rouges sur /login", "result")
    inbox_file = MAILBOX_DIR / "lead.jsonl"
    lines = len(inbox_file.read_text().splitlines())
    print(f"  sur disque : {inbox_file} ({lines} lignes JSONL)")
```

Deux envois (dont un de type `result`, le type des comptes rendus de fin de mission), la preuve sur disque (le fichier `.mailboxes/lead.jsonl` et son nombre de lignes — observable avec `cat` pendant que les agents tournent), puis la **lecture destructive** : le premier `read_inbox("lead")` rend les deux messages, le second rend `[]` — le fichier a été consommé (`read_text` + `unlink`).

### drain_lead_inbox() — lignes 58–68

Le canal passif, le point clé de la session :

```python
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return
    text = "\n".join(f"From {m['from']} ({m['type']}): {m['content'][:200]}"
                     for m in msgs)
    history.append({"role": "user", "content": f"[Inbox]\n{text}"})
```

Appelé en fin de chaque tour : si des teammates ont écrit pendant que le Lead travaillait (spawn non bloquant — ils tournent en parallèle), leurs messages deviennent un message user `[Inbox]` que le LLM verra au tour suivant (« alice a fini le schéma → je lance bob sur l'API »). Le canal **actif** complémentaire est l'outil `check_inbox`, utilisable en plein tour, avec routage protocole.

### main() — lignes 71–98

`shared.CLI_ACTIVE = True` (ligne 74) active le mode console partagée : les threads teammates parlent via `terminal_print`, qui redessine la ligne de saisie en cours au lieu de la massacrer. C'est la seule utilisation qualifiée `shared.X` restante du fichier — un **rebind** du nom module-level, qui doit passer par le module (l'affectation sur un nom from-importé ne toucherait que la copie locale, et `terminal_print` ne verrait jamais le drapeau levé) ; d'où le `import shared` conservé ligne 21 à côté du `from shared import (...)`. Boucle interactive : `bus` (démo hors-ligne), `who` (le registre `active_teammates` des teammates vivants), tout autre texte part dans `agent_loop` avec le pool du Lead, suivi de `print_turn_assistants` puis `drain_lead_inbox`. `q` quitte.

## Ce qui vient de [[shared-py]]

Importé explicitement (`from shared import (...)`, lignes 22–25), sauf `CLI_ACTIVE` — rebindé par `main()`, donc accédé via `import shared` (ligne 21) :

- `BUS` (l'instance de `MessageBus`) / `MAILBOX_DIR` — mailboxes JSONL append-only, enveloppe `{from, to, content, type, ts, metadata}`, `read_inbox` destructive, trace `[bus]` via `terminal_print`.
- `spawn_teammate_thread` — le mini-harness par teammate (8 outils dont `submit_plan`, gate d'approbation, worktree de la tâche revendiquée, `idle_poll`), exposé au Lead par `run_spawn_teammate` ; contient le FIX(mekicode) des tool_use orphelins après `submit_plan`.
- `run_spawn_teammate`, `run_send_message`, `run_check_inbox` — les wrappers lead : expéditeur `lead` codé en dur (pas d'usurpation d'identité), drainage avec routage protocole et affichage des `request_id`.
- `active_teammates` — le registre anti-doublons de noms, consulté par `who`.
- `shared.CLI_ACTIVE` / `terminal_print` / `PROMPT` — la console thread-safe (`CLI_ACTIVE` reste qualifié : voir main()) ; `agent_loop`, `BUILTIN_TOOLS`/`BUILTIN_HANDLERS`, `print_turn_assistants`.

## Différences avec l'original learn-claude-code

- L'original (929 lignes) recopiait s12+s13+s14 et définissait un teammate à 4 outils limité à 10 tours secs ; le teammate de shared.py est le mini-harness fusionné s15+s16+s17+s18 (tâches partagées, `submit_plan`, `idle_poll` au lieu du plafond de tours, worktrees) — `s15.py` n'en montre que la face s15.
- Le `send` de shared.py ajoute `metadata` à l'enveloppe (porteur des `request_id` de s16) et trace chaque envoi à l'écran via `terminal_print` ; l'original envoyait en silence.
- L'injection d'inbox de l'original vivait dans le `__main__` ; ici elle est factorisée en `drain_lead_inbox`, et le canal actif `run_check_inbox` route en plus les réponses de protocole.
- `CLI_ACTIVE`/`terminal_print` n'existaient pas : dans l'original, un teammate qui parlait pendant la saisie cassait la ligne d'invite.
- Piège conservé tel quel : la lecture destructive — un `send` qui s'intercale entre le `read_text` et le `unlink` est perdu (le vrai Claude Code ferme ce trou avec un verrou fichier).

## Lancer la démo

```
python src/sessions/s15.py
```

`bus` et `who` fonctionnent sans clé API : `bus` montre l'append JSONL sur disque puis la double lecture (pleine, puis vide). Avec une clé, demander par exemple « spawn alice, une développeuse backend, pour créer schema.sql » : le spawn est non bloquant, la trace `[bus]` apparaît quand alice écrit, et au tour suivant le message `[Inbox]` injecté permet au Lead de réagir.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s14-cron-scheduler]]
- Session suivante : [[s16-team-protocols]]
- Sessions liées : [[s06-subagent]] (intérimaire vs coéquipier), [[s12-task-system]] (le tableau de tâches que l'équipe partage), [[s17-autonomous-agents]] (l'`idle_poll` des teammates), [[s18-worktree-isolation]] (chacun son répertoire)
