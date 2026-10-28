"""Run Calibre's setup commands with the installed Windows dependency runtime.

setup normally assumes an independent Python development environment. Preserve
the installed native extensions and worker launcher when using calibre-debug.
"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1] / 'upstream/calibre'
native_extensions = getattr(sys, 'extensions_location', None)
sys.path.insert(0, str(ROOT))
import setup
if native_extensions:
    sys.extensions_location = native_extensions
if hasattr(sys, 'running_from_setup'):
    del sys.running_from_setup
from calibre.utils.config import JSONConfig
JSONConfig('gui')['migrated_forms_to_qt6'] = True
sys.argv = [str(ROOT / 'setup.py'), *sys.argv[1:]]
runpy.run_path(str(ROOT / 'setup.py'), run_name='__main__')
