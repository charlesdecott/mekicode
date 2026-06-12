# start.ps1 - lance l'agent mekicore (REPL).
# Usage : .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot   # se placer a la racine du projet (pour trouver .env)
python packages/mekicore/main.py
