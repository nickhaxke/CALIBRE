# -*- coding: utf-8 -*-
"""
Test Calibre Content Server Runner
Launches an isolated test server on 127.0.0.1:8088 with test library and userdb.
"""
import os
import subprocess
import sys
import time

CALIBRE_SERVER = r"C:\Program Files\Calibre2\calibre-server.exe"
BASE_DIR = r"C:\dev\calibre-institutional\test-environment"
LIB_DIR = os.path.join(BASE_DIR, "library")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
USERDB = os.path.join(CONFIG_DIR, "server-users.sqlite")
LOG_FILE = os.path.join(BASE_DIR, "server.log")

cmd = [
    CALIBRE_SERVER,
    "--listen-on=127.0.0.1",
    "--port=8088",
    "--url-prefix=/calibre",
    "--enable-auth",
    "--auth-mode=basic",
    f"--userdb={USERDB}",
    LIB_DIR
]

env = os.environ.copy()
env["CALIBRE_NO_SI_DANGER_DANGER"] = "1"

print(f"Starting Calibre test Content Server on 127.0.0.1:8088...")
print(f"Command: {' '.join(cmd)}")

log_f = open(LOG_FILE, "w", encoding="utf-8")
proc = subprocess.Popen(cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT)

# Save PID
pid_file = os.path.join(BASE_DIR, "calibre_server.pid")
with open(pid_file, "w") as f:
    f.write(str(proc.pid))

print(f"Calibre server process launched with PID {proc.pid}")
time.sleep(2)

# Check if process is still alive
if proc.poll() is not None:
    log_f.close()
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        print("Server exited unexpectedly. Log output:")
        print(f.read())
    sys.exit(1)
else:
    print("Server is running successfully in background!")
