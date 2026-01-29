# Slack Coder Installation Script for Windows
# Usage: irm https://raw.githubusercontent.com/FL-Penly/slack-coder/master/install.ps1 | iex
#
# Prerequisites: None! uv will be installed automatically and manages Python for you.

$ErrorActionPreference = "Stop"

# Configuration
$REPO = "FL-Penly/slack-coder"
$PACKAGE_NAME = "slack-coder"

function Write-Banner {
    Write-Host @"
 __     __ _  _             ____                       _       
 \ \   / /(_)| |__    ___  |  _ \  ___  _ __ ___   ___ | |_  ___ 
  \ \ / / | || '_ \  / _ \ | |_) |/ _ \| '_ `` _ \ / _ \| __|/ _ \
   \ V /  | || |_) ||  __/ |  _ <|  __/| | | | | | (_) | |_|  __/
    \_/   |_||_.__/  \___| |_| \_\\___||_| |_| |_|\___/ \__|\___|
"@ -ForegroundColor Blue
    Write-Host "Local-first agent runtime for Slack" -ForegroundColor Green
    Write-Host ""
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] " -ForegroundColor Blue -NoNewline
    Write-Host $Message
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] " -ForegroundColor Red -NoNewline
    Write-Host $Message
    exit 1
}

function Test-Command {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

function Install-Uv {
    if (Test-Command "uv") {
        Write-Success "uv is already installed"
        return
    }
    
    Write-Info "Installing uv (will also manage Python automatically)..."
    
    try {
        irm https://astral.sh/uv/install.ps1 | iex
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        
        if (Test-Command "uv") {
            Write-Success "uv installed successfully"
        } else {
            # Check common locations
            $uvPath = "$env:USERPROFILE\.local\bin\uv.exe"
            if (Test-Path $uvPath) {
                $env:Path += ";$env:USERPROFILE\.local\bin"
                Write-Success "uv installed successfully"
            } else {
                throw "uv not found after installation"
            }
        }
    } catch {
        Write-Error "Failed to install uv. Please install it manually: https://docs.astral.sh/uv/"
    }
}

function Install-Vibe {
    Write-Info "Installing slack-coder (Python will be downloaded automatically if needed)..."
    
    # uv tool install will auto-download Python if not available
    try {
        & uv tool install $PACKAGE_NAME --force 2>$null
    } catch {
        & uv tool install "git+https://github.com/$REPO.git" --force
    }
    
    Write-Success "slack-coder installed successfully"
}

function Test-Installation {
    Write-Info "Verifying installation..."
    
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path += ";$env:USERPROFILE\.local\bin"
    
    if (Test-Command "slack-coder") {
        Write-Success "slack-coder command is available"
        Write-Host ""
        & slack-coder --help
        return $true
    }
    
    # Check common install locations
    $slackCoderLocations = @(
        "$env:USERPROFILE\.local\bin\slack-coder.exe"
    )
    
    foreach ($loc in $slackCoderLocations) {
        if (Test-Path $loc) {
            Write-Warning "slack-coder installed at $loc but not in PATH"
            Write-Host ""
            Write-Host "Add this directory to your PATH:" -ForegroundColor Yellow
            Write-Host "  $(Split-Path $loc)"
            Write-Host ""
            return $true
        }
    }
    
    Write-Error "Installation verification failed. slack-coder command not found."
}

function Write-NextSteps {
    Write-Host ""
    Write-Host "Installation complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Blue
    Write-Host "  1. Run 'vibe' to start the setup wizard"
    Write-Host "  2. Configure your Slack app tokens in the web UI"
    Write-Host "  3. Enable channels and start chatting with AI agents"
    Write-Host ""
    Write-Host "Quick commands:" -ForegroundColor Blue
    Write-Host "  slack-coder          - Start Slack Coder (service + web UI)"
    Write-Host "  slack-coder status   - Check service status"
    Write-Host "  slack-coder stop     - Stop all services"
    Write-Host "  slack-coder doctor   - Run diagnostics"
    Write-Host ""
    Write-Host "Uninstall:" -ForegroundColor Blue
    Write-Host "  uv tool uninstall slack-coder"
    Write-Host "  Remove-Item -Recurse ~\.slack_coder  # remove config and data"
    Write-Host ""
    Write-Host "Documentation:" -ForegroundColor Blue
    Write-Host "  https://github.com/$REPO#readme"
    Write-Host ""
}

# Main installation flow
function Main {
    Write-Banner
    
    Write-Info "Detected OS: Windows"
    
    # Install uv (which manages Python automatically)
    Install-Uv
    
    # Install slack-coder
    Install-Vibe
    
    # Verify
    Test-Installation
    
    # Done
    Write-NextSteps
}

# Run main
Main
