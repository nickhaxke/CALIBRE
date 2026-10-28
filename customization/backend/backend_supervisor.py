"""
Calibre Backend Supervisor Module
Institutional Digital Library Gateway

Manages the lifecycle of the isolated loopback Calibre Content Server process
(calibre-server.exe) and synchronizes its active library command-line arguments
with the institutional configuration store.
"""

import os
import sys
import time
import socket
import logging
import subprocess
import urllib.request
import urllib.error
from typing import List, Optional

logger = logging.getLogger("backend_supervisor")

DEFAULT_CALIBRE_BIN = r"C:\Program Files\Calibre2\calibre-server.exe"

class BackendSupervisor:
    """
    Supervises the loopback Calibre Content Server backend process.
    Ensures that running library endpoints match active libraries in ConfigManager.
    """

    def __init__(self, config_manager=None, port: int = 8088, host: str = "127.0.0.1",
                 calibre_bin: Optional[str] = None, userdb_path: Optional[str] = None):
        self.config_manager = config_manager
        self.port = port
        self.host = host
        self.calibre_bin = calibre_bin or os.environ.get("CALIBRE_SERVER_BIN", DEFAULT_CALIBRE_BIN)
        
        if not userdb_path:
            config_dir = os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR")
            if config_dir:
                userdb_path = os.path.join(config_dir, "server-users.sqlite")
            elif config_manager and hasattr(config_manager, "db_path"):
                userdb_path = os.path.join(os.path.dirname(config_manager.db_path), "server-users.sqlite")
            else:
                userdb_path = r"C:\dev\calibre-institutional\test-environment\config\server-users.sqlite"
        self.userdb_path = os.path.abspath(userdb_path)
        
        self.pid_file = os.path.join(os.path.dirname(self.userdb_path), "calibre_backend.pid")
        self.current_libraries: List[str] = []
        self.process = None

    def get_configured_library_paths(self) -> List[str]:
        """Returns the list of active library filesystem paths from ConfigManager."""
        paths = []
        if self.config_manager:
            try:
                active_libs = self.config_manager.get_active_libraries()
                for lib in active_libs:
                    p = os.path.abspath(lib.get("path", ""))
                    if os.path.isdir(p) and os.path.isfile(os.path.join(p, "metadata.db")):
                        if p not in paths:
                            paths.append(p)
            except Exception as e:
                logger.warning("Error querying active libraries from config: %s", e)
                
        return paths

    def is_backend_responsive(self, timeout: float = 2.0) -> bool:
        """Verifies if Calibre Content Server is actively responding on loopback port."""
        url = f"http://{self.host}:{self.port}/calibre/ajax/books"
        try:
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except urllib.error.HTTPError as e:
            # Calibre Content Server with auth-mode=basic returns 401 Unauthorized, proving it is running
            return e.code in (401, 200, 302)
        except Exception:
            return False

    def get_running_pid(self) -> Optional[int]:
        """Retrieves the PID from the PID file if the process is currently alive."""
        if not os.path.isfile(self.pid_file):
            return None
        try:
            with open(self.pid_file, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            # Check if process is still alive on Windows
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return pid
            return None
        except Exception:
            return None

    def stop_backend(self) -> bool:
        """Stops the backend process if running."""
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
                
        if os.path.isfile(self.pid_file):
            try:
                os.remove(self.pid_file)
            except Exception:
                pass
        self.current_libraries = []
        return True

    def build_command_args(self) -> List[str]:
        """Constructs the command-line arguments for calibre-server.exe."""
        library_paths = self.get_configured_library_paths()
        return [
            self.calibre_bin,
            f"--listen-on={self.host}",
            f"--port={self.port}",
            "--url-prefix=/calibre",
            "--enable-auth",
            "--auth-mode=basic",
            "--disable-use-bonjour",
            f"--userdb={self.userdb_path}"
        ] + library_paths

    def start_backend(self, wait_ready: bool = True) -> bool:
        """
        Launches the Calibre Content Server backend with current active library paths.
        """
        library_paths = self.get_configured_library_paths()
        if self.process is not None and self.process.poll() is None:
            return self.is_backend_responsive()
        if self.is_backend_responsive():
            logger.error('Backend port occupied; refusing to adopt an unrelated server.')
            return False
        if not library_paths:
            logger.error("No valid Calibre libraries found to start Content Server.")
            return False
            
        if not os.path.isfile(self.calibre_bin):
            logger.error("Calibre server binary not found at: %s", self.calibre_bin)
            return False

        # Build command line
        cmd = self.build_command_args()

        env = os.environ.copy()
        env["CALIBRE_NO_SI_DANGER_DANGER"] = "1"

        logger.info("Starting Calibre backend on %s:%d with %d libraries...", self.host, self.port, len(library_paths))
        try:
            log_dir = os.path.dirname(self.userdb_path)
            log_path = os.path.join(log_dir, "calibre_backend.log")
            log_file = open(log_path, "a", encoding="utf-8")
            
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            self.process = proc
            log_file.close()
            
            with open(self.pid_file, "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
                
            self.current_libraries = list(library_paths)
            logger.info("Calibre backend started with PID %d", proc.pid)
            
            if wait_ready:
                for _ in range(120):
                    time.sleep(0.5)
                    if proc.poll() is not None:
                        logger.error('Backend exited with status %s. See %s', proc.returncode, log_path)
                        return False
                    if self.is_backend_responsive(timeout=1.0):
                        logger.info("Calibre backend is responsive and operational.")
                        return True
                logger.warning("Calibre backend did not respond within 60 seconds.")
                self.stop_backend()
                return False
            return True
        except Exception as e:
            logger.error("Failed to start Calibre backend: %s", e)
            return False

    def restart_backend(self) -> bool:
        """Restarts the Calibre Content Server with updated library paths."""
        self.stop_backend()
        return self.start_backend(wait_ready=True)

    def sync_libraries(self) -> bool:
        """
        Checks if the currently served libraries match active configuration.
        Restarts backend if synchronization is needed.
        """
        desired_paths = self.get_configured_library_paths()
        if sorted(desired_paths) != sorted(self.current_libraries):
            logger.info("Active libraries changed. Resynchronizing backend...")
            return self.restart_backend()
        return True
