# Host setup

Career Compass communicates over MCP stdio. Keep the repository at a stable local path after registration; the host starts the server with `uv`.

## Windows helper

From PowerShell in the repository folder:

```powershell
.\Setup.ps1 -HostName Codex
```

Use `Claude`, `Gemini`, or `Qwen` to configure one of those supported command-line hosts instead. `Setup.ps1` runs `uv sync`, installs the Skill in that host's user Skill directory, and registers the MCP server. It does not modify other host configurations.

For a separate step, run `Install-Skill.ps1 -HostName Codex|Claude|Gemini|Qwen|Shared|All` or `Register-MCP.ps1 -HostName Codex|Claude|Gemini|Qwen`. Gemini and Qwen settings are backed up when `-Force` is used to replace an existing `career-compass` entry.

## Manual MCP registration

First install the dependencies:

```bash
uv sync
```

Use an absolute repository path. If the host cannot locate `uv` on its PATH, use the absolute path to the `uv` executable as the command.

### Codex CLI

```bash
codex mcp add career-compass -- uv --directory "/absolute/path/to/career-compass-mcp-skill" run career-compass-mcp
```

### Claude Code

```bash
claude mcp add --scope user career-compass -- uv --directory "/absolute/path/to/career-compass-mcp-skill" run career-compass-mcp
```

### Gemini CLI

Merge this entry into the `mcpServers` object in `~/.gemini/settings.json` (Windows: `%USERPROFILE%\.gemini\settings.json`):

```json
{
  "career-compass": {
    "command": "uv",
    "args": ["--directory", "/absolute/path/to/career-compass-mcp-skill", "run", "career-compass-mcp"]
  }
}
```

### Qwen Code

Add the same `career-compass` entry under `mcpServers` in `~/.qwen/settings.json` (Windows: `%USERPROFILE%\.qwen\settings.json`).

## Install the Agent Skill

Copy `skills/career-compass` as a folder into the matching host's user Skill directory:

| Host | Common user Skill directory |
| --- | --- |
| Codex | `~/.codex/skills/career-compass` |
| Claude Code | `~/.claude/skills/career-compass` |
| Gemini CLI | `~/.gemini/skills/career-compass` or `~/.agents/skills/career-compass` |
| Qwen Code | `~/.qwen/skills/career-compass` or `~/.agents/skills/career-compass` |

Windows equivalents use `%USERPROFILE%` instead of `~`. Restart or refresh the host to load the MCP server and Skill.

## Host documentation

Host setup details can change independently of this project. Check the current documentation for [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp), [Claude Code MCP](https://code.claude.com/docs/en/mcp), [Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/), and [Qwen Code MCP](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/). For Skills, see [Codex](https://developers.openai.com/plugins/concepts/skills), [Claude Code](https://code.claude.com/docs/en/skills), [Gemini CLI](https://geminicli.com/docs/cli/skills/), and [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/).
