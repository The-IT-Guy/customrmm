$server="http://159.198.44.119:8000"
$key="ALPHA_RMM_KEY_2026"
$state="$env:ProgramData\customrmm"
$idFile="$state\agent_id.txt"

mkdir $state -Force | Out-Null

function Get-IP {
 (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {$_.InterfaceAlias -notlike "*Loopback*"} |
  Select-Object -First 1).IPAddress
}

$machineId = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid
$headers = @{ "X-API-Key" = $key }

if (Test-Path $idFile) {
 $agentId = Get-Content $idFile
} else {
 $body = @{
  machine_id = $machineId
  hostname = $env:COMPUTERNAME
  os = "Windows"
  ip = Get-IP
 } | ConvertTo-Json

 $resp = Invoke-RestMethod "$server/agent/register" -Method POST -Headers $headers -Body $body -ContentType "application/json"
 $agentId = $resp.agent_id
 Set-Content $idFile $agentId
}

while ($true) {
 try {
  Invoke-RestMethod "$server/agent/heartbeat/$agentId" -Headers $headers
 } catch {}
 Start-Sleep 60
}
