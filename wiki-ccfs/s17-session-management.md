---
title: "s17 · Gestion de sessions"
session: 17
phase: "Durcissement production"
fichier: "inspiration/claude-code-from-scratch/s17_session_management.py"
lignes: 301
tags: [sessions, persistance, json, resume, fork, serialisation, repl]
prev: "s16-event-bus"
next: "s18-parallel-tools"
---

# s17 · Gestion de sessions

> **En une phrase** : chaque conversation devient un objet à identité propre (`id` de 8 hex, titre, timestamps), sérialisé en JSON dans `.sessions/` après chaque tour, qu'on peut lister (`:sessions`), reprendre (`:resume`) ou cloner en branche indépendante (`:fork`).

## Rôle dans le harness

Le docstring nomme le problème : la **volatilité** (lignes 7–9). L'historique de conversation ne vit qu'en mémoire ; un crash, un Ctrl+C ou une fermeture de terminal, et des heures de contexte construit — fichiers lus, décisions prises, plan en cours — s'évaporent. La devise (ligne 5) : *« Every conversation is saved; pick up where you left off »*.

La session ajoute une **couche de sérialisation** complète : l'historique `messages` est enveloppé dans un dict de session avec identité (`id` unique de 8 caractères, `title` lisible, timestamps `created`/`updated`) et persisté en JSON après chaque tour réussi (auto-save). La difficulté technique réelle est la sérialisation : `stream_loop` ajoute à l'historique des objets Pydantic du SDK Anthropic (`TextBlock`, `ToolUseBlock`), qui ne passent pas tels quels dans `json.dumps` — `_serialize_messages` les aplatit en dicts. Le `fork` couronne le tout : cloner une session sous un nouvel ID pour explorer deux stratégies en parallèle depuis un point de départ commun, sans polluer l'original.

L'analogie README (tableau Phase 4) : **« CC session persistence »**. Le vrai Claude Code journalise chaque session en JSONL sous `~/.claude/projects/`, propose `claude --resume`/`--continue`, et son fork de conversation (rewind, branchements) repose sur le même principe : l'historique est un fichier, pas un état de process. C'est la dernière session de la phase « Durcissement production » : avec streaming, outils réversibles, permissions, hooks et maintenant persistance, l'agent encaisse un redémarrage — la définition même de « deployable » donnée par le README.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–29 | Shebang & docstring | Motto, 4 concepts (sérialisation, identité, auto-save, fork), les 5 commandes REPL |
| 31–38 | Imports stdlib | `os`, `json`, `uuid`, `sys`, `datetime`, `Path`, `typing` |
| 40–45 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 47–54 | Configuration | `SESSIONS_DIR` (créé au démarrage), `SYSTEM` |
| 56–192 | **Le mécanisme** | 6 fonctions de gestion : création, sérialisation, save, load, listing, affichage |
| 195–296 | REPL | `main()` : commandes `:sessions` `:resume` `:fork` `:title` `:save` + interaction agent |
| 299–301 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`SESSIONS_DIR = Path(".sessions")` (lignes 50–51)** : le répertoire de persistance, créé dès l'import (`mkdir(exist_ok=True)`) — aucune fonction n'a à vérifier son existence ensuite. Un fichier par session : `.sessions/<id>.json`.
- **`SYSTEM` (ligne 54)** : persona minimale `f"You are a coding agent at {os.getcwd()}."` — la session ne touche pas au comportement de l'agent, seulement à son cycle de vie.

## Les fonctions, une à une

### `create_new_session()` — lignes 58–71

Fabrique le dict de session vierge :

```python
    return {
        "id": uuid.uuid4().hex[:8],         # Unique 8-character hex ID
        "created": datetime.now().isoformat(), # ISO 8601 creation timestamp
        "updated": datetime.now().isoformat(), # Last modification timestamp
        "title": "New Session",             # Default human-readable title
        "messages": []                      # Empty conversation history
    }
```

- **Ligne 66** : `uuid.uuid4().hex[:8]` — 8 caractères hexadécimaux, soit 4 octets d'aléa : assez court pour être tapé à la main dans `:resume`, assez large (4 milliards de valeurs) pour qu'une collision locale soit improbable. Aucune vérification d'unicité pour autant : une collision écraserait silencieusement l'ancien fichier.
- La session est un **dict ordinaire**, pas une classe : tout le module la manipule par clés, et la sérialisation JSON est directe.

### `_serialize_messages(messages)` — lignes 74–109

Le cœur technique. L'historique mélange des dicts purs (tours `user`) et des listes de blocs SDK (tours `assistant` produits par `stream_loop`, tours `tool_result`) :

```python
        if isinstance(content, list):
            clean_content = []
            for block in content:
                # If it's a Pydantic model from the SDK, use model_dump()
                if hasattr(block, "model_dump"):
                    clean_content.append(block.model_dump())
                # If it's a generic object with a __dict__, use that
                elif hasattr(block, "__dict__"):
                    clean_content.append(block.__dict__)
                # Otherwise, assume it's already a dictionary
                else:
                    clean_content.append(block)
            content = clean_content
```

- **Ligne 91** : seul un `content` de type liste est traité — un `content` chaîne (requête utilisateur) passe tel quel.
- **Lignes 95–102** : cascade de trois stratégies par bloc. `model_dump()` (Pydantic v2, le cas normal pour les blocs du SDK Anthropic) ; sinon `__dict__` (objet quelconque) ; sinon le bloc est déjà un dict (cas d'une session *rechargée* depuis JSON, dont les blocs sont restés des dicts). Cette troisième branche est ce qui rend la sérialisation **idempotente** — on peut sauvegarder une session resumée sans rien casser.
- **Lignes 105–108** : reconstruction propre `{"role", "content"}` — les éventuelles clés parasites d'un message sont éliminées au passage.
- Le préfixe `_` signale un helper interne : seul `save_session` l'appelle.

### `save_session(session_data)` — lignes 112–132

```python
    # Update the 'updated' timestamp before saving
    session_data["updated"] = datetime.now().isoformat()

    # Define the file path: .sessions/<id>.json
    file_path = SESSIONS_DIR / f"{session_data['id']}.json"

    # Prepare serializable content
    json_ready_data = {
        **session_data,
        "messages": _serialize_messages(session_data["messages"])
    }

    # Write to disk with indentation for readability
    file_path.write_text(json.dumps(json_ready_data, indent=2), encoding="utf-8")
```

- **Ligne 120** : le timestamp `updated` est rafraîchi à chaque save — c'est lui qu'affiche `:sessions`.
- **Lignes 126–129** : copie superficielle `{**session_data}` avec `messages` remplacés par leur version sérialisée — l'historique **en mémoire garde ses objets SDK intacts**, seul le disque reçoit les dicts. La conversation en cours n'est jamais perturbée par une sauvegarde.
- **Ligne 132** : `indent=2` — le JSON est volontairement lisible : on peut ouvrir `.sessions/<id>.json` et relire la conversation, outils compris.

### `load_session(session_id)` — lignes 135–154

Lecture inverse : `SESSIONS_DIR / f"{session_id}.json"`, `None` si le fichier n'existe pas (lignes 146–147), et un `try/except (json.JSONDecodeError, IOError)` qui affiche l'erreur en rouge et renvoie `None` plutôt que de crasher sur un fichier corrompu (lignes 149–154). L'appelant traite `None` comme « session introuvable » — un seul chemin d'erreur pour deux causes.

À noter : aucune *désérialisation* symétrique — les messages rechargés restent des dicts. C'est volontairement suffisant : l'API Anthropic accepte les blocs `tool_use`/`tool_result` au format dict aussi bien qu'en objets SDK.

### `list_all_sessions()` — lignes 157–175

```python
    files = sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    for f in files:
        try:
            sessions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue # Skip corrupted files
```

- **Ligne 168** : tri par **mtime du fichier** (plus récent d'abord), pas par le champ `updated` du JSON — équivalent en pratique puisque chaque save réécrit le fichier, et plus rapide (pas besoin de parser pour trier).
- **Lignes 173–174** : un fichier corrompu est ignoré en silence (`continue`) — le listing survit à un JSON cassé.

### `print_sessions_table()` — lignes 178–192

Le rendu console de la liste : en-tête souligné (code ANSI `\033[4m`), puis une ligne par session — ID en cyan, `updated` tronqué aux secondes (`[:19]` coupe l'ISO 8601 avant les microsecondes), titre tronqué-padded à 40 caractères (`{...[:40]:40}`), compte de messages en gris. Cas vide géré explicitement : `(No saved sessions found in .sessions/)`.

### `main()` — lignes 197–296

Le REPL, sensiblement enrichi. À l'ouverture, une session neuve est créée et son ID affiché (lignes 205–206) ; le prompt l'affiche en continu : `s17 (a3f81b2c) >>` (ligne 212). Les sorties (`q`/`exit`/`quit`, Ctrl+C/D) **sauvegardent avant de quitter** (lignes 213–223) — l'auto-save couvre aussi la fin de vie.

Puis le routage des cinq commandes, chacune terminée par `continue` pour ne jamais atteindre l'appel au modèle :

- **`:sessions`** (lignes 228–230) → `print_sessions_table()`.
- **`:resume <id>`** (lignes 233–241) : `load_session`, et si trouvée, **`current_session = loaded`** — la conversation rechargée devient le contexte courant ; le prochain message utilisateur s'ajoutera à son historique et `stream_loop` repartira avec tout le passé.
- **`:fork <id>`** (lignes 244–261) :

```python
                new_sid = uuid.uuid4().hex[:8]
                current_session = {
                    **source,
                    "id": new_sid,
                    "title": f"Fork of {source['title'][:30]}",
                    "created": datetime.now().isoformat(),
                    "updated": datetime.now().isoformat()
                }
                save_session(current_session)
```

Copie de la session source (donc de ses `messages`) sous un nouvel ID, titre `Fork of ...`, timestamps neufs, **save immédiat** — le fork existe sur disque avant même le premier message. La source n'est jamais modifiée : les deux branches divergent librement. C'est le pattern git appliqué à la conversation.
- **`:title <texte>`** (lignes 264–269) : renomme et sauvegarde aussitôt.
- **`:save`** (lignes 272–274) : sauvegarde manuelle — surtout symbolique vu l'auto-save, mais rassurante.

Enfin l'interaction agent (lignes 277–296) :

```python
        # If it's a new session, auto-title it based on the first query
        if not current_session["messages"]:
            current_session["title"] = query[:50]

        # Append user query to history
        current_session["messages"].append({"role": "user", "content": query})

        # Execute the thinking/acting loop
        stream_loop(
            messages=current_session["messages"],
            tools=EXTENDED_TOOLS,
            dispatch=EXTENDED_DISPATCH,
            system=SYSTEM
        )

        # Auto-save after every assistant turn
        save_session(current_session)
```

- **Lignes 280–281** : auto-titrage — la première requête (tronquée à 50 caractères) devient le titre, exactement comme les titres de sessions du vrai Claude Code. Un `:title` ultérieur peut toujours corriger.
- **Lignes 287–292** : `stream_loop` reçoit directement `current_session["messages"]` et le mute en place — l'enveloppe de session et la boucle de [[core-py]] se partagent la même liste.
- **Ligne 295** : l'auto-save **après chaque tour complet** ; un crash en plein milieu d'un tour ne perd que ce tour, jamais la conversation.

### Point d'entrée — lignes 299–301

`if __name__ == "__main__": main()` — protection standard.

## Ce qui vient de [[core-py]]

Importés lignes 41–45 :

- **`EXTENDED_TOOLS`** — les 6 schémas d'outils ; la persistance est orthogonale aux capacités de l'agent.
- **`EXTENDED_DISPATCH`** — la table de dispatch standard, sans garde ni hooks : s17 isole son sujet.
- **`stream_loop`** — la boucle streaming + dispatch, consommée telle quelle. C'est elle qui injecte les objets SDK dans `messages` — la raison d'être de `_serialize_messages`.

## Pièges et détails d'implémentation

- **L'entrée vide n'est plus filtrée** : contrairement à [[s13-streaming]]–[[s16-event-bus]] (`if not query or ...`), le test de sortie est ici `if query.lower() in ("q", "exit", "quit")` (ligne 220). Appuyer sur Entrée à vide envoie un message `content: ""` au modèle (et fixe un titre vide si la session est neuve) — l'API rejette le contenu vide, d'où une exception non gérée. Régression discrète du gabarit REPL.
- **Quitter immédiatement crée quand même un fichier** : la session est créée au lancement et l'auto-save de sortie s'applique aussi aux sessions vides — `.sessions/` se remplit de « New Session (0 msgs) » si on ouvre/ferme souvent.
- **Le fork est une copie superficielle** : `{**source}` ne copie pas profondément `messages` — sans conséquence ici car `source` sort fraîchement de `load_session` et n'est référencé nulle part ailleurs, mais le pattern deviendrait un bug si l'on forkait la session *courante* en mémoire.
- **`:resume` au milieu d'une conversation abandonne la session courante sans la sauvegarder** : le dernier auto-save date du dernier tour complet — tout `:title` non suivi d'un message est sauvé, mais un basculement sans tour intermédiaire ne déclenche pas de save de l'ancienne session (en pratique couvert par l'auto-save par tour, sauf modifications hors-tour).
- **Sérialisation idempotente grâce à la 3e branche** : les sessions resumées contiennent des dicts, pas des objets SDK ; sans le `else: clean_content.append(block)` de la ligne 102, le premier save après un `:resume` planterait.
- **Aucune validation du contenu rechargé** : `load_session` vérifie que le JSON parse, pas que `messages` alterne correctement `user`/`assistant` ni que les `tool_use` ont leur `tool_result`. Un fichier édité à la main peut produire une erreur API au premier tour.
- **`signature`/champs extra des blocs SDK** : `model_dump()` sérialise *tous* les champs des blocs (y compris `id` des tool_use) — c'est ce qui permet au replay de fonctionner, l'API retrouvant les paires `tool_use_id`/`tool_result` intactes.

## Lancer la démo

```bash
python s17_session_management.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM) ; le répertoire `.sessions/` est créé automatiquement. Scénario complet : poser une question (le titre se fixe tout seul, un fichier `.sessions/<id>.json` apparaît), quitter avec `q`, relancer, `:sessions` pour retrouver l'ID, `:resume <id>` et constater que le modèle se souvient du contexte ; puis `:fork <id>` et faire diverger les deux branches — `:sessions` montre l'original et son « Fork of … » côte à côte.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s16-event-bus]]
- Session suivante : [[s18-parallel-tools]]
- Sessions liées : [[s06-context-compact]] (l'autre réponse à la durée : compresser le contexte plutôt que le persister), [[s07-task-system]] (même principe d'état durable sur disque, pour les tâches), [[s09-agent-teams]] (mailboxes JSONL : la persistance appliquée à la communication inter-agents)
