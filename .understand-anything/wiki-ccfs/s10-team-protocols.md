---
title: "s10 · Team Protocols"
session: 10
phase: "Async & multi-agents"
fichier: "inspiration/claude-code-from-scratch/s10_team_protocols.py"
lignes: 316
tags: [fsm, protocole, états, lock, delegation, protocol-agent]
prev: "s09-agent-teams"
next: "s11-autonomous-agents"
---

# s10 · Team Protocols

> **En une phrase** : chaque équipier devient un objet `ProtocolAgent` gouverné par une machine à états finis à 4 états (IDLE → REQUESTING → WAITING → RESPONDING), avec un `threading.Lock` par agent pour rendre atomiques les transitions d'état et le pop-all de la mailbox.

## Rôle dans le harness

Dans [[s09-agent-teams]], la communication est *de facto* : des fonctions libres écrivent et lisent des fichiers JSONL, et l'état d'un agent (« occupé ? en attente ? ») n'existe nulle part — il faut le déduire des logs. La devise de s10 : *« Teammates need shared communication rules »*. Dès que l'équipe grandit ou que les échanges se croisent, l'absence de règles produit les pathologies classiques du distribué : messages perdus (le lost update du pop-all de s09), agents qui se parlent en même temps, attentes circulaires. s10 répond par la **formalisation** : un état explicite par agent, des transitions nommées, et un verrou qui protège état et courrier.

Trois mouvements structurent la session. D'abord un `Enum` `AgentState` rend l'état **observable et discret** — un agent est dans exactement un des 4 états, et on peut l'afficher, le tester, le logger. Ensuite la classe `ProtocolAgent` **encapsule** ce qui était éclaté en s09 : identité, prompt, mailbox, verrou et boucle d'exécution vivent dans le même objet — envoyer un message devient `agent.send(...)`, plus une fonction libre qui bricole des chemins de fichiers. Enfin le `threading.Lock` rend les sections critiques atomiques — c'est la réponse directe au pop-all non protégé de s09.

Le README aligne cette session sur la **« Tool-call coordination »** du vrai Claude Code : dans CC, la coordination inter-agents passe par des appels d'outils structurés (SendMessage et consorts) dont le cycle requête/réponse est implicitement une machine à états — un agent qui attend une réponse est bloqué dans son tour d'outil, exactement le WAITING d'ici. La version pédagogique rend cet implicite explicite. Dans learn-claude-code, l'équivalent est la session s16 (team protocols), même FSM affichée dans la bannière.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–28 | Shebang & docstring | Devise, 4 concepts (états, verrous, enforcement, encapsulation), définition des 4 états |
| 30–38 | Imports stdlib | `json`, `threading`, `time`, `enum.Enum`, `Path`, typing |
| 40–48 | Imports core | 6 symboles du socle |
| 50–54 | Configuration | `MAILBOX_DIR` (le même `.mailboxes/` que s09) |
| 56–63 | **Nouveau** | `AgentState` : l'Enum des 4 états |
| 66–186 | **Nouveau** | Classe `ProtocolAgent` : `__init__`, `send`, `receive`, `handle` |
| 189–201 | Équipe | `TEAMMATES` : alpha (analyste) et beta (rédacteur), instances de `ProtocolAgent` |
| 203–229 | **Nouveau** | `run_delegate()` : l'outil de délégation du lead |
| 232–268 | Schémas & config | `PROTO_TOOLS`, `PROTO_DISPATCH`, `SYSTEM` du lead |
| 271–311 | Point d'entrée | `main()` : REPL affichant les états au démarrage |
| 314–316 | Lancement | `if __name__ == "__main__"` |

## Constantes et configuration

- **`MAILBOX_DIR` (lignes 53–54)** : le même répertoire `.mailboxes/` que [[s09-agent-teams]], mais les fichiers sont suffixés `_proto.jsonl` (ligne 90) — les deux démos peuvent coexister sans se lire mutuellement le courrier.
- **`TEAMMATES` (lignes 192–201)** : la différence de nature avec s09 saute aux yeux — ce n'est plus un dict `nom → prompt` mais `nom → instance de ProtocolAgent` : `alpha` (*« a senior code analyst … Focus on quality and logic »*) et `beta` (*« a specialized code writer … Focus on implementation »*). L'agent est un objet à état, pas une chaîne.
- **`PROTO_TOOLS` (lignes 234–254)** : `EXTENDED_TOOLS` + un seul outil, `delegate`, avec la même contrainte `"enum": list(TEAMMATES.keys())` qu'en s09 (ligne 243) — d'où l'ordre du fichier : `TEAMMATES` doit exister avant le schéma qui l'énumère.
- **`PROTO_DISPATCH` (lignes 257–260)** : `**EXTENDED_DISPATCH` + `delegate` → `run_delegate`.
- **`SYSTEM` (lignes 263–268)** : persona du lead, interpolation dynamique des noms d'équipiers, consigne de synthèse — même gabarit qu'en s09 avec `delegate` à la place de `send_to_teammate`.

## Les fonctions, une à une

### `class AgentState(Enum)` — lignes 58–63

```python
class AgentState(Enum):
    """Enumeration of the possible operational states of a protocol agent."""
    IDLE       = "idle"        # Available for new work
    REQUESTING = "requesting"  # Actively sending a message
    WAITING    = "waiting"     # Blocked, awaiting a reply
    RESPONDING = "responding"  # Processing a task (LLM active)
```

Quatre états, quatre moments du cycle requête/réponse. L'`Enum` apporte ce qu'une chaîne libre n'a pas : un ensemble fermé (pas d'état « en attente » vs « waiting » selon l'humeur), la comparaison par identité (`agent.state is AgentState.IDLE`), et l'introspection — `main()` liste les états en itérant sur la classe (ligne 279).

### `class ProtocolAgent` — lignes 68–186

L'unité d'encapsulation de la session : identité + rôle + état + mailbox + verrou + boucle d'exécution. Quatre méthodes, détaillées ci-dessous.

### `ProtocolAgent.__init__(name, system)` — lignes 78–92

```python
        self.name: str = name
        self.system: str = system
        self.state: AgentState = AgentState.IDLE
        # Define the private mailbox file path for this agent
        self._inbox: Path = MAILBOX_DIR / f"{name}_proto.jsonl"
        # Lock to ensure thread-safe access to state and mailbox
        self._lock: threading.Lock = threading.Lock()
```

- **Ligne 88** : tout agent naît `IDLE` — l'état initial du FSM.
- **Ligne 90** : la mailbox devient un attribut **privé** (`_inbox`) — en s09, n'importe quelle fonction pouvait fabriquer le chemin et lire le courrier d'autrui ; ici l'accès passe (en principe) par les méthodes.
- **Ligne 92** : un verrou **par agent**, pas global — deux agents peuvent travailler en parallèle, seules les opérations sur le *même* agent se sérialisent.

### `ProtocolAgent.send(to_agent, message, msg_type="request")` — lignes 94–120

L'envoi formel, avec sa double transition IDLE → REQUESTING → WAITING.

```python
        with self._lock:
            # Update state to reflect active sending
            self.state = AgentState.REQUESTING
            
        # Append the structured message to the recipient's mailbox
        with open(to_agent._inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "from": self.name, 
                "type": msg_type, 
                "body": message,
                "timestamp": time.time()
            }) + "\n")
            
        with self._lock:
            # Transition to WAITING after the message is successfully offloaded
            self.state = AgentState.WAITING
```

- **Lignes 105–107 et 118–120** : chaque transition est prise **sous verrou**, mais l'I/O fichier (110–116) est volontairement *hors* verrou — on ne tient pas un lock pendant une écriture disque qui peut bloquer.
- **Ligne 110** : `to_agent._inbox` — l'expéditeur écrit directement dans le fichier du destinataire, sans prendre `to_agent._lock`. La conséquence est importante (voir pièges) : le verrou du destinataire ne protège sa boîte que contre… lui-même.
- **Lignes 111–116** : l'enveloppe gagne un champ `type` (`request`/`reply`) par rapport à s09 — l'amorce d'un vrai protocole typé, même si rien ne l'exploite encore.
- À noter : aucune méthode ne ramène jamais l'agent de WAITING à IDLE — `send` est une impasse du FSM tel qu'implémenté (voir pièges).

### `ProtocolAgent.receive()` — lignes 122–138

```python
        if not self._inbox.exists():
            return []
            
        with self._lock:
            # Read and parse JSONL lines, skipping empty ones
            lines = self._inbox.read_text(encoding="utf-8").splitlines()
            msgs = [json.loads(line) for line in lines if line.strip()]
            # Clear mailbox immediately after reading to avoid duplicates
            self._inbox.write_text("", encoding="utf-8")
            return msgs
```

- **Lignes 132–138** : le pop-all de s09, mais cette fois **sous verrou** : lecture, parsing et effacement forment une section critique. Deux `receive()` concurrents sur le même agent ne peuvent plus se voler de messages — c'est la correction du « lost update » annoncée dans la docstring.
- Limite : la correction n'est que partielle, car `send()` n'acquiert pas ce verrou en écrivant (cf. pièges). Et contrairement à s09, il n'y a pas de `try/except` autour de `json.loads` — une ligne corrompue fait remonter l'exception au code appelant.

### `ProtocolAgent.handle(message)` — lignes 140–186

Le traitement d'une requête : IDLE → RESPONDING → IDLE, autour d'une boucle LLM autonome.

```python
        with self._lock:
            # Mark the agent as busy
            self.state = AgentState.RESPONDING
            
        # Initialize internal message history for this specific request
        sub_history: List[Dict[str, Any]] = [{"role": "user", "content": message}]
        
        # Autonomous "Think-Act" cycle
        while True:
            response = client.messages.create(
                model=MODEL,
                system=self.system,
                messages=sub_history,
                tools=EXTENDED_TOOLS,
                max_tokens=4000,
            )
            sub_history.append({"role": "assistant", "content": response.content})
            
            if response.stop_reason != "tool_use":
                break
            
            results = dispatch_tools(response.content, EXTENDED_DISPATCH)
            sub_history.append({"role": "user", "content": results})
            
        with self._lock:
            # Return to IDLE state once the task is finished
            self.state = AgentState.IDLE
```

- **Lignes 152–154** : passage en RESPONDING sous verrou — mais sans **vérifier** l'état courant : un agent déjà RESPONDING accepterait une seconde requête sans broncher (voir pièges).
- **Lignes 157–176** : c'est mot pour mot la boucle spécialiste de [[s09-agent-teams]] — contexte vierge par requête, `client.messages.create` non-streamé, `dispatch_tools` + `EXTENDED_DISPATCH` de [[core-py]], rebouclage sur `stop_reason == "tool_use"`. La nouveauté n'est pas la boucle, c'est son **emballage** dans un état observable.
- **Le verrou n'enveloppe pas la boucle LLM** : il est relâché entre les deux transitions (lignes 152–154 puis 178–180). Délibéré et indispensable — un tour LLM dure des secondes ; le tenir sous verrou gèlerait toute lecture d'état pendant ce temps. Le verrou protège les *transitions*, pas le *travail*.
- **Lignes 183–186** : extraction du texte final, identique à s09 (`hasattr(block, "text")`).

### `run_delegate(name, message)` — lignes 205–229

L'outil du lead — et la surprise du fichier.

```python
    agent = TEAMMATES.get(name)
    if not agent:
        return f"Error: Agent '{name}' not found."
    
    # Visual feedback in Magenta
    print(f"\033[35m  [protocol] lead → {name}: {message[:60]}...\033[0m")
    
    # Execute the formal handler (IDLE -> RESPONDING -> IDLE)
    result = agent.handle(message)
    
    # Visual feedback in Magenta
    print(f"\033[35m  [protocol] {name} → lead: {result[:60]}...\033[0m")
    
    return result
```

- **Ligne 224** : `agent.handle(message)` — un **appel de méthode direct et synchrone**. Pas de `send()`, pas de `receive()`, pas de polling : là où s09 faisait transiter la tâche par fichier et attendait en sondant, s10 appelle la fonction et attend le `return`. Les mailboxes et le couple REQUESTING/WAITING existent dans la classe mais ne sont pas exercés par la démo (voir pièges — c'est le piège principal de la session).
- **Lignes 221 et 227** : les logs magenta `lead → alpha` / `alpha → lead` matérialisent le protocole dans le terminal — la seule trace « réseau » d'un échange qui est en réalité une pile d'appels.

### `main()` — lignes 273–311

```python
    # Lists the possible states defined in the AgentState Enum
    states_list = [s.value for s in AgentState]
    print(f"\033[90ms10: FSM protocol | states: {states_list}\033[0m\n")
```

REPL standard : prompt cyan `s10 >> ` (ligne 289), sortie sur `q`/`exit`/`quit` (lignes 296–297) ou `Ctrl+C` via `sys.exit(0)` (ligne 293), tour du lead par `stream_loop` avec `PROTO_TOOLS`/`PROTO_DISPATCH` (lignes 303–308). Particularités : la bannière (lignes 279–280) énumère les états du FSM par introspection de l'Enum ; et contrairement à s09, **ni threads à lancer, ni `finally` de nettoyage** — il n'y a rien à arrêter, et le flux de la démo n'écrit aucun fichier mailbox.

## Ce qui vient de [[core-py]]

Import en lignes 41–48, les six symboles sont utilisés :

- **`client`, `MODEL`** — la boucle think-act de `handle()` appelle l'API en direct (lignes 161–162), sans streaming.
- **`EXTENDED_TOOLS`** — outils des équipiers (ligne 165) et base de `PROTO_TOOLS` (ligne 234).
- **`EXTENDED_DISPATCH`** — exécution des outils des équipiers (ligne 175) et base de `PROTO_DISPATCH` (ligne 258).
- **`dispatch_tools`** — moteur d'exécution des `tool_use` dans `handle()` (ligne 175).
- **`stream_loop`** — la boucle du lead (ligne 303).

## Pièges et détails d'implémentation

- **`send()` et `receive()` ne sont jamais appelés** : le chemin réellement exécuté est `run_delegate → agent.handle()`, un appel synchrone. La machinerie asynchrone (mailboxes `_proto.jsonl`, transitions REQUESTING/WAITING) est définie, documentée… et morte dans cette démo. Le FSM ne s'exerce que sur l'axe IDLE ↔ RESPONDING.
- **Aucun thread dans s10** : contrairement à [[s09-agent-teams]], alpha et beta s'exécutent **dans le thread du lead**. Les verrous ne protègent donc rien en pratique ici — ils préparent le terrain pour un usage multi-thread (celui de s09) sans en subir la complexité pendant la leçon.
- **Le lost update n'est corrigé qu'à moitié** : `receive()` verrouille bien son pop-all, mais `send()` écrit dans `to_agent._inbox` **sans prendre `to_agent._lock`** (ligne 110). Un envoi concurrent pendant un `receive()` peut toujours glisser un message entre `read_text` et `write_text("")` — et le perdre. La vraie réponse, c'est un broker avec opérations atomiques : [[s22-production-mailbox]].
- **Le FSM décrit, il n'impose pas** : la docstring promet qu'un agent ne peut pas accepter de requête quand il est RESPONDING ou WAITING, mais `handle()` écrase l'état sans le tester (lignes 152–154) — pas de branche de refus, pas d'exception `InvalidTransition`. L'« enforcement » annoncé est un contrat moral.
- **WAITING est une impasse** : après `send()`, rien ne ramène jamais l'agent à IDLE — `receive()` ne touche pas à l'état. Si on branchait réellement le chemin asynchrone, tout expéditeur resterait WAITING pour l'éternité.
- **L'appel LLM est hors verrou — c'est voulu** : tenir `_lock` pendant `handle()` entier bloquerait toute lecture d'état pendant des secondes. La contrepartie : entre les deux `with self._lock`, l'état peut être lu et modifié par d'autres — la cohérence n'est garantie qu'au niveau de chaque transition.
- **Pas de `try/except` dans `receive()`** : contrairement à `_receive_messages` de s09, une ligne JSONL corrompue lève ici une exception chez l'appelant au lieu d'être loggée — encapsulation mieux rangée, gestion d'erreurs en recul.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s10_team_protocols.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM). Rien d'autre — pas de Redis, pas de dépôt git ; `.mailboxes/` est créé mais reste vide dans le flux de la démo.

La bannière affiche le FSM : `s10: FSM protocol | states: ['idle', 'requesting', 'waiting', 'responding']`. Essayer : `délègue à alpha une analyse critique de core.py, puis demande à beta d'en écrire un résumé dans NOTES.md`. On observe les paires magenta `[protocol] lead → alpha: ...` / `[protocol] alpha → lead: ...`, les appels d'outils des équipiers tracés par `dispatch_tools` (en jaune), puis la synthèse streamée du lead. Les délégations sont strictement séquentielles : beta ne démarre qu'après le retour d'alpha.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s09-agent-teams]]
- Session suivante : [[s11-autonomous-agents]]
- Sessions liées : [[s22-production-mailbox]] (le transport mûrit : Redis pub/sub avec opérations atomiques, là où le verrou local ne suffit pas), [[s12-worktree-task-isolation]] (l'autre moitié de la coordination d'équipe : isoler le *travail* des agents, pas seulement leurs messages)
