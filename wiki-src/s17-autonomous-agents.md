---
title: "s17 · Agents autonomes"
session: 17
phase: "Multi-agents"
fichier: "src/s17.py"
lignes: 92
tags: [autonomie, idle-poll, auto-claim, task-board]
prev: "s16-team-protocols"
next: "s18-worktree-isolation"
---

# s17 · Agents autonomes

> **En une phrase** : un teammate inactif cesse d'attendre les ordres — il scrute le tableau de tâches toutes les 5 s, s'auto-assigne la première tâche libre dont les dépendances sont résolues, et ne s'arrête que sur `shutdown_request` ou après 60 s sans travail ; la démo pilote ce cycle WORK → IDLE → SHUTDOWN à la main, sans LLM.

## Rôle dans le harness

En [[s16-team-protocols]], les teammates savent communiquer et négocier un arrêt propre, mais le lead doit encore assigner chaque tâche à la main — ça ne passe pas à l'échelle. s17 introduit l'**autonomie** : « check the board, claim the task ». Le filtre est `scan_unclaimed_tasks` (pending + sans owner + `can_start`), la boucle d'oisiveté est `idle_poll` — 12 cycles de `IDLE_POLL_INTERVAL = 5` s, avec **priorité à l'inbox** (un `shutdown_request` reçoit immédiatement sa `shutdown_response` corrélée et sort en `"shutdown"`), puis revendication de la plus ancienne tâche libre (sortie `"work"` avec injection d'une balise `<auto-claimed>`), sinon `"timeout"` après `IDLE_TIMEOUT = 60` s.

L'assignation n'est plus un ordre mais une **émergence** : le lead crée des tâches et des teammates, l'attribution résulte de l'auto-claim — protégé par la triple garde de `claim_task` (statut, owner déjà posé, dépendances), qui encaisse les courses entre teammates concurrents.

## Ce que fait ce fichier

### board() — lignes 27–32
Affiche le tableau vu par `scan_unclaimed_tasks` — exactement ce que verrait un teammate en IDLE :

```python
    unclaimed = scan_unclaimed_tasks()
    names = [f"{t['id']} · {t['subject']}" for t in unclaimed]
    print(f"   revendicables : {names if names else 'aucune'}")
```

Les éléments sont des `dict` bruts (lecture JSON directe), pas des `Task` — d'où `t['id']` et non `t.id`.

### main() — lignes 35–87
Le cycle de vie complet, piloté à la main :

1. **Mise en place** (l. 37–45) : drainage des mailboxes résiduelles, puis un mini-graphe — `t1` libre, `t2` avec `blockedBy=[t1.id]`. Le premier `board()` montre que t2 n'est **pas** revendicable : avoir des dépendances ne bloque pas, avoir des dépendances *non résolues* bloque.
2. **Phase WORK simulée** (l. 47–52) : alice revendique t1 (`claim_task(t1.id, "alice")` — l'owner posé est le nom du teammate, comme dans l'auto-claim) puis la termine ; le retour de `complete_task` annonce `Unblocked: ...` et le second `board()` montre t2 devenue démarrable.
3. **Phase IDLE** (l. 54–64) : le **vrai** `idle_poll` de shared (premier scan après 5 s de sommeil). Verdict attendu `"work"`, avec la balise injectée dans l'historique du teammate :

```python
    verdict = idle_poll("alice", messages, "alice", "worker")
    print(f"   verdict : {verdict!r}")
    if verdict != "work":
        print("   (inattendu — tableau ou inbox pollués ? démo abrégée)")
        return
    auto_claimed = messages[-1]["content"]     # balise <auto-claimed>...>
```

La garde l. 60–62 protège la démo si des tâches pendantes d'autres sessions traînent dans `.tasks/` (l'auto-claim prend la plus ancienne, pas forcément la nôtre).
4. **Retour en WORK** (l. 66–70) : l'id revendiqué est extrait de la balise (`auto_claimed.split("Task ")[1].split(":")[0]`) — cette balise est la *seule* consigne donnée au LLM dans le vrai harness — puis `complete_task`.
5. **IDLE → SHUTDOWN** (l. 72–83) : `run_request_shutdown("alice")` dépose un `shutdown_request` **avant** le second `idle_poll` ; l'inbox étant prioritaire sur le tableau, le verdict est `"shutdown"` et la `shutdown_response` part vers le lead. Le drainage `consume_lead_inbox(route_protocol=True)` route la réponse : la requête passe `approved` dans `pending_requests`.
6. **Épilogue** (l. 85–87) : rappel du troisième verdict, `"timeout"` après `IDLE_TIMEOUT` s, non joué (60 s d'attente), et du fait que `spawn_teammate_thread` enchaîne ces mêmes phases avec de vrais tours LLM.

## Ce qui vient de [[shared-py]]

- `scan_unclaimed_tasks()` — le filtre de l'auto-claim (pending + sans owner + `can_start`).
- `idle_poll(agent_name, messages, name, role, worktree_context=None)` — la boucle d'oisiveté, avec ses trois verdicts `work` / `shutdown` / `timeout`.
- `IDLE_TIMEOUT` (et `IDLE_POLL_INTERVAL` implicitement) — les constantes du polling.
- `create_task` / `claim_task` / `complete_task` — le tableau durable de tâches (`.tasks/*.json`) et ses gardes.
- `run_request_shutdown` / `consume_lead_inbox` / `pending_requests` — le protocole d'arrêt de s16, rejoué ici en phase IDLE.
- `BUS.read_inbox` — drainage initial des mailboxes.

## Différences avec l'original learn-claude-code

- L'original `s17_autonomous_agents/code.py` (813 lignes) re-portait toute la pile (task system, protocole, thread teammate, `TOOLS`, `agent_loop`, REPL du lead) ; ici, 91 lignes — uniquement la démo du cycle de vie.
- Aucun tour LLM : la phase WORK est simulée par `claim_task`/`complete_task` directs ; `idle_poll` et `scan_unclaimed_tasks` sont en revanche le vrai code partagé, sommeils de 5 s compris.
- Le `idle_poll` de shared porte le paramètre `worktree_context` (extension venue de s18/s20), absent du s17 original ; sa signature redondante (`agent_name` == `name`, `role` jamais lu) est conservée telle quelle.
- L'id de la tâche auto-revendiquée est extrait de la balise `<auto-claimed>` injectée par `idle_poll` — même couplage au texte que l'original (qui testait `"Claimed" in result`), assumé comme piège pédagogique.
- La démo ajoute une garde de robustesse (verdict ≠ `"work"` → abandon propre) : l'auto-claim prend la plus ancienne tâche libre du tableau, qui peut venir d'une autre session de démo.

## Lancer la démo

```
python src/s17.py
```

Sans appel LLM, mais **comptez ~15 s** : les deux `idle_poll` dorment 5 s avant leur premier scan. On observe : t2 bloquée puis débloquée par la complétion de t1, l'auto-claim en IDLE (`<auto-claimed>Task ...`), la priorité de l'inbox sur le tableau (verdict `"shutdown"`), et la requête de protocole passée `approved` côté lead.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s16-team-protocols]]
- Session suivante : [[s18-worktree-isolation]]
