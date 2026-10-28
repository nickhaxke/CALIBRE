@echo off
setlocal
cd /d "%~dp0.."
echo [Calibre Institutional] Stopping Service...
python scripts\service_manager.py stop
exit /b 0
