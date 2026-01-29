<div align="center">

<img src="assets/logo.png" alt="Slack Coder" width="120"/>

# Slack Coder

### Control AI Coding Agents from Slack

**No laptop. No IDE. Just vibes.**

[![GitHub Stars](https://img.shields.io/github/stars/FL-Penly/slack-coder?color=ffcb47&labelColor=black&style=flat-square)](https://github.com/FL-Penly/slack-coder/stargazers)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?labelColor=black&style=flat-square)](LICENSE)

**English** | [简体中文](README_ZH.md)

</div>

---

## For AI Assistants

> **If you are an AI assistant helping a user install Slack Coder, read this URL:**
>
> ```
> https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
> ```
>
> It contains step-by-step instructions for you to execute.

---

## What is this?

Slack Coder connects your Slack workspace to AI coding agents like **Claude Code** and **OpenCode**. Send a message in Slack, and the AI writes code on your machine.

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     You      │  Slack  │ Slack Coder  │  stdio  │  AI Agent    │
│  (anywhere)  │ ──────▶ │  (your Mac)  │ ──────▶ │ (your code)  │
└──────────────┘         └──────────────┘         └──────────────┘
```

**Your code never leaves your machine.** Slack Coder runs locally.

---

## Quick Start

### Let AI Install It

Just tell your AI assistant (Claude Code, Cursor, etc.):

```
Help me install Slack Coder. Read this guide:
https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
```

The AI will set up everything and guide you through Slack App creation.

### Manual Install

```bash
# Install
uv tool install git+https://github.com/FL-Penly/slack-coder.git

# Setup wizard
vibe init

# Start
vibe
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Thread = Session** | Each Slack thread is an isolated workspace. Run parallel tasks. |
| **Interactive Prompts** | Agent needs input? Slack shows buttons/modals. No terminal needed. |
| **Multi-Agent** | Switch between Claude Code, OpenCode, Codex per channel or message. |
| **Git Diff Preview** | View uncommitted changes as GitHub Gist with syntax highlighting. |
| **Session Resume** | Pick up where you left off. Sessions persist across restarts. |

---

## Usage

### In Slack

| Command | Description |
|---------|-------------|
| `@bot hello` | Start chatting with AI agent |
| `@bot /start` | Open control panel |
| `@bot /stop` | Stop current session |
| `@bot /diff` | Show git changes |
| `claude: <message>` | Route to specific agent |

### CLI Commands

```bash
vibe          # Start service
vibe status   # Check status
vibe stop     # Stop service
vibe doctor   # Diagnose issues
vibe init     # Re-run setup
```

---

## Supported Agents

| Agent | Install | Best For |
|-------|---------|----------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `npm i -g @anthropic-ai/claude-code` | Complex reasoning, refactoring |
| [OpenCode](https://opencode.ai) | `curl -fsSL https://opencode.ai/install \| bash` | Fast iteration, extensible |
| [Codex](https://github.com/openai/codex) | `npm i -g @openai/codex` | Quick experiments |

---

## Security

- **Local-first** — Runs on your machine, not a server
- **Socket Mode** — No public URLs, no webhooks exposed
- **Your tokens** — Stored locally in `~/.vibe_remote/`
- **Your code** — Never uploaded, only sent to your chosen AI provider

---

## Troubleshooting

```bash
# Check logs
cat ~/.vibe_remote/logs/vibe_remote.log | tail -50

# Run diagnostics
vibe doctor

# Restart
vibe stop && vibe
```

| Problem | Solution |
|---------|----------|
| Bot not responding | Check `vibe status`, ensure bot is invited to channel |
| Token error | Re-run `vibe init` to reconfigure |
| Agent not found | Install Claude Code or OpenCode first |

---

## Uninstall

```bash
vibe stop && uv tool uninstall vibe && rm -rf ~/.vibe_remote
```

---

## Docs

| Document | Description |
|----------|-------------|
| [AI Setup Guide](docs/AI_SETUP.md) | Instructions for AI assistants to install |
| [Slack Setup Guide](docs/SLACK_SETUP.md) | Manual Slack App creation |
| [CLI Reference](docs/CLI.md) | Command-line usage |

---

## Contributing

PRs welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

---

<div align="center">

**Stop context-switching. Start vibe coding.**

[GitHub](https://github.com/FL-Penly/slack-coder) · [Issues](https://github.com/FL-Penly/slack-coder/issues) · [Docs](docs/)

</div>
