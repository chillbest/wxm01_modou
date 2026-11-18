$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
# Replace only the final external Python invocation; execute the actual restart logic.
$source = Get-Content (Join-Path $root 'scripts/start_web.ps1') -Raw
$launch = "& (Join-Path `$PWD '.venv/Scripts/python.exe') -m modou.web --port `$Port"
if (-not $source.Contains($launch)) { throw 'Launch seam missing' }
$source = $source.Replace($launch, '$global:startedPorts += $Port')
$global:startScriptRoot = Join-Path $root 'scripts'
$source = $source.Replace('$PSScriptRoot', '$global:startScriptRoot')
$script = [scriptblock]::Create($source)
$global:startedPorts = @()
$global:listeners = @()
$global:stoppedIds = @()
$global:foreign = $false
$global:denyRead = $false
$global:browserUrls = @()
function Start-Job {
    param($ArgumentList, $ScriptBlock)
    $global:browserUrls += $ArgumentList
    & $ScriptBlock $ArgumentList
    [pscustomobject]@{Id=1}
}
function Invoke-WebRequest { [pscustomobject]@{StatusCode=200} }
function Start-Process { param($FilePath) $global:openedUrl = $FilePath }
function Stop-Job { param($Job) }
function Receive-Job { param($Job) }
function Remove-Job { param($Job) }
function Get-NetTCPConnection {
    if ($global:denyRead) { throw 'access denied' }
    $global:listeners
}
function Get-CimInstance {
    if ($global:foreign) { return [pscustomobject]@{CommandLine='other.exe'} }
    [pscustomobject]@{CommandLine=('"' + (Join-Path $root '.venv\Scripts\python.exe') + '" -m modou.web')}
}
function Stop-Process {
    param($Id, $ErrorAction)
    $global:stoppedIds += $Id
    $global:listeners = @()
}
function Assert-True($value) { if (-not $value) { throw 'Assertion failed' } }
# Scriptblocks have no PSScriptRoot: supply the owning script directory explicitly.
function Invoke-Start([int]$Port = 4001) {
    $PSScriptRoot = Join-Path $root 'scripts'
    & $script -Port $Port
}
Invoke-Start
Assert-True ($global:startedPorts.Count -eq 1 -and $global:stoppedIds.Count -eq 0)
Assert-True ($global:openedUrl -eq 'http://127.0.0.1:4001')
$global:listeners = @([pscustomobject]@{LocalPort=4010;State='Listen';OwningProcess=123})
Invoke-Start 4010
Assert-True ($global:startedPorts[-1] -eq 4010 -and $global:stoppedIds[0] -eq 123)
Assert-True ($global:openedUrl -eq 'http://127.0.0.1:4010')
$global:listeners = @([pscustomobject]@{LocalPort=4001;State='Listen';OwningProcess=124})
$global:foreign = $true
$rejected = $false
try { Invoke-Start } catch { $rejected = $true }
Assert-True ($rejected -and $global:startedPorts.Count -eq 2 -and $global:stoppedIds.Count -eq 1)
$global:denyRead = $true
$rejected = $false
try { Invoke-Start } catch { $rejected = $true }
Assert-True ($rejected -and $global:startedPorts.Count -eq 2)
Write-Host 'PASS: start_web restart checks'

