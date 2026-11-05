@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "VISIONRAY_EMBEDDED=%~f0"
if /i "%~1"=="-Destination" set "VISIONRAY_DEST=%~2"
set "VISIONRAY_LOG=%TEMP%\download_visionray.log"
set "VISIONRAY_TEMP_PS=%TEMP%\download_visionray_%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:VISIONRAY_EMBEDDED,[Text.Encoding]::UTF8); $m=':: POWERSHELL_START'; [IO.File]::WriteAllText($env:VISIONRAY_TEMP_PS,$s.Substring($s.LastIndexOf($m)+$m.Length),(New-Object System.Text.UTF8Encoding($true)))"
if errorlevel 1 (echo Could not load embedded script. & pause & exit /b 1)
if defined VISIONRAY_DEST (powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%VISIONRAY_TEMP_PS%" -Destination "%VISIONRAY_DEST%" > "%VISIONRAY_LOG%" 2>&1) else (powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%VISIONRAY_TEMP_PS%" > "%VISIONRAY_LOG%" 2>&1)
set "VISIONRAY_RC=%ERRORLEVEL%"
del /q "%VISIONRAY_TEMP_PS%" >nul 2>&1
type "%VISIONRAY_LOG%"
echo.
echo Log: %VISIONRAY_LOG%
if not "%VISIONRAY_RC%"=="0" echo Failed. Exit code: %VISIONRAY_RC%
if not defined VISIONRAY_NO_PAUSE pause
exit /b %VISIONRAY_RC%
:: POWERSHELL_START
param([string]$Destination = (Join-Path (Get-Location).Path 'VisionRay'))
$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/jigeng-ma/VisionRay.git'
function Find-Git {
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($path in @("$env:ProgramFiles\Git\cmd\git.exe",
                      "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
                      "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}
$gitExe = Find-Git
if (-not $gitExe) {
    Write-Host '未找到 Git，正在尝试自动安装...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id Git.Git --exact --source winget --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning 'winget 安装 Git 失败，尝试下载安装包。' }
        $gitExe = Find-Git
    }
    if (-not $gitExe) {
        try {
            $release = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest'
            $asset = $release.assets | Where-Object { $_.name -match '^Git-[\d.]+-64-bit\.exe$' } | Select-Object -First 1
            if (-not $asset) { throw '未找到 Windows 64 位 Git 安装包' }
            $installer = Join-Path $env:TEMP $asset.name
            Invoke-WebRequest $asset.browser_download_url -OutFile $installer
            if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
                throw 'Git 安装包数字签名校验未通过'
            }
            $process = Start-Process -FilePath $installer -ArgumentList '/VERYSILENT','/NORESTART','/NOCANCEL','/SP-' -Wait -PassThru -WindowStyle Hidden
            if ($process.ExitCode -ne 0) { throw "Git 安装程序返回 $($process.ExitCode)" }
            $gitExe = Find-Git
        } catch {
            Write-Warning "Git 自动安装失败：$($_.Exception.Message)"
        }
    }
    if (-not $gitExe) {
        Write-Error '未能自动安装 Git。请从 https://git-scm.com/install/windows 手动安装，然后重试。'
        exit 1
    }
    $env:Path = (Split-Path -Parent $gitExe) + ';' + $env:Path
    Write-Host "Git 已就绪：$gitExe"
}
$Destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath (Join-Path $Destination '.git')) {
    $origin = (& $gitExe -C $Destination remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or $origin -notmatch '(^|[:/])jigeng-ma/VisionRay(\.git)?$') {
        Write-Error "目标目录不是预期的 VisionRay 仓库：$Destination"
        exit 1
    }
    $branch = (& $gitExe -C $Destination symbolic-ref --quiet --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        Write-Error '当前仓库未处于正常分支，请先切换到需要更新的分支。'
        exit 1
    }
    $before = (& $gitExe -C $Destination rev-parse HEAD).Trim()
    $remoteLine = (& $gitExe -C $Destination ls-remote --exit-code origin "refs/heads/$branch")
    if ($LASTEXITCODE -ne 0 -or -not $remoteLine) {
        Write-Error "无法查询远端 $branch 分支。请检查网络和 GitHub 权限。"
        exit 1
    }
    $latest = ($remoteLine -split '\s+')[0]
    Write-Host "本地版本：$($before.Substring(0, 12))；远端版本：$($latest.Substring(0, 12))"
    if ($before -eq $latest) {
        Write-Host '已经是最新版本，无需下载。'
        exit 0
    }
    & $gitExe -C $Destination fetch origin "refs/heads/$branch"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $gitExe -C $Destination merge-base --is-ancestor HEAD FETCH_HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Error '本地提交与远端历史不一致，已停止自动更新；请人工检查分支。'
        exit 1
    }
    $count = (& $gitExe -C $Destination rev-list --count HEAD..FETCH_HEAD).Trim()
    Write-Host "检测到 $count 个新提交，正在增量更新。"
    & $gitExe -C $Destination merge --ff-only FETCH_HEAD
    if ($LASTEXITCODE -ne 0) {
        Write-Error '更新被本地文件改动阻止。Git 未覆盖本地文件；请处理提示的冲突文件后重试。'
        exit 1
    }
    $after = (& $gitExe -C $Destination rev-parse --short=12 HEAD).Trim()
    Write-Host "更新完成：$after（原版本 $($before.Substring(0, 12))）"
} elseif (Test-Path -LiteralPath $Destination) {
    Write-Error "目标目录已存在但不是 Git 仓库：$Destination。请指定另一个空目录。"
    exit 1
} else {
    & $gitExe clone --depth 1 --single-branch $repo $Destination
    if ($LASTEXITCODE -ne 0) {
        Write-Error '下载失败。若仓库需要权限，请先登录 GitHub 或配置 Git 凭据，再重试。'
        exit 1
    }
    $version = (& $gitExe -C $Destination rev-parse --short=12 HEAD).Trim()
    Write-Host "已下载：$Destination；版本：$version"
}
Write-Host '下一步：在项目目录运行 setup_environment.cmd。'
