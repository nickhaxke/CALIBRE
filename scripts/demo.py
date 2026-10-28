"""Prepare and launch the isolated source-based Friday demonstration.

Run with the installed calibre-debug.exe, or a standard Python interpreter.
Credentials, databases, books and logs are kept under ignored .demo/.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / '.demo'
CALIBRE = Path(os.environ.get('CALIBRE_BIN_DIR', r'C:\Program Files\Calibre2'))


def environment():
    env = os.environ.copy()
    env.update({
        'CALIBRE_DEVELOP_FROM': str(ROOT / 'upstream/calibre/src'),
        'CALIBRE_CONFIG_DIRECTORY': str(DEMO / 'desktop-config'),
        'CALIBRE_CACHE_DIRECTORY': str(DEMO / 'cache'),
        'CALIBRE_INSTITUTIONAL_HOME': str(ROOT),
        'CALIBRE_INSTITUTIONAL_INSTANCE': 'institutional-demo',
        'CALIBRE_INSTITUTIONAL_CONFIG_DIR': str(DEMO / 'config'),
        'CALIBRE_INSTITUTIONAL_GATEWAY_CONFIG': str(DEMO / 'gateway.json'),
        'CALIBRE_INSTITUTIONAL_BRANDING': str(ROOT / 'customization/configuration/demo-branding.json'),
        'CALIBRE_SERVER_BIN': str(CALIBRE / 'calibre-server.exe'),
        'CALIBRE_NO_SI_DANGER_DANGER': '1',
    })
    return env


def prepare():
    DEMO.mkdir(exist_ok=True)
    env = environment()
    for key in ('CALIBRE_CONFIG_DIRECTORY', 'CALIBRE_CACHE_DIRECTORY', 'CALIBRE_INSTITUTIONAL_CONFIG_DIR'):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    for source, destination in [('library', 'library'), ('libraries/research_archive', 'research_archive')]:
        target = DEMO / destination
        if not target.exists():
            shutil.copytree(ROOT / 'test-environment' / source, target)
    configuration = {
        'gateway_host': '127.0.0.1', 'gateway_port': 8085,
        'calibre_backend_url': 'http://127.0.0.1:8088/calibre',
        'session_cookie_name': 'inst_session_id', 'session_timeout_seconds': 3600,
        'trusted_proxies': [], 'allowed_origins': ['http://127.0.0.1:8085', 'http://localhost:8085'],
    }
    (DEMO / 'gateway.json').write_text(json.dumps(configuration, indent=2), encoding='utf-8')
    os.environ.update(env)
    sys.path.insert(0, str(ROOT / 'customization/backend'))
    from config_manager import ConfigManager
    from calibre_user_manager import CalibreUserManager
    manager = ConfigManager()
    credentials_path = DEMO / 'credentials.json'
    if not credentials_path.exists():
        credentials = {'reader': {'username': 'demo_reader', 'password': secrets.token_urlsafe(18)}, 'admin': {'username': 'demo_admin', 'password': secrets.token_urlsafe(18)}}
        credentials_path.write_text(json.dumps(credentials, indent=2), encoding='utf-8')
    credentials = json.loads(credentials_path.read_text(encoding='utf-8'))
    users = CalibreUserManager(config_manager=manager)
    existing = {u['username'] for u in users.list_users()}
    for role, account in credentials.items():
        if account['username'] not in existing:
            users.add_user(account['username'], account['password'], full_name='Demo Reader' if role == 'reader' else 'Demo Administrator', role='Patron' if role == 'reader' else 'Administrator', readonly=role == 'reader', actor='DemoPreparation')
    if not manager.is_setup_completed():
        for lib in manager.get_libraries():
            manager.remove_library(lib['library_id'], actor='DemoPreparation')
        brand = json.loads(Path(env['CALIBRE_INSTITUTIONAL_BRANDING']).read_text(encoding='utf-8'))
        manager.update_institution_settings(name=brand['institution_name'], short_name=brand['short_name'], library_title=brand['library_title'], motto=brand['motto'], logo_path=brand['logo_url'], actor='DemoPreparation')
        manager.add_library('General collection', str(DEMO / 'library'), is_default=True, actor='DemoPreparation')
        manager.add_library('Research archive', str(DEMO / 'research_archive'), actor='DemoPreparation')
        manager.set_setup_completed(True, actor='DemoPreparation')
    probe = subprocess.run([str(CALIBRE / 'calibre-debug.exe'), '-c', 'import calibre,calibre.srv.institutional,calibre.gui2.ui; print(calibre.__file__); print(calibre.srv.institutional.__file__); print(calibre.gui2.ui.__file__)'], env=env, capture_output=True, text=True, check=True)
    (DEMO / 'source-proof.txt').write_text(probe.stdout, encoding='utf-8')
    print('Isolated demo prepared. Credentials:', credentials_path)
    return env


def listening(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def authenticated_demo():
    credentials = json.loads((DEMO / 'credentials.json').read_text(encoding='utf-8'))['admin']
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request = urllib.request.Request('http://127.0.0.1:8085/api/auth/login', data=json.dumps(credentials).encode(), headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8085'})
    with opener.open(request, timeout=10) as response:
        if not json.load(response).get('success'):
            raise RuntimeError('The running service is not this demo.')
    return opener


def launch_desktop(env):
    log = open(DEMO / 'desktop.log', 'a', encoding='utf-8')
    process = subprocess.Popen([str(CALIBRE / 'calibre.exe'), '--with-library=' + str(DEMO / 'library'), '--ignore-plugins'], env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    return process.pid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'start', 'desktop', 'status', 'stop'))
    parser.add_argument('--desktop', action='store_true')
    args = parser.parse_args()
    if args.action == 'stop':
        if not listening(8085):
            print('Demo gateway is already stopped.')
            return
        opener = authenticated_demo()
        request = urllib.request.Request('http://127.0.0.1:8085/api/admin/system/shutdown', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8085'})
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError('Demo shutdown was not accepted.')
        print('Demo gateway and its owned backend are stopping. Desktop remains open.')
        return
    if args.action == 'status':
        print(json.dumps({'gateway': listening(8085), 'backend': listening(8088)}))
        return
    print('Preparing the isolated source-based demo...', flush=True)
    env = prepare()
    if args.action == 'prepare':
        return
    if args.action == 'desktop':
        print('Desktop PID:', launch_desktop(env))
        return
    if listening(8085) or listening(8088):
        if listening(8085) and listening(8088):
            try:
                opener = authenticated_demo()
                with opener.open('http://127.0.0.1:8085/calibre/institutional/api', timeout=10) as response:
                    if json.load(response).get('source') != 'calibre.srv.institutional':
                        raise RuntimeError('Not the source-based demo')
                if args.desktop:
                    launch_desktop(env)
                print('Existing source-based demo is ready at http://127.0.0.1:8085/.')
                return
            except Exception as error:
                raise SystemExit('Demo ports are occupied by an unverified service: ' + str(error))
        raise SystemExit('Demo ports are occupied. Existing processes were not changed.')
    log = open(DEMO / 'gateway.log', 'a', encoding='utf-8')
    print('Starting Calibre Content Server; source web compilation can take up to one minute...', flush=True)
    process = subprocess.Popen([str(CALIBRE / 'calibre-debug.exe'), '-e', str(ROOT / 'customization/backend/gateway_server.py')], env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    (DEMO / 'gateway.pid').write_text(str(process.pid), encoding='ascii')
    for _ in range(160):
        if process.poll() is not None:
            raise SystemExit('Gateway exited. See .demo/gateway.log and .demo/config/calibre_backend.log.')
        if listening(8085):
            break
        time.sleep(.5)
    else:
        raise SystemExit('Gateway readiness timed out. See .demo/gateway.log.')
    if args.desktop:
        launch_desktop(env)
    print('Demo running at http://127.0.0.1:8085/ (loopback only).')


if __name__ == '__main__':
    main()
