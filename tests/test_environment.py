# -*- coding: utf-8 -*-
"""
Automated Environment Sanity Tests
Validates workspace structure, upstream git checkout, and network baseline.
"""
import os
import unittest
import urllib.request
import urllib.error

class TestCalibreEnvironment(unittest.TestCase):
    def setUp(self):
        self.base_dir = r"C:\dev\calibre-institutional"
        self.upstream_dir = os.path.join(self.base_dir, "upstream", "calibre")
        self.calibre_bin = r"C:\Program Files\Calibre2"

    def test_01_calibre_binaries_exist(self):
        self.assertTrue(os.path.exists(os.path.join(self.calibre_bin, "calibre.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.calibre_bin, "calibre-server.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.calibre_bin, "calibredb.exe")))

    def test_02_workspace_structure(self):
        for sub in ["upstream", "customization", "docs", "scripts", "tests"]:
            self.assertTrue(os.path.exists(os.path.join(self.base_dir, sub)))

    def test_03_upstream_source_checkout(self):
        constants_file = os.path.join(self.upstream_dir, "src", "calibre", "constants.py")
        self.assertTrue(os.path.exists(constants_file))
        with open(constants_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("numeric_version = (9, 17, 0)", content)

    def test_04_documentation_deliverables(self):
        for doc in [
            "environment-audit.md",
            "source-code-map.md",
            "architecture-analysis.md",
            "security-assessment.md",
            "implementation-roadmap.md",
        ]:
            doc_path = os.path.join(self.base_dir, "docs", doc)
            self.assertTrue(os.path.exists(doc_path), f"Missing doc: {doc}")
            self.assertGreater(os.path.getsize(doc_path), 500)

    def test_05_content_server_challenge(self):
        tested = False
        for port in [8088, 8080]:
            url = f"http://127.0.0.1:{port}/interface-data/init"
            try:
                req = urllib.request.Request(url)
                urllib.request.urlopen(req, timeout=3)
                self.fail("Expected 401 Unauthorized from Content Server")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 401)
                auth_header = e.headers.get("WWW-Authenticate", "")
                self.assertTrue("Digest" in auth_header or "Basic" in auth_header)
                tested = True
                break
            except urllib.error.URLError:
                continue
        self.assertTrue(tested, "At least one Calibre Content Server backend (port 8088 or 8080) must be running and challenge with 401")

if __name__ == "__main__":
    unittest.main()
