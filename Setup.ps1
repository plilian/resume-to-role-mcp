param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('Codex','Claude','Gemini','Qwen')]
  [string]$HostName,
  [switch]$Force
)
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv -ErrorAction Stop
Push-Location $PSScriptRoot
try {
  Write-Output 'Installing Career Compass dependencies...'
  & $uv.Source sync
  if ($LASTEXITCODE -ne 0) { throw 'uv sync failed; the host was not configured.' }
} finally {
  Pop-Location
}
& (Join-Path $PSScriptRoot 'Install-Skill.ps1') -HostName $HostName
$register = Join-Path $PSScriptRoot 'Register-MCP.ps1'
$registerArgs = @('-HostName', $HostName)
if ($Force) { $registerArgs += '-Force' }
& $register @registerArgs
Write-Output "Career Compass is ready for $HostName. Restart or refresh that host to load its MCP server and skill."
