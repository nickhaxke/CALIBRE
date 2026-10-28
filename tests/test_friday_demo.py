"""Isolated regression tests; no existing accounts, libraries or settings used."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix='institutional-regression-')
os.environ['CALIBRE_INSTITUTIONAL_CONFIG_DIR'] = TEST_DIRECTORY.name
os.environ['CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG'] = str(ROOT / 'customization/configuration/gateway_config.json')
sys.path.insert(0, str(ROOT / 'customization/backend'))
import gateway_server as gateway
from config_manager import ConfigManager
from backend_supervisor import BackendSupervisor


class FridayDemoTests(unittest.TestCase):
    def handler(self, ip='127.0.0.1', headers=None):
        handler = object.__new__(gateway.InstitutionalGatewayHandler)
        handler.client_address = (ip, 12345)
        handler.headers = headers or {}
        handler.send_json = lambda code, body, **kwargs: setattr(handler, 'response', (code, body))
        return handler

    def test_new_configuration_has_no_development_libraries_or_privileged_fixtures(self):
        manager = ConfigManager()
        self.assertEqual(manager.get_libraries(), [])
        self.assertEqual(manager.get_all_user_profiles(), {})
        self.assertFalse(manager.is_setup_completed())

    def test_settings_aliases_match_admin_contract(self):
        settings = ConfigManager().get_institution_settings()
        self.assertEqual(settings['name'], settings['institution_name'])
        self.assertEqual(settings['library_name'], settings['library_title'])
        self.assertEqual(settings['logo_url'], settings['logo_path'])

    def test_empty_supervisor_does_not_serve_development_data(self):
        supervisor = BackendSupervisor(config_manager=types.SimpleNamespace(get_active_libraries=lambda: []))
        self.assertEqual(supervisor.get_configured_library_paths(), [])

    def test_untrusted_forwarding_headers_cannot_spoof_client_identity(self):
        handler = self.handler('192.0.2.10', {'X-Forwarded-For': '127.0.0.1'})
        self.assertEqual(handler.get_client_ip(), '192.0.2.10')
        self.assertFalse(handler.is_local_request())

    def test_csrf_uses_exact_origin_and_requires_browser_context(self):
        handler = self.handler(headers={'Host': '127.0.0.1:8085', 'Referer': 'http://127.0.0.1:8085.invalid/'})
        self.assertFalse(handler.is_valid_csrf_origin())
        handler.headers = {'Origin': 'http://127.0.0.1:8085'}
        self.assertTrue(handler.is_valid_csrf_origin())
        handler.headers = {}
        self.assertFalse(handler.is_valid_csrf_origin())

    def test_loopback_does_not_trust_proxy_for_bootstrap(self):
        handler = self.handler('127.0.0.1')
        self.assertTrue(handler.is_local_request())
        with patch.dict(gateway.CONFIG, {'trusted_proxies': ['127.0.0.1']}):
            self.assertFalse(handler.is_local_request())

    def test_account_changes_revoke_every_session_for_that_user(self):
        with patch.dict(gateway.SESSIONS, {'one': {'username': 'a'}, 'two': {'username': 'a'}, 'three': {'username': 'b'}}, clear=True):
            gateway.revoke_user_sessions('a')
            self.assertEqual(set(gateway.SESSIONS), {'three'})

    def test_profile_route_updates_profile_and_revokes_old_role(self):
        handler = self.handler(headers={'Content-Length': '44'})
        body = json.dumps({'username': 'a', 'role': 'Patron'}).encode()
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        with patch.object(gateway.USER_MANAGER, 'update_profile') as update, patch.dict(gateway.SESSIONS, {'old': {'username': 'a'}}, clear=True):
            handler.handle_admin_posts('/api/admin/users/profile', {'username': 'admin'})
            self.assertEqual(handler.response[0], 200)
            update.assert_called_once()
            self.assertEqual(gateway.SESSIONS, {})


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        TEST_DIRECTORY.cleanup()
