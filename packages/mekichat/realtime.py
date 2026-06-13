"""realtime.py — colle NiceGUI ↔ SessionHub : identité par client, boucle d'abonnement.

Aucune logique métier ici (elle est dans mekihub) : uniquement le rendu live côté NiceGUI.
"""
from __future__ import annotations

import random
import uuid

from nicegui import app

_COLORS = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff", "#2bff88"]


def _browser_id() -> str | None:
    """Id de navigateur stable fourni par NiceGUI (cookie de session signé), ou None.

    Lisible uniquement dans le contexte de page (avant que la réponse ne soit émise) :
    on l'utilise comme graine déterministe de l'identité, pour qu'un même navigateur
    retombe toujours sur le même author_id même si app.storage.user était réinitialisé.
    """
    try:
        return app.storage.browser.get("id")
    except Exception:  # hors contexte de page (tâche de fond) : indisponible
        return None


def author_for_client():
    """Crée/restaure un Author éphémère pour CE navigateur.

    À APPELER DANS LE CONTEXTE DE PAGE (corps de @ui.page) : c'est là que le cookie
    de session est lié à la requête, donc que `app.storage.user`/`app.storage.browser`
    désignent de façon fiable le bon navigateur. Appelée depuis une tâche de fond, la
    résolution resterait correcte en NiceGUI 3.x (le contexte de requête est propagé),
    mais on centralise la résolution dans la page pour rendre le contrat explicite.

    L'identité est dérivée de l'id de navigateur (graine déterministe et stable) ;
    elle est mémorisée dans `app.storage.user` (persisté côté serveur par cookie).
    """
    from mekihub.session import Author
    store = app.storage.user
    if "author_id" not in store:
        bid = _browser_id()
        # graine déterministe par navigateur si dispo, sinon repli aléatoire
        author_id = (bid.replace("-", "")[:8] if bid else uuid.uuid4().hex[:8])
        store["author_id"] = author_id
        store["author_name"] = "anon-" + author_id[:4]
        store["author_color"] = random.choice(_COLORS)
    return Author(id=store["author_id"], name=store["author_name"], color=store["author_color"])
