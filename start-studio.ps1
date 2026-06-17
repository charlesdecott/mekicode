# start-studio.ps1 — lance le front studio (NiceGUI) : 3 modes Chat / Canvas / Mix.
# Usage : .\start-studio.ps1   → http://localhost:8080/studio
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot   # racine du projet (pour trouver .env et .sessions/)
python packages/mekistudio/mekichat/app.py
