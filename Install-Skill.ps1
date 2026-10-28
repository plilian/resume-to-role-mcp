param(
  [ValidateSet('Codex','Claude','Gemini','Qwen','Shared','All')]
  [string]$HostName = 'All'
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'skills\career-compass'
$destinations = @{
  Codex = Join-Path $env:USERPROFILE '.codex\skills\career-compass'
  Claude = Join-Path $env:USERPROFILE '.claude\skills\career-compass'
  Gemini = Join-Path $env:USERPROFILE '.gemini\skills\career-compass'
  Qwen = Join-Path $env:USERPROFILE '.qwen\skills\career-compass'
  Shared = Join-Path $env:USERPROFILE '.agents\skills\career-compass'
}
if ($HostName -eq 'All') { $selected = @('Codex','Claude','Gemini','Qwen') }
else { $selected = @($HostName) }
foreach ($name in $selected) {
  $target = $destinations[$name]
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Copy-Item -LiteralPath (Join-Path $source 'SKILL.md') -Destination (Join-Path $target 'SKILL.md') -Force
  Write-Output "Installed Resume-to-Role skill for ${name}: $target"
}
Write-Output 'Restart or refresh the selected host to load the skill.'
