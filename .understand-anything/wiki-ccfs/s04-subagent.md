---
title: "s04 · Subagent"
session: 04
phase: "Boucle d'agent"
fichier: "inspiration/claude-code-from-scratch/s04_subagent.py"
lignes: 190
tags: [subagent, isolation-contexte, delegation, dispatch-agent]
prev: "s03-todo-write"
next: "s05-skill-loading"
---

# s04 · Subagent

> **En une phrase** : un outil `spawn_subagent` dont le handler contient une boucle d'agent complète — le sous-agent travaille dans un historique vierge et seul son résumé final remonte au lead, dont le contexte reste propre.

## Rôle dans le harness

Motto : *« Break big tasks down; each subtask gets a clean context »*. Le problème visé est la **pollution de contexte** : une exploration de codebase ou un débogage par essais-erreurs génère des dizaines de tours d'outils (lectures de fichiers, greps infructueux, stack traces) qui encombrent l'historique du lead bien après avoir cessé d'être utiles. Chaque token de ces détours est rechargé à *chaque* appel suivant — coût et dilution de l'attention.

La solution est architecturalement élégante : puisque la boucle d'agent est une fonction, et qu'un outil est une fonction, **un outil peut contenir une boucle d'agent**. `run_subagent` instancie un historique neuf, fait tourner le cycle perception-action de [[s01-perception-action-loop]] jusqu'au bout, et ne renvoie au parent que le texte final. La docstring résume le mapping d'états : côté parent, quatre entrées (« User Request, Asst: "I will spawn a subagent", User: (Subagent Result), Asst: "Done" ») ; côté sous-agent, tout le travail sale. Le lead devient un chef de projet : il délègue, il ne lit pas les brouillons.

Dans le vrai Claude Code, l'analogue est l'outil **`dispatch_agent`** (colonne « Claude Code Analog » du README) — l'outil Task qui lance des sous-agents Explore ou general-purpose, potentiellement en parallèle, avec des budgets propres. Le repo jumeau learn-claude-code introduit le même mécanisme dans sa session subagent (s09), avec types d'agents nommés et profondeur de récursion contrôlée ; la version d'ici est volontairement minimale : un seul type de sous-agent, exécution synchrone, un seul niveau de profondeur. Le README liste d'ailleurs en première piste d'amélioration : *« refactor `spawn_subagent` to use `asyncio.gather` and dispatch three explore subagents simultaneously, exactly how Claude Code does it internally »* — ce que préparent [[s08-background-tasks]] et [[s09-agent-teams]].

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–23 | Shebang & docstring | Motto, les 3 concepts (isolation, protection, délégation), le mapping des deux historiques |
| 25–28 | Imports stdlib | `os`, `sys`, `typing` |
| 30–38 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `dispatch_tools`, `stream_loop` |
| 40–53 | Configuration | `SYSTEM` (le manager) et `SUBAGENT_SYSTEM` (le spécialiste) |
| 56–112 | **Nouveau** | `run_subagent()` : la boucle s01 encapsulée dans un handler d'outil |
| 115–143 | Schémas & dispatch | `SUBAGENT_TOOLS`, `SUBAGENT_DISPATCH` |
| 146–185 | REPL | `main()` : boucle du lead via `stream_loop` |
| 188–190 | Point d'entrée | Garde `if __name__ == "__main__"` |

## Constantes et configuration

- **`SYSTEM` (lignes 43–47)** : le prompt du lead — « You are a **lead** coding agent… For complex or isolated subtasks, use spawn_subagent to delegate. » Il vend l'outil au modèle : « Subagents run in a fresh context — perfect for exploration or risky operations. » Comme en [[s03-todo-write]], c'est le prompt qui active le mécanisme.
- **`SUBAGENT_SYSTEM` (lignes 50–53)** : le prompt du spécialiste — « You are a subagent working on a specific subtask… **Summarize your result clearly at the end.** » La dernière phrase est le contrat critique : le résumé final est *la seule chose* que le parent verra ; un sous-agent qui finit sur un appel d'outil ou un texte vague rend sa délégation inutile.
- **`SUBAGENT_TOOLS` (lignes 118–137)** : `EXTENDED_TOOLS + [spawn_subagent]`. La description du schéma (lignes 121–125) guide l'usage : « Use for exploration, risky operations, or tasks that shouldn't pollute the main conversation history » — les trois cas d'usage canoniques.
- **`SUBAGENT_DISPATCH` (lignes 140–143)** : le pattern d'extension habituel :

```python
SUBAGENT_DISPATCH: Dict[str, Any] = {
    **EXTENDED_DISPATCH, # Include bash, read, write, etc.
    "spawn_subagent": lambda inp: run_subagent(inp["prompt"]),
}
```

## Les fonctions, une à une

### `run_subagent(prompt)` — lignes 58–112

Le cœur de la session : une boucle d'agent complète déguisée en handler d'outil. Tout commence par l'isolation :

```python
    # UI Notification: Print in Magenta (\033[35m) to distinguish from the Lead Agent
    print(f"\033[35m  [subagent] spawned for: {prompt[:60]}...\033[0m")
    
    # Initialize a FRESH, isolated message history for the subagent
    sub_messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
```

- **Ligne 76** : `sub_messages` ne contient que le prompt de délégation. Le sous-agent ne voit ni la requête utilisateur d'origine, ni les tours précédents du lead — l'isolation est totale, dans les deux sens. Conséquence directe : **la qualité du `prompt` rédigé par le lead est le seul canal d'information** ; un prompt vague produit un sous-agent perdu.

Puis la boucle, structurellement identique à celle de [[s01-perception-action-loop]] :

```python
    while True:
        # Step 1: Call the LLM with the specialist's system prompt and fresh history
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            messages=sub_messages,
            tools=EXTENDED_TOOLS, # Subagents have full access to standard tools
            max_tokens=8000,
        )
        
        # Step 2: Record the subagent's response to its internal history
        sub_messages.append({"role": "assistant", "content": response.content})
        
        # Step 3: Check if the subagent is finished (stop_reason isn't tool_use)
        if response.stop_reason != "tool_use":
            break
        
        # Step 4: If the subagent wants to use tools, execute them using the standard dispatch
        results: List[Dict[str, Any]] = dispatch_tools(response.content, EXTENDED_DISPATCH)
        
        # Step 5: Append results back to the subagent's private history
        sub_messages.append({"role": "user", "content": results})
```

- **Ligne 83** : `system=SUBAGENT_SYSTEM` — le sous-agent a sa propre identité, pas celle du lead.
- **Ligne 85** : `tools=EXTENDED_TOOLS` et **non** `SUBAGENT_TOOLS` — le sous-agent n'a pas accès à `spawn_subagent`. La récursion est bornée à un niveau *par construction* : pas de garde-fou à coder, le schéma absent suffit. Même choix que le vrai Claude Code, dont les sous-agents n'ont pas l'outil Task.
- **Lignes 81–100** : `create()` non streamé, `stop_reason`, `dispatch_tools`, réinjection — la boucle de s01 au mot près, mais sur `sub_messages` et `EXTENDED_DISPATCH`. La démonstration que le primitif perception-action est *composable* : il tourne aussi bien au sommet qu'à l'intérieur d'un outil.

Enfin l'extraction du résultat :

```python
    # Final Step: Extract the text components from the subagent's last message
    # We ignore tool_use blocks here to provide a clean summary to the parent
    final_result: str = "".join(
        block.text for block in sub_messages[-1]["content"]
        if hasattr(block, "text")
    )
    
    # UI Notification: Log completion in Magenta
    print(f"\033[35m  [subagent] done: {final_result[:100]}...\033[0m")
    
    return final_result
```

- **Lignes 104–107** : on ne garde que les blocs porteurs de `.text` du dernier message assistant (objets SDK, d'où `hasattr` plutôt qu'un test de type dict). Tout le reste — les dizaines de tours d'outils intermédiaires — est **jeté** avec `sub_messages` à la sortie de la fonction. C'est ça, la compression : N tours de travail → une chaîne.
- **Ligne 112** : le retour est une simple `str` ; côté parent, `dispatch_tools` l'emballera en `tool_result`. Du point de vue du lead, `spawn_subagent` est un outil comme `grep` : une requête, une réponse texte.

### `main()` — lignes 148–185

REPL identique à [[s03-todo-write]] dans sa structure : header (ligne 153), `history` du lead, capture d'entrée, mots de sortie, puis :

```python
        # Start the Lead Agent's autonomous loop
        # Note: We use the SUBAGENT_TOOLS and SUBAGENT_DISPATCH sets here.
        stream_loop(
            messages=history,
            tools=SUBAGENT_TOOLS,
            dispatch=SUBAGENT_DISPATCH,
            system=SYSTEM
        )
```

- **Lignes 177–182** : le lead tourne dans `stream_loop` (streaming), avec le trio complet `tools`/`dispatch`/`system`. Quand le modèle appelle `spawn_subagent`, c'est `dispatch_tools` — à l'intérieur de `stream_loop` — qui invoque `run_subagent`, lequel fait tourner sa propre boucle `create()` de manière **synchrone** : le lead est suspendu jusqu'au retour du sous-agent.

### Point d'entrée — lignes 188–190

Garde standard `if __name__ == "__main__": main()`.

## Ce qui vient de [[core-py]]

| Import | Définition dans core.py | Rôle ici |
|---|---|---|
| `client` | ligne 72 | Réutilisé pour les appels `create()` du sous-agent |
| `MODEL` | ligne 75 | Même modèle pour lead et sous-agent (le vrai CC peut en changer, ex. un modèle léger pour l'exploration) |
| `EXTENDED_TOOLS` | lignes 369–426 | La palette du sous-agent (ligne 85) et la base de `SUBAGENT_TOOLS` (ligne 118) |
| `EXTENDED_DISPATCH` | lignes 436–443 | Le routage du sous-agent (ligne 97) et la base de `SUBAGENT_DISPATCH` (ligne 141) |
| `dispatch_tools` | lignes 524–570 | Exécute les appels d'outils *du sous-agent* dans sa boucle interne |
| `stream_loop` | lignes 573–626 | La boucle *du lead* ; c'est elle qui finit par appeler `run_subagent` via le dispatch |

## Pièges et détails d'implémentation

- **Exécution synchrone** : `run_subagent` tourne dans le fil du handler d'outil — le lead (et le terminal) sont bloqués pendant toute la vie du sous-agent. L'exécution en arrière-plan arrive en [[s08-background-tasks]], les équipiers persistants en [[s09-agent-teams]].
- **Pas de récursion, par omission de schéma** : ligne 85, le sous-agent reçoit `EXTENDED_TOOLS`, pas `SUBAGENT_TOOLS`. Un seul niveau de délégation possible — choix de design encodé dans *ce que le modèle ne voit pas*.
- **Aucune borne sur le sous-agent** : pas de limite de tours ni de budget tokens. Un sous-agent qui patine consomme des appels API en silence (seules les lignes magenta et les sorties d'outils trahissent l'activité).
- **`max_tokens` tronque le résumé sans signal** : si le sous-agent s'arrête sur `stop_reason == "max_tokens"`, la boucle sort normalement et le parent reçoit un résumé coupé, présenté comme complet.
- **L'isolation est contextuelle, pas filesystem** : lead et sous-agent partagent le même cwd, les mêmes fichiers — et le même dict `SNAPSHOTS` de [[core-py]] : un `revert` du lead peut annuler un `write` fait par le sous-agent. L'isolation des effets de bord, c'est [[s12-worktree-task-isolation]].
- **Le sous-agent ne streame pas** : boucle à base de `create()` — son raisonnement intermédiaire est invisible ; on ne voit que `[subagent] spawned`, les appels d'outils de `dispatch_tools`, et `[subagent] done`.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s04_subagent.py
```

Prérequis : `pip install -r requirements.txt` et un `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou proxy LiteLLM via `ANTHROPIC_BASE_URL`).

Bon test : « explore ce repo et dis-moi comment les sessions partagent leur code, puis propose une amélioration ». On observe le lead annoncer la délégation, puis la ligne magenta `  [subagent] spawned for: ...`, la rafale d'appels `[read]`/`[grep]`/`[glob]` du sous-agent (sans texte streamé : il ne streame pas), la ligne `  [subagent] done: ...`, et enfin le lead qui reprend la main et synthétise — son historique ne contient que le résumé, pas l'exploration.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s03-todo-write]]
- Session suivante : [[s05-skill-loading]]
- Sessions liées : [[s08-background-tasks]] (la délégation devient non bloquante), [[s09-agent-teams]] (les sous-agents deviennent des équipiers persistants), [[s12-worktree-task-isolation]] (l'isolation s'étend au filesystem)
