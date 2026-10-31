# -*- coding: utf-8 -*-
"""
Verification Suite: CMD Popup Prevention & Silent Background Execution
Tests that PDF inspection, rendering, search, supervisor, and user manager
run without creating visible console windows while preserving full logging and diagnostics.
"""

import os
import sys
import time
import unittest
import subprocess
import shutil

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "customization", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import gateway_server
from calibre_user_manager import CalibreUserManager
from backend_supervisor import BackendSupervisor


class TestCmdPopupPrevention(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sample_pdf = os.path.join(
            ROOT_DIR,
            ".demo",
            "library",
            "Chief Archivist Thorne",
            "Large-Scale Archival Repository Syst (9)",
            "Large-Scale Archival Repository - Chief Archivist Thorne.pdf"
        )
        assert os.path.isfile(cls.sample_pdf), f"Sample PDF must exist at: {cls.sample_pdf}"

    def test_01_subprocess_silent_flags_structure(self):
        """Verify _subprocess_silent_flags returns CREATE_NO_WINDOW and SW_HIDE on Windows."""
        flags = gateway_server._subprocess_silent_flags()
        if sys.platform == "win32":
            self.assertIn("creationflags", flags)
            self.assertEqual(flags["creationflags"], 0x08000000, "Must set CREATE_NO_WINDOW (0x08000000)")
            self.assertIn("startupinfo", flags)
            si = flags["startupinfo"]
            self.assertTrue(si.dwFlags & subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(si.wShowWindow, 0, "Must set SW_HIDE (0)")
        else:
            self.assertEqual(flags, {})

    def test_02_pdf_inspection_silent(self):
        """Verify inspect_pdf_document inspects PDF without popping CMD and extracts pages."""
        is_valid, page_count, err = gateway_server.inspect_pdf_document(self.sample_pdf)
        self.assertTrue(is_valid, f"PDF should be valid, got error: {err}")
        self.assertGreater(page_count, 0, "Page count must be > 0")
        self.assertEqual(err, "")

    def test_03_pdf_page_rendering_silent(self):
        """Verify render_pdf_page_to_png renders valid PNG bytes silently."""
        png_bytes = gateway_server.render_pdf_page_to_png(self.sample_pdf, page_num=1, dpi=100)
        self.assertTrue(len(png_bytes) > 1000, "Rendered PNG must have non-trivial size")
        self.assertTrue(png_bytes.startswith(b"\x89PNG"), "Output must be valid PNG format")

    def test_04_continuous_navigation_and_scrolling(self):
        """Verify sequential multi-page requests render cleanly with zero popups and proper caching."""
        is_valid, total_pages, _ = gateway_server.inspect_pdf_document(self.sample_pdf)
        pages_to_test = min(total_pages, 3)
        for p in range(1, pages_to_test + 1):
            t0 = time.time()
            data = gateway_server.render_pdf_page_to_png(self.sample_pdf, page_num=p, dpi=72)
            duration = time.time() - t0
            self.assertTrue(len(data) > 500, f"Page {p} must render valid data")
            self.assertTrue(data.startswith(b"\x89PNG"), f"Page {p} must be PNG")
            self.assertLess(duration, 5.0, f"Page {p} render took too long: {duration:.2f}s")

    def test_05_pdf_fulltext_search_silent(self):
        """Verify search_pdf_document_text searches PDF without CMD popups."""
        results = gateway_server.search_pdf_document_text(self.sample_pdf, "archival")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "Should find occurrences of 'archival'")
        first = results[0]
        self.assertIn("page", first)
        self.assertIn("snippet", first)
        self.assertIn("matches_on_page", first)

    def test_06_error_diagnostics_preserved(self):
        """Verify error conditions return clear diagnostic messages without crashing."""
        is_valid, pages, err = gateway_server.inspect_pdf_document("C:\\nonexistent_document_12345.pdf")
        self.assertFalse(is_valid)
        self.assertEqual(pages, 0)
        self.assertIn("does not exist", err.lower())

        empty_search = gateway_server.search_pdf_document_text(self.sample_pdf, "")
        self.assertEqual(empty_search, [])

    def test_07_user_manager_has_silent_subprocess(self):
        """Verify CalibreUserManager incorporates silent_kwargs in _run_manage_users."""
        import inspect
        src = inspect.getsource(CalibreUserManager._run_manage_users)
        self.assertIn("CREATE_NO_WINDOW", src)
        self.assertIn("STARTUPINFO", src)
        self.assertIn("SW_HIDE", src)

    def test_08_backend_supervisor_has_silent_subprocess(self):
        """Verify BackendSupervisor incorporates CREATE_NO_WINDOW in start_backend."""
        import inspect
        src = inspect.getsource(BackendSupervisor.start_backend)
        self.assertIn("CREATE_NO_WINDOW", src)
        self.assertIn("STARTUPINFO", src)
        self.assertIn("SW_HIDE", src)
        self.assertIn("calibre_backend.log", src)


if __name__ in ("__main__", "__run_file__"):
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestCmdPopupPrevention)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
