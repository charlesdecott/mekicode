# Lance le viewer de wiki multi-projets de mekicode.
# Usage : .\lancer-wiki-viewer.ps1 [port]   (port par defaut : 8088)
# Fonctionne depuis n'importe quel repertoire : $PSScriptRoot = .understand-anything/.
param([int]$Port = 8088)

$server = Join-Path $PSScriptRoot 'wiki-viewer\server.mjs'
if (-not (Test-Path $server)) {
    Write-Error "server.mjs introuvable : $server"
    exit 1
}

Write-Host "Wiki viewer mekicode -> http://127.0.0.1:$Port/  (Ctrl+C pour arreter)"
node $server $Port
