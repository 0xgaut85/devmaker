"""Build DevMaker as a standalone .exe using PyInstaller."""

import subprocess
import sys


def build():
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=DevMaker",
        "--onefile",
        "--windowed",
        "--add-data=content;content",
        "--add-data=core;core",
        "--add-data=browser;browser",
        "--add-data=gui;gui",
        "--hidden-import=openai",
        "--hidden-import=anthropic",
        "--hidden-import=playwright",
        "--hidden-import=PyQt6",
        "main.py",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("\nBuild complete! Find DevMaker.exe in the dist/ folder.")
    print("Before first run, install Playwright browsers:")
    print("  python -m playwright install chromium")


if __name__ == "__main__":
    build()
