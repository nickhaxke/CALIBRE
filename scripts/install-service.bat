@echo off
setlocal
cd /d "%~dp0.."
echo [Calibre Institutional] Installing Windows Scheduled Task Service...
python scripts\service_manager.py install --on-boot
if errorlevel 1 (
    echo [Calibre Institutional] Admin privileges not detected, falling back to User Logon task...
    python scripts\service_manager.py install
)
echo [Calibre Institutional] Service installation completed.
exit /b 0
