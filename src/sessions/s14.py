"""s14 — Cron : le réveil-matin de l'agent.

Démo du scheduler cron de shared.py, porté de
inspiration/learn-claude-code/s14_cron_scheduler/code.py :

- validate_cron        : validation 5 champs, messages nommant le champ fautif ;
- schedule_job         : crée un CronJob (récurrent/one-shot, durable/session) ;
- cron_scheduler_loop  : thread daemon, tick 1 s, anti-double-tir par minute —
  démarré PAR SHARED à l'import (shared.py l. 1469), pas par ce fichier ;
- consume_cron_queue   : drainage atomique des jobs tirés.

L'original recopiait 805 lignes (dont son propre queue processor) ; ici tout
vient de shared.py — agent_loop draine déjà cron_queue en tête de tour. Ce
fichier vérifie que le thread importé tourne, et ajoute deux démos hors-ligne :
`valide` (la validation) et `minute` (un one-shot programmé à la prochaine
minute, qu'on regarde tirer en direct). Lancement : python src/sessions/s14.py
"""

import threading
import time
from datetime import datetime, timedelta
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
from shared import (
    BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT, WORKDIR, agent_loop,
    cancel_job, consume_cron_queue, cron_scheduler_loop,
    print_turn_assistants, run_list_crons, schedule_job, validate_cron,
)


def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("schedule_cron", "list_crons", "cancel_cron", "bash")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}
SYSTEM = ("You are a scheduling agent. schedule_cron takes a 5-field cron "
          "expression (min hour dom month dow); recurring=false makes a "
          "one-shot, durable=true persists to .scheduled_tasks.json. Fired "
          "jobs are injected as [Scheduled] user messages. "
          f"Workspace: {WORKDIR}.")


def scheduler_thread():
    """Retrouve le thread cron_scheduler_loop démarré à l'import de shared
    (inspection de _target : suffisant pour une vérification de démo)."""
    for t in threading.enumerate():
        if getattr(t, "_target", None) is cron_scheduler_loop:
            return t
    return None


def show_validation():
    """Hors-ligne : validate_cron accepte *, */n, listes, plages, et nomme
    le champ fautif sinon — y compris le OU dom/dow du vrai cron."""
    samples = ["0 9 * * *", "*/5 * * * *", "0 9 13 * 5", "30 8-10 * * 1,3,5",
               "61 9 * * *", "0 9 * * 7", "pas un cron"]
    for expr in samples:
        err = validate_cron(expr)
        verdict = "OK    " if err is None else "ERREUR"
        print(f"  {verdict} '{expr}'" + (f" -> {err}" if err else ""))


def demo_one_shot():
    """Hors-ligne : programme un one-shot de session sur la prochaine minute,
    puis regarde le thread de shared le faire tirer (consume_cron_queue)."""
    target = datetime.now() + timedelta(minutes=1)
    expr = f"{target.minute} {target.hour} * * *"
    job = schedule_job(expr, "Dire bonjour à l'utilisateur",
                       recurring=False, durable=False)
    if isinstance(job, str):
        print(f"  erreur de validation : {job}")
        return
    print(f"  {job.id} programmé sur '{expr}' (tir vers {target:%H:%M}:00)")
    print("  attente du tick scheduler (jusqu'à ~60 s, Ctrl-C pour annuler)...")
    try:
        while True:
            fired = consume_cron_queue()
            if fired:
                for j in fired:
                    print(f"  [tir] {j.id} -> prompt planifié : {j.prompt!r}")
                print("  (one-shot : le job s'est retiré de scheduled_jobs)")
                return
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  annulé : {cancel_job(job.id)}")


def main():
    t = scheduler_thread()
    if t is not None and t.is_alive():
        print(f"s14 — cron. Thread scheduler de shared actif ({t.name}, "
              f"démarré à l'import).")
    else:
        print("s14 — cron. [!] thread scheduler introuvable : "
              "vérifier l'amorçage de shared.py (l. 1468-1469).")
    print("`valide`, `minute`, `jobs`, ou un prompt LLM. `q` pour quitter.")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("q", "quit", "exit"):
            break
        if not user:
            continue
        if user == "valide":
            show_validation()
            continue
        if user == "minute":
            demo_one_shot()
            continue
        if user == "jobs":
            print(run_list_crons())
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
