<div align="center">

<img src="assets/logo.png" alt="Slack Coder" width="120"/>

# Slack Coder

### Your AI coding army, commanded from Slack.

**No laptop. No IDE. Just vibes.**

[![GitHub Stars](https://img.shields.io/github/stars/FL-Penly/slack-coder?color=ffcb47&labelColor=black&style=flat-square)](https://github.com/FL-Penly/slack-coder/stargazers)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?labelColor=black&style=flat-square)](LICENSE)

[English](README.md) | [中文](README_ZH.md)

---

![Banner](assets/banner.jpg)

</div>

## The Pitch

You're at the beach. Phone buzzes — production's on fire.

**Old you:** Panic. Find WiFi. Open laptop. Wait for IDE. Lose your tan.

**Slack Coder you:** Open Slack. Type "Fix the auth bug in login.py". Watch Claude Code fix it in real-time. Approve. Sip margarita.

```
AI works. You live.
```

---

## Install

### Option 1: Let AI Do It For You

> **Just paste this URL to your AI assistant (Claude Code, Cursor, etc.):**
>
> ```
> https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
> ```
>
> Your AI will read the instructions and set everything up. When done, run `vibe init` to complete configuration.

### Option 2: Manual Install

```bash
# 1. Install with uv
uv tool install git+https://github.com/FL-Penly/slack-coder.git

# 2. Run interactive setup
vibe init
```

The setup wizard will guide you through:
- Detecting/installing AI agents (Claude Code, OpenCode)
- Creating a Slack App and getting tokens
- Configuring your working directory

See [Slack Setup Guide](docs/SLACK_SETUP.md) for detailed manual instructions.

---

## Why This Exists

| Problem | Solution |
|---------|----------|
| Claude Code is amazing but needs a terminal | Slack IS your terminal now |
| Context-switching kills flow | Stay in one app |
| Can't code from phone | Yes you can |
| Multiple agents, multiple setups | One Slack, any agent |

**Supported Agents:**
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — Deep reasoning, complex refactors
- [OpenCode](https://opencode.ai) — Fast, extensible, community favorite  
- [Codex](https://github.com/openai/codex) — OpenAI's coding model

---

## Highlights

### Thread = Session

Each Slack thread is an isolated workspace. Open 5 threads, run 5 parallel tasks. Context stays separate.

### Interactive Prompts

When your agent needs input — file selection, confirmation, options — Slack pops up buttons or a modal. Full CLI interactivity, zero terminal required.

![Interactive Prompts](assets/screenshots/question-en.jpg)

### Instant Notifications

Get notified the moment your AI finishes. Like assigning tasks to employees — delegate, go do something else, and come back when the work is done. No need to babysit.

### Control Panel

Open the control panel with `@bot /start` to access:
- **Agent Settings** — Configure which agent to use per channel
- **Working Directory** — Set the project path for your agent
- **Session Management** — View and resume previous sessions
- **Git Changes** — View uncommitted changes with rich diff display

---

## How It Works

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     You      │  Slack  │ Slack Coder  │  stdio  │  AI Agent    │
│  (anywhere)  │ ──────▶ │  (your Mac)  │ ──────▶ │ (your code)  │
└──────────────┘         └──────────────┘         └──────────────┘
```

1. **You type** in Slack: *"Add dark mode to the settings page"*
2. **Slack Coder** routes to your configured agent
3. **Agent** reads your codebase, writes code, streams back
4. **You review** in Slack, iterate in thread

**Your code never leaves your machine.** Slack Coder runs locally and connects via Slack's Socket Mode.

---

## Commands

| In Slack | What it does |
|----------|--------------|
| `@bot /start` | Open control panel |
| `@bot /stop` | Kill current session |
| `@bot /diff` | Show git changes |
| `@bot /sessions` | View session history |
| Just type | Talk to your agent |
| Reply in thread | Continue conversation |

**Pro tip:** Each Slack thread = isolated session. Start multiple threads for parallel tasks.

---

## Instant Agent Switching

Need a different agent mid-conversation? Just prefix your message:

```
claude: Design a new caching layer for the API
```

That's it. No menus, no commands. Type `AgentName:` and your message routes to that agent instantly.

---

## Per-Channel Routing

Different projects, different agents:

```
#frontend    → OpenCode (fast iteration)
#backend     → Claude Code (complex logic)  
#prototypes  → Codex (quick experiments)
```

Configure via the **Agent Settings** button in the control panel (`@bot /start`).

---

## CLI

```bash
vibe          # Start the bot
vibe status   # Check if running
vibe stop     # Stop the bot
vibe doctor   # Diagnose issues
```

---

## Prerequisites

You need at least one coding agent installed:

<details>
<summary><b>OpenCode</b> (Recommended)</summary>

```bash
curl -fsSL https://opencode.ai/install | bash
```

**Required:** Add to `~/.config/opencode/opencode.json` to skip permission prompts:

```json
{
  "permission": "allow"
}
```
</details>

<details>
<summary><b>Claude Code</b></summary>

```bash
npm install -g @anthropic-ai/claude-code
```
</details>

<details>
<summary><b>Codex</b></summary>

```bash
npm install -g @openai/codex
```
</details>

---

## Security

- **Local-first** — Slack Coder runs on your machine
- **Socket Mode** — No public URLs, no webhooks
- **Your tokens** — Stored in `~/.vibe_remote/`, never uploaded
- **Your code** — Stays on your disk, sent only to your chosen AI provider

---

## Uninstall

```bash
vibe stop && uv tool uninstall vibe && rm -rf ~/.vibe_remote
```

---

## Roadmap

- [ ] SaaS Mode
- [ ] Custom Coding Agent (one agent to rule them all)
- [ ] File attachments in Slack
- [ ] Multi-workspace

---

## Docs

- **[AI Setup Guide](docs/AI_SETUP.md)** — Let your AI assistant install everything for you
- **[CLI Reference](docs/CLI.md)** — Command-line usage and service lifecycle
- **[Slack Setup Guide](docs/SLACK_SETUP.md)** — Detailed manual setup with screenshots

---

<div align="center">

**Stop context-switching. Start vibe coding.**

[Install Now](#install) · [Setup Guide](docs/SLACK_SETUP.md) · [Report Bug](https://github.com/FL-Penly/slack-coder/issues)

---

*Built for developers who code from anywhere.*

</div>
