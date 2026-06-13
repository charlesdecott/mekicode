"""realtime.py — colle NiceGUI ↔ SessionHub : identité par client, boucle d'abonnement.

Aucune logique métier ici (elle est dans mekihub) : uniquement le rendu live côté NiceGUI.
"""
from __future__ import annotations

import random
import uuid

from nicegui import app

_COLORS = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff", "#2bff88"]


def author_for_client():
    """Crée/restaure un Author éphémère pour ce navigateur (stocké dans app.storage.user)."""
    from mekihub.session import Author
    store = app.storage.user
    if "author_id" not in store:
        store["author_id"] = uuid.uuid4().hex[:8]
        store["author_name"] = "anon-" + store["author_id"][:4]
        store["author_color"] = random.choice(_COLORS)
    return Author(id=store["author_id"], name=store["author_name"], color=store["author_color"])
