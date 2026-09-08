<#
  把 Norms-AI 定额库静默启动注册到当前用户的「启动」文件夹。

  用启动文件夹而不是任务计划程序，原因（同 CostSpread）：
    - 用户登录后才触发，无需管理员权限
    - 卸载就是删一个快捷方式，可控

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\startup\install-autostart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\startup\install-autostart.ps1 -Uninstall
#>

param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$StartupDir = [Environment]::GetFolderPath('Startup')
# 用 ASCII 文件名：启动项会被各类工具读取，中文名在 GBK 环境下易出编码问题
$LinkPath = Join-Path $StartupDir 'NormsAI-AutoStart.lnk'
$VbsPath = Join-Path $PSScriptRoot 'silent-start.vbs'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if ($Uninstall) {
    if (Test-Path $LinkPath) {
        Remove-Item $LinkPath -Force
        Write-Host "已移除开机启动: $LinkPath" -ForegroundColor Green
    } else {
        Write-Host "开机启动项本就不存在，无需处理" -ForegroundColor Yellow
    }
    exit 0
}

if (-not (Test-Path $VbsPath)) {
    throw "找不到 $VbsPath"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($LinkPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = """$VbsPath"""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = 'Norms-AI 定额库开机静默启动（后台拉起 start.py 并打开浏览器）'
$shortcut.Save()

Write-Host "已注册开机启动" -ForegroundColor Green
Write-Host "  快捷方式: $LinkPath"
Write-Host "  目标:     wscript.exe $VbsPath"
Write-Host ""
Write-Host "下次开机登录后会自动：后台拉起服务 -> 打开 http://localhost:18080/norms_browser.html" -ForegroundColor Gray
Write-Host "启动日志: temp\startup\startup-<日期>.log" -ForegroundColor Gray
Write-Host ""
Write-Host "立即测试（不必重启）：" -ForegroundColor Cyan
Write-Host "  wscript `"$VbsPath`""
