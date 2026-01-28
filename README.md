<div align="center">

<img src="assets/logo.png" alt="Slack Coder" width="120"/>

# Slack Coder

### Control AI Coding Agents from Slack | 在 Slack 中控制 AI 编程助手

**No laptop. No IDE. Just vibes.** | **无需电脑，无需 IDE，随时随地编程**

[![GitHub Stars](https://img.shields.io/github/stars/FL-Penly/slack-coder?color=ffcb47&labelColor=black&style=flat-square)](https://github.com/FL-Penly/slack-coder/stargazers)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?labelColor=black&style=flat-square)](LICENSE)

</div>

---

## For AI Assistants | 给 AI 助手

> **If you are an AI assistant helping a user install Slack Coder, read this URL:**
>
> ```
> https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
> ```
>
> It contains step-by-step instructions for you to execute.

> **如果你是 AI 助手，正在帮用户安装 Slack Coder，请读取上面的 URL，里面有详细的安装步骤。**

---

## What is this? | 这是什么？

Slack Coder connects your Slack workspace to AI coding agents like **Claude Code** and **OpenCode**. Send a message in Slack, and the AI writes code on your machine.

Slack Coder 将你的 Slack 工作区连接到 AI 编程助手（如 **Claude Code** 和 **OpenCode**）。在 Slack 中发消息，AI 就会在你的电脑上写代码。

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     You      │  Slack  │ Slack Coder  │  stdio  │  AI Agent    │
│  (anywhere)  │ ──────▶ │  (your Mac)  │ ──────▶ │ (your code)  │
└──────────────┘         └──────────────┘         └──────────────┘
```

**Your code never leaves your machine.** Slack Coder runs locally.

**代码不会离开你的电脑。** Slack Coder 在本地运行。

---

## Quick Start | 快速开始

### Let AI Install It | 让 AI 帮你安装

Just tell your AI assistant (Claude Code, Cursor, etc.):

只需告诉你的 AI 助手（Claude Code、Cursor 等）：

```
Help me install Slack Coder. Read this guide:
https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
```

The AI will set up everything and guide you through Slack App creation.

AI 会帮你安装所有依赖，并引导你创建 Slack App。

### Manual Install | 手动安装

```bash
# Install | 安装
uv tool install git+https://github.com/FL-Penly/slack-coder.git

# Setup wizard | 配置向导
vibe init

# Start | 启动
vibe
```

---

## Features | 功能特点

| Feature | Description |
|---------|-------------|
| **Thread = Session** | Each Slack thread is an isolated workspace. Run parallel tasks. |
| **Interactive Prompts** | Agent needs input? Slack shows buttons/modals. No terminal needed. |
| **Multi-Agent** | Switch between Claude Code, OpenCode, Codex per channel or message. |
| **Git Diff Preview** | View uncommitted changes as GitHub Gist with syntax highlighting. |
| **Session Resume** | Pick up where you left off. Sessions persist across restarts. |

| 功能 | 描述 |
|------|------|
| **Thread = Session** | 每个 Slack 线程是独立的工作区，可并行执行多个任务 |
| **交互式提示** | Agent 需要输入时，Slack 会弹出按钮/对话框，无需终端 |
| **多 Agent 支持** | 按频道或消息切换 Claude Code、OpenCode、Codex |
| **Git Diff 预览** | 以 GitHub Gist 形式查看未提交的代码变更 |
| **会话恢复** | 支持恢复之前的会话，重启后继续工作 |

---

## Usage | 使用方法

### In Slack | 在 Slack 中

| Command | Description |
|---------|-------------|
| `@bot hello` | Start chatting with AI agent |
| `@bot /start` | Open control panel |
| `@bot /stop` | Stop current session |
| `@bot /diff` | Show git changes |
| `claude: <message>` | Route to specific agent |

| 命令 | 描述 |
|------|------|
| `@bot 你好` | 开始与 AI 对话 |
| `@bot /start` | 打开控制面板 |
| `@bot /stop` | 停止当前会话 |
| `@bot /diff` | 显示 Git 变更 |
| `claude: <消息>` | 指定使用某个 Agent |

### CLI Commands | 命令行

```bash
vibe          # Start service | 启动服务
vibe status   # Check status | 查看状态
vibe stop     # Stop service | 停止服务
vibe doctor   # Diagnose issues | 诊断问题
vibe init     # Re-run setup | 重新配置
```

---

## Supported Agents | 支持的 Agent

| Agent | Install | Best For |
|-------|---------|----------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `npm i -g @anthropic-ai/claude-code` | Complex reasoning, refactoring |
| [OpenCode](https://opencode.ai) | `curl -fsSL https://opencode.ai/install \| bash` | Fast iteration, extensible |
| [Codex](https://github.com/openai/codex) | `npm i -g @openai/codex` | Quick experiments |

---

## Security | 安全性

- **Local-first** — Runs on your machine, not a server
- **Socket Mode** — No public URLs, no webhooks exposed
- **Your tokens** — Stored locally in `~/.vibe_remote/`
- **Your code** — Never uploaded, only sent to your chosen AI provider

---

- **本地优先** — 在你的电脑上运行，不是服务器
- **Socket 模式** — 无需公开 URL，无需暴露 webhook
- **你的令牌** — 存储在本地 `~/.vibe_remote/`
- **你的代码** — 不会上传，只发送给你选择的 AI 提供商

---

## Troubleshooting | 故障排查

```bash
# Check logs | 查看日志
cat ~/.vibe_remote/logs/vibe_remote.log | tail -50

# Run diagnostics | 运行诊断
vibe doctor

# Restart | 重启
vibe stop && vibe
```

| Problem | Solution |
|---------|----------|
| Bot not responding | Check `vibe status`, ensure bot is invited to channel |
| Token error | Re-run `vibe init` to reconfigure |
| Agent not found | Install Claude Code or OpenCode first |

| 问题 | 解决方案 |
|------|----------|
| Bot 不响应 | 检查 `vibe status`，确保 bot 已被邀请到频道 |
| Token 错误 | 重新运行 `vibe init` 配置 |
| 找不到 Agent | 先安装 Claude Code 或 OpenCode |

---

## Uninstall | 卸载

```bash
vibe stop && uv tool uninstall vibe && rm -rf ~/.vibe_remote
```

---

## Docs | 文档

| Document | Description |
|----------|-------------|
| [AI Setup Guide](docs/AI_SETUP.md) | Instructions for AI assistants to install |
| [Slack Setup Guide](docs/SLACK_SETUP.md) | Manual Slack App creation with screenshots |
| [CLI Reference](docs/CLI.md) | Command-line usage |

---

## Contributing | 贡献

PRs welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

欢迎 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

<div align="center">

**Stop context-switching. Start vibe coding.**

**告别频繁切换，开始 vibe 编程。**

[GitHub](https://github.com/FL-Penly/slack-coder) · [Issues](https://github.com/FL-Penly/slack-coder/issues) · [Docs](docs/)

</div>
