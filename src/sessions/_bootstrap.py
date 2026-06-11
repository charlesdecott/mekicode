"""Rend src/ importable quand une session est lancee en script direct
(python src/sessions/sNN.py) : ajoute le dossier parent (src/) a sys.path
pour que rom shared import ... fonctionne depuis le sous-dossier."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
