import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from config import paths
from config.v2_config import (
    AgentsConfig,
    ClaudeConfig,
    CodexConfig,
    OpenCodeConfig,
    RuntimeConfig,
    SlackConfig,
    V2Config,
)
from vibe import runtime
from vibe import api

logger = logging.getLogger(__name__)


class _Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"


def _print_header(text: str):
    print(f"\n{_Colors.CYAN}{'=' * 50}{_Colors.RESET}")
    print(f"{_Colors.BOLD}{text}{_Colors.RESET}")
    print(f"{_Colors.CYAN}{'=' * 50}{_Colors.RESET}\n")


def _print_status(ok: bool, message: str):
    icon = (
        f"{_Colors.GREEN}✓{_Colors.RESET}" if ok else f"{_Colors.RED}✗{_Colors.RESET}"
    )
    print(f"  {icon} {message}")


# i18n translations for cmd_init()
_INIT_TEXTS = {
    "en": {
        "title": "Slack Coder Setup",
        "lang_prompt": "Language / 语言 [1=中文, 2=English]: ",
        "existing_config": "Existing configuration found.",
        "reconfigure": "Reconfigure? [y/N]: ",
        "keeping_config": "Keeping existing configuration.",
        "step1": "Step 1: Detect AI Agents",
        "not_found": "not found",
        "no_agents": "No AI agents found. Please install opencode or claude first.",
        "configuring_opencode": "Configuring OpenCode permissions...",
        "permission_configured": "Permission configured: {path}",
        "permission_failed": "Permission setup failed: {message}",
        "step2": "Step 2: Configure Slack",
        "create_slack_app": "You need to create a Slack App and get tokens.",
        "press_enter_browser": "Press Enter to open browser and create Slack App...",
        "browser_opened": "Browser opened.",
        "ssh_detected": "SSH session detected. Please open this URL manually:",
        "create_app_manual": "Please create a Slack App manually: https://api.slack.com/apps",
        "after_creating": "After creating the app, get tokens:",
        "token_step1": "  1. {bold}OAuth & Permissions{reset} -> Install to Workspace -> Copy Bot Token",
        "token_step2": "  2. {bold}Basic Information{reset} -> App-Level Tokens -> Generate",
        "token_step3": "     Name: 'socket', Scope: {bold}connections:write{reset}",
        "bot_token_prompt": "Bot Token (xoxb-...): ",
        "bot_token_invalid": "Invalid format, should start with xoxb-",
        "app_token_prompt": "App Token (xapp-...): ",
        "app_token_invalid": "Invalid format, should start with xapp-",
        "validating": "Validating tokens...",
        "valid_workspace": "Valid! Workspace: {team}, Bot: {bot}",
        "validation_failed": "Validation failed: {error}",
        "continue_anyway": "Continuing anyway, please verify tokens are correct.",
        "step3": "Step 3: Set Working Directory",
        "workdir_prompt": "Working directory [{default}]: ",
        "dir_not_exist": "Directory doesn't exist. Create it? [Y/n]: ",
        "created": "Created: {path}",
        "step4": "Step 4: Save Configuration",
        "saved": "Saved: {path}",
        "start_now": "Start service now? [Y/n]: ",
        "starting": "Starting service...",
        "service_started": "Service started (PID: {pid})",
        "setup_complete": "Setup complete!",
        "next_steps": "Next steps:",
        "next_step1": "  1. In Slack: {bold}/invite @Slack Coder{reset}",
        "next_step2": "  2. Send: {bold}@Slack Coder hello{reset}",
        "run_doctor": "Run {bold}vibe doctor{reset} to check status",
    },
    "zh": {
        "title": "Slack Coder 设置向导",
        "lang_prompt": "Language / 语言 [1=中文, 2=English]: ",
        "existing_config": "发现已有配置。",
        "reconfigure": "重新配置？[y/N]: ",
        "keeping_config": "保留现有配置。",
        "step1": "步骤 1: 检测 AI 代理",
        "not_found": "未找到",
        "no_agents": "未找到 AI 代理。请先安装 opencode 或 claude。",
        "configuring_opencode": "正在配置 OpenCode 权限...",
        "permission_configured": "权限已配置: {path}",
        "permission_failed": "权限配置失败: {message}",
        "step2": "步骤 2: 配置 Slack",
        "create_slack_app": "您需要创建一个 Slack App 并获取令牌。",
        "press_enter_browser": "按 Enter 键打开浏览器创建 Slack App...",
        "browser_opened": "浏览器已打开。",
        "ssh_detected": "检测到 SSH 会话。请手动打开此 URL：",
        "create_app_manual": "请手动创建 Slack App: https://api.slack.com/apps",
        "after_creating": "创建应用后，获取令牌：",
        "token_step1": "  1. {bold}OAuth & Permissions{reset} -> Install to Workspace -> 复制 Bot Token",
        "token_step2": "  2. {bold}Basic Information{reset} -> App-Level Tokens -> Generate",
        "token_step3": "     名称: 'socket', 范围: {bold}connections:write{reset}",
        "bot_token_prompt": "Bot Token (xoxb-...): ",
        "bot_token_invalid": "格式无效，应以 xoxb- 开头",
        "app_token_prompt": "App Token (xapp-...): ",
        "app_token_invalid": "格式无效，应以 xapp- 开头",
        "validating": "正在验证令牌...",
        "valid_workspace": "验证成功！工作区: {team}, 机器人: {bot}",
        "validation_failed": "验证失败: {error}",
        "continue_anyway": "继续进行，请确认令牌正确。",
        "step3": "步骤 3: 设置工作目录",
        "workdir_prompt": "工作目录 [{default}]: ",
        "dir_not_exist": "目录不存在。是否创建？[Y/n]: ",
        "created": "已创建: {path}",
        "step4": "步骤 4: 保存配置",
        "saved": "已保存: {path}",
        "start_now": "现在启动服务？[Y/n]: ",
        "starting": "正在启动服务...",
        "service_started": "服务已启动 (PID: {pid})",
        "setup_complete": "设置完成！",
        "next_steps": "后续步骤：",
        "next_step1": "  1. 在 Slack 中: {bold}/invite @Slack Coder{reset}",
        "next_step2": "  2. 发送: {bold}@Slack Coder hello{reset}",
        "run_doctor": "运行 {bold}vibe doctor{reset} 检查状态",
    },
}


def _get_init_lang() -> str:
    """Prompt user to select language for init wizard."""
    print(f"\n{_Colors.BOLD}Slack Coder Setup / Slack Coder 设置向导{_Colors.RESET}\n")
    while True:
        choice = input(_INIT_TEXTS["en"]["lang_prompt"]).strip()
        if choice == "1":
            return "zh"
        elif choice == "2" or choice == "":
            return "en"
        print("Please enter 1 or 2 / 请输入 1 或 2")


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _in_ssh_session() -> bool:
    """Best-effort detection for SSH sessions."""
    return any(
        os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
    )


def _open_browser(url: str) -> bool:
    """Open a URL in the default browser (best effort).

    Returns True if a launch attempt was made successfully.
    """
    try:
        import webbrowser

        if webbrowser.open(url):
            return True
    except Exception:
        pass

    # Fallbacks for environments where webbrowser isn't configured.
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
            return True
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "", url])
            return True
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", url])
            return True
    except Exception:
        pass

    return False


def _default_config():
    return V2Config(
        mode="self_host",
        version="v2",
        slack=SlackConfig(bot_token="", app_token=""),
        runtime=RuntimeConfig(default_cwd=str(Path.cwd())),
        agents=AgentsConfig(
            default_backend="opencode",
            opencode=OpenCodeConfig(enabled=True, cli_path="opencode"),
            claude=ClaudeConfig(enabled=True, cli_path="claude"),
            codex=CodexConfig(enabled=False, cli_path="codex"),
        ),
    )


def _ensure_config():
    config_path = paths.get_config_path()
    if not config_path.exists():
        default = _default_config()
        default.save(config_path)
    return V2Config.load(config_path)


def _write_status(state, detail=None):
    payload = {
        "state": state,
        "detail": detail,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_json(paths.get_runtime_status_path(), payload)


def _spawn_background(
    args,
    pid_path,
    stdout_name: str = "service_stdout.log",
    stderr_name: str = "service_stderr.log",
):
    stdout_path = paths.get_runtime_dir() / stdout_name
    stderr_path = paths.get_runtime_dir() / stderr_name
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    process = subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    stdout.close()
    stderr.close()
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _stop_process(pid_path):
    if not pid_path.exists():
        return False
    pid = int(pid_path.read_text(encoding="utf-8").strip())
    if not _pid_alive(pid):
        pid_path.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    pid_path.unlink(missing_ok=True)
    return True


def cmd_init():
    lang = _get_init_lang()
    t = _INIT_TEXTS[lang]

    print(f"\n{_Colors.BOLD}{t['title']}{_Colors.RESET}\n")

    paths.ensure_data_dirs()
    config_path = paths.get_config_path()

    if config_path.exists():
        print(f"{_Colors.YELLOW}{t['existing_config']}{_Colors.RESET}")
        response = input(t["reconfigure"]).strip().lower()
        if response != "y":
            print(t["keeping_config"])
            return 0

    _print_header(t["step1"])

    agents_config = {}
    default_backend = "opencode"

    for name in ["opencode", "claude", "codex"]:
        result = api.detect_cli(name)
        if result["found"]:
            _print_status(True, f"{name}: {result['path']}")
            agents_config[name] = {"enabled": True, "cli_path": result["path"]}
            if name == "opencode":
                default_backend = "opencode"
            elif name == "claude" and default_backend != "opencode":
                default_backend = "claude"
        else:
            _print_status(False, f"{name}: {t['not_found']}")
            agents_config[name] = {"enabled": False, "cli_path": name}

    if not any(a["enabled"] for a in agents_config.values()):
        print(f"\n{_Colors.RED}{t['no_agents']}{_Colors.RESET}")
        return 1

    if agents_config.get("opencode", {}).get("enabled"):
        print(f"\n{t['configuring_opencode']}")
        perm_result = api.setup_opencode_permission()
        if perm_result["ok"]:
            _print_status(
                True, t["permission_configured"].format(path=perm_result["config_path"])
            )
        else:
            _print_status(
                False, t["permission_failed"].format(message=perm_result["message"])
            )

    _print_header(t["step2"])

    manifest_result = api.get_slack_manifest()
    if manifest_result["ok"] and manifest_result.get("manifest_compact"):
        import urllib.parse

        manifest_url = f"https://api.slack.com/apps?new_app=1&manifest_json={urllib.parse.quote(manifest_result['manifest_compact'])}"
        print(t["create_slack_app"])
        print(f"\n{_Colors.CYAN}{t['press_enter_browser']}{_Colors.RESET}")
        input()

        if not _in_ssh_session():
            _open_browser(manifest_url)
            print(t["browser_opened"])
        else:
            print(t["ssh_detected"])
            print(f"\n{manifest_url}\n")
    else:
        print(t["create_app_manual"])

    print(f"\n{t['after_creating']}")
    print(t["token_step1"].format(bold=_Colors.BOLD, reset=_Colors.RESET))
    print(t["token_step2"].format(bold=_Colors.BOLD, reset=_Colors.RESET))
    print(t["token_step3"].format(bold=_Colors.BOLD, reset=_Colors.RESET) + "\n")

    bot_token = ""
    while not bot_token.startswith("xoxb-"):
        bot_token = input(t["bot_token_prompt"]).strip()
        if not bot_token.startswith("xoxb-"):
            print(f"{_Colors.RED}{t['bot_token_invalid']}{_Colors.RESET}")

    app_token = ""
    while not app_token.startswith("xapp-"):
        app_token = input(t["app_token_prompt"]).strip()
        if not app_token.startswith("xapp-"):
            print(f"{_Colors.RED}{t['app_token_invalid']}{_Colors.RESET}")

    print(f"\n{t['validating']}")
    auth_result = api.slack_auth_test(bot_token)
    if auth_result["ok"]:
        response = auth_result.get("response", {})
        team_name = response.get("team", "Unknown")
        bot_name = response.get("user", "Bot")
        _print_status(True, t["valid_workspace"].format(team=team_name, bot=bot_name))
    else:
        _print_status(
            False, t["validation_failed"].format(error=auth_result.get("error"))
        )
        print(f"{_Colors.YELLOW}{t['continue_anyway']}{_Colors.RESET}")

    _print_header(t["step3"])

    default_cwd = str(Path.cwd())
    work_dir = input(
        t["workdir_prompt"].format(default=f"{_Colors.DIM}{default_cwd}{_Colors.RESET}")
    ).strip()
    if not work_dir:
        work_dir = default_cwd
    work_dir = os.path.expanduser(work_dir)
    work_dir = os.path.abspath(work_dir)

    if not os.path.exists(work_dir):
        create = input(t["dir_not_exist"]).strip().lower()
        if create != "n":
            os.makedirs(work_dir, exist_ok=True)
            _print_status(True, t["created"].format(path=work_dir))

    _print_header(t["step4"])

    config = V2Config(
        mode="self_host",
        version="v2",
        slack=SlackConfig(
            bot_token=bot_token, app_token=app_token, require_mention=False
        ),
        runtime=RuntimeConfig(default_cwd=work_dir, log_level="INFO"),
        agents=AgentsConfig(
            default_backend=default_backend,
            opencode=OpenCodeConfig(
                enabled=agents_config.get("opencode", {}).get("enabled", False),
                cli_path=agents_config.get("opencode", {}).get("cli_path", "opencode"),
            ),
            claude=ClaudeConfig(
                enabled=agents_config.get("claude", {}).get("enabled", False),
                cli_path=agents_config.get("claude", {}).get("cli_path", "claude"),
            ),
            codex=CodexConfig(
                enabled=agents_config.get("codex", {}).get("enabled", False),
                cli_path=agents_config.get("codex", {}).get("cli_path", "codex"),
            ),
        ),
    )
    config.save(config_path)
    _print_status(True, t["saved"].format(path=config_path))

    start_now = input(f"\n{t['start_now']}").strip().lower()
    if start_now != "n":
        print(f"\n{t['starting']}")
        runtime.stop_service()
        service_pid = runtime.start_service()
        runtime.write_status("running", f"pid={service_pid}", service_pid)
        _print_status(True, t["service_started"].format(pid=service_pid))

    print(f"\n{_Colors.GREEN}{'=' * 50}{_Colors.RESET}")
    print(f"{_Colors.BOLD}{t['setup_complete']}{_Colors.RESET}")
    print(f"{_Colors.GREEN}{'=' * 50}{_Colors.RESET}")
    print(f"\n{t['next_steps']}")
    print(t["next_step1"].format(bold=_Colors.BOLD, reset=_Colors.RESET))
    print(t["next_step2"].format(bold=_Colors.BOLD, reset=_Colors.RESET))
    print(f"\n{t['run_doctor'].format(bold=_Colors.BOLD, reset=_Colors.RESET)}\n")

    return 0


def _is_service_running():
    pid_path = paths.get_runtime_pid_path()
    if not pid_path.exists():
        return False, None
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        if _pid_alive(pid):
            return True, pid
    except (ValueError, OSError):
        pass
    return False, None


def cmd_vibe():
    paths.ensure_data_dirs()
    config_path = paths.get_config_path()

    needs_init = False
    if not config_path.exists():
        needs_init = True
    else:
        try:
            config = V2Config.load(config_path)
            if not config.slack.bot_token or not config.slack.app_token:
                needs_init = True
        except Exception:
            needs_init = True

    if needs_init:
        print(
            f"{_Colors.YELLOW}No valid configuration found. Starting setup...{_Colors.RESET}\n"
        )
        return cmd_init()

    running, pid = _is_service_running()
    if running:
        print(
            f"{_Colors.GREEN}Slack Coder is already running (PID: {pid}){_Colors.RESET}"
        )
        print(f"\nTo restart: {_Colors.BOLD}vibe stop && vibe{_Colors.RESET}")
        return 0

    config = V2Config.load(config_path)

    _write_status("starting")

    service_pid = runtime.start_service()
    runtime.write_status("running", "pid={}".format(service_pid), service_pid)

    print(f"{_Colors.GREEN}Slack Coder started (PID: {service_pid}){_Colors.RESET}")
    print(f"\nTo stop: {_Colors.BOLD}vibe stop{_Colors.RESET}")

    return 0


def _stop_opencode_server():
    """Terminate the OpenCode server if running."""
    pid_file = paths.get_logs_dir() / "opencode_server.json"
    if not pid_file.exists():
        return False

    try:
        info = json.loads(pid_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Failed to parse OpenCode PID file: %s", e)
        return False

    pid = info.get("pid") if isinstance(info, dict) else None
    if not isinstance(pid, int) or not _pid_alive(pid):
        pid_file.unlink(missing_ok=True)
        return False

    # Verify it's actually an opencode serve process
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
        )
        cmd = result.stdout.strip()
        if "opencode" not in cmd or "serve" not in cmd:
            return False
    except Exception as e:
        logger.debug("Failed to verify OpenCode process (pid=%s): %s", pid, e)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.warning("Failed to stop OpenCode server (pid=%s): %s", pid, e)
        return False


def cmd_stop():
    running, pid = _is_service_running()
    if not running:
        print(f"{_Colors.YELLOW}Slack Coder is not running{_Colors.RESET}")
        return 0

    runtime.stop_service()

    if _stop_opencode_server():
        print("OpenCode server stopped")

    _write_status("stopped")
    print(f"{_Colors.GREEN}Slack Coder stopped{_Colors.RESET}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="vibe", description="Slack Coder - AI coding agent for Slack"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Interactive setup wizard")
    subparsers.add_parser("stop", help="Stop service")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        sys.exit(cmd_init())
    if args.command == "stop":
        sys.exit(cmd_stop())
    sys.exit(cmd_vibe())
