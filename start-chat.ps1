# start-chat.ps1 - lance le front web mekichat (NiceGUI).
# Usage : .\start-chat.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot   # racine du projet (pour trouver .env et .sessions/)
python packages/mekistudio/mekichat/app.py
