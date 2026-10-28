"""
Calibre Institutional Gateway - Windows Service & Task Manager
Provides automated installation, startup, shutdown, and health checking
for the Institutional Gateway background service on Windows.
"""

import os
import sys
import time
import socket
import logging
import argparse
import subprocess
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("service_manager")

TASK_NAME = "CalibreInstitutionalGateway"

def get_executable_path() -> str:
    """Finds the best path to launch the gateway."""
    # Check for compiled frozen binary
    candidates = [
        r"C:\Program Files\CalibreInstitutional\bin\CalibreInstitutionalGateway.exe",
        r"C:\dev\calibre-institutional\build\dist\CalibreInstitutionalGateway\CalibreInstitutionalGateway.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
            
    # Fallback to python runner
    py_exe = sys.executable
    # Prefer pythonw if available for windowless execution
    pyw_exe = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
    runner = pyw_exe if os.path.isfile(pyw_exe) else py_exe
    gw_script = r"C:\dev\calibre-institutional\customization\backend\gateway_server.py"
    return f'"{runner}" "{gw_script}"'

def is_admin() -> bool:
    """Checks if the current process has Windows Administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def install_task(on_boot: bool = False) -> bool:
    """Registers the scheduled task in Windows Task Scheduler."""
    cmd_target = get_executable_path()
    logger.info("Configuring Windows Scheduled Task: %s", TASK_NAME)
    logger.info("Target: %s", cmd_target)
    
    # If admin and on_boot requested, run as SYSTEM at startup. Otherwise run ONLOGON.
    if is_admin() and on_boot:
        args = [
            "schtasks.exe", "/create", "/tn", TASK_NAME,
            "/tr", cmd_target,
            "/sc", "ONSTART",
            "/ru", "SYSTEM",
            "/rl", "HIGHEST",
            "/f"
        ]
    else:
        args = [
            "schtasks.exe", "/create", "/tn", TASK_NAME,
            "/tr", cmd_target,
            "/sc", "ONLOGON",
            "/rl", "HIGHEST",
            "/f"
        ]
        
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode == 0:
        logger.info("Successfully registered scheduled task '%s'.", TASK_NAME)
        return True
    else:
        logger.error("Failed to register scheduled task: %s", res.stderr.strip() or res.stdout.strip())
        return False

def uninstall_task() -> bool:
    """Removes the scheduled task and stops the service."""
    stop_service()
    args = ["schtasks.exe", "/delete", "/tn", TASK_NAME, "/f"]
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode == 0:
        logger.info("Successfully deleted scheduled task '%s'.", TASK_NAME)
        return True
    else:
        logger.warning("Scheduled task '%s' was not found or already removed.", TASK_NAME)
        return False

def start_service() -> bool:
    """Starts the service task or launches the background process."""
    logger.info("Starting %s...", TASK_NAME)
    # First try via schtasks
    res = subprocess.run(["schtasks.exe", "/run", "/tn", TASK_NAME], capture_output=True, text=True)
    if res.returncode == 0:
        logger.info("Task trigger initiated via Task Scheduler.")
    else:
        # Launch directly in background
        target = get_executable_path()
        logger.info("Launching directly: %s", target)
        subprocess.Popen(target, shell=True, creationflags=0x08000000) # CREATE_NO_WINDOW
        
    # Wait and check status
    for _ in range(10):
        time.sleep(1)
        if check_port(8085):
            logger.info("Gateway service is actively listening on port 8085.")
            return True
    logger.warning("Gateway port 8085 not detected yet. Check logs if needed.")
    return False

def stop_service() -> bool:
    """Terminates running gateway and backend processes."""
    logger.info("Stopping %s and Calibre backend...", TASK_NAME)
    # Stop scheduled task if running
    subprocess.run(["schtasks.exe", "/end", "/tn", TASK_NAME], capture_output=True)
    
    # Kill CalibreInstitutionalGateway.exe if present
    subprocess.run(["taskkill", "/F", "/IM", "CalibreInstitutionalGateway.exe"], capture_output=True)
    
    # Check pid files in test config
    config_dir = os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR", r"C:\dev\calibre-institutional\test-environment\config")
    backend_pid = os.path.join(config_dir, "calibre_backend.pid")
    if os.path.isfile(backend_pid):
        try:
            with open(backend_pid, "r") as f:
                pid = int(f.read().strip())
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            os.remove(backend_pid)
        except Exception:
            pass
            
    logger.info("Service stop signal executed.")
    return True

def check_port(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a TCP port is open."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def get_status() -> dict:
    """Returns the operational status of the institutional gateway and backend."""
    port_8085 = check_port(8085)
    port_8088 = check_port(8088)
    
    http_8085_ok = False
    if port_8085:
        try:
            req = urllib.request.Request("http://127.0.0.1:8085/api/auth/status")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                http_8085_ok = (resp.status == 200)
        except Exception:
            http_8085_ok = False
            
    return {
        "task_name": TASK_NAME,
        "port_8085_listening": port_8085,
        "port_8088_listening": port_8088,
        "gateway_responsive": http_8085_ok,
        "status": "RUNNING" if (port_8085 and http_8085_ok) else "STOPPED"
    }

def main():
    parser = argparse.ArgumentParser(description="Calibre Institutional Service Manager")
    parser.add_argument("action", choices=["install", "uninstall", "start", "stop", "restart", "status"],
                        help="Action to perform")
    parser.add_argument("--on-boot", action="store_true", help="Register on boot (requires Admin)")
    args = parser.parse_args()
    
    if args.action == "install":
        install_task(on_boot=args.on_boot)
    elif args.action == "uninstall":
        uninstall_task()
    elif args.action == "start":
        start_service()
    elif args.action == "stop":
        stop_service()
    elif args.action == "restart":
        stop_service()
        time.sleep(2)
        start_service()
    elif args.action == "status":
        st = get_status()
        print(f"Service: {st['task_name']}")
        print(f"Status:  {st['status']}")
        print(f"Gateway (Port 8085): {'ONLINE' if st['port_8085_listening'] else 'OFFLINE'}")
        print(f"Calibre Backend (Port 8088): {'ONLINE' if st['port_8088_listening'] else 'OFFLINE'}")

if __name__ == "__main__":
    main()
