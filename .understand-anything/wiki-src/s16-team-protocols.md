---
title: "s16 · Protocoles d'équipe"
session: 16
phase: "Multi-agents"
fichier: "src/sessions/s16.py"
lignes: 118
tags: [protocoles, request-id, machine-a-etats, shutdown, plan-approval]
prev: "s15-agent-teams"
next: "s17-autonomous-agents"
---

# s16 · Protocoles d'équipe

> **En une phrase** : les échanges lead ↔ teammate deviennent des protocoles requête–réponse corrélés par `request_id` et suivis par une machine à états (`pending → approved | rejected`) — la démo joue les deux protocoles (arrêt négocié, approbation de plan) sans aucun appel LLM, en simulant le côté teammate par des écritures directes sur le MessageBus.

## Rôle dans le harness

Les teammates de [[s15-agent-teams]] savent travailler et se parler, mais en texte libre : impossible de savoir quelle réponse résout quelle demande. s16 structure deux scénarios critiques — **l'arrêt négocié** (tuer un thread brutalement peut laisser des fichiers à moitié écrits ; le lead demande, le teammate confirme) et **l'approbation de plan** (le teammate soumet, le lead tranche avant que le teammate agisse). Les deux partagent la même mécanique : un identifiant `req_NNNNNN` voyage dans les `metadata` du message à l'aller comme au retour, un `ProtocolState` vit dans `pending_requests`, et `match_response` apparie la réponse **par id ET par type** (une `shutdown_response` égarée ne peut pas « approuver » un plan).

L'autre pièce est `consume_lead_inbox` : la lecture d'inbox étant destructive, un seul entonnoir consomme l'inbox du lead et route les `*_response` vers la machine à états avant de retourner les messages — sinon une réponse lue « au mauvais endroit » laisserait sa requête `pending` pour toujours.

## Ce que fait ce fichier

### show() — lignes 27–34
Affiche l'état courant d'une requête : `pending_requests.get(req_id)` puis une ligne `req_id type=... sender → target : status`. C'est la sonde qui rend visibles les transitions de la machine à états avant/après chaque étape.

### drain_mailboxes() — lignes 37–41
Vide les mailboxes `lead`, `alice` et `bob` d'éventuels restes d'exécutions précédentes (la lecture de `MessageBus.read_inbox` est **destructive** : fichier supprimé après lecture) — la démo repart d'un état déterministe.

### demo_shutdown() — lignes 44–70
Le handshake d'arrêt, en quatre temps :

1. `run_request_shutdown("alice")` (l. 48) crée la `ProtocolState` `pending` et envoie le `shutdown_request` ; le `request_id` est retrouvé dans `pending_requests` (l. 49–50).
2. Le côté teammate est **simulé** (l. 55–60) : alice lit son inbox et répond en recopiant le `request_id` reçu — c'est ce recopiage qui boucle la corrélation :

```python
    for msg in BUS.read_inbox("alice"):
        if msg["type"] == "shutdown_request":
            BUS.send("alice", "lead", "Shutting down.",
                     "shutdown_response",
                     {"request_id": msg["metadata"]["request_id"],
                      "approve": True})
```

3. La garde de type est exhibée (l. 62–65) : `match_response("plan_approval_response", req_id, True)` ne change rien — la requête est de type `shutdown`, elle reste `pending`.
4. `consume_lead_inbox(route_protocol=True)` (l. 68) draine l'inbox du lead et route la vraie `shutdown_response` → la requête passe `approved`.

### demo_plan_approval() — lignes 73–101
Le protocole inverse (teammate → lead) :

1. `run_request_plan("bob", ...)` (l. 78) — simple `message`, sans `request_id` : le lead **suggère**, c'est le teammate qui ouvrira la requête formelle.
2. `_teammate_submit_plan("bob", "Plan : ...")` (l. 84–85) crée la `ProtocolState` `plan_approval` et envoie la `plan_approval_request` ; le `req_id` est extrait du retour `Plan submitted (req_...)` (l. 87), exactement comme le fait le gate du teammate dans `spawn_teammate_thread`.
3. Le lead voit la requête arriver via `consume_lead_inbox` (l. 91–92) — pas une `*_response`, donc affichée sans routage.
4. `run_review_plan(req_id, approve=False, feedback=...)` (l. 96–97) : pour ce protocole c'est le **lead qui fait la transition d'état lui-même** (`rejected`) avant d'envoyer la `plan_approval_response` ; bob la lit avec le feedback (l. 99–101).

### main() — lignes 104–113
Enchaîne : drainage initial, deux exemples de `new_request_id()` (l. 107–108), les deux démos, puis l'état final de `pending_requests` — qui ne se vide jamais (les requêtes résolues restent consultables, fuite lente assumée).

## Ce qui vient de [[shared-py]]

- `ProtocolState` / `pending_requests` — la machine à états (un enregistrement par requête en vol) que `show()` inspecte.
- `new_request_id()` — l'identifiant appariable `req_NNNNNN`.
- `match_response(response_type, request_id, approve)` — l'appariement par id ET par type, transitions à sens unique.
- `consume_lead_inbox(route_protocol=True)` — l'entonnoir unique de l'inbox lead.
- `run_request_shutdown` / `run_request_plan` / `run_review_plan` — les trois outils de protocole côté lead.
- `_teammate_submit_plan(from_name, plan)` — le côté teammate de l'approbation de plan.
- `BUS` (`MessageBus.send` / `read_inbox`) — le transport JSONL par mailboxes.

## Différences avec l'original learn-claude-code

- L'original `s16_team_protocols/code.py` (881 lignes) re-portait task system, prompt assembly, MessageBus, background tasks, le thread teammate complet, `TOOLS`, `agent_loop` et le REPL ; tout cela vit dans shared.py — ce fichier ne garde que la démo des protocoles.
- Aucun LLM ni thread : le côté teammate (le `handle_inbox_message` de l'original) est rejoué à la main par `BUS.read_inbox`/`BUS.send`, ce qui rend le recopiage du `request_id` directement lisible.
- Le `match_response` de shared est la version **silencieuse** héritée du s19/s20 original (plus de diagnostics colorés sur id inconnu ou type incohérent) ; la démo compense en affichant l'état avant/après chaque garde.
- De même, le `run_review_plan` de shared a perdu la garde anti-double-review (`status != "pending"`) qu'avait le s16 original — état hérité du resserrement s19/s20.
- Ajout : `drain_mailboxes()` en ouverture, pour que la démo soit déterministe malgré la lecture destructive des mailboxes.

## Lancer la démo

```
python src/sessions/s16.py
```

Sans appel LLM (l'import de shared exige quand même `MODEL_ID` dans `.env`). On observe : deux `req_NNNNNN` d'exemple, puis le handshake d'arrêt — requête `pending`, réponse de type incohérent ignorée, routage par `consume_lead_inbox` → `approved` — puis l'approbation de plan — suggestion en texte libre, `plan_approval_request` de bob, rejet avec feedback → `rejected` — et l'état final de la table `pending_requests`.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s15-agent-teams]]
- Session suivante : [[s17-autonomous-agents]]
