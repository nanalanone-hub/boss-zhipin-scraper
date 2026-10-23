param(
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Dist = Join-Path $Root "dist"
$Artifacts = Join-Path $Dist "artifacts"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $Root ".pyinstaller"
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null

python --version
python -m PyInstaller --version
python tools/generate_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

$Separator = [IO.Path]::PathSeparator
$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--paths", $Root,
    "--add-data", "data\city_codes.json$($Separator)data"
)

Write-Host "Building console core..."
$coreArgs = @(
    "-m", "PyInstaller",
    @Common,
    "--name", "boss-core",
    "--console",
    "boss_tool/core_launcher.py"
)
python @coreArgs
if ($LASTEXITCODE -ne 0) { throw "Core PyInstaller build failed" }

Write-Host "Building desktop app..."
$appArgs = @(
    "-m", "PyInstaller",
    @Common,
    "--name", "BossCollector",
    "--windowed",
    "--icon", "assets/boss-collector.ico",
    "--add-data", "boss_tool\static$($Separator)boss_tool\static",
    "--add-data", "boss_tool\task_schema.json$($Separator)boss_tool",
    "--add-data", "$(Join-Path $Dist 'boss-core')$($Separator)boss-core",
    "--collect-submodules", "waitress",
    "--collect-submodules", "pystray",
    "--collect-data", "flask",
    "packaging/desktop_launcher.py"
)
python @appArgs
if ($LASTEXITCODE -ne 0) { throw "Desktop PyInstaller build failed" }

Write-Host "Creating portable ZIP..."
$PortableRoot = Join-Path $Dist "portable/BossCollector"
if (Test-Path (Join-Path $Dist "portable")) { Remove-Item -Recurse -Force (Join-Path $Dist "portable") }
New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null
Copy-Item -Recurse -Force (Join-Path $Dist "BossCollector/*") $PortableRoot
New-Item -ItemType File -Force -Path (Join-Path $PortableRoot "PORTABLE") | Out-Null
$zip = Join-Path $Artifacts "BossCollector-portable-v$Version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $PortableRoot -DestinationPath $zip

Write-Host "Creating Inno Setup installer..."
$isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$isccPath = if ($isccCommand) { $isccCommand.Source } else { "" }
if (-not $isccPath) {
    $candidate = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) { $isccPath = $candidate }
}
if (-not $isccPath) { throw "未找到 Inno Setup Compiler (ISCC.exe)。请在 windows-latest 或已安装 Inno Setup 6 的环境构建。" }
& $isccPath "/DAppVersion=$Version" "packaging/windows/boss-collector.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $LASTEXITCODE" }

Write-Host "Artifacts:"
Get-ChildItem $Artifacts | Select-Object FullName, Length
