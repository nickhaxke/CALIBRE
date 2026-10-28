# Safe Development Test Server Runner
# Launches an isolated test server instance on port 8088 without affecting production.

param (
    [int]$Port = 8088
)

$CalibreServer = "C:\Program Files\Calibre2\calibre-server.exe"
$TestLib = "C:\dev\calibre-institutional\tests\fixtures\test-library"

if (-not (Test-Path $TestLib)) {
    New-Item -ItemType Directory -Path $TestLib -Force | Out-Null
    Write-Host "Created isolated test library directory at $TestLib" -ForegroundColor Yellow
}

Write-Host "Starting isolated development Calibre server on port $Port..." -ForegroundColor Green
Write-Host "Command: $CalibreServer --port $Port --listen-on 127.0.0.1 '$TestLib'" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to terminate test server." -ForegroundColor Yellow

& $CalibreServer --port $Port --listen-on 127.0.0.1 $TestLib
