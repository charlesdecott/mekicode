"""mekichat — front web (NiceGUI) du harness packages/.

Phase 1 : sessions persistées + UI statique. La logique de persistance
(sessions.py) est importable seule, sans NiceGUI.
"""
from .sessions import Session, SessionMeta, SessionStore

__all__ = ["Session", "SessionMeta", "SessionStore"]
