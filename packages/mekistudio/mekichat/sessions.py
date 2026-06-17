"""sessions.py — ré-export de la couche session canonique (packages/mekihub/session.py).

Conservé pour compatibilité des imports existants (`import sessions`). La source unique de
vérité est désormais mekihub. (Retrait de ce shim = piste différée, cf. docs/refacto-differe.md.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))   # packages/ → mekihub

from mekihub.session import (  # noqa: F401
    Author, QueueItem, Session, SessionMeta, SessionState, SessionStore,
    _DEFAULT_TITLE,
)
