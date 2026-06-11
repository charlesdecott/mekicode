"""s16 · Protocoles d'équipe — requête/réponse corrélées par request_id.

Concept : en s15, les échanges lead ↔ teammate étaient du texte libre. s16 les
structure en PROTOCOLES : chaque requête (arrêt négocié, approbation de plan)
reçoit un identifiant `req_NNNNNN` (new_request_id), vit dans pending_requests
sous forme de ProtocolState — machine à états pending → approved | rejected,
transitions à sens unique — et la réponse est appariée par match_response,
par id ET par type : une shutdown_response égarée ne peut pas « approuver »
un plan. consume_lead_inbox est l'entonnoir unique de l'inbox du lead : il
route les *_response avant de retourner les messages.

Mapping vers l'original (inspiration/learn-claude-code/s16_team_protocols/
code.py) : ProtocolState, pending_requests, new_request_id, match_response,
consume_lead_inbox, run_request_shutdown, run_request_plan, run_review_plan
et le côté teammate _teammate_submit_plan vivent dans shared.py (sections
« Protocoles » et « Teams / MessageBus »). Ce fichier ne garde que le délta :
une démo scriptée SANS appel LLM — le côté teammate est simulé par des
écritures directes sur le MessageBus, exactement ce que ferait
handle_inbox_message dans spawn_teammate_thread.
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
from shared import (BUS, _teammate_submit_plan, consume_lead_inbox,
                    match_response, new_request_id, pending_requests,
                    run_request_plan, run_request_shutdown, run_review_plan)


def show(req_id: str):
    """Affiche l'état courant d'une requête de pending_requests."""
    st = pending_requests.get(req_id)
    if st is None:
        print(f"   (requête {req_id} inconnue)")
        return
    print(f"   {st.request_id} type={st.type} "
          f"{st.sender} → {st.target} : {st.status}")


def drain_mailboxes():
    """Vide les mailboxes résiduelles d'exécutions précédentes (la lecture
    est destructive : on repart d'un état propre et déterministe)."""
    for agent in ("lead", "alice", "bob"):
        BUS.read_inbox(agent)


def demo_shutdown():
    """Arrêt négocié : lead → shutdown_request, teammate (simulé) →
    shutdown_response, routage automatique par consume_lead_inbox."""
    print("\n=== 1. Arrêt négocié (shutdown handshake) ===")
    print("   " + run_request_shutdown("alice"))
    req_id = next(r for r, s in pending_requests.items()
                  if s.type == "shutdown" and s.target == "alice")
    show(req_id)

    # Côté teammate, simulé : alice lit son inbox et répond en RECOPIANT le
    # request_id reçu — c'est ce recopiage qui boucle la corrélation.
    for msg in BUS.read_inbox("alice"):
        if msg["type"] == "shutdown_request":
            BUS.send("alice", "lead", "Shutting down.",
                     "shutdown_response",
                     {"request_id": msg["metadata"]["request_id"],
                      "approve": True})

    # Garde de match_response : une réponse du MAUVAIS type ne résout rien.
    match_response("plan_approval_response", req_id, True)
    print("   après une réponse de type incohérent (ignorée) :")
    show(req_id)                                   # toujours pending

    # L'entonnoir unique de l'inbox lead route les *_response avant retour.
    msgs = consume_lead_inbox(route_protocol=True)
    print(f"   consume_lead_inbox → {len(msgs)} message(s) consommé(s)")
    show(req_id)                                   # → approved


def demo_plan_approval():
    """Approbation de plan : le lead suggère (run_request_plan, simple
    message), le teammate ouvre la requête formelle (_teammate_submit_plan),
    le lead tranche (run_review_plan)."""
    print("\n=== 2. Approbation de plan ===")
    print("   " + run_request_plan("bob", "refactorer le module auth"))
    for m in BUS.read_inbox("bob"):                # bob lit la suggestion
        print(f"   bob reçoit [{m['type']}] {m['content']}")

    # Côté teammate : submit_plan crée la ProtocolState ET envoie la requête
    # plan_approval_request au lead, request_id dans les métadonnées.
    ret = _teammate_submit_plan(
        "bob", "Plan : 1) extraire auth.py 2) adapter les tests")
    print(f"   bob : {ret}")
    req_id = ret.split("(")[1].rstrip(")")
    show(req_id)                                   # pending

    # Le lead voit la requête (pas une *_response : affichée, pas routée).
    for m in consume_lead_inbox(route_protocol=True):
        print(f"   lead reçoit [{m['type']}] {m['content'][:60]}")

    # Verdict — pour ce protocole, c'est le LEAD qui fait la transition
    # d'état lui-même (la requête est de sens teammate → lead).
    print("   " + run_review_plan(
        req_id, approve=False, feedback="Trop risqué, découpe en 2 étapes"))
    show(req_id)                                   # → rejected
    for m in BUS.read_inbox("bob"):
        print(f"   bob reçoit [{m['type']}] "
              f"approve={m['metadata'].get('approve')} : {m['content']}")


def main():
    print("s16 : protocoles d'équipe — sans LLM, teammates simulés via le bus")
    drain_mailboxes()
    print(f"\nnew_request_id() → exemples : "
          f"{new_request_id()}, {new_request_id()}")
    demo_shutdown()
    demo_plan_approval()
    print("\nÉtat final de pending_requests (la table ne se vide jamais) :")
    for rid in pending_requests:
        show(rid)


if __name__ == "__main__":
    main()
