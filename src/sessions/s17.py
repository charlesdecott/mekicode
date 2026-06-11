"""s17 · Agents autonomes — check the board, claim the task.

Concept : en s16, un teammate inactif attendait passivement les ordres du
lead — avec 10 tâches libres sur le tableau, le lead assignait 10 fois à la
main. s17 rend le teammate AUTONOME : à l'état IDLE, il scrute son inbox puis
le tableau de tâches (scan_unclaimed_tasks) toutes les IDLE_POLL_INTERVAL =
5 s, revendique lui-même la première tâche pending, sans owner, dont toutes
les dépendances sont résolues (auto-claim), et ne s'arrête qu'après
IDLE_TIMEOUT = 60 s sans travail ou sur shutdown_request. Le cycle de vie
complet : WORK → IDLE → (work | shutdown | timeout).

Mapping vers l'original (inspiration/learn-claude-code/s17_autonomous_agents/
code.py) : scan_unclaimed_tasks, idle_poll, claim_task (garde anti-collision
d'owner), consume_lead_inbox et le thread teammate complet
(spawn_teammate_thread) vivent dans shared.py. Ce fichier ne garde que le
délta : une démo qui pilote le cycle de vie À LA MAIN, sans appel LLM — la
phase WORK est simulée, mais idle_poll est le vrai code de shared (sommeils
de 5 s inclus, comptez ~15 s d'exécution).
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
from shared import (BUS, IDLE_TIMEOUT, claim_task, complete_task,
                    consume_lead_inbox, create_task, idle_poll,
                    pending_requests, run_request_shutdown,
                    scan_unclaimed_tasks)


def board():
    """Affiche le tableau vu par scan_unclaimed_tasks (le filtre de
    l'auto-claim : pending + sans owner + can_start)."""
    unclaimed = scan_unclaimed_tasks()
    names = [f"{t['id']} · {t['subject']}" for t in unclaimed]
    print(f"   revendicables : {names if names else 'aucune'}")


def main():
    print("s17 : agents autonomes — cycle WORK → IDLE → SHUTDOWN, sans LLM")
    BUS.read_inbox("alice")                   # mailboxes résiduelles
    consume_lead_inbox()

    # Mini-graphe : t2 dépend de t1 → t2 n'est PAS revendicable au départ.
    t1 = create_task("s17-demo : écrire le module", "démo s17")
    t2 = create_task("s17-demo : tester le module", "démo s17",
                     blockedBy=[t1.id])
    print("\n1. Tableau initial (t2 bloquée par t1) :")
    board()

    # Phase WORK, simulée (pas de LLM) : alice revendique et termine t1.
    messages: list = []
    print("\n2. WORK : alice revendique puis termine t1")
    print("   " + claim_task(t1.id, "alice"))
    print("   " + complete_task(t1.id).replace("\n", " — "))
    board()                                    # t2 est maintenant démarrable

    # Phase IDLE : le VRAI idle_poll de shared. Priorités : inbox d'abord,
    # tableau ensuite (premier scan après 5 s de sommeil). Attendu ici :
    # auto-claim de la plus ancienne tâche libre → verdict "work".
    print("\n3. IDLE : idle_poll('alice', ...) scrute inbox puis tableau...")
    verdict = idle_poll("alice", messages, "alice", "worker")
    print(f"   verdict : {verdict!r}")
    if verdict != "work":
        print("   (inattendu — tableau ou inbox pollués ? démo abrégée)")
        return
    auto_claimed = messages[-1]["content"]     # balise <auto-claimed>...>
    print(f"   message injecté au teammate : {auto_claimed}")

    # Retour en WORK : alice termine la tâche qu'elle s'est auto-assignée
    # (l'id est extrait de la balise — seule consigne donnée au LLM réel).
    claimed_id = auto_claimed.split("Task ")[1].split(":")[0]
    print("\n4. WORK : alice termine la tâche auto-revendiquée")
    print("   " + complete_task(claimed_id))

    # Nouvel IDLE, mais cette fois un shutdown_request attend dans l'inbox :
    # l'inbox est PRIORITAIRE sur le tableau, idle_poll répond et sort.
    print("\n5. lead demande l'arrêt pendant qu'alice est IDLE :")
    print("   " + run_request_shutdown("alice"))
    verdict = idle_poll("alice", messages, "alice", "worker")
    print(f"   verdict : {verdict!r} (shutdown_response envoyée au lead)")

    # SHUTDOWN : le drainage de l'inbox lead route la réponse → approved.
    consume_lead_inbox(route_protocol=True)
    for st in pending_requests.values():
        if st.type == "shutdown" and st.target == "alice":
            print(f"   protocole : {st.request_id} → {st.status}")

    print(f"\n(3e verdict possible : 'timeout' après {IDLE_TIMEOUT} s "
          "sans inbox ni tâche libre — non joué ici. Dans le vrai harness, "
          "spawn_teammate_thread enchaîne ces phases avec des tours LLM.)")


if __name__ == "__main__":
    main()
