# run_js_tests.ps1 — lance les tests de la géométrie pure (node --test).
# Usage : .\tests\js\run_js_tests.ps1
$ErrorActionPreference = "Stop"
$js = Join-Path $PSScriptRoot "..\..\packages\mekistudio\mekicanvas\static\js"
node --test (Join-Path $js "cables.test.js") (Join-Path $js "collision.test.js")
