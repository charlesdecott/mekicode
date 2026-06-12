#!/usr/bin/env bash
# start.sh - lance l'agent mekicore (REPL).
# Usage : ./start.sh
set -e
cd "$(dirname "$0")"   # se placer a la racine du projet (pour trouver .env)
python packages/mekicore/main.py
