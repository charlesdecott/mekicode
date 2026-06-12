---
title: "s01 · La boucle d'agent"
session: 01
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s01_agent_loop/code.py"
lignes: 138
tags: [agent-loop, stop-reason, tool-use, bash]
prev: ""
next: "s02-tool-use"
---

# s01 · La boucle d'agent

> **En une phrase** : tout le secret d'un agent de code tient dans une boucle `while` qui exécute les outils demandés par le modèle et lui renvoie les résultats, jusqu'à ce que `stop_reason` ne vaille plus `"tool_use"`.

## Rôle dans le harness

Le problème de départ est simple : vous demandez au modèle « liste les fichiers de mon répertoire et lance tel script ». Le modèle sait *produire* une commande bash, mais une fois sa réponse terminée, il s'arrête — il n'exécute rien lui-même et ne peut pas raisonner sur un résultat qu'il n'a jamais vu. Sans harness, c'est l'humain qui fait la navette : copier la commande, l'exécuter, recoller la sortie dans le chat, attendre la commande suivante. Le README de la session le formule ainsi : *« Every round-trip, you're the middle layer. Automating that is what this chapter is about. »*

La solution est une boucle `while True` articulée autour de deux signaux renvoyés par l'API Anthropic :

| Signal | Sens | Action de la boucle |
|---|---|---|
| `stop_reason == "tool_use"` | Le modèle lève la main : « j'ai besoin d'un outil » | Exécuter → renvoyer le résultat → continuer |
| `stop_reason != "tool_use"` | Le modèle dit : « j'ai fini » | Sortir de la boucle |

C'est LE motif fondateur : **le modèle décide** (appeler un outil ou non, lequel, avec quels arguments), **le harness exécute** (lance l'outil, renvoie le résultat). Les 19 sessions suivantes ne font qu'empiler des mécanismes *autour* de cette boucle — la boucle elle-même ne change plus jamais.

Dans le vrai Claude Code, le cœur de `query.ts` (1729 lignes) est exactement cette boucle de ~30 lignes, enrobée de protections. Différence notable relevée par le README : CC ne se fie pas uniquement à `stop_reason` (peu fiable en streaming, où les blocs `tool_use` peuvent arriver avant la mise à jour du champ) ; il utilise un drapeau `needsFollowUp` positionné dès qu'un bloc `tool_use` est détecté pendant le streaming. CC ajoute aussi un objet d'état à 10 champs (compaction, récupération de tokens, hooks de stop, compteur de tours…) là où la version pédagogique n'a besoin que de `messages`.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–28 | Docstring | Le motif `while stop_reason == "tool_use"` en ASCII art, usage |
| 30–41 | Imports & readline | `os`, `subprocess` ; correctif readline pour la saisie sous macOS/libedit |
| 43–52 | Client API | `load_dotenv`, instanciation `Anthropic`, lecture de `MODEL_ID` |
| 54 | Prompt système | `SYSTEM` : persona « coding agent » + répertoire courant |
| 57–65 | Définition d'outil | `TOOLS` : un seul outil, `bash` |
| 69–81 | Exécution d'outil | `run_bash()` : sous-processus shell avec garde-fous minimaux |
| 85–113 | **Le cœur** | `agent_loop()` : la boucle `while True` + `stop_reason` |
| 117–138 | Point d'entrée | REPL interactif : lit une question, lance la boucle, affiche le texte final |

## Constantes et configuration

- **Bloc readline (lignes 33–41)** : `import readline` dans un `try/except ImportError` (absent sous Windows), avec quatre `parse_and_bind` qui corrigent un bug de retour arrière de libedit (macOS) sur les caractères multi-octets. Les commentaires de ce bloc sont en chinois — le dépôt d'origine est sino-anglophone.
- **`load_dotenv(override=True)` (ligne 46)** : charge `.env` en écrasant les variables déjà présentes dans l'environnement.
- **Purge de `ANTHROPIC_AUTH_TOKEN` (lignes 48–49)** : si `ANTHROPIC_BASE_URL` est défini (passerelle ou proxy), le jeton d'authentification standard est retiré pour éviter un conflit d'authentification avec la passerelle.
- **`client` (ligne 51)** : instance `Anthropic`, avec `base_url` optionnelle.
- **`MODEL` (ligne 52)** : `os.environ["MODEL_ID"]` — accès direct sans valeur par défaut : le programme plante immédiatement si la variable manque (échec rapide voulu).
- **`SYSTEM` (ligne 54)** : `f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."` — trois informations seulement : le rôle, le répertoire de travail, et la consigne d'agir au lieu d'expliquer (sinon le modèle a tendance à décrire les commandes au lieu de les appeler).
- **`TOOLS` (lignes 57–65)** : la liste des outils envoyée à l'API. Un seul outil ici :

```python
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]
```

C'est un JSON Schema : c'est tout ce que le modèle « sait » de l'outil. Le nom, la description et le schéma des paramètres suffisent au modèle pour produire des blocs `tool_use` bien formés.

## Les fonctions, une à une

### `run_bash(command)` — lignes 69–81

L'unique exécuteur d'outil : lance une commande shell et renvoie sa sortie sous forme de chaîne — car le modèle ne consomme que du texte.

```python
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"
```

- **Lignes 70–72** : un embryon de sécurité par sous-chaînes — si la commande contient `rm -rf /`, `sudo`, etc., on renvoie une erreur *textuelle* au lieu d'exécuter. C'est trivialement contournable (`rm -rf //`, variables shell…) ; le README l'assume : c'est une démo pédagogique, le vrai système de permission arrive en [[s03-permission]].
- **Ligne 74–75** : `shell=True` (le modèle peut utiliser pipes et redirections), `capture_output=True` + `text=True` (stdout/stderr capturés en `str`), `timeout=120` (une commande qui bloque ne gèle pas l'agent indéfiniment).
- **Ligne 76** : `stdout + stderr` concaténés — le modèle a besoin de voir les erreurs autant que la sortie normale pour s'auto-corriger.
- **Ligne 77** : troncature à 50 000 caractères — premier rempart contre l'explosion du contexte (traité sérieusement en [[s08-context-compact]]). Si la sortie est vide, on renvoie `"(no output)"` : une chaîne vide laisserait le modèle dans le doute (« la commande a-t-elle tourné ? »).
- **Lignes 78–81** : *toutes* les erreurs (timeout, binaire introuvable) sont converties en chaînes `"Error: ..."`. Détail capital : **un outil ne lève jamais d'exception vers la boucle** — l'erreur est un résultat comme un autre, renvoyé au modèle pour qu'il s'adapte.

### `agent_loop(messages)` — lignes 85–113

LE cœur de tout harness d'agent. Tout Claude Code, et tout agent de code en général, est une variation de ces 29 lignes.

```python
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # If the model didn't call a tool, we're done
        if response.stop_reason != "tool_use":
            return

        # Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m$ {block.input['command']}\033[0m")
                output = run_bash(block.input["command"])
                print(output[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

        # Feed tool results back, loop continues
        messages.append({"role": "user", "content": results})
```

Décortiquons chaque étape, car tout le reste du cours repose dessus :

- **Lignes 87–90 — l'appel LLM.** À chaque itération, on renvoie à l'API *l'historique complet* (`messages`) plus les définitions d'outils (`tools=TOOLS`). L'API est sans état : le modèle ne « se souvient » de rien, c'est le harness qui transporte la mémoire. `max_tokens=8000` plafonne chaque réponse.
- **Ligne 93 — archiver le tour assistant.** `response.content` est une liste de blocs (`text` et/ou `tool_use`). On l'ajoute telle quelle dans l'historique avec `role: "assistant"`. Indispensable : au prochain tour, le modèle doit revoir ses propres appels d'outils pour comprendre à quoi correspondent les résultats.
- **Lignes 96–97 — la condition de sortie.** `stop_reason` vaut `"tool_use"` quand le modèle s'est arrêté *parce qu'il demande un outil*. Toute autre valeur (`"end_turn"` quand il a fini de répondre, `"max_tokens"` s'il est tronqué…) fait sortir de la boucle par `return`. C'est le seul point de décision : **le modèle contrôle la durée de la boucle**, pas le harness. La version pédagogique n'a qu'un seul chemin de sortie ; CC en a une dizaine (abandon utilisateur, limite de tours, prompt trop long, hooks de stop…).
- **Lignes 100–110 — exécution des appels d'outils.** Une réponse peut contenir *plusieurs* blocs `tool_use` (et des blocs `text` mélangés) : on itère donc sur `response.content` et on filtre par `block.type`. Pour chaque appel : ligne 103 affiche la commande en jaune (codes ANSI `\033[33m`), ligne 104 exécute, ligne 105 montre un aperçu (200 premiers caractères — l'affichage est tronqué, mais pas le contenu renvoyé au modèle). Lignes 106–110 : le résultat est emballé dans un bloc `tool_result` dont le champ **`tool_use_id` reprend `block.id`** — c'est ce qui permet à l'API d'apparier chaque résultat avec l'appel correspondant. Sans cet identifiant, l'API rejette la requête suivante.
- **Ligne 113 — la rétro-alimentation.** Les résultats repartent dans l'historique **avec `role: "user"`** : du point de vue du protocole de l'API, un résultat d'outil est un message utilisateur (c'est l'environnement qui « parle » au modèle). Puis le `while True` reboucle : nouvel appel LLM, qui voit maintenant les résultats et décide de continuer ou de conclure.

Subtilité de conception : `messages` est muté en place (pas de copie, pas de valeur de retour). C'est ce qui permet au point d'entrée de relire `history[-1]` après l'appel pour afficher la réponse finale — et de conserver tout l'historique entre deux questions de l'utilisateur.

### Point d'entrée `if __name__ == "__main__"` — lignes 117–138

Un REPL minimal autour de la boucle.

```python
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
```

- **Ligne 121** : `history` vit *en dehors* de la boucle REPL — la conversation est multi-tours, chaque nouvelle question s'empile sur l'historique précédent (le modèle garde le fil).
- **Lignes 123–127** : sortie propre sur Ctrl-D/Ctrl-C (`EOFError`/`KeyboardInterrupt`) ou sur `q`, `exit`, ou entrée vide.
- **Lignes 129–130** : la question est ajoutée comme message `user`, puis `agent_loop(history)` tourne jusqu'à ce que le modèle s'arrête.
- **Lignes 132–136** : après la boucle, `history[-1]` est le dernier tour assistant. Son `content` est une liste d'objets SDK (pas des dicts), d'où le `getattr(block, "type", None)` défensif — on n'affiche que les blocs `text`. Le garde `isinstance(response_content, list)` couvre le cas théorique où le dernier message ne serait pas un tour assistant structuré.

À noter : les messages d'accueil (lignes 118–119) sont en chinois (« tapez votre question, Entrée pour envoyer, q pour quitter ») — hérité du dépôt d'origine ; les sessions [[s04-hooks]] et suivantes passent à l'anglais.

## Ce qui change par rapport à la session précédente

s01 est la graine : il n'y a pas de session précédente. Ce fichier *est* le noyau que toutes les autres sessions reprennent intégralement et étendent d'UN mécanisme à la fois :

- [[s02-tool-use]] remplace l'appel codé en dur `run_bash(...)` par une table de dispatch `TOOL_HANDLERS` et passe de 1 à 5 outils ;
- [[s03-permission]] insère un contrôle de permission avant chaque exécution d'outil ;
- [[s04-hooks]] sort cette logique d'extension de la boucle vers un registre de hooks ;
- la boucle `while True` + `stop_reason`, elle, reste identique au caractère près jusqu'à la fin du cours.

## Pièges et détails d'implémentation

- **Les résultats d'outils sont des messages `user`**, pas `assistant` ni un rôle spécial : c'est la convention du protocole Messages, et la source d'erreur n°1 quand on réimplémente la boucle.
- **`tool_use_id` est obligatoire** : chaque `tool_result` doit citer l'`id` du bloc `tool_use` correspondant, sinon l'API rejette le message suivant.
- **Le tour assistant doit être archivé *avant* le test de sortie** (ligne 93 avant ligne 96) : même quand le modèle s'arrête, sa réponse finale doit figurer dans l'historique — c'est elle que le REPL affiche.
- **Une réponse = potentiellement N appels d'outils** : d'où la boucle `for block in response.content` et la liste `results` — tous les résultats du tour repartent dans *un seul* message user.
- **`stop_reason` est fiable ici, pas en streaming** : la version pédagogique fait des appels non-streamés. Le vrai CC streame et utilise un drapeau `needsFollowUp` posé dès qu'un bloc `tool_use` apparaît, car `stop_reason` peut ne pas être encore renseigné (`query.ts:554-558`).
- **Les outils ne lèvent jamais d'exception** : timeout et erreurs système deviennent des chaînes `"Error: ..."` renvoyées au modèle. Un crash d'outil ne doit jamais tuer la boucle — le modèle est censé lire l'erreur et se corriger ([[s11-error-recovery]] systématise cette idée).
- **La liste `dangerous` n'est pas une sécurité** : correspondance de sous-chaînes naïve, contournable par mille variantes. Elle évite juste les accidents les plus grossiers en démo.

## Liens

- Session suivante : [[s02-tool-use]]
- Sessions liées : [[s03-permission]] (la vraie barrière avant exécution), [[s04-hooks]] (extension de la boucle sans la modifier), [[s08-context-compact]] (que faire quand `messages` devient trop gros), [[s11-error-recovery]] (les chemins de sortie multiples du vrai CC)
