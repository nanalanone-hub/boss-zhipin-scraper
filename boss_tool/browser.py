"""Browser discovery and Windows app-window launching."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .config import AppPaths, Settings


CommandBuilder = Callable[[list[str]], Sequence[str]]


def default_core_command_builder(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        exe = base / "boss-core" / ("boss-core.exe" if os.name == "nt" else "boss-core")
        return [str(exe), *args]
    root = Path(__file__).resolve().parents[1]
    return [sys.executable, str(root / "scripts" / "boss_cdp_raw.py"), *args]


def _windows_candidates() -> dict[str, list[Path]]:
    program_files = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
                     Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return {
        "edge": [local_app / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                 *(base / "Microsoft" / "Edge" / "Application" / "msedge.exe" for base in program_files)],
        "chrome": [local_app / "Google" / "Chrome" / "Application" / "chrome.exe",
                   *(base / "Google" / "Chrome" / "Application" / "chrome.exe" for base in program_files)],
    }


def _mac_candidates() -> dict[str, list[Path]]:
    applications = [Path("/Applications"), Path.home() / "Applications"]
    return {
        "edge": [base / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge" for base in applications],
        "chrome": [base / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome" for base in applications],
    }


def detect_browsers() -> dict[str, dict[str, str | bool]]:
    if os.name == "nt":
        candidates = _windows_candidates()
    elif sys.platform == "darwin":
        candidates = _mac_candidates()
    else:
        candidates = {
            "edge": [Path("/usr/bin/microsoft-edge"), Path("/usr/bin/microsoft-edge-stable")],
            "chrome": [Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable")],
        }
    result = {}
    for name, paths in candidates.items():
        found = next((path for path in paths if path.exists()), None)
        if found is None:
            on_path = shutil.which("msedge" if name == "edge" else ("chrome" if os.name != "nt" else "chrome"))
            found = Path(on_path) if on_path else None
        result[name] = {"available": found is not None, "path": str(found) if found else ""}
    chosen = "edge" if result["edge"]["available"] else ("chrome" if result["chrome"]["available"] else "")
    result["selected"] = {"available": bool(chosen), "browser": chosen}
    return result


def core_environment(paths: AppPaths | None = None) -> Mapping[str, str]:
    env = dict(os.environ)
    if paths and paths.portable:
        browser_home = paths.documents_dir / "browser-home"
        browser_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(browser_home)
        if os.name == "nt":
            env["USERPROFILE"] = str(browser_home)
    return env


def resolve_browser_name(settings: Settings) -> str:
    if settings.browser in {"edge", "chrome"}:
        return settings.browser
    detected = detect_browsers()
    return "edge" if detected["edge"]["available"] else "chrome"


class BrowserController:
    def __init__(self, command_builder: CommandBuilder | None = None, popen=subprocess.Popen, environment: Mapping[str, str] | None = None):
        self.build_command = command_builder or default_core_command_builder
        self.popen = popen
        self.environment = dict(environment) if environment is not None else None

    def _browser_args(self, browser: str, action: str, settings: Settings, wait_login: bool | None = None) -> list[str]:
        flag = "--setup-edge" if browser == "edge" else "--setup-chrome"
        if action == "start":
            args = [flag, "--cdp-port", str(settings.cdp_port)]
            if wait_login is False:
                args.append("--no-wait-login")
            return args
        if action == "stop":
            return ["--stop-edge" if browser == "edge" else "--stop-chrome"]
        raise ValueError(action)

    def _popen_kwargs(self) -> dict:
        if os.name == "nt":
            return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        return {"start_new_session": True}

    def start(self, settings: Settings, wait_login: bool = True):
        browser = resolve_browser_name(settings)
        args = self._browser_args(browser, "start", settings, wait_login)
        kwargs = self._popen_kwargs()
        if self.environment is not None:
            kwargs["env"] = self.environment
        return self.popen(list(self.build_command(args)), **kwargs)

    def stop(self, settings: Settings):
        browser = resolve_browser_name(settings)
        kwargs = self._popen_kwargs()
        if self.environment is not None:
            kwargs["env"] = self.environment
        return self.popen(list(self.build_command(self._browser_args(browser, "stop", settings))), **kwargs)


def open_app_window(url: str) -> bool:
    browsers = detect_browsers()
    preferred = ["edge", "chrome"]
    for name in preferred:
        info = browsers.get(name, {})
        path = info.get("path")
        if path:
            try:
                subprocess.Popen([str(path), f"--app={url}"], start_new_session=True)
                return True
            except OSError:
                pass
    return webbrowser.open(url)
