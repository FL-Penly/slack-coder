# AI Setup Instructions for Slack Coder

> **FOR AI ASSISTANTS**: This document contains step-by-step instructions for you to help a user install and configure Slack Coder. Execute each step, verify success, and proceed. When user input is required, STOP and ask clearly.

---

## OVERVIEW

**What is Slack Coder?**
A local service that connects Slack to AI coding agents (Claude Code, OpenCode). Users can send coding tasks from Slack, and the AI agent executes them on their machine.

**End Goal:**
After completing this setup, the user runs `vibe init` which handles Slack App creation, token configuration, and service startup interactively.

**Your Role:**
1. Install prerequisites (uv, Node.js if needed)
2. Install Slack Coder via uv
3. Install at least one AI agent (Claude Code or OpenCode)
4. **Tell user to run `vibe init`** - the wizard handles everything else

---

## STEP 1: Check System Requirements

Run these commands and report results:

```bash
# Check OS
uname -s

# Check Python version (need 3.10+)
python3 --version

# Check if uv is installed
uv --version 2>/dev/null || echo "uv not installed"

# Check if Node.js is installed (needed for Claude Code)
node --version 2>/dev/null || echo "node not installed"

# Check if npm is installed
npm --version 2>/dev/null || echo "npm not installed"
```

### If uv is NOT installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null
```

### If Node.js is NOT installed (and user wants Claude Code):

**macOS:**
```bash
brew install node
```

**Linux (Ubuntu/Debian):**
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

---

## STEP 2: Install Slack Coder

```bash
uv tool install git+https://github.com/FL-Penly/slack-coder.git
```

**Verify installation:**
```bash
vibe --help
```

Expected output should show available commands: `init`, `status`, `stop`, `doctor`, etc.

**If command not found**, add uv tools to PATH:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
# Or for zsh:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

---

## STEP 3: Install AI Agent(s)

Check which agents are already installed:

```bash
# Check Claude Code
claude --version 2>/dev/null && echo "Claude Code: installed" || echo "Claude Code: not installed"

# Check OpenCode  
opencode --version 2>/dev/null && echo "OpenCode: installed" || echo "OpenCode: not installed"
```

### If BOTH are already installed:
Skip to Step 4.

### If NEITHER is installed - Ask the user:

> "Which AI agent would you like to use?
> 1. **Claude Code** - Best for complex reasoning and refactoring (requires Anthropic API key)
> 2. **OpenCode** - Fast and extensible (requires API key for your chosen provider)
> 3. **Both** - Install both for flexibility
> 
> Which do you prefer? (1/2/3)"

---

### Option 1: Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

**Verify:**
```bash
claude --version
```

**Note:** User will need an Anthropic API key. They can set it up when first running Claude Code, or set `ANTHROPIC_API_KEY` environment variable.

---

### Option 2: Install OpenCode

```bash
curl -fsSL https://opencode.ai/install | bash
```

**Verify:**
```bash
opencode --version
```

---

## STEP 4: Run Setup Wizard

**IMPORTANT: This is where you STOP and let the user take over.**

Tell the user:

> "All prerequisites are installed! Now run the setup wizard:
>
> ```bash
> vibe init
> ```
>
> The wizard will:
> 1. Detect your installed AI agents
> 2. Open your browser to create a Slack App (with pre-filled settings)
> 3. Guide you to get the required tokens
> 4. Validate everything and start the service
>
> **Please run `vibe init` now and follow the prompts.**"

### **STOP HERE** - Wait for user to complete `vibe init`

The `vibe init` wizard is interactive and handles:
- Slack App creation (opens browser with pre-filled manifest)
- Token input and validation
- Working directory setup
- Service startup

---

## STEP 5: Verify Setup

After user completes `vibe init`, verify:

```bash
# Check service status
vibe status

# Run diagnostics
vibe doctor
```

**Expected output for `vibe status`:**
```
Slack Coder is already running (PID: xxxxx)
```

**If not running:**
```bash
vibe
```

---

## STEP 6: Test in Slack

Guide the user:

> "Final step! Let's test in Slack:
>
> 1. Open Slack
> 2. Go to any channel
> 3. Type: `/invite @Slack Coder`
> 4. Then send: `@Slack Coder hello`
>
> You should see a response from the AI agent. If it works, setup is complete!"

---

## TROUBLESHOOTING

### Bot doesn't respond in Slack

```bash
# Check logs
cat ~/.vibe_remote/logs/vibe_remote.log | tail -50

# Run diagnostics
vibe doctor

# Restart service
vibe stop && vibe
```

### "Command not found: vibe"

```bash
# Add to PATH
export PATH="$HOME/.local/bin:$PATH"

# Make permanent
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc  # or ~/.bashrc
source ~/.zshrc
```

### Token validation failed

- Verify Bot Token starts with `xoxb-`
- Verify App Token starts with `xapp-`
- Ensure App Token has `connections:write` scope
- Re-run `vibe init` to reconfigure

### Agent not responding

```bash
# Test Claude Code directly
claude --version

# Test OpenCode directly
opencode --version

# Check if API keys are set
echo $ANTHROPIC_API_KEY  # for Claude
```

---

## SUCCESS CRITERIA

Setup is complete when:

- [ ] `vibe status` shows "running"
- [ ] `vibe doctor` shows no errors
- [ ] `@Slack Coder hello` in Slack gets a response
- [ ] User can send a coding task like `@Slack Coder list files in current directory`

---

## QUICK REFERENCE

| Command | Description |
|---------|-------------|
| `vibe init` | Interactive setup wizard |
| `vibe` | Start the service |
| `vibe status` | Check if running |
| `vibe stop` | Stop the service |
| `vibe doctor` | Diagnose issues |

| In Slack | Description |
|----------|-------------|
| `@Slack Coder /start` | Open control panel |
| `@Slack Coder hello` | Test the bot |
| `@Slack Coder <task>` | Send coding task |

---

## SUMMARY FOR AI

**Execution Flow:**
1. Check/install uv → `uv --version`
2. Install slack-coder → `uv tool install git+https://github.com/FL-Penly/slack-coder.git`
3. Check/install AI agent → Claude Code or OpenCode
4. **STOP** → Tell user to run `vibe init` (handles Slack App creation, tokens, everything)
5. Verify → `vibe status`, `vibe doctor`
6. Test → User sends message in Slack

**Key Points:**
- `vibe init` is the interactive wizard that handles ALL configuration
- Do NOT manually guide Slack App creation - `vibe init` does this better (opens browser with pre-filled manifest)
- Your job is to prepare the environment; `vibe init` handles the rest
