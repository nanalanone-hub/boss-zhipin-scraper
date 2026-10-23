"""Four-stage collector execution: check, list, local pipeline, details."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .browser import default_core_command_builder, resolve_browser_name
from .config import AppPaths, Settings, TaskConfig, atomic_write_json
from .pipeline import PipelineError, process_details_file, process_list_file

SECURITY_MARKERS = ("_security_check", "安全验证", "滑块", "短信", "登录失效", "未登录", "请先登录")


class RunnerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class RunResult:
    raw_total: int
    filtered_total: int
    repeated_total: int
    new_total: int
    detail_total: int
    task_dir: Path
    history_file: Path
    raw_json: Path
    latest_json: Path
    latest_csv: Path
    latest_detail_csv: Path | None
    fingerprint_changed: bool
    log_file: Path


class CollectorRunner:
    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        core_command_builder: Callable[[list[str]], list[str]] | None = None,
        environment: Mapping[str, str] | None = None,
    ):
        self.paths = paths.ensure()
        self.settings = settings
        self.build_core_command = core_command_builder or default_core_command_builder
        self.environment = dict(environment) if environment is not None else None
        self.log_messages: list[str] = []
        self.current_process: subprocess.Popen | None = None
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()

    def log(self, message: str) -> None:
        line = str(message).rstrip()
        if line:
            self.log_messages.append(line)

    def _run_core(self, args: list[str], stage: str) -> str:
        if self._cancel.is_set():
            raise RunnerError("cancelled", "采集已取消")
        command = list(self.build_core_command(args))
        self.log(f"阶段 {stage}：{' '.join(command)}")
        try:
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if self.environment is not None:
                popen_kwargs["env"] = self.environment
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            raise RunnerError("core_not_found", f"找不到核心采集程序：{exc}") from exc
        with process:
            self.current_process = process
            output: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                text = line.rstrip()
                if text:
                    output.append(text)
                    self.log(text)
            return_code = process.wait()
        if process is self.current_process:
            self.current_process = None
        combined = "\n".join(output)
        if return_code != 0:
            if self._cancel.is_set():
                raise RunnerError("cancelled", "采集已取消")
            if any(marker in combined for marker in SECURITY_MARKERS):
                raise RunnerError(
                    "login_or_security_check_required",
                    "未登录、登录失效或出现安全验证，请在专用浏览器中手动处理后重试。",
                )
            raise RunnerError("core_command_failed", f"核心采集程序失败（退出码 {return_code}）")
        return combined

    @staticmethod
    def _write_empty_list(path: Path, config: TaskConfig) -> None:
        # Core intentionally does not create an output file for a successful zero-result run.
        atomic_write_json(path, {
            "keyword": config.keyword,
            "city": config.city,
            "filters": config.filters(),
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
            "total": 0,
            "jobs": [],
        })

    def _stop_browser_if_requested(self) -> None:
        if not self.close_browser:
            return
        browser = resolve_browser_name(self.settings)
        flag = "--stop-edge" if browser == "edge" else "--stop-chrome"
        self._run_core([flag], "收尾：关闭专用浏览器")

    def run(self, task_id: str, config: TaskConfig) -> RunResult:
        self._cancel.clear()
        self.close_browser = config.close_chrome
        task_dir = self.paths.task_dir(task_id)
        for name in ("history", "raw", "new", "details", "logs"):
            (task_dir / name).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        history_file = task_dir / "history" / f"{task_id}_history.json"
        raw_json = task_dir / "raw" / f"{timestamp}_jobs.json"
        new_json = task_dir / "new" / f"{timestamp}_new_jobs.json"
        new_csv = task_dir / "new" / f"{timestamp}_new_jobs.csv"
        detail_json = task_dir / "details" / f"{timestamp}_details.json"
        detail_csv = task_dir / "details" / f"{timestamp}_new_details.csv"
        log_file = task_dir / "logs" / f"{timestamp}.log"
        latest_detail_path = task_dir / "latest_new_details.csv"
        self.log_messages = []
        self.log(f"任务：{config.name} ({task_id})")
        history_backup: bytes | None = None
        detail_stage_attempted = False
        detail_stage_succeeded = False

        try:
            self._run_core(["--check", "--cdp-port", str(self.settings.cdp_port)], "1/4 检查浏览器与登录态")
            list_args = [
                "--keyword", config.keyword, "--city", config.city, "--pages", str(config.pages),
                "--format", "json", "--output", str(raw_json), "--detail-output", str(detail_json),
                "--cdp-port", str(self.settings.cdp_port), "--no-detail",
            ]
            if config.allow_dom_fallback:
                list_args.append("--allow-dom-fallback")
            for key, value in config.filters().items():
                list_args.extend([f"--{key}", value])
            self._run_core(list_args, "2/4 抓取职位列表")
            if not raw_json.exists():
                self._write_empty_list(raw_json, config)
            with raw_json.open(encoding="utf-8") as f:
                raw_payload = json.load(f)

            if history_file.exists():
                history_backup = history_file.read_bytes()
            stats = process_list_file(
                list_input=raw_json,
                list_csv=new_csv,
                json_out=new_json,
                history_file=history_file,
                task_name=task_id,
                config_name=f"{task_id}.json",
                keyword=config.keyword,
                city=config.city,
                filters=config.filters(),
                include_keywords=config.title_include,
                exclude_keywords=config.title_exclude,
                fields=config.export_fields,
                chinese_headers=config.chinese_header,
                history_enabled=True,
                changed_policy=config.changed_policy,
            )
            self.log(f"阶段 3/4：标题过滤、历史去重与结果导出")
            self.log(f"历史去重：过滤后 {stats['filtered_total']} 条，新增 {stats['new_total']} 条，历史重复 {stats['repeated_total']} 条")
            if stats.get("fingerprint_changed"):
                self.log("⚠️ 警告：搜索条件与历史记录不一致，本次已按 warn 策略继续，建议为不同条件新建任务。")
            detail_count = 0
            latest_detail_csv = None
            detail_stage_attempted = stats["new_total"] > 0 and config.fetch_detail and config.max_details > 0
            if detail_stage_attempted:
                detail_args = [
                    "--input", str(new_json), "--format", "json", "--detail-output", str(detail_json),
                    "--max-details", str(min(config.max_details, stats["new_total"])),
                    "--cdp-port", str(self.settings.cdp_port),
                ]
                if config.analysis:
                    detail_args.append("--analysis")
                self._run_core(detail_args, "4/4 抓取新增岗位 JD")
                if detail_json.exists():
                    detail_stats = process_details_file(
                        list_input=new_json, detail_input=detail_json, detail_csv=detail_csv,
                        fields=config.detail_export_fields, chinese_headers=config.chinese_header,
                    )
                    detail_count = detail_stats["detail_total"]
                    latest_detail_csv = detail_csv
                    detail_stage_succeeded = True
            elif stats["new_total"] > 0 and config.analysis:
                # Point analysis at this empty file so it cannot pick up unrelated CLI details.
                atomic_write_json(detail_json, [])
                analysis_args = [
                    "--input", str(new_json), "--no-detail", "--analysis",
                    "--detail-output", str(detail_json),
                ]
                self._run_core(analysis_args, "3/4 统计新增岗位")
            else:
                self.log("没有新增岗位或已配置跳过 JD，本次不访问详情页")

            latest_json = task_dir / "latest_new_jobs.json"
            latest_csv = task_dir / "latest_new_jobs.csv"
            shutil.copy2(new_json, latest_json)
            shutil.copy2(new_csv, latest_csv)
            if latest_detail_csv:
                shutil.copy2(latest_detail_csv, latest_detail_path)
                latest_detail_csv = latest_detail_path
            else:
                latest_detail_path.unlink(missing_ok=True)
            self._stop_browser_if_requested()
            result = RunResult(
                raw_total=int(raw_payload.get("total", stats["raw_total"])),
                filtered_total=stats["filtered_total"],
                repeated_total=stats["repeated_total"],
                new_total=stats["new_total"],
                detail_total=detail_count,
                task_dir=task_dir,
                history_file=history_file,
                raw_json=raw_json,
                latest_json=latest_json,
                latest_csv=latest_csv,
                latest_detail_csv=latest_detail_csv,
                fingerprint_changed=bool(stats.get("fingerprint_changed")),
                log_file=log_file,
            )
            self.log(f"采集完成：新增 {result.new_total}，详情 {result.detail_total}")
            return result
        except (RunnerError, PipelineError, OSError, json.JSONDecodeError) as exc:
            # A failed optional JD stage should not permanently consume jobs from history.
            if detail_stage_attempted and not detail_stage_succeeded and history_file.exists():
                if history_backup is None:
                    history_file.unlink()
                else:
                    history_file.write_bytes(history_backup)
            code = getattr(exc, "code", "collector_failed")
            if isinstance(exc, PipelineError):
                code = exc.code
            raise RunnerError(code, str(exc)) from exc
        finally:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("\n".join(self.log_messages) + "\n", encoding="utf-8")
