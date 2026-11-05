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
function Add-UserPath([string]$directory) {
    if (-not $directory -or -not (Test-Path -LiteralPath $directory)) { return }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ })
    if ($entries -notcontains $directory) {
        [Environment]::SetEnvironmentVariable('Path', (($entries + $directory) -join ';'), 'User')
    }
    $env:Path = $directory + ';' + $env:Path
}
function Find-Installed([string]$file, [string[]]$roots) {
    foreach ($directory in $roots) {
        if (-not $directory -or -not (Test-Path -LiteralPath $directory)) { continue }
        $match = Get-ChildItem -LiteralPath $directory -Filter $file -File -Recurse -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($match) { return $match.FullName }
    }
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
$jdk = if ($javac -and (Test-Path -LiteralPath $javac)) { Split-Path (Split-Path $javac -Parent) -Parent } else { $null }
if (-not $jdk) {
    $jdkRoots = @("$env:ProgramFiles\Eclipse Adoptium", "${env:ProgramFiles(x86)}\Eclipse Adoptium",
                  "$env:LOCALAPPDATA\Programs\Eclipse Adoptium", (Join-Path $root '.tools\jdk17'))
    $found = Find-Installed 'javac.exe' $jdkRoots
    if ($found) { $jdk = Split-Path (Split-Path $found -Parent) -Parent }
}
if (-not $jdk) {
    Try-Winget 'EclipseAdoptium.Temurin.17.JDK'
    $found = Find-Installed 'javac.exe' $jdkRoots
    if ($found) { $jdk = Split-Path (Split-Path $found -Parent) -Parent }
}
if (-not $jdk -and -not $CheckOnly) {
    try {
        Write-Host '下载 JDK 17 中...'
        $jdkRoot = Join-Path $root '.tools\jdk17'
        New-Item -ItemType Directory -Force $jdkRoot | Out-Null
        $archive = Join-Path $env:TEMP 'visionray-jdk17.zip'
        Invoke-WebRequest 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $jdkRoot -Force
        Remove-Item -LiteralPath $archive -Force
        $found = Find-Installed 'javac.exe' @($jdkRoot)
        if (-not $found) { throw '下载包中没有 javac.exe' }
        $jdk = Split-Path (Split-Path $found -Parent) -Parent
    } catch { Write-Host "JDK 自动下载失败：$($_.Exception.Message)" }
}
if ($jdk -and (Test-Path -LiteralPath (Join-Path $jdk 'bin\java.exe'))) {
    if (-not $CheckOnly) {
        [Environment]::SetEnvironmentVariable('JAVA_HOME', $jdk, 'User')
        $env:JAVA_HOME = $jdk
        Add-UserPath (Join-Path $jdk 'bin')
    }
    $java = Join-Path $jdk 'bin\java.exe'
    $javac = Join-Path $jdk 'bin\javac.exe'
}
Report 'Java JDK' ([bool]($java -and $javac)) 'https://adoptium.net/temurin/releases/?version=17&os=windows'
if (-not $java -or -not $javac) { $missing.Add('Java JDK：https://adoptium.net/temurin/releases/?version=17&os=windows') }

$node = Command-Path 'node'
$npm = Command-Path 'npm.cmd'
if (-not $node -or -not $npm) { Try-Winget 'OpenJS.NodeJS.LTS'; $node = Command-Path 'node'; $npm = Command-Path 'npm.cmd' }
Report 'Node.js / npm' ([bool]($node -and $npm)) 'https://nodejs.org/en/download'
if (-not $node -or -not $npm) { $missing.Add('Node.js LTS：https://nodejs.org/en/download') }

$sdkCandidates = @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME,
                   (Join-Path $root '.tools\android-sdk'),
                   (Join-Path $env:LOCALAPPDATA 'Android\Sdk'),
                   [Environment]::GetEnvironmentVariable('ANDROID_SDK_ROOT', 'User'),
                   [Environment]::GetEnvironmentVariable('ANDROID_HOME', 'User'))
$sdk = $sdkCandidates | Where-Object { $_ -and (Test-Path -LiteralPath (Join-Path $_ 'platform-tools\adb.exe')) } | Select-Object -First 1
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
    } catch {
        $sdk = $null
        Write-Host "ADB 自动安装失败：$($_.Exception.Message)"
    }
}
if ($sdk) {
    $adb = Join-Path $sdk 'platform-tools\adb.exe'
    if (-not $CheckOnly) {
        [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $sdk, 'User')
        $env:ANDROID_SDK_ROOT = $sdk
        Add-UserPath (Join-Path $sdk 'platform-tools')
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

$ffprobe = Command-Path 'ffprobe'
if (-not $ffprobe) {
    $ffprobe = Find-Installed 'ffprobe.exe' @("$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
                                                "$env:ProgramFiles\FFmpeg", (Join-Path $root '.tools\ffmpeg'))
}
if (-not $ffprobe) {
    Try-Winget 'Gyan.FFmpeg'
    $ffprobe = Command-Path 'ffprobe'
    if (-not $ffprobe) { $ffprobe = Find-Installed 'ffprobe.exe' @("$env:LOCALAPPDATA\Microsoft\WinGet\Packages") }
}
if (-not $ffprobe -and -not $CheckOnly) {
    try {
        Write-Host '下载 FFmpeg 中...'
        $ffmpegRoot = Join-Path $root '.tools\ffmpeg'
        New-Item -ItemType Directory -Force $ffmpegRoot | Out-Null
        $archive = Join-Path $env:TEMP 'visionray-ffmpeg.zip'
        Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $ffmpegRoot -Force
        Remove-Item -LiteralPath $archive -Force
        $ffprobe = Find-Installed 'ffprobe.exe' @($ffmpegRoot)
        if (-not $ffprobe) { throw '下载包中没有 ffprobe.exe' }
    } catch { Write-Host "FFmpeg 自动下载失败：$($_.Exception.Message)" }
}
if ($ffprobe -and -not $CheckOnly) { Add-UserPath (Split-Path $ffprobe -Parent) }
Report 'FFmpeg / ffprobe' ([bool]$ffprobe) 'https://ffmpeg.org/download.html'
if (-not $ffprobe) { $missing.Add('FFmpeg：https://ffmpeg.org/download.html') }

$tesseract = Command-Path 'tesseract'
if (-not $tesseract) {
    $tesseract = Find-Installed 'tesseract.exe' @("$env:ProgramFiles\Tesseract-OCR",
                                                   "${env:ProgramFiles(x86)}\Tesseract-OCR",
                                                   "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
                                                   (Join-Path $root '.tools\Tesseract-OCR'))
}
if (-not $tesseract) {
    Try-Winget 'UB-Mannheim.TesseractOCR'
    $tesseract = Command-Path 'tesseract'
    if (-not $tesseract) { $tesseract = Find-Installed 'tesseract.exe' @("$env:ProgramFiles\Tesseract-OCR",
                                                            "$env:LOCALAPPDATA\Microsoft\WinGet\Packages") }
}
if (-not $tesseract -and -not $CheckOnly) {
    try {
        Write-Host '下载 Tesseract OCR 中...'
        $ocrRoot = Join-Path $root '.tools\Tesseract-OCR'
        New-Item -ItemType Directory -Force $ocrRoot | Out-Null
        $installer = Join-Path $env:TEMP 'visionray-tesseract.exe'
        Invoke-WebRequest 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe' -OutFile $installer
        Write-Host '安装 Tesseract OCR 中...'
        $process = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$ocrRoot") -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) { throw "安装程序返回 $($process.ExitCode)" }
        Remove-Item -LiteralPath $installer -Force
        $tesseract = Find-Installed 'tesseract.exe' @($ocrRoot)
        if (-not $tesseract) { throw '安装后未找到 tesseract.exe' }
    } catch { Write-Host "Tesseract 自动安装失败：$($_.Exception.Message)" }
}
if ($tesseract -and -not $CheckOnly) {
    Add-UserPath (Split-Path $tesseract -Parent)
    [Environment]::SetEnvironmentVariable('TESSERACT_CMD', $tesseract, 'User')
    $env:TESSERACT_CMD = $tesseract
}
Report 'Tesseract OCR' ([bool]$tesseract) 'https://github.com/UB-Mannheim/tesseract/wiki'
if (-not $tesseract) { $missing.Add('Tesseract OCR：https://github.com/UB-Mannheim/tesseract/wiki') }
if ($missing.Count) {
    Write-Host "`n需要处理："
    $missing | ForEach-Object { Write-Host "- $_" }
    exit 1
}
Write-Host "`n核心环境检查通过。连接手机并授权 USB 调试后，可运行 启动Windows测试工作台.cmd。"
