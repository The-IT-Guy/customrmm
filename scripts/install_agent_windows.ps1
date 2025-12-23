\
Param(
  [Parameter(Mandatory=$true)][string]$ServerUrl,
  [Parameter(Mandatory=$true)][string]$EnrollToken
)

$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:ProgramData "customrmm"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

# Copy agent.py (assumes this repo is present; adjust path if you download separately)
$AgentSrc = Join-Path $PSScriptRoot "..\agent\agent.py"
$AgentDst = Join-Path $InstallDir "agent.py"
Copy-Item $AgentSrc $AgentDst -Force

# Ensure Python exists
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "Python not found. Install Python 3.10+ first." }

python -m pip install --upgrade pip | Out-Null
python -m pip install --upgrade psutil httpx | Out-Null

# Create scheduled task to run agent at startup + repeat
$TaskName = "CustomRMM Agent"
$Action = New-ScheduledTaskAction -Execute "python" -Argument "`"$AgentDst`" --server $ServerUrl --enroll-token $EnrollToken --interval 30"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started scheduled task: $TaskName"
