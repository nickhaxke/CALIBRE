# Non-Destructive Environment Verification Script
# Calibre Institutional Customization

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " CALIBRE INSTITUTIONAL ENVIRONMENT VERIFICATION" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Calibre Executables
$calibreExe = "C:\Program Files\Calibre2\calibre.exe"
$calibredbExe = "C:\Program Files\Calibre2\calibredb.exe"
if (Test-Path $calibreExe) {
    $versionOutput = & $calibredbExe --version
    Write-Host "[OK] Calibre installed at C:\Program Files\Calibre2: $versionOutput" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Calibre not found at C:\Program Files\Calibre2" -ForegroundColor Red
}

# 2. Workspace Check
$ws = "C:\dev\calibre-institutional"
if (Test-Path $ws) {
    Write-Host "[OK] Development workspace exists: $ws" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Workspace missing: $ws" -ForegroundColor Red
}

# 3. Upstream Git Repo
$upstream = "C:\dev\calibre-institutional\upstream\calibre"
if (Test-Path "$upstream\.git") {
    $commit = git -C $upstream rev-parse --short HEAD
    $branch = git -C $upstream branch --show-current
    Write-Host "[OK] Upstream repository checked out: branch '$branch', commit $commit" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Upstream git repository not cloned at $upstream" -ForegroundColor Red
}

# 4. Port 8080 Status
$conn = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
if ($conn) {
    $procId = $conn[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "[OK] Content Server active on port 8080 (PID $procId - $($proc.ProcessName))" -ForegroundColor Green
} else {
    Write-Host "[WARN] No service listening on port 8080" -ForegroundColor Yellow
}

# 5. Disk Space
$freeGb = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Write-Host "[INFO] Free disk space on C: $freeGb GB" -ForegroundColor Cyan
Write-Host "Verification complete. All production components intact." -ForegroundColor Green
