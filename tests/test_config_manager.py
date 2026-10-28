"""
Unit Test Suite for Institutional Configuration Manager
Aethelgard Institute of Technology - Calibre Institutional Digital Library
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Add customization/backend to sys.path
import sys
sys.path.insert(0, "C:/dev/calibre-institutional/customization/backend")
from config_manager import ConfigManager

class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_config.sqlite")
        self.mgr = ConfigManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_schema_initialization_and_migration(self):
        """Verifies schema tables, migrations table, and default seeds."""
        with self.mgr.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            expected = {"schema_migrations", "institution_settings", "libraries", "system_config", "institutional_user_profiles", "audit_records"}
            self.assertTrue(expected.issubset(tables), f"Tables missing: {expected - tables}")

            # Verify migration record
            cur.execute("SELECT version FROM schema_migrations")
            versions = [r[0] for r in cur.fetchall()]
            self.assertIn(1, versions)

    def test_02_institution_settings_crud(self):
        """Verifies reading and updating institutional identity settings."""
        inst = self.mgr.get_institution_settings()
        self.assertEqual(inst["short_name"], "AIT")
        self.assertIn("Aethelgard", inst["institution_name"])

        # Update settings
        self.mgr.update_institution_settings(
            name="New Academic University",
            short_name="NAU",
            library_title="Central Digital Repository",
            motto="Veritas et Lux",
            contact_email="admin@nau.edu",
            actor="admin1"
        )
        updated = self.mgr.get_institution_settings()
        self.assertEqual(updated["institution_name"], "New Academic University")
        self.assertEqual(updated["short_name"], "NAU")
        self.assertEqual(updated["motto"], "Veritas et Lux")

        # Verify audit log recorded the change
        logs = self.mgr.get_audit_log(5)
        self.assertTrue(any(l["action"] == "INSTITUTION_SETTINGS_UPDATED" and l["actor"] == "admin1" for l in logs))

    def test_03_library_configuration(self):
        """Verifies library registration, default toggling, and non-destructive removal."""
        fake_lib = os.path.join(self.temp_dir, "fake_lib")
        os.makedirs(fake_lib, exist_ok=True)

        lib = self.mgr.add_library("Engineering Library", fake_lib, is_active=True, is_default=True, access_policy="campus_only", actor="librarian1")
        self.assertIsNotNone(lib)
        self.assertEqual(lib["display_name"], "Engineering Library")
        self.assertEqual(lib["is_default"], 1)

        # Add another library as default
        fake_lib2 = os.path.join(self.temp_dir, "fake_lib2")
        os.makedirs(fake_lib2, exist_ok=True)
        lib2 = self.mgr.add_library("Medical Library", fake_lib2, is_active=True, is_default=True, access_policy="restricted")
        self.assertEqual(lib2["is_default"], 1)

        # Previous default should be cleared
        lib1_updated = self.mgr.get_library(lib["library_id"])
        self.assertEqual(lib1_updated["is_default"], 0)

        # Soft removal
        self.assertTrue(self.mgr.remove_library(lib2["library_id"]))
        self.assertIsNone(self.mgr.get_library(lib2["library_id"]))
        # Physical files must NOT be deleted
        self.assertTrue(os.path.exists(fake_lib2), "Library removal must not delete filesystem directories")

    def test_04_system_config_and_setup_flag(self):
        """Verifies system configuration key-value storage and setup completion toggling."""
        self.assertTrue(self.mgr.is_setup_completed())
        self.mgr.mark_setup_completed(False, actor="installer")
        self.assertFalse(self.mgr.is_setup_completed())
        self.mgr.mark_setup_completed(True, actor="installer")
        self.assertTrue(self.mgr.is_setup_completed())

    def test_05_institutional_user_profiles(self):
        """Verifies mapping between Calibre usernames and institutional profiles."""
        prof = self.mgr.get_user_profile("student1")
        self.assertEqual(prof["role"], "Student")

        # Set new profile
        self.mgr.set_user_profile("prof_smith", "Faculty", "Prof. John Smith (Physics)", "Physics & Astronomy", actor="admin1")
        smith = self.mgr.get_user_profile("prof_smith")
        self.assertEqual(smith["role"], "Faculty")
        self.assertEqual(smith["display_name"], "Prof. John Smith (Physics)")

        # Delete profile
        self.mgr.delete_user_profile("prof_smith", actor="admin1")
        fallback = self.mgr.get_user_profile("prof_smith")
        self.assertEqual(fallback["role"], "Student")  # default fallback

    def test_06_database_backup(self):
        """Verifies backup snapshot creation."""
        backup_path = self.mgr.backup_database()
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))
        self.assertGreater(os.path.getsize(backup_path), 0)

if __name__ == "__main__":
    unittest.main()
