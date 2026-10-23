"""Local filtering, history deduplication, and CSV/JSON output."""
from __future__ import annotations

import copy
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    DETAIL_FIELDS, FILTER_KEYS, LIST_FIELDS, atomic_write_json, load_json,
)

LIST_CN = {
    "job_id": "岗位ID", "title": "岗位名称", "salary": "薪资", "salary_source": "薪资来源",
    "location": "工作地点", "tags": "经验/学历", "boss_name": "公司", "boss_title": "招聘者身份",
    "boss_active_status": "招聘者活跃状态", "company_scale": "公司规模", "company_stage": "融资阶段",
    "company_industry": "行业", "job_labels": "岗位标签", "skills": "技能标签",
    "job_link": "岗位链接", "company_link": "公司链接", "welfare": "福利", "is_new": "本次新增",
    "security_id": "securityId", "lid": "lid", "encrypt_job_id": "加密岗位ID",
    "encrypt_boss_id": "加密招聘者ID", "encrypt_brand_id": "加密公司ID",
}
DETAIL_CN = {
    "job_id": "岗位ID", "title": "岗位名称", "company": "公司", "salary": "薪资",
    "salary_source": "薪资来源", "location": "工作地点", "boss_active_status": "招聘者活跃状态",
    "tags_list": "经验/学历", "job_link": "岗位链接", "link": "岗位链接(备用)",
    "skill_tags": "技能标签", "jd": "职位描述(JD)",
}


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_jobs(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {}, data
    if not isinstance(data, dict):
        raise PipelineError("invalid_list_file", "列表文件结构异常")
    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        raise PipelineError("invalid_list_file", "列表文件 jobs 不是数组")
    meta = {key: value for key, value in data.items() if key != "jobs"}
    return meta, jobs


def load_details(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise PipelineError("invalid_detail_file", "详情文件必须是 JSON 数组")
    return data


def keep_title(title: str, include: list[str], exclude: list[str]) -> bool:
    text = (title or "").lower()
    if include and not any(keyword.lower() in text for keyword in include if keyword):
        return False
    if exclude and any(keyword.lower() in text for keyword in exclude if keyword):
        return False
    return True


def filter_jobs(jobs: list[dict[str, Any]], include: list[str], exclude: list[str]) -> list[dict[str, Any]]:
    return [job for job in jobs if keep_title(str(job.get("title", "")), include, exclude)]


def stringify(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str], cn_map: dict[str, str], chinese: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [cn_map.get(field, field) if chinese else field for field in fields]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([stringify(row.get(field, "")) for field in fields])


def build_fingerprint(meta: dict[str, Any], keyword: str, city: str, filters: dict[str, str]) -> dict[str, str]:
    return {
        "keyword": str(meta.get("keyword") or keyword or ""),
        "city": str(meta.get("city") or city or ""),
        **{key: str(filters.get(key, "")) for key in FILTER_KEYS},
    }


def apply_history(jobs: list[dict[str, Any]], history_file: Path, fingerprint: dict[str, str], changed_policy: str) -> tuple[list[dict[str, Any]], int, int, bool]:
    history_file = Path(history_file)
    history = load_json(history_file, {})
    if not isinstance(history, dict):
        history = {}
    jobs_map = history.get("jobs") if isinstance(history.get("jobs"), dict) else {}
    seen = {str(item) for item in history.get("seen_job_ids", []) if item}
    previous = history.get("search_fingerprint") if isinstance(history.get("search_fingerprint"), dict) else None
    changed = bool(previous and previous != fingerprint)
    if changed and changed_policy == "stop":
        changes = []
        for key in sorted(set(fingerprint) | set(previous)):
            old = previous.get(key, "")
            new = fingerprint.get(key, "")
            if old != new:
                changes.append(f"{key}: {old or '空'} -> {new or '空'}")
        raise PipelineError("search_fingerprint_changed", "搜索条件与历史库不一致：" + "；".join(changes))

    new_jobs: list[dict[str, Any]] = []
    repeated = 0
    timestamp = now_iso()
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        marked = copy.deepcopy(job)
        if job_id and (job_id in seen or job_id in jobs_map):
            marked["is_new"] = False
            repeated += 1
            is_first = False
        else:
            marked["is_new"] = True
            new_jobs.append(marked)
            is_first = True
        if job_id:
            existing = jobs_map.get(job_id, {})
            if not isinstance(existing, dict):
                existing = {}
            seen.add(job_id)
            jobs_map[job_id] = {
                "job_id": job_id,
                "title": job.get("title", ""),
                "salary": job.get("salary", ""),
                "location": job.get("location", ""),
                "boss_name": job.get("boss_name", ""),
                "job_link": job.get("job_link", ""),
                "first_seen_at": existing.get("first_seen_at") or timestamp,
                "last_seen_at": timestamp,
                "seen_count": int(existing.get("seen_count") or 0) + (1 if is_first else 0),
            }
    updated = {
        "created_at": history.get("created_at") or timestamp,
        "last_run_at": timestamp,
        "search_fingerprint": fingerprint,
        "seen_job_ids": sorted(seen),
        "jobs": jobs_map,
    }
    atomic_write_json(history_file, updated)
    return new_jobs, repeated, len(seen), changed


def process_list_file(
    list_input: Path, json_out: Path, list_csv: Path, history_file: Path,
    task_name: str, config_name: str, keyword: str, city: str, filters: dict[str, str],
    include_keywords: list[str], exclude_keywords: list[str], fields: list[str],
    chinese_headers: bool, history_enabled: bool, changed_policy: str,
) -> dict[str, Any]:
    meta, raw_jobs = load_jobs(Path(list_input))
    kept = filter_jobs(raw_jobs, include_keywords, exclude_keywords)
    fingerprint = build_fingerprint(meta, keyword, city, filters)
    warning_changed = False
    if history_enabled:
        new_jobs, repeated, history_total, warning_changed = apply_history(
            kept, Path(history_file), fingerprint, changed_policy
        )
    else:
        new_jobs = [copy.deepcopy(job) for job in kept]
        for job in new_jobs:
            job["is_new"] = True
        repeated = 0
        history_total = 0
    write_csv(Path(list_csv), new_jobs, fields, LIST_CN, chinese_headers)
    payload = dict(meta)
    payload.update({
        "source_file": str(Path(list_input).resolve()),
        "task_name": task_name,
        "config_file": config_name,
        "title_include": include_keywords,
        "title_exclude": exclude_keywords,
        "export_fields": fields,
        "total": len(new_jobs),
        "filtered_total": len(kept),
        "jobs": new_jobs,
    })
    atomic_write_json(Path(json_out), payload)
    return {
        "raw_total": len(raw_jobs),
        "filtered_total": len(kept),
        "new_total": len(new_jobs),
        "repeated_total": repeated,
        "history_total": history_total,
        "fingerprint_changed": warning_changed,
        "new_json": Path(json_out),
        "new_csv": Path(list_csv),
    }


def process_details_file(
    list_input: Path, detail_input: Path, detail_csv: Path, fields: list[str], chinese_headers: bool
) -> dict[str, Any]:
    _, new_jobs = load_jobs(Path(list_input))
    details = load_details(Path(detail_input))
    new_ids = {str(job.get("job_id")) for job in new_jobs if job.get("job_id")}
    kept = [detail for detail in details if str(detail.get("job_id")) in new_ids]
    write_csv(Path(detail_csv), kept, fields, DETAIL_CN, chinese_headers)
    return {"detail_total": len(kept), "detail_csv": Path(detail_csv)}
