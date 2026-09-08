<#
  Norms-AI 定额库开机静默启动。
  由 silent-start.vbs 以无窗口方式调用，不要直接双击（会弹控制台）。

  流程：检测服务是否已在跑 -> pythonw 后台拉起 start.py -> 等待端口响应 -> 打开浏览器
  全过程日志写入 temp/startup/startup-<日期>.log

  端口默认 18080 而不是 8080：Hyper-V/WSL 会在动态端口范围（默认 1024-15000）
  内成块预留端口，被预留的端口即便空闲也 bind 失败（WinError 10013）。
  18080 在动态范围之外，不会被抢。
#>

param(
    [int]$Port = 18080,
    [int]$HealthWaitSeconds = 60,   # 等待服务可访问的上限
    [switch]$NoBrowser              # 只启动服务，不弹浏览器
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$AppUrl = "http://localhost:$Port/norms_browser.html"

$LogDir = Join-Path $ProjectRoot 'temp\startup'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("startup-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-PortAlive {
    param([int]$P)
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $P)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# pythonw.exe 才是无控制台版本；python.exe 会闪一个黑框。
# 排除 System32 / WindowsApps 下的 Microsoft Store 转发存根，它们不带 pythonw。
function Resolve-Pythonw {
    if ($env:NORMS_PYTHONW -and (Test-Path $env:NORMS_PYTHONW)) { return $env:NORMS_PYTHONW }

    $candidates = @(Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }) |
        Where-Object { $_ -notlike "$env:WINDIR\*" -and $_ -notlike "*\WindowsApps\*" }

    foreach ($c in $candidates) {
        $pw = Join-Path (Split-Path -Parent $c) 'pythonw.exe'
        if (Test-Path $pw) { return $pw }
    }

    $direct = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($direct) { return $direct.Source }

    return $null
}

Write-Log "==== 启动流程开始 ===="
Write-Log "项目目录: $ProjectRoot"
Write-Log "端口: $Port"

# ---------- 1. 已在运行则跳过拉起 ----------
if (Test-PortAlive -P $Port) {
    Write-Log "端口 $Port 已有服务在监听，跳过启动"
} else {
    $pythonw = Resolve-Pythonw
    if (-not $pythonw) {
        Write-Log "未找到 pythonw.exe，无法静默启动。可设置环境变量 NORMS_PYTHONW 指定路径。" 'ERROR'
        exit 1
    }
    Write-Log "解释器: $pythonw"

    $startPy = Join-Path $ProjectRoot 'start.py'
    if (-not (Test-Path $startPy)) {
        Write-Log "找不到 $startPy" 'ERROR'
        exit 1
    }

    Write-Log "后台拉起 start.py --no-open --port $Port ..."
    Start-Process -FilePath $pythonw `
        -ArgumentList "`"$startPy`"", '--no-open', '--port', "$Port" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden
}

# ---------- 2. 等待服务可访问 ----------
Write-Log "等待服务响应（上限 ${HealthWaitSeconds}s）..."
$healthy = $false
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt $HealthWaitSeconds) {
    try {
        $resp = Invoke-WebRequest -Uri $AppUrl -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}
$sw.Stop()

if ($healthy) {
    Write-Log ("服务就绪，耗时 {0:N0}s" -f $sw.Elapsed.TotalSeconds)
} else {
    Write-Log "服务在 ${HealthWaitSeconds}s 内未响应，放弃打开浏览器。检查端口是否被系统保留：netsh int ipv4 show excludedportrange protocol=tcp" 'ERROR'
    Write-Log "==== 启动流程结束 ===="
    exit 1
}

# ---------- 3. 打开浏览器 ----------
if ($NoBrowser) {
    Write-Log "指定了 -NoBrowser，跳过打开浏览器"
} else {
    Write-Log "打开 $AppUrl"
    Start-Process $AppUrl
}

Write-Log "==== 启动流程结束 ===="
