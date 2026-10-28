param([switch]$Desktop)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$calibreBin = if ($env:CALIBRE_BIN_DIR) { $env:CALIBRE_BIN_DIR } else { 'C:\Program Files\Calibre2' }
$env:CALIBRE_DEVELOP_FROM = Join-Path $projectRoot 'upstream\calibre\src'
$env:CALIBRE_CONFIG_DIRECTORY = Join-Path $projectRoot '.demo\desktop-config'
$env:CALIBRE_CACHE_DIRECTORY = Join-Path $projectRoot '.demo\local-cache'
$demoArgs = @('-e', (Join-Path $PSScriptRoot 'demo.py'), '--', 'start')
if ($Desktop) { $demoArgs += '--desktop' }
& (Join-Path $calibreBin 'calibre-debug.exe') @demoArgs
exit $LASTEXITCODE
