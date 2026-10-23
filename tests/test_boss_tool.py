import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BossToolTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    def tearDown(self):
        sys.path.remove(str(Path(__file__).resolve().parents[1]))
        self.tmp.cleanup()

    def test_task_config_defaults_are_low_frequency_and_valid(self):
        from boss_tool.config import TaskConfig, validate_task_data

        data = validate_task_data({"name": "GEO上海", "keyword": "GEO优化师", "city": "上海"})
        config = TaskConfig.from_dict(data)

        self.assertEqual(config.name, "GEO上海")
        self.assertEqual(config.pages, 1)
        self.assertFalse(config.fetch_detail)
        self.assertEqual(config.max_details, 2)
        self.assertTrue(config.chinese_header)
        self.assertFalse(config.close_chrome)
        self.assertEqual(config.changed_policy, "warn")

    def test_task_config_rejects_unsafe_values(self):
        from boss_tool.config import validate_task_data, ConfigValidationError

        with self.assertRaises(ConfigValidationError):
            validate_task_data({"name": "", "keyword": "GEO", "city": "上海"})
        with self.assertRaises(ConfigValidationError):
            validate_task_data({"name": "任务", "keyword": "GEO", "city": "上海", "pages": 11})
        with self.assertRaises(ConfigValidationError):
            validate_task_data({"name": "任务", "keyword": "GEO", "city": "上海", "scale": "abc"})
        with self.assertRaises(ConfigValidationError):
            validate_task_data({"name": "任务", "keyword": "GEO", "city": "上海", "fetch_detail": "yes"})
        with self.assertRaises(ConfigValidationError):
            validate_task_data({"name": "../escape", "keyword": "GEO", "city": "上海"})

    def test_task_store_creates_updates_and_keeps_independent_records(self):
        from boss_tool.config import AppPaths, TaskStore

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        store = TaskStore(paths)
        first = store.create({"name": "上海AI", "keyword": "AI Agent", "city": "上海"})
        second = store.create({"name": "北京Java", "keyword": "Java", "city": "北京"})

        self.assertNotEqual(first.id, second.id)
        self.assertTrue(store.path.exists())
        updated = store.update(first.id, {"pages": 2, "title_exclude": ["销售"]})
        self.assertEqual(updated.config.pages, 2)
        self.assertEqual(updated.config.title_exclude, ["销售"])
        self.assertEqual(store.get(first.id).config.pages, 2)
        self.assertEqual(store.list()[1].config.keyword, "Java")

    def test_paths_split_state_and_documents_but_portable_uses_one_folder(self):
        from boss_tool.config import AppPaths

        installed = AppPaths(self.root / "state", self.root / "docs", portable=False)
        self.assertEqual(installed.task_dir("abc"), self.root / "docs" / "tasks" / "abc")
        self.assertEqual(installed.tasks_file, self.root / "state" / "tasks.json")

        portable_root = self.root / "stick"
        portable = AppPaths.portable(portable_root)
        self.assertTrue(portable.portable)
        self.assertEqual(portable.state_dir, portable_root / "data" / "app")
        self.assertEqual(portable.documents_dir, portable_root / "data")
        self.assertEqual(portable.task_dir("abc"), portable_root / "data" / "tasks" / "abc")

    def test_pipeline_filters_titles_and_deduplicates_across_runs(self):
        from boss_tool.pipeline import process_list_file

        raw_path = self.root / "raw.json"
        history = self.root / "history.json"
        new_json_1 = self.root / "new1.json"
        new_csv_1 = self.root / "new1.csv"
        jobs = [
            {"job_id": "1", "title": "AI产品经理", "salary": "20-30K", "job_link": "https://zhipin.com/job/1/"},
            {"job_id": "2", "title": "AI销售", "salary": "10-20K", "job_link": "https://zhipin.com/job/2/"},
            {"job_id": "3", "title": "大模型工程师", "salary": "30-50K", "job_link": "https://zhipin.com/job/3/"},
        ]
        raw_path.write_text(json.dumps({"keyword": "AI", "city": "上海", "jobs": jobs}, ensure_ascii=False), encoding="utf-8")

        first = process_list_file(
            raw_path, new_json_1, new_csv_1, history,
            task_name="ai_sh", config_name="ai_sh.json",
            keyword="AI", city="上海", filters={},
            include_keywords=[], exclude_keywords=["销售"],
            fields=["title", "salary", "job_link", "is_new"],
            chinese_headers=True, history_enabled=True, changed_policy="warn",
        )
        self.assertEqual(first["raw_total"], 3)
        self.assertEqual(first["filtered_total"], 2)
        self.assertEqual(first["new_total"], 2)
        self.assertEqual(first["repeated_total"], 0)
        with new_csv_1.open(encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["岗位名称", "薪资", "岗位链接", "本次新增"])

        new_json_2 = self.root / "new2.json"
        new_csv_2 = self.root / "new2.csv"
        second = process_list_file(
            raw_path, new_json_2, new_csv_2, history,
            task_name="ai_sh", config_name="ai_sh.json",
            keyword="AI", city="上海", filters={},
            include_keywords=[], exclude_keywords=["销售"],
            fields=["title", "salary", "job_link", "is_new"],
            chinese_headers=True, history_enabled=True, changed_policy="warn",
        )
        self.assertEqual(second["new_total"], 0)
        self.assertEqual(second["repeated_total"], 2)

    def test_pipeline_warns_when_search_fingerprint_changes(self):
        from boss_tool.pipeline import process_list_file

        raw = self.root / "raw.json"
        raw.write_text(json.dumps({"jobs": [{"job_id": "1", "title": "AI"}]}, ensure_ascii=False), encoding="utf-8")
        kwargs = dict(
            list_input=raw, list_csv=self.root / "a.csv", json_out=self.root / "a.json",
            history_file=self.root / "h.json", task_name="t", config_name="t.json",
            include_keywords=[], exclude_keywords=[], fields=["title"], chinese_headers=False,
            history_enabled=True, changed_policy="warn",
        )
        process_list_file(keyword="AI", city="上海", filters={}, **kwargs)
        result = process_list_file(keyword="Java", city="上海", filters={}, **kwargs)
        self.assertTrue(result["fingerprint_changed"])

    def test_pipeline_stops_when_search_fingerprint_changes(self):
        from boss_tool.pipeline import process_list_file, PipelineError

        raw = self.root / "raw.json"
        raw.write_text(json.dumps({"jobs": [{"job_id": "1", "title": "AI"}]}, ensure_ascii=False), encoding="utf-8")
        kwargs = dict(
            list_input=raw, list_csv=self.root / "a.csv", json_out=self.root / "a.json",
            history_file=self.root / "h.json", task_name="t", config_name="t.json",
            include_keywords=[], exclude_keywords=[], fields=["title"], chinese_headers=False,
            history_enabled=True, changed_policy="stop",
        )
        process_list_file(keyword="AI", city="上海", filters={}, **kwargs)
        with self.assertRaises(PipelineError):
            process_list_file(keyword="Java", city="上海", filters={}, **kwargs)

    def _fake_core_script(self, mode="ok"):
        path = self.root / "fake_core.py"
        path.write_text(
            """
import csv, json, sys
args = sys.argv[1:]
if '--check' in args:
    if mode == 'security':
        print('_security_check 需要人工验证')
        sys.exit(2)
    sys.exit(0)
if '--input' in args:
    if mode == 'detail_failed':
        print('详情抓取失败')
        sys.exit(3)
    if mode == 'detail_ok':
        detail_out = Path(args[args.index('--detail-output') + 1])
        input_path = Path(args[args.index('--input') + 1])
        jobs = json.loads(input_path.read_text(encoding='utf-8'))['jobs']
        details = [{'job_id': job['job_id'], 'title': job['title'], 'company': '测试公司', 'jd': '职位描述'} for job in jobs[:1]]
        detail_out.write_text(json.dumps(details, ensure_ascii=False), encoding='utf-8')
    sys.exit(0)
if mode == 'empty':
    sys.exit(0)
out = Path(args[args.index('--output') + 1]) if '--output' in args else None
if out:
    jobs = [
        {'job_id': '1', 'title': 'AI工程师', 'salary': '20-30K', 'job_link': 'https://zhipin.com/job/1/'},
        {'job_id': '2', 'title': 'AI产品经理', 'salary': '30-40K', 'job_link': 'https://zhipin.com/job/2/'},
    ]
    payload = {'keyword': 'AI', 'city': '上海', 'total': len(jobs), 'jobs': jobs}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    with out.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f); writer.writerow(['岗位名称']); writer.writerows([[j['title']] for j in jobs])
sys.exit(0)
""".replace("mode = 'ok'", f"mode = {mode!r}").replace("from pathlib import Path", "from pathlib import Path")
            , encoding="utf-8")
        # Ensure the fake imports Path before use.
        text = path.read_text(encoding="utf-8")
        text = text.replace("import csv, json, sys\n", "import csv, json, sys\nfrom pathlib import Path\nmode = " + repr(mode) + "\n")
        path.write_text(text, encoding="utf-8")
        return lambda args: [sys.executable, str(path), *args]

    def test_runner_executes_four_stage_flow_and_updates_history(self):
        from boss_tool.config import AppPaths, Settings, TaskConfig
        from boss_tool.runner import CollectorRunner

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        paths.ensure()
        config = TaskConfig(name="AI上海", keyword="AI", city="上海")
        runner = CollectorRunner(paths, Settings(), core_command_builder=self._fake_core_script())
        result = runner.run("ai_sh", config)

        self.assertEqual(result.raw_total, 2)
        self.assertEqual(result.new_total, 2)
        self.assertEqual(result.repeated_total, 0)
        self.assertTrue(result.latest_csv.exists())
        second = runner.run("ai_sh", config)
        self.assertEqual(second.new_total, 0)
        self.assertEqual(second.repeated_total, 2)
        self.assertIn("历史去重", "\n".join(runner.log_messages))

    def test_runner_accepts_successful_zero_result_list(self):
        from boss_tool.config import AppPaths, Settings, TaskConfig
        from boss_tool.runner import CollectorRunner

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        runner = CollectorRunner(paths, Settings(), core_command_builder=self._fake_core_script("empty"))
        result = runner.run("empty_jobs", TaskConfig(name="空结果", keyword="不存在", city="上海", analysis=False))

        self.assertEqual(result.raw_total, 0)
        self.assertEqual(result.new_total, 0)
        self.assertTrue(result.raw_json.exists())
        self.assertTrue(result.latest_json.exists())
        self.assertTrue(result.latest_csv.exists())

    def test_runner_uses_json_raw_output_and_closes_browser_once(self):
        from boss_tool.config import AppPaths, Settings, TaskConfig
        from boss_tool.runner import CollectorRunner

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        calls = []
        script = self._fake_core_script()
        def builder(args):
            calls.append(args)
            return script(args)
        config = TaskConfig(name="AI上海", keyword="AI", city="上海", close_chrome=True)
        CollectorRunner(paths, Settings(browser="edge"), core_command_builder=builder).run("close_browser", config)

        self.assertTrue(any(arg == "--stop-edge" for args in calls for arg in args))
        self.assertFalse(any("--close-chrome" in args for args in calls))
        self.assertIn("--format", calls[1])
        self.assertEqual(calls[1][calls[1].index("--format") + 1], "json")

    def test_failed_detail_stage_rolls_back_history_for_retry(self):
        from boss_tool.config import AppPaths, Settings, TaskConfig
        from boss_tool.runner import CollectorRunner, RunnerError

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        paths.ensure()
        config = TaskConfig(name="AI详情", keyword="AI", city="上海", fetch_detail=True, max_details=1, analysis=False)
        failed = CollectorRunner(paths, Settings(), core_command_builder=self._fake_core_script("detail_failed"))
        with self.assertRaises(RunnerError):
            failed.run("detail_retry", config)
        history = paths.task_dir("detail_retry") / "history" / "detail_retry_history.json"
        self.assertFalse(history.exists())

        ok = CollectorRunner(paths, Settings(), core_command_builder=self._fake_core_script("detail_ok"))
        result = ok.run("detail_retry", config)
        self.assertEqual(result.new_total, 2)
        self.assertEqual(result.detail_total, 1)
        self.assertTrue(result.latest_detail_csv.exists())

    def test_runner_reports_login_or_security_gate_without_retrying(self):
        from boss_tool.config import AppPaths, Settings, TaskConfig
        from boss_tool.runner import CollectorRunner, RunnerError

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        paths.ensure()
        runner = CollectorRunner(paths, Settings(), core_command_builder=self._fake_core_script("security"))
        with self.assertRaises(RunnerError) as ctx:
            runner.run("secure", TaskConfig(name="secure", keyword="AI", city="上海"))
        self.assertEqual(ctx.exception.code, "login_or_security_check_required")

    def test_panel_url_keeps_token_in_fragment(self):
        from boss_tool.app import panel_url

        url = panel_url(17890, "abc-token")
        self.assertEqual(url, "http://127.0.0.1:17890/#token=abc-token")

    def test_portable_core_environment_redirects_browser_profile(self):
        from unittest import mock
        from boss_tool.config import AppPaths
        from boss_tool.browser import core_environment

        portable = AppPaths.portable(self.root / "stick")
        with mock.patch("os.name", "nt"):
            env = core_environment(portable)
        self.assertEqual(env["USERPROFILE"], str(self.root / "stick" / "data" / "browser-home"))
        self.assertTrue((self.root / "stick" / "data" / "browser-home").exists())

    def test_browser_commands_prefer_edge_and_can_stop(self):
        from boss_tool.config import AppPaths, Settings
        from boss_tool.browser import BrowserController, core_environment

        calls = []
        def popen(cmd, **kwargs):
            calls.append(cmd)
            class Proc:
                returncode = 0
                def terminate(self): pass
                def wait(self, timeout=None): return 0
            return Proc()
        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        controller = BrowserController(command_builder=lambda args: ["fake-core", *args], popen=popen, environment=core_environment(paths))
        controller.start(Settings(browser="edge", cdp_port=9333), wait_login=False)
        controller.stop(Settings(browser="edge"))
        self.assertIn(["fake-core", "--setup-edge", "--cdp-port", "9333", "--no-wait-login"], calls)
        self.assertIn(["fake-core", "--stop-edge"], calls)


@unittest.skipUnless(__import__("importlib.util").util.find_spec("flask"), "Flask is required for API tests")
class ServerApiTestCase(unittest.TestCase):
    setUp = BossToolTestCase.setUp
    tearDown = BossToolTestCase.tearDown


    def test_api_task_crud_and_run_with_token(self):
        from boss_tool.config import AppPaths, SettingsStore, TaskStore
        from boss_tool.server import create_app

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        paths.ensure()
        class FakeBrowser:
            class Proc: pid = 123
            def start(self, settings, wait_login=True): return self.Proc()
            def stop(self, settings): return None
        class FakeRunManager:
            def start(self, task_id): return {"status": "queued", "task_id": task_id}, 202
        app = create_app(
            paths=paths, token="secret-token", task_store=TaskStore(paths),
            settings_store=SettingsStore(paths), browser_controller=FakeBrowser(),
            run_manager=FakeRunManager(),
        )
        client = app.test_client()

        self.assertEqual(client.get("/api/tasks").status_code, 401)
        headers = {"X-Boss-Tool-Token": "secret-token"}
        response = client.post("/api/tasks", headers=headers, json={"name": "AI上海", "keyword": "AI", "city": "上海"})
        self.assertEqual(response.status_code, 201)
        task_id = response.get_json()["id"]
        self.assertEqual(len(client.get("/api/tasks", headers=headers).get_json()["tasks"]), 1)
        self.assertEqual(client.get(f"/api/tasks/{task_id}", headers=headers).get_json()["name"], "AI上海")
        self.assertEqual(client.post(f"/api/tasks/{task_id}/run", headers=headers).status_code, 403)
        client.put("/api/settings", headers=headers, json={"accepted_compliance": True, "browser": "edge", "cdp_port": 9222})
        self.assertEqual(client.post(f"/api/tasks/{task_id}/run", headers=headers).status_code, 202)
        self.assertEqual(client.post("/api/browser/start", headers=headers).status_code, 202)

    def test_bundled_resource_uses_pyinstaller_package_layout(self):
        from unittest import mock
        from boss_tool import server

        static = self.root / "bundle" / "boss_tool" / "static"
        static.mkdir(parents=True)
        (static / "index.html").write_text("ok", encoding="utf-8")
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", self.root / "bundle", create=True):
            self.assertEqual(server.bundled_resource("static", "index.html"), static / "index.html")

    def test_missing_latest_result_returns_404_without_opening_app(self):
        from boss_tool.config import AppPaths, SettingsStore, TaskStore
        from boss_tool.server import create_app

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        store = TaskStore(paths)
        record = store.create({"name": "AI上海", "keyword": "AI", "city": "上海"})
        app = create_app(paths=paths, token="secret-token", task_store=store, settings_store=SettingsStore(paths))
        client = app.test_client()
        response = client.post(
            f"/api/tasks/{record.id}/open-result",
            headers={"X-Boss-Tool-Token": "secret-token"},
            json={"kind": "details"},
        )
        self.assertEqual(response.status_code, 404)

    def test_static_index_is_available(self):
        from boss_tool.config import AppPaths
        from boss_tool.server import create_app

        paths = AppPaths(self.root / "state", self.root / "docs", portable=False)
        app = create_app(paths=paths, token="t")
        with app.test_client().get("/") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"BOSS", response.data)


if __name__ == "__main__":
    unittest.main()
