@echo off
setlocal
cd /d "%~dp0.."
echo [Calibre Institutional] Starting Service...
python scripts\service_manager.py start
exit /b 0
