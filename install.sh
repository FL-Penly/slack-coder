#!/usr/bin/env bash
# Slack Coder Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/FL-Penly/slack-coder/master/install.sh | bash
#
# Prerequisites: None! uv will be installed automatically and manages Python for you.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO="FL-Penly/slack-coder"
PACKAGE_NAME="slack-coder"

print_banner() {
    echo -e "${BLUE}"
    cat << 'EOF'
 __     __ _  _             ____                       _       
 \ \   / /(_)| |__    ___  |  _ \  ___  _ __ ___   ___ | |_  ___ 
  \ \ / / | || '_ \  / _ \ | |_) |/ _ \| '_ ` _ \ / _ \| __|/ _ \
   \ V /  | || |_) ||  __/ |  _ <|  __/| | | | | | (_) | |_|  __/
    \_/   |_||_.__/  \___| |_| \_\\___||_| |_| |_|\___/ \__|\___|
EOF
    echo -e "${NC}"
    echo -e "${GREEN}Local-first agent runtime for Slack${NC}"
    echo ""
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Detect OS
detect_os() {
    case "$(uname -s)" in
        Linux*)     OS="linux";;
        Darwin*)    OS="macos";;
        CYGWIN*|MINGW*|MSYS*) OS="windows";;
        *)          OS="unknown";;
    esac
    echo "$OS"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install uv if not present
install_uv() {
    if command_exists uv; then
        success "uv is already installed"
        return 0
    fi
    
    info "Installing uv (will also manage Python automatically)..."
    
    local os
    os=$(detect_os)
    
    case "$os" in
        macos|linux)
            curl -LsSf https://astral.sh/uv/install.sh | sh
            # Add to PATH for current session
            export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
            ;;
        windows)
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
            ;;
        *)
            error "Unsupported operating system"
            ;;
    esac
    
    if command_exists uv; then
        success "uv installed successfully"
    else
        # Try to find it in common locations
        if [ -f "$HOME/.local/bin/uv" ]; then
            export PATH="$HOME/.local/bin:$PATH"
            success "uv installed successfully"
        elif [ -f "$HOME/.cargo/bin/uv" ]; then
            export PATH="$HOME/.cargo/bin:$PATH"
            success "uv installed successfully"
        else
            error "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
        fi
    fi
}

# Install slack-coder using uv (uv auto-downloads Python if needed)
install_vibe() {
    info "Installing slack-coder (Python will be downloaded automatically if needed)..."
    
    # uv tool install will auto-download Python if not available
    # --force: reinstall even if already installed
    # --refresh: refresh package cache to get latest version
    # Try in order: PyPI -> China mirror (tsinghua) -> GitHub
    if uv tool install "$PACKAGE_NAME" --force --refresh 2>/dev/null; then
        success "slack-coder installed successfully (from PyPI)"
    elif uv tool install "$PACKAGE_NAME" --force --refresh --index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null; then
        success "slack-coder installed successfully (from Tsinghua mirror)"
    elif uv tool install "git+https://github.com/${REPO}.git" --force 2>/dev/null; then
        success "slack-coder installed successfully (from GitHub)"
    else
        error "Failed to install slack-coder from all sources"
    fi
}

# Verify installation
verify_installation() {
    info "Verifying installation..."
    
    # Refresh PATH
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    
    if command_exists slack-coder; then
        success "slack-coder command is available"
        echo ""
        slack-coder --help 2>/dev/null || true
        return 0
    fi
    
    # Check common install locations
    local slack_coder_locations=(
        "$HOME/.local/bin/slack-coder"
        "$HOME/.cargo/bin/slack-coder"
    )
    
    for loc in "${slack_coder_locations[@]}"; do
        if [ -f "$loc" ]; then
            warn "slack-coder installed at $loc but not in PATH"
            echo ""
            echo -e "${YELLOW}Add this to your shell config (.bashrc, .zshrc, etc.):${NC}"
            echo -e "  export PATH=\"$(dirname "$loc"):\$PATH\""
            echo ""
            return 0
        fi
    done
    
    error "Installation verification failed. slack-coder command not found."
}

# Print next steps
print_next_steps() {
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Run 'vibe' to start the setup wizard"
    echo "  2. Configure your Slack app tokens in the web UI"
    echo "  3. Enable channels and start chatting with AI agents"
    echo ""
    echo -e "${BLUE}Quick commands:${NC}"
    echo "  slack-coder          - Start Slack Coder (service + web UI)"
    echo "  slack-coder status   - Check service status"
    echo "  slack-coder stop     - Stop all services"
    echo "  slack-coder doctor   - Run diagnostics"
    echo ""
    echo -e "${BLUE}Uninstall:${NC}"
    echo "  uv tool uninstall slack-coder    # if installed with uv"
    echo "  pip uninstall slack-coder        # if installed with pip"
    echo "  rm -rf ~/.slack_coder            # remove config and data"
    echo ""
    echo -e "${BLUE}Documentation:${NC}"
    echo "  https://github.com/${REPO}#readme"
    echo ""
}

# Main installation flow
main() {
    print_banner
    
    local os
    os=$(detect_os)
    info "Detected OS: $os"
    
    # Install uv (which manages Python automatically)
    install_uv
    
    # Install slack-coder
    install_vibe
    
    # Verify
    verify_installation
    
    # Done
    print_next_steps
}

# Run main
main "$@"
