# AI Setup Instructions for Slack Coder

> **FOR AI ASSISTANTS**: This document contains step-by-step instructions for you to help a user install and configure Slack Coder. Execute each step, verify success, and proceed. When user input is required, STOP and ask clearly.

---

## OVERVIEW

**What is Slack Coder?**
A local service that connects Slack to AI coding agents (Claude Code, OpenCode). Users can send coding tasks from Slack, and the AI agent executes them on their machine.

**End Goal:**
After completing this setup, the user runs `vibe init` and `vibe` to start the service, then uses `@Slack Coder` in Slack to interact with AI coding agents.

**Your Role:**
1. Install prerequisites (uv, Node.js if needed)
2. Install Slack Coder via uv
3. Install at least one AI agent (Claude Code or OpenCode)
4. Guide user through Slack App creation (requires manual steps)
5. Verify everything works

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

### **STOP HERE** - Ask the user:

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

**Configure auto-approve (required for non-interactive use):**
```bash
mkdir -p ~/.config/opencode
cat > ~/.config/opencode/opencode.json << 'EOF'
{
  "permission": "allow"
}
EOF
```

---

## STEP 4: Create Slack App

### **STOP HERE** - This requires user action in browser.

Tell the user:

> "Now we need to create a Slack App. This requires a few manual steps in your browser.
>
> **Please do the following:**
>
> 1. Open this URL: https://api.slack.com/apps
> 2. Click **'Create New App'**
> 3. Choose **'From a manifest'**
> 4. Select your workspace
> 5. Choose **YAML** format
> 6. Paste the manifest below and click **Create**"

---

### Slack App Manifest (YAML)

```yaml
display_information:
  name: Slack Coder
  description: AI coding agent runtime for Slack
  background_color: "#262626"
features:
  bot_user:
    display_name: Slack Coder
    always_online: true
  app_home:
    home_tab_enabled: true
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
oauth_config:
  scopes:
    bot:
      - channels:history
      - channels:read
      - chat:write
      - app_mentions:read
      - users:read
      - commands
      - groups:read
      - groups:history
      - im:history
      - im:read
      - im:write
      - mpim:history
      - mpim:read
      - mpim:write
      - files:read
      - files:write
      - reactions:read
      - reactions:write
settings:
  event_subscriptions:
    bot_events:
      - message.channels
      - message.groups
      - message.im
      - message.mpim
      - app_mention
      - app_home_opened
      - reaction_added
      - reaction_removed
  interactivity:
    is_enabled: true
  org_deploy_enabled: true
  socket_mode_enabled: true
  token_rotation_enabled: false
```

---

### Get Tokens

After creating the app, guide the user:

> "Great! Now we need two tokens:
>
> **Token 1 - Bot Token:**
> 1. In your Slack App settings, go to **'OAuth & Permissions'** in the left sidebar
> 2. Click **'Install to Workspace'** and authorize
> 3. Copy the **'Bot User OAuth Token'** (starts with `xoxb-`)
>
> **Token 2 - App Token:**
> 1. Go to **'Basic Information'** in the left sidebar
> 2. Scroll down to **'App-Level Tokens'**
> 3. Click **'Generate Token and Scopes'**
> 4. Name it `socket`
> 5. Add scope: `connections:write`
> 6. Click **Generate**
> 7. Copy the token (starts with `xapp-`)
>
> Please provide both tokens."

### **STOP HERE** - Wait for user to provide:
1. Bot Token (xoxb-...)
2. App Token (xapp-...)

---

## STEP 5: Run Interactive Setup

Now that prerequisites are installed, run the interactive setup wizard:

```bash
vibe init
```

This will:
1. Detect installed AI agents
2. Prompt for Slack tokens (user provides the tokens from Step 4)
3. Set working directory
4. Save configuration
5. Optionally start the service

**Tell the user:**
> "Run `vibe init` now. It will ask for:
> - Language preference (Chinese/English)
> - The Slack tokens you just copied
> - Your project's working directory (where AI will read/write code)
>
> After completing the wizard, the service will start automatically."

---

## STEP 6: Verify Setup

After `vibe init` completes:

```bash
# Check service status
vibe status

# Run diagnostics
vibe doctor
```

**Expected output for `vibe status`:**
```
Service is running (PID: xxxxx)
```

**If not running, start manually:**
```bash
vibe
```

---

## STEP 7: Test in Slack

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
- Try reinstalling the Slack App to workspace

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
4. **STOP** → Guide user through Slack App creation (browser required)
5. **STOP** → Get tokens from user
6. Run `vibe init` → User completes interactive wizard
7. Verify → `vibe status`, `vibe doctor`
8. Test → User sends message in Slack

**Key Points:**
- Steps 4-5 require user interaction (browser + copy tokens)
- Step 6 (`vibe init`) is interactive - user runs it themselves
- You prepare the environment; user completes the wizard
