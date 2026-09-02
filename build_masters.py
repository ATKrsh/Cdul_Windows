import os
import sys
import subprocess

CDUL_FILE = "cdul.py"
EXE_NAME = "Cdul_v4"

def build():
    print(f"--- Building {EXE_NAME}.exe ---")
    
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{CDUL_FILE}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psutil', 'pynvml'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'PIL', 'mss', 'cv2', 'soundcard', 'sounddevice'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{EXE_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""
    spec_file = f"{EXE_NAME}.spec"
    with open(spec_file, "w", encoding="utf-8") as f:
        f.write(spec_content)
        
    print(f"Running pyinstaller {spec_file}...")
    subprocess.run(["pyinstaller", "-y", spec_file])
    print(f"Finished building {EXE_NAME}.exe in dist/\n")

if __name__ == "__main__":
    build()
