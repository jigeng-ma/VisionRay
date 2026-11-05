@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "VISIONRAY_EMBEDDED=%~f0"
if /i "%~1"=="-CheckOnly" set "VISIONRAY_CHECKONLY=-CheckOnly"
set "VISIONRAY_LOG=%TEMP%\setup_environment.log"
set "VISIONRAY_TEMP_PS=%TEMP%\setup_environment_%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:VISIONRAY_EMBEDDED,[Text.Encoding]::UTF8); $m=':: POWERSHELL_START'; [IO.File]::WriteAllText($env:VISIONRAY_TEMP_PS,$s.Substring($s.LastIndexOf($m)+$m.Length),(New-Object System.Text.UTF8Encoding($true)))"
if errorlevel 1 (echo Could not load embedded script. & pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%VISIONRAY_TEMP_PS%" %VISIONRAY_CHECKONLY%
set "VISIONRAY_RC=%ERRORLEVEL%"
del /q "%VISIONRAY_TEMP_PS%" >nul 2>&1
echo.
echo Log: %VISIONRAY_LOG%
if not "%VISIONRAY_RC%"=="0" echo Failed. Exit code: %VISIONRAY_RC%
if not defined VISIONRAY_NO_PAUSE pause
exit /b %VISIONRAY_RC%
:: POWERSHELL_START
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:VISIONRAY_LOG) { Start-Transcript -Path $env:VISIONRAY_LOG -Force | Out-Null }
$root = if ($env:VISIONRAY_EMBEDDED) { Split-Path -Parent $env:VISIONRAY_EMBEDDED }
        else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location -LiteralPath $root
$missing = [Collections.Generic.List[string]]::new()

function Command-Path([string]$name) {
    $item = Get-Command $name -ErrorAction SilentlyContinue
    if ($item) { return $item.Source }
    return $null
}
function Report([string]$name, [bool]$ok, [string]$detail) {
    if ($ok) { Write-Host "$name OK" }
}
function Invoke-Quiet([string]$exe, [string[]]$arguments) {
    try { & $exe @arguments *> $null; return $LASTEXITCODE }
    catch { return 1 }
}
function Try-Winget([string]$id) {
    if ($CheckOnly -or -not (Command-Path 'winget')) { return }
    Write-Host "安装 $id 中..."
    $result = Invoke-Quiet (Command-Path 'winget') @('install','--id',$id,'--exact','--source','winget','--accept-package-agreements','--accept-source-agreements','--silent')
    if ($result -ne 0) { Write-Host "$id 自动安装失败。" }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
}
function Python-Path {
    $local = Join-Path $root '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    $py = Command-Path 'py'
    if ($py) {
        try {
            & $py -3.11 -c 'import sys; assert sys.version_info >= (3,11)' 2>$null
            if ($LASTEXITCODE -eq 0) { return "$py -3.11" }
        } catch { }
    }
    $python = Command-Path 'python'
    if ($python) {
        try {
            & $python -c 'import sys; assert sys.version_info >= (3,11)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $python }
        } catch { }
    }
    return $null
}
function Installed-Drivers([string]$appiumPath) {
    if (-not $appiumPath) { return '' }
    $ErrorActionPreference = 'Continue'
    return (& $appiumPath driver list --installed 2>&1 | Out-String)
}

Write-Host '检查 VisionRay 运行环境中...'
if ($CheckOnly) { Write-Host '只检查模式。' }

$python = Python-Path
if (-not $python) {
    Try-Winget 'Python.Python.3.11'
    $python = Python-Path
}
Report 'Python 3.11+' ([bool]$python) 'https://www.python.org/downloads/windows/'
if (-not $python) { $missing.Add('Python 3.11+：https://www.python.org/downloads/windows/') }

if ($python -and (Test-Path -LiteralPath (Join-Path $root 'requirements.txt'))) {
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    if (-not $CheckOnly -and -not (Test-Path -LiteralPath $venvPython)) {
        if ($python -like '* -3.11') { & ($python -replace ' -3.11$', '') -3.11 -m venv .venv }
        else { & $python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
    }
    if (Test-Path -LiteralPath $venvPython) {
        if (-not $CheckOnly) {
            Write-Host '安装 Python 依赖中...'
            $result = Invoke-Quiet $venvPython @('-m','pip','install','--disable-pip-version-check','--timeout','10','--retries','1','-q','-r','requirements.txt')
            if ($result -ne 0) { $missing.Add('Python 依赖安装失败：请检查网络或 pip 错误') }
        }
        $packagesOk = $false
        try {
            & $venvPython -c 'import pytest, appium, PIL' 2>$null
            $packagesOk = $LASTEXITCODE -eq 0
        } catch { }
        Report 'Python 依赖' $packagesOk 'requirements.txt / .venv'
        if (-not $packagesOk -and -not ($missing | Where-Object { $_ -like 'Python 依赖安装失败*' })) {
            $missing.Add('Python 依赖：运行 .venv\Scripts\python.exe -m pip install -r requirements.txt')
        }
    } else {
        Report 'Python 依赖' $false '尚未创建 .venv'
        $missing.Add('Python 依赖：运行本脚本安装')
    }
}

$java = Command-Path 'java'
$javac = Command-Path 'javac'
if (-not $java -and $env:JAVA_HOME) {
    $candidate = Join-Path $env:JAVA_HOME 'bin\java.exe'
    if (Test-Path -LiteralPath $candidate) { $java = $candidate }
}
if (-not $javac -and $env:JAVA_HOME) {
    $candidate = Join-Path $env:JAVA_HOME 'bin\javac.exe'
    if (Test-Path -LiteralPath $candidate) { $javac = $candidate }
}
if (-not $java -or -not $javac) {
    Try-Winget 'EclipseAdoptium.Temurin.17.JDK'
    $java = Command-Path 'java'
    $javac = Command-Path 'javac'
}
Report 'Java JDK' ([bool]($java -and $javac)) 'https://adoptium.net/temurin/releases/?version=17&os=windows'
if (-not $java -or -not $javac) { $missing.Add('Java JDK：https://adoptium.net/temurin/releases/?version=17&os=windows') }

$node = Command-Path 'node'
$npm = Command-Path 'npm.cmd'
if (-not $node -or -not $npm) { Try-Winget 'OpenJS.NodeJS.LTS'; $node = Command-Path 'node'; $npm = Command-Path 'npm.cmd' }
Report 'Node.js / npm' ([bool]($node -and $npm)) 'https://nodejs.org/en/download'
if (-not $node -or -not $npm) { $missing.Add('Node.js LTS：https://nodejs.org/en/download') }

$sdk = @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME) | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'platform-tools\adb.exe')) } | Select-Object -First 1
if (-not $sdk -and (Test-Path -LiteralPath 'configs\environment.json')) {
    $configured = (Get-Content 'configs\environment.json' -Raw | ConvertFrom-Json).android_sdk
    if ($configured -and (Test-Path -LiteralPath (Join-Path $configured 'platform-tools\adb.exe'))) { $sdk = $configured }
}
$adb = Command-Path 'adb'
if (-not $sdk -and $adb -and (Split-Path $adb -Leaf) -eq 'adb.exe' -and
    (Split-Path (Split-Path $adb -Parent) -Leaf) -eq 'platform-tools') {
    $sdk = Split-Path (Split-Path $adb -Parent) -Parent
}
if (-not $sdk -and -not $CheckOnly) {
    try {
        Write-Host '下载 Android Platform-Tools 中...'
        $sdk = Join-Path $root '.tools\android-sdk'
        New-Item -ItemType Directory -Force $sdk | Out-Null
        $zip = Join-Path $env:TEMP 'visionray-platform-tools-windows.zip'
        Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $sdk -Force
        Remove-Item -LiteralPath $zip -Force
        if (-not (Test-Path -LiteralPath (Join-Path $sdk 'platform-tools\adb.exe'))) { throw '压缩包中没有 adb.exe' }
        [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $sdk, 'User')
        $env:ANDROID_SDK_ROOT = $sdk
        $env:Path = (Join-Path $sdk 'platform-tools') + ';' + $env:Path
        $adb = Command-Path 'adb'
    } catch {
        $sdk = $null
        Write-Host "ADB 自动安装失败：$($_.Exception.Message)"
    }
}
Report 'Android SDK Platform-Tools / ADB' ([bool]($sdk -and $adb)) 'https://developer.android.com/tools/releases/platform-tools'
if (-not $sdk -or -not $adb) { $missing.Add('ADB：https://developer.android.com/tools/releases/platform-tools') }

if ($node -and $npm) {
    $appium = Command-Path 'appium.cmd'
    if (-not $appium -and -not $CheckOnly) {
        Write-Host '安装 Appium 中...'
        $result = Invoke-Quiet $npm @('install','-g','appium','--fetch-retries=1','--fetch-timeout=30000')
        if ($result -ne 0) { Write-Host 'Appium 自动安装失败。' }
        $appium = Command-Path 'appium.cmd'
    }
    if ($appium -and -not $CheckOnly) {
        $drivers = Installed-Drivers $appium
        if ($drivers -notmatch 'uiautomator2') {
            Write-Host '安装 UiAutomator2 中...'
            $result = Invoke-Quiet $appium @('driver','install','uiautomator2')
            if ($result -ne 0) { Write-Host 'UiAutomator2 驱动安装失败。' }
        }
    }
    $drivers = Installed-Drivers $appium
    $ready = [bool]($appium -and $drivers -match 'uiautomator2')
    Report 'Appium / UiAutomator2' $ready 'https://appium.io/docs/en/latest/quickstart/install/'
    if (-not $ready) { $missing.Add('Appium / UiAutomator2：npm install -g appium；appium driver install uiautomator2') }
}

if (-not (Command-Path 'ffprobe')) { Write-Host '可选：视频检查需 FFmpeg（https://ffmpeg.org/download.html）' }
if (-not (Command-Path 'tesseract')) { Write-Host '可选：图片文字检查需 Tesseract（https://github.com/UB-Mannheim/tesseract/wiki）' }
if ($missing.Count) {
    Write-Host "`n需要处理："
    $missing | ForEach-Object { Write-Host "- $_" }
    exit 1
}
Write-Host "`n核心环境检查通过。连接手机并授权 USB 调试后，可运行 启动Windows测试工作台.cmd。"
