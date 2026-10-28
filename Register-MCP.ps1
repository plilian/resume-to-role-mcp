param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('Codex','Claude','Gemini','Qwen')]
  [string]$HostName,
  [switch]$Force
)
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv -ErrorAction Stop
$uvPath = $uv.Source
$argsList = @('--directory', $PSScriptRoot, 'run', 'career-compass-mcp')
if ($HostName -eq 'Codex') {
  if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'Codex CLI was not found. Add the MCP command from README.md instead.' }
  & codex mcp add career-compass -- $uvPath @argsList
  if ($LASTEXITCODE -ne 0) { throw 'Codex did not register the MCP server.' }
  Write-Output 'Career Compass MCP registered with Codex.'
  exit 0
}
if ($HostName -eq 'Claude') {
  if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw 'Claude Code CLI was not found. Add the MCP command from README.md instead.' }
  & claude mcp add --scope user career-compass -- $uvPath @argsList
  if ($LASTEXITCODE -ne 0) { throw 'Claude Code did not register the MCP server.' }
  Write-Output 'Career Compass MCP registered with Claude Code.'
  exit 0
}
$settingsPath = if ($HostName -eq 'Gemini') {
  Join-Path $env:USERPROFILE '.gemini\settings.json'
} else {
  Join-Path $env:USERPROFILE '.qwen\settings.json'
}
if (-not (Test-Path -LiteralPath $settingsPath)) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $settingsPath) | Out-Null
  $settings = @{}
} else {
  $raw = Get-Content -LiteralPath $settingsPath -Raw
  $settings = if ([string]::IsNullOrWhiteSpace($raw)) { @{} } else { ConvertFrom-Json -InputObject $raw -AsHashtable }
}
if (-not ($settings.Keys -contains 'mcpServers')) { $settings['mcpServers'] = @{} }
if (($settings['mcpServers'].Keys -contains 'career-compass') -and -not $Force) {
  throw "career-compass already exists in $settingsPath. Re-run with -Force to replace its entry."
}
$settings['mcpServers']['career-compass'] = @{
  command = $uvPath
  args = $argsList
}
$backup = $settingsPath + '.career-compass-backup'
if ((Test-Path -LiteralPath $settingsPath) -and $Force) {
  Copy-Item -LiteralPath $settingsPath -Destination $backup -Force
}
$json = ConvertTo-Json -InputObject $settings -Depth 80
[IO.File]::WriteAllText($settingsPath,$json,[Text.UTF8Encoding]::new($false))
Write-Output "Career Compass MCP registered with $HostName in $settingsPath"
if (Test-Path -LiteralPath $backup) { Write-Output "Previous settings backed up to $backup" }
