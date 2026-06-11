"""s01 — La boucle d'agent minimale.

Tout le secret d'un agent de code tient dans une boucle :

    while True:
        response = LLM(messages)
        archiver la réponse
        if stop_reason != "tool_use": sortir
        exécuter les outils, renvoyer les tool_result

Mapping vers l'original (inspiration/learn-claude-code/s01_agent_loop/code.py) :
- client API, MODEL, extract_text : repris de shared.py (config dédupliquée) ;
- la boucle while + stop_reason : réécrite ICI, inline — c'est l'EXCEPTION
  pédagogique de la série. Toutes les autres sessions appellent
  shared.agent_loop ; s01 montre le mécanisme nu que cette fonction généralise.
- l'outil bash de l'original est volontairement absent : zéro outil, pour
  isoler le squelette conversationnel (l'outillage arrive en s02).

Lancer : python src/sessions/s01.py   (q pour quitter)
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # rebind de shared.PROMPT : l'affectation doit viser le module
from shared import (WORKDIR, client, MODEL, extract_text)

SYSTEM = (f"You are a helpful coding assistant at {WORKDIR}. "
          "Answer concisely.")


def boucle_agent(messages: list):
    """Le mécanisme nu : appel LLM → archivage → test stop_reason → feedback.

    Sans outils déclarés, stop_reason ne vaut jamais "tool_use" : la boucle ne
    fait qu'un seul tour. La STRUCTURE est le point — dès qu'on déclare des
    outils (s02), la partie basse exécute et renvoie les tool_result.
    """
    while True:
        # 1. L'appel LLM. L'API est sans état : on renvoie TOUT l'historique
        # à chaque itération ; c'est le harness qui transporte la mémoire.
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, max_tokens=8000)

        # 2. Archiver le tour assistant AVANT le test de sortie : même la
        # réponse finale doit figurer dans l'historique (c'est elle que le
        # REPL affichera).
        messages.append({"role": "assistant", "content": response.content})

        # 3. La condition de sortie : le modèle contrôle la durée de la
        # boucle, pas le harness. Toute valeur autre que "tool_use"
        # ("end_turn", "max_tokens", ...) termine le tour.
        if response.stop_reason != "tool_use":
            return

        # 4. La rétro-alimentation : un tool_result par tool_use, tous
        # renvoyés dans UN message de rôle "user" (l'environnement « parle »
        # au modèle). Branche dormante en s01 — aucun outil déclaré — mais
        # gardée pour montrer le squelette complet du protocole.
        results = []
        for block in response.content:
            if block.type == "tool_use":
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": "Error: no tool available in s01"})
        messages.append({"role": "user", "content": results})


def main():
    shared.PROMPT = "\033[36ms01 >> \033[0m"
    print("s01 : la boucle d'agent minimale — inline, sans outils")
    print("Tape une question, Entrée pour envoyer, q pour quitter.\n")
    history = []
    while True:
        try:
            query = input(shared.PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        boucle_agent(history)
        print(extract_text(history[-1]["content"]))
        print()


if __name__ == "__main__":
    main()
