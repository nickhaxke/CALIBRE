"""
Tests for Calibre User Manager Module
Institutional Digital Library Gateway

Verifies that the CalibreUserManager successfully manages users via the official
Calibre CLI without raw SQL database writes.
"""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, "C:/dev/calibre-institutional/customization/backend")
from config_manager import ConfigManager
from calibre_user_manager import CalibreUserManager

class TestCalibreUserManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="calibre_usr_test_")
        cls.temp_userdb = os.path.join(cls.test_dir, "server-users.sqlite")
        cls.temp_cfg_db = os.path.join(cls.test_dir, "institutional_config.sqlite")
        
        # Copy test userdb
        src_userdb = "C:/dev/calibre-institutional/test-environment/config/server-users.sqlite"
        if os.path.isfile(src_userdb):
            shutil.copy2(src_userdb, cls.temp_userdb)
            
        cls.config_mgr = ConfigManager(db_path=cls.temp_cfg_db)
        cls.user_mgr = CalibreUserManager(userdb_path=cls.temp_userdb, config_manager=cls.config_mgr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_list_users_enriched(self):
        users = self.user_mgr.list_users()
        self.assertIsInstance(users, list)
        usernames = [u["username"] for u in users]
        self.assertIn("student1", usernames)
        self.assertIn("librarian1", usernames)

    def test_02_add_and_query_user(self):
        res = self.user_mgr.add_user(
            username="test_user42",
            password="StrongPassword123!",
            full_name="Test User FortyTwo",
            role="Staff",
            department="Archives",
            readonly=True,
            actor="AdminTest"
        )
        self.assertEqual(res["username"], "test_user42")
        self.assertTrue(res["readonly"])
        
        # Check that user is in list
        users = self.user_mgr.list_users()
        user_dict = next((u for u in users if u["username"] == "test_user42"), None)
        self.assertIsNotNone(user_dict)
        self.assertEqual(user_dict["display_name"], "Test User FortyTwo")
        self.assertEqual(user_dict["role"], "Staff")
        self.assertTrue(user_dict["readonly"])

    def test_03_change_password(self):
        success = self.user_mgr.change_password("test_user42", "EvenStronger456!", actor="AdminTest")
        self.assertTrue(success)

    def test_04_toggle_readonly(self):
        # Reset readonly (make read-write)
        self.user_mgr.set_readonly("test_user42", False, actor="AdminTest")
        users = self.user_mgr.list_users()
        user_dict = next((u for u in users if u["username"] == "test_user42"), None)
        self.assertFalse(user_dict["readonly"])
        
        # Set readonly again
        self.user_mgr.set_readonly("test_user42", True, actor="AdminTest")
        users = self.user_mgr.list_users()
        user_dict = next((u for u in users if u["username"] == "test_user42"), None)
        self.assertTrue(user_dict["readonly"])

    def test_05_remove_user(self):
        success = self.user_mgr.remove_user("test_user42", actor="AdminTest")
        self.assertTrue(success)
        
        users = self.user_mgr.list_users()
        usernames = [u["username"] for u in users]
        self.assertNotIn("test_user42", usernames)

if __name__ == "__main__":
    unittest.main()
