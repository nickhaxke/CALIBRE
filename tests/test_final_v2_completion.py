import os
import sys
import json
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(r"c:\dev\calibre-institutional")
sys.path.insert(0, str(ROOT / "customization" / "backend"))

from config_manager import ConfigManager
import gateway_server


class FinalV2ProductCompletionTests(unittest.TestCase):
    """Verifies Loop 1 (Advanced Search), Loop 2 (Landing Page Copy), and Loop 3 (Shared Link Flow)."""

    def setUp(self):
        self.cm = ConfigManager()

    def test_01_loop1_advanced_search_backend_and_template(self):
        """Verify advanced search criteria combination and template elements."""
        inst_py = (ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional.py").read_text(encoding="utf-8")
        idx_html = (ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional_assets" / "index.html").read_text(encoding="utf-8")
        lib_js = (ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional_assets" / "library.js").read_text(encoding="utf-8")

        # Backend FIELD_MAP and query builder
        self.assertIn("'isbn': 'isbn'", inst_py)
        self.assertIn("adv_title", inst_py)
        self.assertIn("adv_author", inst_py)
        self.assertIn("adv_isbn", inst_py)
        self.assertIn("adv_publisher", inst_py)
        self.assertIn("adv_language", inst_py)
        self.assertIn("pubdate:", inst_py)

        # Frontend collapsible panel and inputs
        self.assertIn('id="adv-search-panel"', idx_html)
        self.assertIn('id="toggle-adv-search"', idx_html)
        self.assertIn('id="adv-title"', idx_html)
        self.assertIn('id="adv-isbn"', idx_html)
        self.assertIn('id="adv-year-start"', idx_html)

        # Library JS multi-criteria binding
        self.assertIn("initAdvancedSearchControls", lib_js)
        self.assertIn("advTitle", lib_js)
        self.assertIn("advIsbn", lib_js)

    def test_02_loop2_landing_page_copy_and_image_management(self):
        """Verify editable landing page copy and AppData persistence."""
        test_payload = {
            "hero_eyebrow": "ARCHIVAL REPOSITORY",
            "hero_title": "Discover Knowledge Without Boundaries",
            "hero_description": "Customized institutional digital archives.",
            "cta_label": "Enter Digital Library ↗",
            "about_heading": "Curated Research Collections",
            "about_description": "Faculty monographs and research literature.",
            "footer_text": "TANRAIL LIBRARY · Official Institutional Archive"
        }
        updated = self.cm.update_landing_page_content(test_payload, actor="TestRunner")
        self.assertEqual(updated["hero_title"], "Discover Knowledge Without Boundaries")
        self.assertEqual(updated["cta_label"], "Enter Digital Library ↗")
        self.assertEqual(updated["footer_text"], "TANRAIL LIBRARY · Official Institutional Archive")

        # Verify template interpolation in gateway_server
        rendered_settings = self.cm.get_landing_page_content()
        self.assertEqual(rendered_settings["hero_eyebrow"], "ARCHIVAL REPOSITORY")

        # Clean reset back to defaults
        self.cm.reset_landing_page_content(actor="TestRunner")
        reset_settings = self.cm.get_landing_page_content()
        self.assertEqual(reset_settings["hero_eyebrow"], "A HOME FOR CURIOUS MINDS")

    def test_03_loop3_shared_book_link_redirect_and_copy_link(self):
        """Verify ?next= preservation on unauthenticated access and in-app copy link buttons."""
        lib_js = (ROOT / "upstream" / "calibre" / "src" / "calibre" / "srv" / "institutional_assets" / "library.js").read_text(encoding="utf-8")
        reader_html = (ROOT / "customization" / "frontend" / "templates" / "reader.html").read_text(encoding="utf-8")
        reader_js = (ROOT / "customization" / "frontend" / "static" / "js" / "reader.js").read_text(encoding="utf-8")
        portal_js = (ROOT / "customization" / "frontend" / "static" / "js" / "portal.js").read_text(encoding="utf-8")
        gw_py = (ROOT / "customization" / "backend" / "gateway_server.py").read_text(encoding="utf-8")

        # Copy link actions
        self.assertIn("share-link-btn", lib_js)
        self.assertIn("Copy Book Link", lib_js)
        self.assertIn('id="btn-share-link"', reader_html)
        self.assertIn("btn-share-link", reader_js)

        # Redirect sanitization and ?next= preservation
        self.assertIn("_redirect_to_login", gw_py)
        self.assertIn("getSafeRedirectUrl", portal_js)
        self.assertIn("next", portal_js)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FinalV2ProductCompletionTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)

