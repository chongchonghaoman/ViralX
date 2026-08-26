#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the loopback-only ViralX Connector and open the hosted pairing page."""

from __future__ import annotations

import argparse
import json
import socket
import threading
import webbrowser
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from werkzeug.serving import ThreadedWSGIServer

from local_connector import (
    CONNECTOR_HOST,
    CONNECTOR_ORIGIN,
    CONNECTOR_PORT,
    LOCAL_PAIRING_PATH,
    PRODUCTION_ORIGIN,
    create_connector_app,
)


class ExclusiveThreadedWSGIServer(ThreadedWSGIServer):
    """Prevent two Connector processes from sharing the loopback port on Windows."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_address_use is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
        super().server_bind()


def pairing_page_url(site: str, pairing_secret: str) -> str:
    return (
        f"{site.rstrip('/')}/settings.html"
        f"#viralx-connector={quote(pairing_secret, safe='')}"
    )


def request_pairing_from_running_connector(site: str) -> str:
    """Ask an existing loopback Connector for a fresh one-use browser link."""

    request = Request(
        f"{CONNECTOR_ORIGIN}{LOCAL_PAIRING_PATH}",
        data=json.dumps({"site": site}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return ""

    pairing_url = str(payload.get("pairing_url", ""))
    parsed_url = urlsplit(pairing_url)
    parsed_site = urlsplit(site)
    pairing_values = parse_qs(parsed_url.fragment).get("viralx-connector", [])
    if (
        (parsed_url.scheme, parsed_url.netloc) != (parsed_site.scheme, parsed_site.netloc)
        or parsed_url.path != "/settings.html"
        or len(pairing_values) != 1
        or not pairing_values[0]
    ):
        return ""
    return pairing_url


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

    existing_pairing_url = request_pairing_from_running_connector(args.site)
    if existing_pairing_url:
        print("[ViralX Connector] 已有实例正在运行，正在生成新的安全配对页。")
        print(f"[监听] {CONNECTOR_ORIGIN}（仅本机）")
        if not args.no_open:
            webbrowser.open(existing_pairing_url)
        else:
            print("[提示] --no-open 模式不会打开配对页；请不带该参数重新运行。")
        return

    app, broker = create_connector_app()

    # Bind before issuing or opening a one-use pairing link. Werkzeug enables
    # SO_REUSEADDR by default, which can let two Python processes share the
    # same loopback port on Windows. A link created by the second process would
    # then be sent to the first process and always fail as "invalid or expired".
    server = ExclusiveThreadedWSGIServer(CONNECTOR_HOST, CONNECTOR_PORT, app)
    pairing_secret = broker.issue_pairing_secret()
    pairing_url = pairing_page_url(args.site, pairing_secret)

    print("[ViralX Connector] 已启动本机安全桥接。")
    print(f"[监听] http://{CONNECTOR_HOST}:{CONNECTOR_PORT}（仅本机）")
    print("[安全] 配对信息只存在 URL fragment 与本机内存，不会发送到 EdgeOne。")
    print("[停止] 按 Ctrl+C。")
    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(pairing_url)).start()
    else:
        print("[提示] --no-open 模式不会输出配对密钥；请不带该参数重新启动以完成配对。")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ViralX Connector] 已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
