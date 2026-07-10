import subprocess

from .dry_run import guarded

# Substrings matched case-insensitively against WM_CLASS to decide what NOT
# to minimize. Covers common Linux terminal emulators, not just whatever's
# running today -- untuned, easy to extend if it misses one.
PROTECTED_WM_CLASS_SUBSTRINGS = ["erminal", "konsole", "alacritty", "kitty", "xterm"]


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=3)


def _list_window_ids():
    result = _run(["xprop", "-root", "_NET_CLIENT_LIST"])
    if result.returncode != 0:
        return []
    # e.g. "_NET_CLIENT_LIST(WINDOW): window id # 0x1e00610, 0x1e00614"
    _, _, ids_part = result.stdout.partition("#")
    return [part.strip() for part in ids_part.split(",") if part.strip()]


def _window_class(window_id):
    result = _run(["xprop", "-id", window_id, "WM_CLASS"])
    return result.stdout if result.returncode == 0 else ""


def _is_protected(window_class_output):
    lowered = window_class_output.lower()
    return any(substring.lower() in lowered for substring in PROTECTED_WM_CLASS_SUBSTRINGS)


@guarded(lambda: "minimize all windows except terminal")
def minimize_all_except_terminal():
    for window_id in _list_window_ids():
        if _is_protected(_window_class(window_id)):
            continue
        subprocess.run(["xdotool", "windowminimize", window_id], timeout=3)
