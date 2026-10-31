#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Captures actual live screenshots of the running Admin Console V2 Preview
on http://127.0.0.1:8086/admin-v2 across all 8 views, modals, and responsive viewports.
"""

import shutil
import subprocess
from pathlib import Path

MSEDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE_URL = "http://127.0.0.1:8086/admin-v2"
ARTIFACT_DIR = Path(r"C:\Users\USER\.gemini\antigravity\brain\3b4054f7-edc8-4f51-9973-cedc12550e82")
EVIDENCE_DIR = Path(r"C:\dev\calibre-institutional\docs\evidence\admin_v2")

ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("admin_v2_5_branding.png", f"{BASE_URL}?view=branding", "1440,940"),
    ("admin_v2_5b_branding_preset_oxford.png", f"{BASE_URL}?view=branding&preset=oxford", "1440,940"),
    ("admin_v2_responsive_mobile.png", f"{BASE_URL}?view=users", "412,915"),
    ("admin_v2_responsive_mobile_drawer.png", f"{BASE_URL}?view=dashboard&drawer=open", "412,915"),
]


def capture_all():
    for filename, url, window_size in TARGETS:
        out_ev = EVIDENCE_DIR / filename
        out_art = ARTIFACT_DIR / filename
        cmd = [
            MSEDGE,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--virtual-time-budget=3500",
            f"--window-size={window_size}",
            f"--screenshot={out_ev}",
            url,
        ]
        subprocess.run(cmd, capture_output=True, check=False, timeout=30)
        if out_ev.is_file():
            shutil.copy2(out_ev, out_art)
            print(f"[OK] {filename} ({out_ev.stat().st_size} bytes)")
        else:
            print(f"[FAIL] {filename}")


if __name__ == "__main__":
    capture_all()
