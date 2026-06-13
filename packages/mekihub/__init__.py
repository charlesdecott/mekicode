"""mekihub — hub de session temps réel (salle partagée, file FIFO, pub/sub)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))           # mekihub/ (session, events, hub)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))    # packages/ (mekillm)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mekicore"))  # base, tools, events de mekicore

from session import Author, QueueItem, Session, SessionMeta, SessionState, SessionStore  # noqa: E402,F401
