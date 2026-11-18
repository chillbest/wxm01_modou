param([ValidateRange(1, 65535)][int]$Port = 4001)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = Join-Path $PWD 'src'
& (Join-Path $PSScriptRoot 'stop_web.ps1') -Port $Port
# Stop-Process may return before the listening socket has been released.
$deadline = [DateTime]::UtcNow.AddSeconds(10)
while (@(Get-NetTCPConnection -ErrorAction Stop | Where-Object {
    $_.LocalPort -eq $Port -and $_.State -eq 'Listen'
}).Count -gt 0) {
    if ([DateTime]::UtcNow -ge $deadline) {
        throw "端口${Port}未在10秒内释放，未启动审核服务。"
    }
    Start-Sleep -Milliseconds 100
}
$browserJob = Start-Job -ArgumentList "http://127.0.0.1:$Port" -ScriptBlock {
    param($Url)
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                Start-Process $Url
                return
            }
        } catch {
            # The foreground server is still starting.
        }
        Start-Sleep -Milliseconds 300
    }
    Write-Warning "服务在60秒内未就绪，未自动打开浏览器：$Url"
}
try {
    & (Join-Path $PWD '.venv/Scripts/python.exe') -m modou.web --port $Port
} finally {
    Stop-Job -Job $browserJob
    Receive-Job -Job $browserJob
    Remove-Job -Job $browserJob
}
