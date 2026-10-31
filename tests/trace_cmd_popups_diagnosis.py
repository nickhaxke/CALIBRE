import os
import sys
import time
import subprocess

def test_execution():
    app_bin = r"C:\dev\calibre-institutional\test-environment\installed-app\calibre\app\bin"
    pdftoppm = os.path.join(app_bin, "pdftoppm.exe")
    pdfinfo = os.path.join(app_bin, "pdfinfo.exe")
    sample_pdf = r"C:\dev\calibre-institutional\.demo\library\Chief Archivist Thorne\Large-Scale Archival Repository Syst (9)\Large-Scale Archival Repository - Chief Archivist Thorne.pdf"

    print("Sample PDF exists:", os.path.isfile(sample_pdf))

    # Test 1: Standard subprocess (Current gateway_server implementation)
    t0 = time.time()
    res1 = subprocess.run([pdfinfo, sample_pdf], capture_output=True, text=True, errors="replace", timeout=10)
    dt1 = time.time() - t0
    print(f"[TEST 1 - CURRENT] pdfinfo returncode: {res1.returncode}, time: {dt1:.3f}s")
    for line in res1.stdout.splitlines()[:5]:
        print(f"  > {line}")

    # Test 2: With CREATE_NO_WINDOW and STARTUPINFO
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0 # SW_HIDE
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    t0 = time.time()
    res2 = subprocess.run(
        [pdfinfo, sample_pdf],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
        creationflags=creationflags,
        startupinfo=si
    )
    dt2 = time.time() - t0
    print(f"[TEST 2 - NO WINDOW] pdfinfo returncode: {res2.returncode}, time: {dt2:.3f}s")
    assert res1.stdout == res2.stdout, "Outputs must match exactly!"
    print("MATCH: Output with CREATE_NO_WINDOW is identical!")

    # Test pdftoppm page rendering
    t0 = time.time()
    res_page = subprocess.run(
        [pdftoppm, "-png", "-r", "150", "-f", "1", "-l", "1", sample_pdf],
        capture_output=True,
        timeout=15,
        creationflags=creationflags,
        startupinfo=si
    )
    dt_page = time.time() - t0
    print(f"[TEST 3 - NO WINDOW] pdftoppm page 1 render: code={res_page.returncode}, size={len(res_page.stdout)} bytes, time={dt_page:.3f}s")
    assert res_page.stdout.startswith(b"\x89PNG"), "Must produce valid PNG"
    print("SUCCESS: Valid PNG rendered cleanly with zero window creation!")

if __name__ == "__main__":
    test_execution()
