$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$calibreBin = if ($env:CALIBRE_BIN_DIR) { $env:CALIBRE_BIN_DIR } else { 'C:\Program Files\Calibre2' }
$env:CALIBRE_DEVELOP_FROM = Join-Path $projectRoot 'upstream\calibre\src'
$env:CALIBRE_CONFIG_DIRECTORY = Join-Path $projectRoot '.demo\desktop-config'
& (Join-Path $calibreBin 'calibre-debug.exe') -e (Join-Path $PSScriptRoot 'demo.py') -- stop
exit $LASTEXITCODE
