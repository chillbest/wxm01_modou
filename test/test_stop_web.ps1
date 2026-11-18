$ErrorActionPreference = 'Stop'
$stopScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts/stop_web.ps1'
$pythonPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
$global:stopWebTestconnections = @()
$global:stopWebTestcommands = @{}
$global:stopWebTeststopped = @()
$global:stopWebTestdenyRead = $false
function Get-NetTCPConnection {
    if ($global:stopWebTestdenyRead) { throw 'access denied' }
    $global:stopWebTestconnections
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $idValue = [int]($Filter -replace 'ProcessId=', '')
    if ($global:stopWebTestcommands.ContainsKey($idValue)) {
        [pscustomobject]@{ CommandLine = $global:stopWebTestcommands[$idValue] }
    }
}
function Stop-Process {
    param($Id, $ErrorAction)
    $global:stopWebTeststopped += $Id
}
function Assert-True($Condition, $Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-Rejected {
    $rejected = $false
    try { & $stopScript } catch { $rejected = $true }
    Assert-True $rejected 'Expected refusal'
    Assert-True ($global:stopWebTeststopped.Count -eq 0) 'An unrelated process was stopped'
}

& $stopScript
Assert-True ($global:stopWebTeststopped.Count -eq 0) 'No listener must be a no-op'
$global:stopWebTestconnections = @([pscustomobject]@{LocalPort=4001;State='Listen';OwningProcess=123})
$global:stopWebTestcommands[123] = '"' + $pythonPath + '" -m modou.web --port 4001'
& $stopScript -WhatIf
Assert-True ($global:stopWebTeststopped.Count -eq 0) 'WhatIf stopped a process'
& $stopScript
Assert-True ($global:stopWebTeststopped.Count -eq 1 -and $global:stopWebTeststopped[0] -eq 123) 'Correct listener was not stopped'
$global:stopWebTeststopped = @()
foreach ($cmd in @('python.exe -m modou.web', '"' + $pythonPath + '" -m modou.web.other', '"' + $pythonPath + '" -m other')) {
    $global:stopWebTestcommands[123] = $cmd
    Assert-Rejected
}
$global:stopWebTestcommands[123] = '"' + $pythonPath + '" -m modou.web'
$global:stopWebTestconnections += [pscustomobject]@{LocalPort=4001;State='Listen';OwningProcess=124}
$global:stopWebTestcommands[124] = 'other.exe'
Assert-Rejected
$global:stopWebTestconnections = @([pscustomobject]@{LocalPort=4010;State='Listen';OwningProcess=123})
& $stopScript -Port 4010
Assert-True ($global:stopWebTeststopped.Count -eq 1) 'Custom port did not work'
$global:stopWebTeststopped = @()
$global:stopWebTestdenyRead = $true
Assert-Rejected
Write-Host 'PASS: stop_web mocked process checks'
