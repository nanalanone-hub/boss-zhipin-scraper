"""Local-only Flask control panel and JSON API."""
from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_from_directory

from .browser import BrowserController, core_environment, default_core_command_builder, detect_browsers
from .config import (
    AppPaths, ConfigValidationError, Settings, SettingsStore, TaskStore,
)
from .runner import CollectorRunner, RunnerError
from . import __version__

def bundled_resource(*parts: str) -> Path:
    """Return a package resource path in both source and PyInstaller layouts."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if getattr(sys, "frozen", False):
        root = root / "boss_tool"
    return root.joinpath(*parts)


STATIC_DIR = bundled_resource("static")


class RunManager:
    def __init__(self, paths: AppPaths, task_store: TaskStore, settings_store: SettingsStore, core_environment_data=None):
        self.paths = paths
        self.task_store = task_store
        self.settings_store = settings_store
        self.core_environment_data = core_environment_data
        self._states: dict[str, dict[str, Any]] = {}
        self._runners: dict[str, CollectorRunner] = {}
        self._lock = threading.RLock()

    def state(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._states.get(task_id, {"status": "idle", "logs": []}))

    def start(self, task_id: str) -> tuple[dict[str, Any], int]:
        try:
            record = self.task_store.get(task_id)
        except KeyError:
            return {"error": "task_not_found"}, 404
        with self._lock:
            current = self._states.get(task_id, {}).get("status")
            if current in {"queued", "running"}:
                return {"error": "task_already_running", "status": current}, 409
            self._states[task_id] = {"status": "queued", "logs": [], "started_at": None, "ended_at": None, "error": "", "result": None}
        thread = threading.Thread(target=self._worker, args=(task_id, record.config), daemon=True)
        thread.start()
        return {"status": "queued", "task_id": task_id}, 202

    def cancel(self, task_id: str) -> tuple[dict[str, Any], int]:
        with self._lock:
            runner = self._runners.get(task_id)
        if not runner:
            return {"error": "task_not_running"}, 409
        runner.cancel()
        return {"status": "cancelling"}, 202

    def _worker(self, task_id: str, config) -> None:
        from datetime import datetime
        runner = CollectorRunner(self.paths, self.settings_store.load(), environment=self.core_environment_data)
        with self._lock:
            self._runners[task_id] = runner
            self._states[task_id].update({"status": "running", "started_at": datetime.now().isoformat(timespec="seconds")})

        def relay(message: str) -> None:
            with self._lock:
                logs = self._states[task_id].setdefault("logs", [])
                logs.append(message)
                del logs[:-500]

        runner.log = relay
        try:
            result = runner.run(task_id, config)
            payload = {
                "raw_total": result.raw_total,
                "filtered_total": result.filtered_total,
                "repeated_total": result.repeated_total,
                "new_total": result.new_total,
                "detail_total": result.detail_total,
                "task_dir": str(result.task_dir),
                "history_file": str(result.history_file),
                "raw_json": str(result.raw_json),
                "latest_json": str(result.latest_json),
                "latest_csv": str(result.latest_csv),
                "latest_detail_csv": str(result.latest_detail_csv) if result.latest_detail_csv else "",
                "fingerprint_changed": result.fingerprint_changed,
                "log_file": str(result.log_file),
            }
            with self._lock:
                self._states[task_id].update({"status": "success", "result": payload})
        except RunnerError as exc:
            with self._lock:
                cancelled = exc.code == "cancelled"
                status = "cancelled" if cancelled else "failed"
                self._states[task_id].update({"status": status, "error": exc.code, "message": str(exc)})
                relay("采集已取消。" if cancelled else f"❌ {exc.code}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface unexpected local failure to UI
            with self._lock:
                self._states[task_id].update({"status": "failed", "error": "unexpected_error", "message": str(exc)})
                relay(traceback.format_exc())
        finally:
            with self._lock:
                self._states[task_id]["ended_at"] = datetime.now().isoformat(timespec="seconds")
                self._runners.pop(task_id, None)


def _record_json(record) -> dict[str, Any]:
    return record.to_dict()


def create_app(
    paths: AppPaths | None = None,
    token: str = "",
    task_store: TaskStore | None = None,
    settings_store: SettingsStore | None = None,
    run_manager: RunManager | None = None,
    browser_controller: BrowserController | None = None,
) -> Flask:
    paths = paths or AppPaths(Path.cwd() / ".boss-tool-state", Path.cwd() / ".boss-tool-data")
    paths.ensure()
    task_store = task_store or TaskStore(paths)
    settings_store = settings_store or SettingsStore(paths)
    env = core_environment(paths)
    run_manager = run_manager or RunManager(paths, task_store, settings_store, core_environment_data=env)
    browser = browser_controller or BrowserController(environment=env)
    app = Flask(__name__, static_folder=None)
    app.config["BOSS_TOKEN"] = token
    app.config["VERSION"] = __version__

    @app.before_request
    def guard_local_api():
        if not request.path.startswith("/api/"):
            return None
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            host = request.host.split(":")[0]
            if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.hostname != host:
                return jsonify({"error": "invalid_origin"}), 403
        supplied = request.headers.get("X-Boss-Tool-Token", "") or request.args.get("token", "")
        if not token or not hmac.compare_digest(supplied, token):
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.errorhandler(ConfigValidationError)
    def handle_validation(exc):
        return jsonify({"error": "invalid_config", "message": str(exc)}), 400

    @app.errorhandler(KeyError)
    def handle_missing(exc):
        return jsonify({"error": "not_found", "message": str(exc)}), 404

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/<path:asset>")
    def static_asset(asset: str):
        return send_from_directory(STATIC_DIR, asset)

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "portable": paths.portable,
            "state_dir": str(paths.state_dir),
            "documents_dir": str(paths.documents_dir),
            "version": app.config.get("VERSION", "0.1.0"),
        })

    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings_store.load().to_dict())

    @app.put("/api/settings")
    def put_settings():
        settings = Settings.from_dict(request.get_json(silent=True) or {})
        settings_store.save(settings)
        return jsonify(settings.to_dict())

    @app.get("/api/browsers")
    def browsers():
        return jsonify(detect_browsers())

    @app.get("/api/task-schema")
    def task_schema():
        schema = bundled_resource("task_schema.json")
        return jsonify(json.loads(schema.read_text(encoding="utf-8")))

    @app.post("/api/browser/start")
    def browser_start():
        settings = settings_store.load()
        if not settings.accepted_compliance:
            return jsonify({"error": "compliance_required"}), 403
        try:
            process = browser.start(settings, wait_login=True)
        except OSError as exc:
            return jsonify({"error": "browser_start_failed", "message": str(exc)}), 500
        return jsonify({"started": True, "pid": getattr(process, "pid", None)}), 202

    @app.post("/api/browser/check")
    def browser_check():
        settings = settings_store.load()
        if not settings.accepted_compliance:
            return jsonify({"error": "compliance_required"}), 403
        command = list(default_core_command_builder(["--check", "--cdp-port", str(settings.cdp_port)]))
        run_kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": 90, "env": env}
        if sys.platform == "win32":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(command, **run_kwargs)
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "exit_code": 124, "output": "登录检查超时，请稍后重试或在专用浏览器中先完成登录。"}), 504
        except OSError as exc:
            return jsonify({"ok": False, "exit_code": 127, "output": f"无法启动核心采集程序：{exc}"}), 500
        output = (completed.stdout or "") + (completed.stderr or "")
        return jsonify({"ok": completed.returncode == 0, "exit_code": completed.returncode, "output": output}), 200 if completed.returncode == 0 else 422

    @app.post("/api/browser/stop")
    def browser_stop():
        try:
            browser.stop(settings_store.load())
        except OSError as exc:
            return jsonify({"error": "browser_stop_failed", "message": str(exc)}), 500
        return jsonify({"stopping": True}), 202

    @app.get("/api/tasks")
    def list_tasks():
        return jsonify({"tasks": [_record_json(record) for record in task_store.list()]})

    @app.post("/api/tasks")
    def create_task():
        record = task_store.create(request.get_json(silent=True) or {})
        return jsonify(_record_json(record)), 201

    @app.get("/api/tasks/<task_id>")
    def get_task(task_id: str):
        return jsonify(_record_json(task_store.get(task_id)))

    @app.put("/api/tasks/<task_id>")
    def update_task(task_id: str):
        return jsonify(_record_json(task_store.update(task_id, request.get_json(silent=True) or {})))

    @app.delete("/api/tasks/<task_id>")
    def delete_task(task_id: str):
        task_store.delete(task_id)
        return jsonify({"deleted": True})

    @app.post("/api/tasks/<task_id>/duplicate")
    def duplicate_task(task_id: str):
        new_name = (request.get_json(silent=True) or {}).get("name")
        return jsonify(_record_json(task_store.duplicate(task_id, new_name))), 201

    @app.get("/api/tasks/<task_id>/export")
    def export_task(task_id: str):
        record = _record_json(task_store.get(task_id))
        response = jsonify(record)
        response.headers["Content-Disposition"] = f"attachment; filename={task_id}.json"
        return response

    @app.post("/api/tasks/import")
    def import_task():
        data = request.get_json(silent=True) or {}
        data.pop("id", None)
        return jsonify(_record_json(task_store.create(data))), 201

    @app.post("/api/tasks/<task_id>/run")
    def run_task(task_id: str):
        if not settings_store.load().accepted_compliance:
            return jsonify({"error": "compliance_required"}), 403
        payload, status = run_manager.start(task_id)
        return jsonify(payload), status

    @app.post("/api/tasks/<task_id>/cancel")
    def cancel_task(task_id: str):
        payload, status = run_manager.cancel(task_id)
        return jsonify(payload), status

    @app.get("/api/tasks/<task_id>/run")
    def run_state(task_id: str):
        task_store.get(task_id)
        return jsonify(run_manager.state(task_id))

    @app.post("/api/tasks/<task_id>/open")
    def open_task(task_id: str):
        task_store.get(task_id)
        path = paths.task_dir(task_id)
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return jsonify({"path": str(path)})


    @app.post("/api/tasks/<task_id>/open-result")
    def open_result(task_id: str):
        task_store.get(task_id)
        kind = (request.get_json(silent=True) or {}).get("kind", "folder")
        names = {
            "folder": "",
            "csv": "latest_new_jobs.csv",
            "json": "latest_new_jobs.json",
            "details": "latest_new_details.csv",
        }
        if kind not in names:
            return jsonify({"error": "invalid_result_kind"}), 400
        task_path = paths.task_dir(task_id)
        target = task_path if not names[kind] else task_path / names[kind]
        if kind != "folder" and not target.exists():
            return jsonify({"error": "result_not_found", "path": str(target)}), 404
        task_path.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            return jsonify({"error": "open_failed", "message": str(exc)}), 500
        return jsonify({"path": str(target)})

    app.run_manager = run_manager  # type: ignore[attr-defined]
    return app
