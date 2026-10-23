"""Configuration and local storage paths for the desktop collector."""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


APP_NAME = "BossCollector"

DEFAULT_EXPORT_FIELDS = [
    "title", "salary", "location", "tags", "boss_name", "boss_active_status",
    "company_scale", "company_industry", "skills", "job_link", "is_new",
]
DEFAULT_DETAIL_FIELDS = ["title", "company", "salary", "location", "skill_tags", "jd", "job_link"]

FILTER_KEYS = ("scale", "stage", "salary", "experience", "degree", "industry")
FILTER_CODES = {
    "scale": {"301", "302", "303", "304", "305", "306"},
    "stage": {"801", "802", "803", "804", "805", "806", "807", "808"},
    "salary": {"402", "403", "404", "405", "406", "407"},
    "experience": {"101", "102", "103", "104", "105", "106", "107", "108"},
    "degree": {"202", "203", "204", "205", "206", "208", "209"},
    "industry": {str(i) for i in range(1001, 1011)},
}
LIST_FIELDS = {
    "job_id", "title", "salary", "salary_source", "location", "tags",
    "boss_name", "boss_title", "boss_active_status", "company_scale",
    "company_stage", "company_industry", "job_labels", "skills", "job_link",
    "company_link", "welfare", "is_new", "security_id", "lid",
    "encrypt_job_id", "encrypt_boss_id", "encrypt_brand_id",
}
DETAIL_FIELDS = {
    "job_id", "title", "company", "salary", "salary_source", "location",
    "boss_active_status", "tags_list", "job_link", "link", "skill_tags", "jd",
}
SAFE_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff .\-（）()]+$", re.UNICODE)


class ConfigValidationError(ValueError):
    """Raised when a UI/API configuration payload is invalid."""


@dataclass(frozen=True)
class AppPaths:
    state_dir: Path
    documents_dir: Path
    portable: bool = False

    @property
    def tasks_file(self) -> Path:
        return self.state_dir / "tasks.json"

    @property
    def settings_file(self) -> Path:
        return self.state_dir / "settings.json"

    @property
    def tasks_root(self) -> Path:
        return self.documents_dir / "tasks"

    def task_dir(self, task_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{3,40}", task_id):
            raise ConfigValidationError("任务 ID 不安全")
        return self.tasks_root / task_id

    def ensure(self) -> "AppPaths":
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_root.mkdir(parents=True, exist_ok=True)
        return self

    @staticmethod
    def portable(root: Path) -> "AppPaths":
        root = Path(root)
        return AppPaths(root / "data" / "app", root / "data", portable=True)


def discover_app_paths() -> AppPaths:
    override = os.environ.get("BOSS_COLLECTOR_HOME")
    if override:
        root = Path(override)
        portable_flag = os.environ.get("BOSS_COLLECTOR_PORTABLE", "").lower() in {"1", "true", "yes"}
        if portable_flag:
            return AppPaths.portable(root)
        return AppPaths(root / "app", root, portable=False)

    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        if (app_dir / "PORTABLE").exists():
            return AppPaths.portable(app_dir)

    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        documents = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
        return AppPaths(local_app / APP_NAME, documents / APP_NAME, portable=False)

    return AppPaths(
        Path.home() / ".local" / "share" / APP_NAME.lower(),
        Path.home() / "Documents" / APP_NAME,
        portable=False,
    )


@dataclass
class Settings:
    browser: str = "edge"
    cdp_port: int = 9222
    accepted_compliance: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any] | None = None) -> "Settings":
        data = data or {}
        browser = str(data.get("browser", "edge"))
        if browser not in {"auto", "edge", "chrome"}:
            raise ConfigValidationError("浏览器只能是 auto、edge 或 chrome")
        try:
            port = int(data.get("cdp_port", 9222))
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError("CDP 端口必须是数字") from exc
        if not 1024 <= port <= 65535:
            raise ConfigValidationError("CDP 端口必须在 1024-65535 之间")
        return Settings(browser=browser, cdp_port=port, accepted_compliance=bool(data.get("accepted_compliance", False)))


@dataclass
class TaskConfig:
    name: str
    keyword: str
    city: str
    pages: int = 1
    fetch_detail: bool = False
    max_details: int = 2
    format: str = "csv"
    analysis: bool = True
    close_chrome: bool = False
    allow_dom_fallback: bool = False
    scale: str = ""
    stage: str = ""
    salary: str = ""
    experience: str = ""
    degree: str = ""
    industry: str = ""
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    export_fields: list[str] = field(default_factory=lambda: list(DEFAULT_EXPORT_FIELDS))
    detail_export_fields: list[str] = field(default_factory=lambda: list(DEFAULT_DETAIL_FIELDS))
    chinese_header: bool = True
    changed_policy: str = "warn"

    def filters(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in FILTER_KEYS if getattr(self, key)}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TaskConfig":
        validated = validate_task_data(data)
        return TaskConfig(**validated)


def _clean_keywords(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part.strip() for part in re.split(r"[,，;；\n]", value)]
    if not isinstance(value, list):
        raise ConfigValidationError("关键词过滤条件必须是字符串数组")
    result = [str(item).strip() for item in value if str(item).strip()]
    if any("\x00" in item or "/" in item for item in result):
        raise ConfigValidationError("过滤词包含非法字符")
    return result


def _clean_fields(value: Any, default: list[str], allowed: set[str], label: str) -> list[str]:
    if value in (None, []):
        return list(default)
    if not isinstance(value, list):
        raise ConfigValidationError(f"{label}必须是数组")
    fields = [str(item).strip() for item in value if str(item).strip()]
    unknown = [item for item in fields if item not in allowed]
    if unknown:
        raise ConfigValidationError(f"{label}包含不支持的字段: {', '.join(unknown)}")
    return fields


def validate_task_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigValidationError("任务配置必须是对象")
    name = str(data.get("name", "")).strip()
    keyword = str(data.get("keyword", "")).strip()
    city = str(data.get("city", "")).strip()
    if not name or not SAFE_NAME_RE.fullmatch(name) or ".." in name:
        raise ConfigValidationError("任务名称必填，且只能包含中文、英文、数字、空格、下划线、短横线或括号")
    if len(name) > 60:
        raise ConfigValidationError("任务名称不能超过 60 个字符")
    if not keyword or len(keyword) > 100:
        raise ConfigValidationError("搜索关键词不能为空且不能超过 100 个字符")
    if not city or len(city) > 40:
        raise ConfigValidationError("城市不能为空且不能超过 40 个字符")
    try:
        pages = int(data.get("pages", 1))
        max_details = int(data.get("max_details", 2))
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError("页数和详情数量必须是整数") from exc
    if not 1 <= pages <= 10:
        raise ConfigValidationError("页数必须在 1-10 之间")
    if not 0 <= max_details <= 100:
        raise ConfigValidationError("详情数量必须在 0-100 之间")
    fmt = str(data.get("format", "csv"))
    if fmt not in {"json", "csv"}:
        raise ConfigValidationError("输出格式只能是 json 或 csv")
    policy = str(data.get("changed_policy", "warn"))
    if policy not in {"warn", "stop"}:
        raise ConfigValidationError("搜索条件变化策略只能是 warn 或 stop")
    for key in FILTER_KEYS:
        raw = str(data.get(key, "") or "").strip()
        if raw and not raw.isdigit():
            raise ConfigValidationError(f"{key} 必须是数字代码或空值")
        if raw and raw not in FILTER_CODES[key]:
            raise ConfigValidationError(f"{key}={raw} 不是受支持的筛选代码")
    bool_fields = ("fetch_detail", "analysis", "close_chrome", "allow_dom_fallback", "chinese_header")
    bool_values = {}
    defaults = TaskConfig(name=name, keyword=keyword, city=city)
    for key in bool_fields:
        if key not in data or data[key] is None:
            bool_values[key] = getattr(defaults, key)
        elif isinstance(data[key], bool):
            bool_values[key] = data[key]
        else:
            raise ConfigValidationError(f"{key} 必须是 true 或 false")
    result = {
        "name": name,
        "keyword": keyword,
        "city": city,
        "pages": pages,
        "fetch_detail": bool_values["fetch_detail"],
        "max_details": max_details,
        "format": fmt,
        "analysis": bool_values["analysis"],
        "close_chrome": bool_values["close_chrome"],
        "allow_dom_fallback": bool_values["allow_dom_fallback"],
        **{key: str(data.get(key, "") or "").strip() for key in FILTER_KEYS},
        "title_include": _clean_keywords(data.get("title_include")),
        "title_exclude": _clean_keywords(data.get("title_exclude")),
        "export_fields": _clean_fields(data.get("export_fields"), DEFAULT_EXPORT_FIELDS, LIST_FIELDS, "列表导出字段"),
        "detail_export_fields": _clean_fields(data.get("detail_export_fields"), DEFAULT_DETAIL_FIELDS, DETAIL_FIELDS, "详情导出字段"),
        "chinese_header": bool_values["chinese_header"],
        "changed_policy": policy,
    }
    return result


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{uuid.uuid4().hex[:8]}")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class SettingsStore:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.paths.ensure()

    def load(self) -> Settings:
        try:
            return Settings.from_dict(load_json(self.paths.settings_file, {}))
        except (json.JSONDecodeError, ConfigValidationError):
            return Settings()

    def save(self, settings: Settings) -> Settings:
        atomic_write_json(self.paths.settings_file, settings.to_dict())
        return settings


@dataclass(frozen=True)
class TaskRecord:
    id: str
    created_at: str
    updated_at: str
    config: TaskConfig

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "created_at": self.created_at, "updated_at": self.updated_at, **self.config.to_dict()}


class TaskStore:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.paths.ensure()
        self.path = paths.tasks_file
        self._records: dict[str, TaskRecord] = {}
        self._load()

    def _load(self) -> None:
        raw = load_json(self.path, {"tasks": []})
        if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
            return
        for item in raw["tasks"]:
            try:
                config = TaskConfig.from_dict(item)
                task_id = str(item["id"])
                if not re.fullmatch(r"task_[0-9a-f]{12}", task_id):
                    continue
                record = TaskRecord(task_id, item.get("created_at", now_iso()), item.get("updated_at", now_iso()), config)
                self._records[task_id] = record
            except (KeyError, TypeError, ConfigValidationError):
                continue

    def _write(self) -> None:
        atomic_write_json(self.path, {"tasks": [record.to_dict() for record in self.list()]})

    def list(self) -> list[TaskRecord]:
        return sorted(self._records.values(), key=lambda record: (record.config.name, record.id))

    def get(self, task_id: str) -> TaskRecord:
        if task_id not in self._records:
            raise KeyError(task_id)
        return self._records[task_id]

    def create(self, data: dict[str, Any]) -> TaskRecord:
        config = TaskConfig.from_dict(data)
        timestamp = now_iso()
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        record = TaskRecord(task_id, timestamp, timestamp, config)
        self._records[task_id] = record
        self.paths.task_dir(task_id).mkdir(parents=True, exist_ok=True)
        self._write()
        return record

    def update(self, task_id: str, data: dict[str, Any]) -> TaskRecord:
        existing = self.get(task_id)
        merged = {**existing.config.to_dict(), **(data or {})}
        config = TaskConfig.from_dict(merged)
        record = TaskRecord(existing.id, existing.created_at, now_iso(), config)
        self._records[task_id] = record
        self._write()
        return record

    def duplicate(self, task_id: str, new_name: str | None = None) -> TaskRecord:
        existing = self.get(task_id)
        data = existing.config.to_dict()
        data["name"] = new_name or f"{data['name']} 副本"
        return self.create(data)

    def delete(self, task_id: str) -> None:
        self.get(task_id)
        del self._records[task_id]
        self._write()
