"""s03 — Permissions : la sécurité est du code, pas de la confiance.

Trois barrières s'interposent entre le tool_use du modèle et son exécution :
1. DENY_LIST   — interdits absolus (sudo, rm -rf /, ...) : refus sans question ;
2. DESTRUCTIVE — opérations douteuses (rm , chmod 777, ...) : l'humain tranche ;
3. safe_path   — confinement des outils fichiers au workspace.

Dans notre harness, tout cela vit déjà dans shared.permission_hook, enregistré
sur l'événement PreToolUse à l'import de shared (AVANT log_hook : un outil
refusé n'est jamais loggé). Cette session ne recâble donc rien : elle EXPOSE la
politique active, l'étend (la politique est une donnée : on ajoute un motif à
DENY_LIST) et montre qu'une règle de session s'ajoute par register_hook.

Mapping vers l'original (inspiration/learn-claude-code/s03_permission/code.py) :
- check_deny_list + check_rules + ask_user + check_permission de l'original
  sont fusionnés dans shared.permission_hook (recâblage s04 : hook PreToolUse) ;
- PERMISSION_RULES déclaratif de l'original = constantes DENY_LIST/DESTRUCTIVE ;
- l'insertion `if not check_permission(block)` dans la boucle de l'original =
  le trigger_hooks("PreToolUse", block) déjà présent dans shared.agent_loop.

Lancer : python src/s03.py   (q pour quitter)
Essais : « supprime le dossier tmp » (confirmation), « lance sudo ls » (refus),
         « écris dans ../dehors.txt » (safe_path).
"""

import shared  # rebind de shared.PROMPT : l'affectation doit viser le module
from shared import (BUILTIN_TOOLS, BUILTIN_HANDLERS, WORKDIR, DENY_LIST,
                    DESTRUCTIVE, register_hook, safe_path, agent_loop,
                    print_turn_assistants)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par noms — le délta de chaque session."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file", "edit_file", "glob")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "All destructive operations require user approval.")

# La politique est une donnée : une session peut durcir la deny list globale
# sans toucher au hook (recherche de sous-chaînes naïve, assumée).
DENY_LIST.append("format c:")


def pipe_shell_hook(block):
    """PreToolUse custom : refuse les téléchargements exécutés à la volée.

    Démonstration de register_hook côté session : une règle locale s'empile
    derrière permission_hook et log_hook sans modifier shared.py.
    """
    if block.name == "bash":
        command = block.input.get("command", "")
        if any(dl in command for dl in ("curl", "wget")) and "| sh" in command:
            return "Permission denied: piping a download into a shell"
    return None


register_hook("PreToolUse", pipe_shell_hook)


def demo_safe_path():
    """Barrière 3 hors LLM : le confinement se montre sans dépenser un token."""
    interne = safe_path("notes.txt")
    print(f"  safe_path('notes.txt')        -> {interne}")
    try:
        safe_path("../hors-workspace.txt")
    except ValueError as e:
        print(f"  safe_path('../hors-workspace') -> ValueError: {e}")


def main():
    shared.PROMPT = "\033[36ms03 >> \033[0m"
    print("s03 : permissions — la politique active de shared.permission_hook")
    print(f"  deny list    : {', '.join(DENY_LIST)}")
    print(f"  confirmation : {', '.join(DESTRUCTIVE)}")
    demo_safe_path()
    print("Tape une question, Entrée pour envoyer, q pour quitter.\n")
    history = []
    while True:
        try:
            query = input(shared.PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        turn_start = len(history)
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        print()


if __name__ == "__main__":
    main()
