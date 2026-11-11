param([string]$Destination = (Join-Path (Get-Location).Path 'VisionRay'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:VISIONRAY_LOG) { Start-Transcript -Path $env:VISIONRAY_LOG -Force | Out-Null }
function Fail([string]$message) { Write-Host "失败：$message"; exit 1 }
if (-not $PSBoundParameters.ContainsKey('Destination') -and
    (Test-Path -LiteralPath (Join-Path (Get-Location).Path '.git'))) {
    $Destination = (Get-Location).Path
}
function Invoke-Quiet([string]$exe, [string[]]$arguments) {
    try { & $exe @arguments *> $null; return $LASTEXITCODE }
    catch { return 1 }
}
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
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host '下载 Git 中（Windows 包管理器）...'
        $winget = (Get-Command winget).Source
        $result = Invoke-Quiet $winget @('install','--id','Git.Git','--exact','--source','winget','--silent','--accept-package-agreements','--accept-source-agreements')
        $gitExe = Find-Git
    }
    if (-not $gitExe) {
        try {
            Write-Host '下载 Git 中（官方安装包）...'
            $release = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest'
            $asset = $release.assets | Where-Object { $_.name -match '^Git-[\d.]+-64-bit\.exe$' } | Select-Object -First 1
            if (-not $asset) { throw '未找到 Windows 64 位 Git 安装包' }
            $installer = Join-Path $env:TEMP $asset.name
            Invoke-WebRequest $asset.browser_download_url -OutFile $installer
            if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
                throw 'Git 安装包数字签名校验未通过'
            }
            Write-Host '安装 Git 中...'
            $process = Start-Process -FilePath $installer -ArgumentList '/VERYSILENT','/NORESTART','/NOCANCEL','/SP-' -Wait -PassThru -WindowStyle Hidden
            if ($process.ExitCode -ne 0) { throw "Git 安装程序返回 $($process.ExitCode)" }
            $gitExe = Find-Git
        } catch {
            Write-Host "Git 自动安装失败：$($_.Exception.Message)"
        }
    }
    if (-not $gitExe) {
        Fail '未能自动安装 Git。请从 https://git-scm.com/install/windows 手动安装后重试。'
    }
    $env:Path = (Split-Path -Parent $gitExe) + ';' + $env:Path
}
Write-Host 'Git OK'
$Destination = [IO.Path]::GetFullPath($Destination)
Write-Host "项目目录：$Destination"
if (Test-Path -LiteralPath (Join-Path $Destination '.git')) {
    $origin = (& $gitExe -C $Destination remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or $origin -notmatch '(^|[:/])jigeng-ma/VisionRay(\.git)?$') {
        Fail "目标目录不是预期的 VisionRay 仓库：$Destination"
    }
    $branch = (& $gitExe -C $Destination symbolic-ref --quiet --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
        Fail '当前仓库未处于正常分支，请先切换到需要更新的分支。'
    }
    $before = (& $gitExe -C $Destination rev-parse HEAD).Trim()
    Write-Host '检查项目版本中...'
    $remoteLine = $null
    try { $remoteLine = (& $gitExe -C $Destination ls-remote --exit-code origin "refs/heads/$branch" 2>$null) }
    catch { }
    if ($LASTEXITCODE -ne 0 -or -not $remoteLine) {
        Fail "无法查询远端 $branch 分支。请检查网络和 GitHub 权限。"
    }
    $latest = ($remoteLine -split '\s+')[0]
    if ($before -eq $latest) {
        Write-Host "已是最新版本：$($before.Substring(0, 12))"
        exit 0
    }
    Write-Host '下载更新中...'
    try { & $gitExe -C $Destination fetch --quiet origin "refs/heads/$branch" 2>$null }
    catch { Fail '获取新增提交失败。请检查网络和 GitHub 权限。' }
    if ($LASTEXITCODE -ne 0) { Fail '获取新增提交失败。请检查网络和 GitHub 权限。' }
    & $gitExe -C $Destination merge-base --is-ancestor HEAD FETCH_HEAD
    if ($LASTEXITCODE -ne 0) {
        Fail '本地提交与远端历史不一致，请人工检查分支。'
    }
    $count = (& $gitExe -C $Destination rev-list --count HEAD..FETCH_HEAD).Trim()
    try { & $gitExe -C $Destination merge --quiet --ff-only FETCH_HEAD 2>$null }
    catch { Fail '本地文件改动阻止了更新；请先处理本地改动。' }
    if ($LASTEXITCODE -ne 0) {
        Fail '本地文件改动阻止了更新；请处理 Git 提示的文件后重试。'
    }
    $after = (& $gitExe -C $Destination rev-parse --short=12 HEAD).Trim()
    Write-Host "更新完成：$after（新增 $count 个提交）"
} elseif (Test-Path -LiteralPath $Destination) {
    Fail "目标目录已存在但不是 Git 仓库：$Destination。请指定另一个空目录。"
} else {
    Write-Host '下载项目中...'
    try { & $gitExe clone --quiet --depth 1 --single-branch $repo $Destination 2>$null }
    catch { Fail '下载项目失败。请检查 GitHub 权限与网络。' }
    if ($LASTEXITCODE -ne 0) {
        Fail '下载项目失败。请检查 GitHub 权限与网络。'
    }
    $version = (& $gitExe -C $Destination rev-parse --short=12 HEAD).Trim()
    Write-Host "下载完成：$version"
}
Write-Host '下一步：在 VisionRay 目录运行 setup_environment.cmd。'
