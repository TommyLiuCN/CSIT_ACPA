"""
build_exe.py — CSIT_ACPA 一键打包脚本

用法:
    python build_exe.py

行为:
  1. 调用 PyInstaller 把 main_gui_v5beta.py 打包为单个 exe 到 dist/
  2. 自动清理打包垃圾 (build/、__pycache__/、*.spec)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "CSIT_ACPA_V5Beta"
ENTRY = "main_gui_v5beta.py"
ICON = "app_icon.ico"

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ROOT / ICON),
        "--add-data",
        f"{ICON};.",
        str(ROOT / ENTRY),
    ]
    print(f"[build] 运行: {' '.join(cmd)}")
    code = subprocess.call(cmd, cwd=str(ROOT))
    if code != 0:
        print(f"[build] PyInstaller 打包失败 (exit={code})")
        return code

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if not exe.exists():
        print("[build] 未找到打包产物，可能失败")
        return 1
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"[build] 打包完成: {exe} ({size_mb:.1f} MB)")

    cleaned = []
    build_dir = ROOT / "build"
    if build_dir.is_dir():
        shutil.rmtree(build_dir)
        cleaned.append(str(build_dir))
    for pycache in ROOT.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache)
            cleaned.append(str(pycache))
    for spec in ROOT.glob("*.spec"):
        spec.unlink()
        cleaned.append(str(spec))

    if cleaned:
        print("[build] 已清理打包垃圾:")
        for path in cleaned:
            print(f"  - {path}")
    else:
        print("[build] 无需清理")

    return 0


if __name__ == "__main__":
    sys.exit(main())