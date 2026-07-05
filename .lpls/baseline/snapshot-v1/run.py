#!/usr/bin/env python3
"""Lead Gen Pro — Bring Your Own Keys Lead Generation Module

Usage:
    python run.py

Then open http://localhost:8080 in your browser.
Get a free Exa API key at https://dashboard.exa.ai
"""
import os
import sys
import webbrowser
from pathlib import Path


def main():
    os.chdir(Path(__file__).parent)

    port = int(os.getenv("PORT", "8080"))

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║              LEAD GEN PRO  v3.0                     ║")
    print("  ║        Bring Your Own Keys Lead Generation          ║")
    print("  ╠══════════════════════════════════════════════════════╣")
    print("  ║                                                     ║")
    print(f"  ║  Dashboard   http://localhost:{port}                 ║")
    print(f"  ║  API Docs    http://localhost:{port}/docs            ║")
    print(f"  ║                                                     ║")
    print("  ║  Get your free Exa API key:                          ║")
    print("  ║  https://dashboard.exa.ai                            ║")
    print("  ║                                                     ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    webbrowser.open(f"http://localhost:{port}")

    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
