"""
Phase 5 Release Blockers and Security Hardening Tests
Verifies:
1. No credential exposure in process argument list (passwords fed via stdin only).
2. Remote LAN restriction for first-time setup (local loopback only).
3. Backend supervisor multi-library synchronization argument construction.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "C:/dev/calibre-institutional/customization/backend")
from config_manager import ConfigManager
from calibre_user_manager import CalibreUserManager
from backend_supervisor import BackendSupervisor
import gateway_server

class TestPhase5ReleaseBlockers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="phase5_test_")
        cls.temp_cfg_db = os.path.join(cls.test_dir, "institutional_config.sqlite")
        cls.temp_userdb = os.path.join(cls.test_dir, "server-users.sqlite")
        
        src_userdb = "C:/dev/calibre-institutional/test-environment/config/server-users.sqlite"
        if os.path.isfile(src_userdb):
            shutil.copy2(src_userdb, cls.temp_userdb)
            
        cls.config_mgr = ConfigManager(db_path=cls.temp_cfg_db)
        cls.user_mgr = CalibreUserManager(userdb_path=cls.temp_userdb, config_manager=cls.config_mgr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    @patch("subprocess.run")
    def test_01_add_user_never_exposes_password_in_process_args(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        secret_pwd = "SuperSecretPassword999!"
        
        self.user_mgr.add_user(
            username="sec_test_user",
            password=secret_pwd,
            full_name="Security Test",
            role="Student"
        )
        
        self.assertTrue(mock_run.called)
        call_args, call_kwargs = mock_run.call_args
        cmd_args = call_args[0]
        
        # The password MUST NOT appear in the cmd args list
        for arg in cmd_args:
            self.assertNotIn(secret_pwd, str(arg), "CRITICAL: Password exposed in command-line arguments!")
            
        # The password MUST be delivered via input (stdin)
        self.assertEqual(call_kwargs.get("input"), secret_pwd, "Password was not passed cleanly via stdin!")

    @patch("subprocess.run")
    def test_02_change_password_never_exposes_password_in_process_args(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        secret_new_pwd = "NewSuperSecretPassword123!"
        
        self.user_mgr.change_password(
            username="student1",
            new_password=secret_new_pwd
        )
        
        self.assertTrue(mock_run.called)
        call_args, call_kwargs = mock_run.call_args
        cmd_args = call_args[0]
        
        for arg in cmd_args:
            self.assertNotIn(secret_new_pwd, str(arg), "CRITICAL: New password exposed in command-line arguments!")
            
        self.assertEqual(call_kwargs.get("input"), secret_new_pwd, "New password was not passed cleanly via stdin!")

    def test_03_is_local_request_ip_filtering(self):
        handler = MagicMock()
        
        # Local loopback addresses must be allowed
        for local_ip in ["127.0.0.1", "::1", "localhost", "127.0.0.2", "::ffff:127.0.0.1"]:
            handler.client_address = (local_ip, 54321)
            self.assertTrue(
                gateway_server.InstitutionalGatewayHandler.is_local_request(handler),
                f"Expected {local_ip} to be recognized as local"
            )
        
        # Remote LAN addresses must be rejected
        for remote_ip in ["192.168.1.100", "10.0.0.5", "172.16.0.2", "8.8.8.8"]:
            handler.client_address = (remote_ip, 54321)
            self.assertFalse(
                gateway_server.InstitutionalGatewayHandler.is_local_request(handler),
                f"Expected {remote_ip} to be rejected as non-local"
            )

    def test_04_backend_supervisor_command_construction(self):
        sup = BackendSupervisor(
            calibre_bin="C:/Program Files/Calibre2/calibre-server.exe",
            port=8088,
            host="127.0.0.1",
            userdb_path=self.temp_userdb,
            config_manager=self.config_mgr
        )
        
        # Create test library directories with metadata.db
        lib1 = os.path.join(self.test_dir, "Engineering")
        os.makedirs(lib1, exist_ok=True)
        with open(os.path.join(lib1, "metadata.db"), "w") as f:
            f.write("")

        lib2 = os.path.join(self.test_dir, "Medical")
        os.makedirs(lib2, exist_ok=True)
        with open(os.path.join(lib2, "metadata.db"), "w") as f:
            f.write("")

        lib_inactive = os.path.join(self.test_dir, "Inactive")
        os.makedirs(lib_inactive, exist_ok=True)
        with open(os.path.join(lib_inactive, "metadata.db"), "w") as f:
            f.write("")
        
        self.config_mgr.add_library("Engineering", lib1, is_active=True)
        self.config_mgr.add_library("Medical", lib2, is_active=True)
        self.config_mgr.add_library("InactiveArchive", lib_inactive, is_active=False)
        
        args = sup.build_command_args()
        
        self.assertIn("--port=8088", args)
        self.assertIn("--listen-on=127.0.0.1", args)
        self.assertIn(f"--userdb={self.temp_userdb}", args)
        
        self.assertIn(os.path.abspath(lib1), args)
        self.assertIn(os.path.abspath(lib2), args)
        self.assertNotIn(os.path.abspath(lib_inactive), args)

if __name__ == "__main__":
    unittest.main()
