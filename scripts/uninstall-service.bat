@echo off
setlocal
cd /d "%~dp0.."
echo [Calibre Institutional] Uninstalling Windows Scheduled Task Service...
python scripts\service_manager.py uninstall
echo [Calibre Institutional] Service removed. User libraries and configuration remain untouched.
exit /b 0
