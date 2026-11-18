[CmdletBinding(SupportsShouldProcess)]
param([ValidateRange(1, 65535)][int]$Port = 4001)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$commandPattern = '^\s*"?' + [regex]::Escape($pythonPath) + '"?\s+-m\s+modou\.web(?:\s|$)'

# Do not hide access failures as "already stopped" or stop an unrelated listener.
$listeners = @(Get-NetTCPConnection -ErrorAction Stop | Where-Object {
    $_.LocalPort -eq $Port -and $_.State -eq 'Listen'
})
if ($listeners.Count -eq 0) {
    Write-Host "端口${Port}没有监听服务，无需关闭。"
    return
}
$serviceIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($serviceId in $serviceIds) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$serviceId" -ErrorAction Stop
    if (-not $processInfo -or $processInfo.CommandLine -notmatch $commandPattern) {
        throw "端口${Port}的进程${serviceId}不属于本项目审核服务，未停止任何进程。"
    }
}
foreach ($serviceId in $serviceIds) {
    if ($PSCmdlet.ShouldProcess("本项目审核服务PID=$serviceId，端口=$Port", '停止进程')) {
        Stop-Process -Id $serviceId -ErrorAction Stop
        Write-Host "已停止审核服务：端口$Port，PID=$serviceId。"
    }
}
