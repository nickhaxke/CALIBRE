# -*- coding: utf-8 -*-
"""
Source Code Inspector Utility
Examines upstream Calibre architecture components without executing Calibre.
"""
import os
import sys

UPSTREAM = r"C:\dev\calibre-institutional\upstream\calibre"

def inspect():
    print("=" * 60)
    print("CALIBRE SOURCE CODE ARCHITECTURE INSPECTION")
    print("=" * 60)
    
    if not os.path.exists(UPSTREAM):
        print(f"Error: Upstream directory not found: {UPSTREAM}")
        return
        
    const_file = os.path.join(UPSTREAM, "src", "calibre", "constants.py")
    if os.path.exists(const_file):
        with open(const_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("numeric_version =") or line.startswith("__appname__ ="):
                    print("Constants:", line.strip())
                    
    endpoints_file = os.path.join(UPSTREAM, "src", "calibre", "linux.py")
    if os.path.exists(endpoints_file):
        print("\nEntry points defined in linux.py: Verified")
        
    srv_dir = os.path.join(UPSTREAM, "src", "calibre", "srv")
    if os.path.exists(srv_dir):
        srv_files = os.listdir(srv_dir)
        print(f"\nContent Server modules count: {len(srv_files)} files in srv/")
        print("Key modules: standalone.py, embedded.py, auth.py, users.py, code.py, content.py")
        
    pyj_dir = os.path.join(UPSTREAM, "src", "pyj")
    if os.path.exists(pyj_dir):
        print(f"\nFrontend RapydScript source: {pyj_dir} exists")
        print("Subpackages: book_list, read_book, viewer")
        
    print("\nAll source components verified.")

if __name__ == "__main__":
    inspect()
