"""Desktop tray process and local web panel bootstrap."""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote

from .browser import open_app_window
from .config import discover_app_paths
from .server import create_app

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # Tray is optional in development/CI.
    pystray = None
    Image = None
    ImageDraw = None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def panel_url(port: int, token: str) -> str:
    return f"http://127.0.0.1:{port}/#token={quote(token, safe='')}"


def make_icon():
    if Image is None or ImageDraw is None:
        return None
    image = Image.new("RGBA", (64, 64), (15, 76, 129, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 8, 58, 56), radius=10, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((13, 16, 51, 25), radius=4, fill=(15, 76, 129, 255))
    draw.rounded_rectangle((13, 32, 43, 40), radius=4, fill=(15, 76, 129, 255))
    draw.rounded_rectangle((13, 45, 48, 51), radius=3, fill=(15, 76, 129, 255))
    return image


def _start_waitress(app, port: int):
    from waitress import create_server

    server = create_server(app, host="127.0.0.1", port=port, threads=4, channel_timeout=120)
    thread = threading.Thread(target=server.run, name="boss-tool-waitress", daemon=True)
    thread.start()
    return server, thread


def run_app(port: int = 0, open_browser: bool = True, use_tray: bool = True) -> int:
    paths = discover_app_paths().ensure()
    token = secrets.token_urlsafe(24)
    app = create_app(paths=paths, token=token)
    actual_port = port or find_free_port()
    try:
        log_path = paths.state_dir / "desktop-app.log"
        logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        server, _ = _start_waitress(app, actual_port)
    except OSError as exc:
        logging.exception("无法启动本地服务")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, f"无法启动本地服务：{exc}", "BOSS采集助手", 0x10)
        raise
    url = panel_url(actual_port, token)
    stop_event = threading.Event()

    if open_browser:
        timer = threading.Timer(0.6, lambda: open_app_window(url))
        timer.daemon = True
        timer.start()

    def shutdown(icon=None, item=None):
        stop_event.set()
        try:
            server.close()
        except (OSError, RuntimeError):
            pass
        if icon is not None:
            icon.stop()

    if use_tray and pystray is not None:
        def open_panel(icon=None, item=None):
            open_app_window(url)

        def open_data(icon=None, item=None):
            import os
            import subprocess
            import sys
            if os.name == "nt":
                os.startfile(str(paths.documents_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(paths.documents_dir)])
            else:
                subprocess.Popen(["xdg-open", str(paths.documents_dir)])

        menu = pystray.menu.Menu(
            pystray.MenuItem("打开面板", open_panel, default=True),
            pystray.MenuItem("打开数据目录", open_data),
            pystray.MenuItem("退出", shutdown),
        )
        icon = pystray.Icon("boss-collector", make_icon(), "BOSS采集助手", menu)
        try:
            icon.run()
        finally:
            shutdown()
        return 0

    try:
        while not stop_event.wait(1):
            time.sleep(0.1)
    except KeyboardInterrupt:
        shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOSS采集助手本地桌面服务")
    parser.add_argument("--port", type=int, default=0, help="固定本地端口；默认自动选择")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开面板")
    parser.add_argument("--no-tray", action="store_true", help="不创建系统托盘图标")
    args = parser.parse_args(argv)
    return run_app(port=args.port, open_browser=not args.no_browser, use_tray=not args.no_tray)


if __name__ == "__main__":
    raise SystemExit(main())
