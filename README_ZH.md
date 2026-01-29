<div align="center">

<img src="assets/logo.png" alt="Slack Coder" width="120"/>

# Slack Coder

### 在 Slack 中控制 AI 编程助手

**无需电脑，无需 IDE，随时随地编程**

[![GitHub Stars](https://img.shields.io/github/stars/FL-Penly/slack-coder?color=ffcb47&labelColor=black&style=flat-square)](https://github.com/FL-Penly/slack-coder/stargazers)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green?labelColor=black&style=flat-square)](LICENSE)

[English](README.md) | **简体中文**

</div>

---

## 给 AI 助手

> **如果你是 AI 助手，正在帮用户安装 Slack Coder，请读取以下 URL：**
>
> ```
> https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
> ```
>
> 里面有详细的安装步骤供你执行。

---

## 这是什么？

Slack Coder 将你的 Slack 工作区连接到 AI 编程助手（如 **Claude Code** 和 **OpenCode**）。在 Slack 中发消息，AI 就会在你的电脑上写代码。

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     你       │  Slack  │ Slack Coder  │  stdio  │  AI Agent    │
│  (任何地方)   │ ──────▶ │  (你的电脑)   │ ──────▶ │  (你的代码)   │
└──────────────┘         └──────────────┘         └──────────────┘
```

**代码不会离开你的电脑。** Slack Coder 在本地运行。

---

## 快速开始

### 让 AI 帮你安装

只需告诉你的 AI 助手（Claude Code、Cursor 等）：

```
帮我安装 Slack Coder。请阅读这个安装指南：
https://raw.githubusercontent.com/FL-Penly/slack-coder/master/docs/AI_SETUP.md
```

AI 会帮你安装所有依赖，并引导你创建 Slack App。

### 手动安装

```bash
# 安装
uv tool install git+https://github.com/FL-Penly/slack-coder.git

# 配置向导
vibe init

# 启动
vibe
```

---

## 功能特点

| 功能 | 描述 |
|------|------|
| **Thread = Session** | 每个 Slack 线程是独立的工作区，可并行执行多个任务 |
| **交互式提示** | Agent 需要输入时，Slack 会弹出按钮/对话框，无需终端 |
| **多 Agent 支持** | 按频道或消息切换 Claude Code、OpenCode、Codex |
| **Git Diff 预览** | 以 GitHub Gist 形式查看未提交的代码变更 |
| **会话恢复** | 支持恢复之前的会话，重启后继续工作 |

---

## 使用方法

### 在 Slack 中

| 命令 | 描述 |
|------|------|
| `@bot 你好` | 开始与 AI 对话 |
| `@bot /start` | 打开控制面板 |
| `@bot /stop` | 停止当前会话 |
| `@bot /diff` | 显示 Git 变更 |
| `claude: <消息>` | 指定使用某个 Agent |

### 命令行

```bash
vibe          # 启动服务
vibe status   # 查看状态
vibe stop     # 停止服务
vibe doctor   # 诊断问题
vibe init     # 重新配置
```

---

## 支持的 Agent

| Agent | 安装命令 | 适用场景 |
|-------|----------|----------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `npm i -g @anthropic-ai/claude-code` | 复杂推理、代码重构 |
| [OpenCode](https://opencode.ai) | `curl -fsSL https://opencode.ai/install \| bash` | 快速迭代、可扩展 |
| [Codex](https://github.com/openai/codex) | `npm i -g @openai/codex` | 快速实验 |

---

## 安全性

- **本地优先** — 在你的电脑上运行，不是服务器
- **Socket 模式** — 无需公开 URL，无需暴露 webhook
- **你的令牌** — 存储在本地 `~/.vibe_remote/`
- **你的代码** — 不会上传，只发送给你选择的 AI 提供商

---

## 故障排查

```bash
# 查看日志
cat ~/.vibe_remote/logs/vibe_remote.log | tail -50

# 运行诊断
vibe doctor

# 重启
vibe stop && vibe
```

| 问题 | 解决方案 |
|------|----------|
| Bot 不响应 | 检查 `vibe status`，确保 bot 已被邀请到频道 |
| Token 错误 | 重新运行 `vibe init` 配置 |
| 找不到 Agent | 先安装 Claude Code 或 OpenCode |

---

## 卸载

```bash
vibe stop && uv tool uninstall vibe && rm -rf ~/.vibe_remote
```

---

## 文档

| 文档 | 描述 |
|------|------|
| [AI 安装指南](docs/AI_SETUP.md) | AI 助手安装说明 |
| [Slack 配置指南](docs/SLACK_SETUP_ZH.md) | 手动创建 Slack App |
| [CLI 参考](docs/CLI_ZH.md) | 命令行使用说明 |

---

## 贡献

欢迎 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

<div align="center">

**告别频繁切换，开始 vibe 编程。**

[GitHub](https://github.com/FL-Penly/slack-coder) · [Issues](https://github.com/FL-Penly/slack-coder/issues) · [文档](docs/)

</div>
