"""
Calibre User Manager Module
Institutional Digital Library Gateway

Wraps the official Calibre Server CLI user-management subcommands
(calibre-server.exe --manage-users) to provide safe, robust user administration
without raw SQL mutations to server-users.sqlite.
"""

import os
import sys
import sqlite3
import subprocess
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("calibre_user_manager")


def _is_valid_calibre_exe(exe_path: Optional[str]) -> bool:
    if not exe_path or not os.path.isfile(exe_path):
        return False
    base = os.path.dirname(os.path.abspath(exe_path))
    return os.path.isfile(os.path.join(base, "app", "resources", "default_tweaks.py"))


def find_default_calibre_bin():
    localappdata = os.environ.get("LOCALAPPDATA", "")
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        os.path.join(localappdata, "Programs", "CalibreInstitutional", "calibre", "calibre-server.exe") if localappdata else None,
        os.path.join(repo_root, "test-environment", "installed-app", "calibre", "calibre-server.exe"),
        r"C:\Program Files\CalibreInstitutional\calibre\calibre-server.exe",
        r"C:\Program Files\Calibre2\calibre-server.exe",
        r"C:\Program Files (x86)\Calibre2\calibre-server.exe",
    ]
    for c in candidates:
        if _is_valid_calibre_exe(c):
            return c
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return candidates[2]


DEFAULT_CALIBRE_BIN = find_default_calibre_bin()


class CalibreUserManager:
    """
    Institutional wrapper around the official Calibre Server CLI user-management
    subcommands (calibre-server.exe --manage-users).

    Provides high-level user administration without direct SQL writes to
    server-users.sqlite, preserving Calibre internal database integrity and security.
    """

    def __init__(self, userdb_path: Optional[str] = None, calibre_bin: Optional[str] = None, config_manager=None):
        home = os.environ.get("CALIBRE_INSTITUTIONAL_HOME", "")
        cand_bins = [
            calibre_bin,
            os.environ.get("CALIBRE_SERVER_BIN"),
            os.path.join(home, "calibre", "calibre-server.exe") if home else None,
            DEFAULT_CALIBRE_BIN,
        ]
        self.calibre_bin = next(
            (b for b in cand_bins if b and os.path.isfile(b)),
            calibre_bin or os.environ.get("CALIBRE_SERVER_BIN", DEFAULT_CALIBRE_BIN)
        )

        if not userdb_path:
            config_dir = os.environ.get("CALIBRE_INSTITUTIONAL_CONFIG_DIR")
            if config_dir:
                userdb_path = os.path.join(config_dir, "server-users.sqlite")
            elif config_manager and hasattr(config_manager, "db_path"):
                userdb_path = os.path.join(os.path.dirname(config_manager.db_path), "server-users.sqlite")
            else:
                from config_manager import get_config_directory
                userdb_path = os.path.join(get_config_directory(), "server-users.sqlite")
        self.userdb_path = os.path.abspath(userdb_path)
        self.config_manager = config_manager

        if not os.path.isfile(self.calibre_bin):
            logger.warning("Calibre server binary not found at: %s", self.calibre_bin)

    def _run_manage_users(self, args: List[str], input_text: Optional[str] = None) -> subprocess.CompletedProcess:
        cmd = [self.calibre_bin, "--manage-users", f"--userdb={self.userdb_path}", "--"] + args
        try:
            stdin_arg = subprocess.DEVNULL if input_text is None else None
            silent_kwargs = {}
            if sys.platform == "win32":
                silent_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0  # SW_HIDE
                silent_kwargs["startupinfo"] = si
            res = subprocess.run(
                cmd,
                stdin=stdin_arg,
                capture_output=True,
                text=True,
                input=input_text,
                check=False,
                timeout=15,
                **silent_kwargs
            )
            return res
        except Exception as e:
            logger.error("Failed to execute calibre-server --manage-users: %s", e)
            raise

    def list_users(self) -> List[Dict[str, Any]]:
        """
        Queries users from Calibre userdb (read-only, never exposing password hashes)
        and enriches each user with institutional metadata, active status, and library scopes.
        """
        raw_users = []
        if os.path.isfile(self.userdb_path):
            try:
                conn = sqlite3.connect(f"file:{self.userdb_path}?mode=ro", uri=True, timeout=5.0)
                cur = conn.cursor()
                cur.execute("SELECT name, readonly, timestamp FROM users ORDER BY name ASC")
                for row in cur.fetchall():
                    raw_users.append({
                        "username": row[0],
                        "readonly": (str(row[1]).lower() == "y"),
                        "timestamp": row[2]
                    })
                conn.close()
            except Exception as e:
                logger.warning("Direct read-only query failed, falling back to CLI: %s", e)

        if not raw_users:
            res = self._run_manage_users(["list"])
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    u = line.strip()
                    if u:
                        raw_users.append({"username": u, "readonly": False, "timestamp": None})

        enriched = []
        for u_item in raw_users:
            username = u_item["username"]
            profile = {}
            if self.config_manager:
                try:
                    profile = self.config_manager.get_user_profile(username) or {}
                except Exception as ex:
                    logger.warning("Could not fetch institutional profile for %s: %s", username, ex)

            enriched.append({
                "username": username,
                "readonly": u_item["readonly"],
                "role": profile.get("role", "Patron"),
                "display_name": profile.get("display_name", username),
                "full_name": profile.get("display_name", username),
                "department": profile.get("department", ""),
                "is_active": bool(profile.get("is_active", True)),
                "allowed_libraries": profile.get("allowed_libraries", "*"),
                "created_at": profile.get("created_at", u_item.get("timestamp")),
                "updated_at": profile.get("updated_at", None),
            })
        return enriched

    def add_user(self, username: str, password: str, full_name: str = "", role: str = "Patron",
                 department: str = "", readonly: bool = False, is_active: bool = True,
                 allowed_libraries: str = "*", actor: str = "System") -> Dict[str, Any]:
        """
        Provisions a new user in Calibre via official CLI and stores their institutional profile.
        """
        username = username.strip()
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters long.")
        if not password or len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")

        args = ["add"]
        if readonly:
            args.append("--readonly")
        args.append(username)

        res = self._run_manage_users(args, input_text=password)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"Calibre user creation failed: {err}")

        display_name = full_name.strip() or username
        if self.config_manager:
            self.config_manager.set_user_profile(
                username=username,
                role=role,
                display_name=display_name,
                department=department,
                is_active=is_active,
                allowed_libraries=allowed_libraries,
                actor=actor
            )
            self.config_manager.log_audit(
                actor=actor,
                action="CREATE_USER",
                details={
                    "username": username,
                    "role": role,
                    "readonly": readonly,
                    "display_name": display_name,
                    "allowed_libraries": allowed_libraries
                }
            )

        return {
            "username": username,
            "full_name": display_name,
            "display_name": display_name,
            "role": role,
            "department": department,
            "readonly": readonly,
            "is_active": bool(is_active),
            "allowed_libraries": allowed_libraries
        }

    def change_password(self, username: str, new_password: str, actor: str = "System") -> bool:
        """
        Changes a user password via official Calibre CLI without exposing hash internals.
        """
        username = username.strip()
        if not new_password or len(new_password) < 6:
            raise ValueError("New password must be at least 6 characters long.")

        res = self._run_manage_users(["chpass", username], input_text=new_password)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"Failed to change password for {username}: {err}")

        if self.config_manager:
            self.config_manager.log_audit(
                actor=actor,
                action="CHANGE_USER_PASSWORD",
                details={"username": username}
            )
        return True

    def set_readonly(self, username: str, readonly: bool, actor: str = "System") -> bool:
        """
        Modifies read-only status in Calibre database via official CLI.
        """
        username = username.strip()
        action_arg = "set" if readonly else "reset"
        res = self._run_manage_users(["readonly", username, action_arg])
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"Failed to set readonly for {username}: {err}")

        if self.config_manager:
            self.config_manager.log_audit(
                actor=actor,
                action="SET_USER_READONLY",
                details={"username": username, "readonly": readonly}
            )
        return True

    def update_profile(self, username: str, full_name: str, role: str, department: str = "",
                       is_active: Optional[bool] = None, allowed_libraries: Optional[str] = None,
                       actor: str = "System") -> bool:
        """
        Updates institutional profile metadata, active status, and backend library scope.
        """
        username = username.strip()
        if not self.config_manager:
            return False

        self.config_manager.set_user_profile(
            username=username,
            role=role,
            display_name=full_name or username,
            department=department,
            is_active=is_active,
            allowed_libraries=allowed_libraries,
            actor=actor
        )
        self.config_manager.log_audit(
            actor=actor,
            action="UPDATE_USER_PROFILE",
            details={
                "username": username,
                "role": role,
                "display_name": full_name,
                "is_active": is_active,
                "allowed_libraries": allowed_libraries
            }
        )
        return True

    def remove_user(self, username: str, actor: str = "System") -> bool:
        """
        Deletes a user from Calibre via official CLI and logs the action.
        """
        username = username.strip()
        res = self._run_manage_users(["remove", username])
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            raise RuntimeError(f"Failed to remove Calibre user {username}: {err}")

        if self.config_manager:
            self.config_manager.log_audit(
                actor=actor,
                action="REMOVE_USER",
                details={"username": username}
            )
        return True
