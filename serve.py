"""Start API on all interfaces (LAN / same Wi‑Fi). Use: python serve.py"""

from __future__ import annotations

import os
import sys

import uvicorn

from app.utils.network import get_lan_ipv4


def main() -> None:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "true").lower() in ("1", "true", "yes")

    lan = get_lan_ipv4()
    print("=" * 60)
    print(f"Binding: {host}:{port}  (0.0.0.0 = reachable on your Wi-Fi)")
    print(f"On this PC:     http://127.0.0.1:{port}/docs")
    if lan:
        print(f"Other devices:  http://{lan}:{port}/docs")
        print(f"Analyze API:    http://{lan}:{port}/v1/assets/analyze")
    else:
        print("LAN IP not detected - check Wi-Fi, then open http://localhost:8000/")
    print("Stop with Ctrl+C.")
    print("If another device says 'refused to connect':")
    print("  1) You must use THIS script (not: uvicorn app.main:app --reload)")
    print("  2) Run scripts\\open-firewall.ps1 as Administrator")
    print("  3) Phone must use the IP above, NOT localhost")
    print("  4) PC and phone on the same Wi-Fi (not guest network)")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
