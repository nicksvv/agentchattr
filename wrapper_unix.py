"""Mac/Linux agent injection — uses tmux send-keys to type into the agent CLI.

Called by wrapper.py on Mac and Linux. Requires tmux to be installed.
  - Mac:   brew install tmux
  - Linux: apt install tmux  (or yum, pacman, etc.)

How it works:
  1. Creates a tmux session running the agent CLI
  2. Queue watcher sends keystrokes via 'tmux send-keys'
  3. Wrapper attaches to the session so you see the full TUI
  4. Ctrl+B, D to detach (agent keeps running in background)
"""

import shlex
import shutil
import subprocess
import sys
import time


def _check_tmux():
    """Verify tmux is installed, exit with helpful message if not."""
    if shutil.which("tmux"):
        return
    print("\n  Error: tmux is required for auto-trigger on Mac/Linux.")
    if sys.platform == "darwin":
        print("  Install: brew install tmux")
    else:
        print("  Install: apt install tmux  (or yum/pacman equivalent)")
    sys.exit(1)


def _run_tmux(args: list[str], *, timeout: float = 2.0):
    """Run tmux command with timeout and helpful error on failure."""
    result = subprocess.run(
        ["tmux"] + args,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.decode("utf-8", errors="ignore").strip()
    raise RuntimeError(
        f"tmux {' '.join(args)} failed (exit {result.returncode}): {stderr}"
    )


def inject(text: str, *, tmux_session: str):
    """Send text + Enter to a tmux session via send-keys."""
    # Use -l to send text literally (avoids misinterpreting as key names),
    # then submit with C-m (more reliable for TUIs than "Enter").
    # Target pane 0.0 explicitly to avoid keystrokes going to a wrong pane.
    target = f"{tmux_session}:0.0"
    _run_tmux(["send-keys", "-t", target, "-l", text])
    time.sleep(0.3)
    try:
        _run_tmux(["send-keys", "-t", target, "C-m"])
    except Exception:
        # Fallback for tmux/keymap edge-cases.
        _run_tmux(["send-keys", "-t", target, "Enter"])


def get_activity_checker(session_name):
    """Return a callable that detects tmux pane output by hashing content."""
    last_hash = [None]

    def check():
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p"],
                capture_output=True, timeout=2,
            )
            h = hash(result.stdout)
            changed = last_hash[0] is not None and h != last_hash[0]
            last_hash[0] = h
            return changed
        except Exception:
            return False

    return check


def run_agent(command, extra_args, cwd, env, queue_file, agent, no_restart, start_watcher, strip_env=None, pid_holder=None):
    """Run agent inside a tmux session, inject via tmux send-keys."""
    _check_tmux()

    session_name = f"agentchattr-{agent}"
    agent_cmd = " ".join(
        [shlex.quote(command)] + [shlex.quote(a) for a in extra_args]
    )

    # Prefix command with `env -u VAR ...` so env vars are unset inside the
    # tmux session. subprocess.run(env=...) only affects the tmux client
    # binary — the session shell inherits from the tmux server instead.
    if strip_env:
        unset_args = " ".join(f"-u {shlex.quote(v)}" for v in strip_env)
        agent_cmd = f"env {unset_args} {agent_cmd}"

    # Resolve cwd to absolute path (tmux -c needs it)
    from pathlib import Path
    abs_cwd = str(Path(cwd).resolve())

    # Wire up injection with the tmux session name
    inject_fn = lambda text: inject(text, tmux_session=session_name)
    start_watcher(inject_fn)

    print(f"  Using tmux session: {session_name}")
    print(f"  Detach: Ctrl+B, D  (agent keeps running)")
    print(f"  Reattach: tmux attach -t {session_name}\n")

    while True:
        try:
            # Clean up stale session from a previous crash
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
            )

            # Create tmux session running the agent CLI
            result = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name,
                 "-c", abs_cwd, agent_cmd],
                env=env,
            )
            if result.returncode != 0:
                print(f"  Error: failed to create tmux session (exit {result.returncode})")
                break

            # Attach — blocks until agent exits or user detaches (Ctrl+B, D)
            subprocess.run(["tmux", "attach-session", "-t", session_name])

            # Check: did the agent exit, or did the user just detach?
            check = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
            )
            if check.returncode == 0:
                # Session still alive — user detached, agent running in background
                print(f"\n  Detached. {agent.capitalize()} still running in tmux.")
                print(f"  Reattach: tmux attach -t {session_name}")
                break

            # Session gone — agent exited
            if no_restart:
                break

            print(f"\n  {agent.capitalize()} exited.")
            print(f"  Restarting in 3s... (Ctrl+C to quit)")
            time.sleep(3)
        except KeyboardInterrupt:
            # Kill the tmux session on Ctrl+C
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
            )
            break
