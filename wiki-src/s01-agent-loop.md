---
title: "s01 · La boucle d'agent minimale"
session: 01
phase: "Fondamentaux"
fichier: "src/s01.py"
lignes: 87
tags: [agent-loop, stop-reason, tool-use]
prev: ""
next: "s02-tool-use"
---

# s01 · La boucle d'agent minimale

> **En une phrase** : le mécanisme nu de tout agent de code — une boucle `while True` qui rappelle le LLM avec l'historique complet jusqu'à ce que `stop_reason` ne vaille plus `"tool_use"` — écrit inline, sans `shared.agent_loop`, pour le voir à l'os.

## Rôle dans le harness

Le modèle sait produire du texte et demander des outils ; il n'exécute rien lui-même et ne voit jamais un résultat qu'on ne lui renvoie pas. Le harness fait donc la navette : appeler l'API avec tout l'historique, archiver la réponse, exécuter les outils demandés, renvoyer les résultats, recommencer. Deux signaux suffisent : `stop_reason == "tool_use"` (« j'ai besoin d'un outil » → exécuter et continuer) et toute autre valeur (« j'ai fini » → sortir). **Le modèle décide, le harness exécute** — et c'est le modèle qui contrôle la durée de la boucle.

Cette session est l'EXCEPTION pédagogique de la série : toutes les autres (`s02` à `s20`) appellent la boucle de synthèse `agent_loop` de [[shared-py]] ; ici la boucle est réécrite inline dans `boucle_agent()`, sans outils, pour isoler le squelette conversationnel que `shared.agent_loop` généralise ensuite (compaction, hooks, retry, injections…). Seuls le client API, le modèle et l'extraction de texte viennent de la bibliothèque.

## Ce que fait ce fichier

### Câblage module — lignes 22–26

L'import est en deux temps (lignes 22–23) : `from shared import (WORKDIR, client, MODEL, extract_text)` nomme explicitement ce que la session consomme, et `import shared` est conservé pour `shared.PROMPT` — la session le *rebinde* dans `main()`, or une affectation sur un nom from-importé ne toucherait pas le module. L'ensemble remplace toute la configuration de l'original (dotenv, client Anthropic, readline). Le system prompt est figé localement :

```python
SYSTEM = (f"You are a helpful coding assistant at {WORKDIR}. "
          "Answer concisely.")
```

Pas de « Use bash to solve tasks » comme dans l'original : il n'y a aucun outil à utiliser.

### boucle_agent() — lignes 29–64

Le cœur du fichier, quatre étapes numérotées en commentaires :

```python
    while True:
        # 1. L'appel LLM. L'API est sans état : on renvoie TOUT l'historique
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, max_tokens=8000)

        # 2. Archiver le tour assistant AVANT le test de sortie
        messages.append({"role": "assistant", "content": response.content})

        # 3. La condition de sortie : le modèle contrôle la durée de la boucle
        if response.stop_reason != "tool_use":
            return
```

- **Lignes 39–41** : l'API est sans état — `messages` complet repart à chaque itération ; c'est le harness qui transporte la mémoire. Aucun paramètre `tools` n'est passé : zéro outil déclaré.
- **Ligne 46** : le tour assistant est archivé *avant* le test de sortie — même la réponse finale doit figurer dans l'historique, c'est elle que le REPL affiche.
- **Lignes 51–52** : la condition de sortie. Sans outils déclarés, `stop_reason` ne vaut jamais `"tool_use"` : la boucle ne fait qu'un tour. La *structure* est le point.
- **Lignes 58–64** : la rétro-alimentation — un `tool_result` par `tool_use` (apparié par `tool_use_id`), tous renvoyés dans **un** message de rôle `"user"`. Branche dormante en s01, gardée pour montrer le squelette complet du protocole ; si elle s'exécutait, chaque appel recevrait le placeholder `"Error: no tool available in s01"` (le protocole exige une réponse à chaque `tool_use`, même pour refuser).

### main() — lignes 67–82

Le REPL minimal : `shared.PROMPT` est repositionné en `s01 >> ` (ligne 68), `history` vit hors de la boucle (ligne 71, la conversation est multi-tours), sortie sur `q`/`exit`/vide ou Ctrl-C/Ctrl-D (lignes 73–78). Chaque question est ajoutée comme message `user` puis `boucle_agent(history)` tourne jusqu'à l'arrêt du modèle ; la ligne 81 affiche la réponse finale via `extract_text(history[-1]["content"])` — qui remplace la boucle `for block ... if type == "text"` de l'original.

La garde `if __name__ == "__main__":` (lignes 85–86) lance `main()`.

## Ce qui vient de [[shared-py]]

- `client` — l'instance `Anthropic` (respecte `ANTHROPIC_BASE_URL`), appelée directement ligne 39.
- `MODEL` — l'identifiant de modèle lu dans l'env `MODEL_ID` à l'import de shared.
- `WORKDIR` — la racine du workspace, injectée dans `SYSTEM`.
- `extract_text(content)` — concatène les blocs `text` d'une réponse (affichage final, ligne 81).
- `PROMPT` — le prompt ANSI consommé par `input()`, repositionné par la session (ligne 68). Seul nom encore accédé en `shared.PROMPT` : le rebind doit viser le module, les quatre autres sont from-importés explicitement (ligne 23).

À noter : l'import de shared déclenche aussi son état module-level (répertoires `.tasks/` etc., thread cron, hooks enregistrés) — inutilisé ici, mais présent.

## Différences avec l'original learn-claude-code

- **Zéro outil** : l'original déclarait un outil `bash` et l'exécutait dans la boucle (`run_bash`, ~13 lignes plus le schéma). Ici, aucun outil — la branche d'exécution subsiste en squelette avec un placeholder d'erreur, jamais atteinte. L'outillage arrive en [[s02-tool-use]].
- **~30 lignes de configuration remplacées par `import shared`** : dotenv, purge `ANTHROPIC_AUTH_TOKEN`, instanciation du client, correctif readline.
- **La liste `dangerous` de `run_bash` disparaît** avec l'outil ; la vraie barrière de sécurité de notre harness est `shared.permission_hook` ([[s03-permission]]).
- **Affichage final** : `extract_text` (from-importé de shared) au lieu de l'itération manuelle sur les blocs avec `getattr`.

## Lancer la démo

```
python src/s01.py
```

On observe : un prompt `s01 >> `, une réponse texte par question (un seul aller-retour LLM puisque aucun outil n'est déclaré), l'historique conservé entre les questions. `q` pour quitter. Nécessite `MODEL_ID` (et la clé API) dans `.env`.

## Liens

- Bibliothèque : [[shared-py]]
- Session suivante : [[s02-tool-use]]
