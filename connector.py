#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the loopback-only ViralX Connector and open the hosted pairing page."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from urllib.parse import quote

from local_connector import (
    CONNECTOR_HOST,
    CONNECTOR_PORT,
    PRODUCTION_ORIGIN,
    create_connector_app,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="ViralX hosted-page connector for local LibTV")
    parser.add_argument("--no-open", action="store_true", help="do not open the pairing page")
    parser.add_argument(
        "--site",
        default=PRODUCTION_ORIGIN,
        choices=[PRODUCTION_ORIGIN, "http://127.0.0.1:4173", "http://localhost:4173"],
        help="trusted ViralX site to open",
    )
    args = parser.parse_args()

    app, broker = create_connector_app()
    pairing_secret = broker.issue_pairing_secret()
    pairing_url = (
        f"{args.site.rstrip('/')}/settings.html"
        f"#viralx-connector={quote(pairing_secret, safe='')}"
    )

    print("[ViralX Connector] 已启动本机安全桥接。")
    print(f"[监听] http://{CONNECTOR_HOST}:{CONNECTOR_PORT}（仅本机）")
    print("[安全] 配对信息只存在 URL fragment 与本机内存，不会发送到 EdgeOne。")
    print("[停止] 按 Ctrl+C。")
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(pairing_url)).start()
    else:
        print("[提示] --no-open 模式不会输出配对密钥；请不带该参数重新启动以完成配对。")

    app.run(
        host=CONNECTOR_HOST,
        port=CONNECTOR_PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
