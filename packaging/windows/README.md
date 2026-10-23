# BOSS 采集助手 Windows 独立工具

## 安装

- `BossCollector-Setup-*.exe`：当前用户安装，不需要管理员权限，会创建开始菜单和可选桌面快捷方式。
- `BossCollector-portable-*.zip`：解压后双击 `BossCollector.exe`；目录中的 `PORTABLE` 标记会让配置、历史和采集结果都写入软件旁边的 `data/` 文件夹。

卸载程序不会删除 `%LOCALAPPDATA%\\BossCollector` 和 `Documents\\BossCollector` 中的用户数据。

## 首次使用

1. 打开软件后阅读并确认低频、合规使用提示。
2. 点击“检测浏览器”，电脑需要安装 Microsoft Edge 或 Google Chrome。
3. 点击“启动并登录”，在弹出的专用浏览器中手动登录 BOSS。
4. 点击“检查登录”。出现短信、滑块或安全校验时，在专用浏览器中手动完成，本工具不会绕过验证。
5. 新建任务，首次建议 1 页、不抓 JD 或 JD 上限 2。
6. 点击“开始采集”，完成后可直接打开最新 CSV/JSON，或打开结果目录查看 `latest_new_jobs.csv`。

## 数据位置

安装版：

- 配置：`%LOCALAPPDATA%\\BossCollector\\`
- 结果：`%USERPROFILE%\\Documents\\BossCollector\\tasks\\<任务ID>\\`
- 专用浏览器登录态：`%USERPROFILE%\\.boss-zhipin-scraper\\chrome-profile\\`

便携版：

- 全部业务数据位于软件目录的 `data/` 文件夹；专用浏览器登录态位于 `data\browser-home\.boss-zhipin-scraper\`。

每个任务包含 `history/`、`raw/`、`new/`、`details/` 和 `logs/`。同一任务重复运行会按 BOSS `job_id` 去重，只把新岗位写入最新结果。

## 风控与合规边界

- 不保存、代填或上传 BOSS 账号密码。
- 不绕过验证码、短信、滑块或访问控制。
- 不使用代理池、指纹伪造或高频重试。
- 出现安全验证时停止自动流程，由用户手动处理。
- 默认建议低频运行；搜索条件长期变化时新建任务，避免混用历史库。

## 故障排查

- “未登录或安全验证”：重新点击“启动并登录”，在专用浏览器完成登录或验证后再运行。
- “找不到浏览器”：安装 Edge 或 Chrome；软件不会捆绑浏览器。
- 端口冲突：在右上角更换 CDP 端口。
- SmartScreen 未知发布者：第一版未做代码签名，正式大规模分发前建议购买并接入 Windows 代码签名证书。

## 从源码构建 Windows 包

在 Windows 10/11 x64 或 GitHub Actions `windows-latest` 上执行：

```powershell
uv sync --frozen --extra desktop --extra build
uv run python -m unittest discover -s tests
uv run powershell -ExecutionPolicy Bypass -File ./scripts/build_windows.ps1 -Version 0.1.0
```

产物位于 `dist/artifacts/`：

- `BossCollector-Setup-v0.1.0.exe`
- `BossCollector-portable-v0.1.0.zip`

真实 BOSS 登录和采集不进入 CI，只在干净 Windows 机器上人工验收。
