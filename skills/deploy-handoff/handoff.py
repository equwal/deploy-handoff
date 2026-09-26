"""Open a web page and wait while the user does a step that only a human may do.

A tool calls this script when it reaches a step that an AI agent must not do:
the final deploy, publish, or billing click, a sign-in, an OAuth consent, or
the creation of a GitHub pull request. The script opens the page in the
default browser and shows a small dialog with the steps. It never clicks for
the user. It prints the answer of the user as one JSON object on stdout.

The command "browser" starts a separate browser for the browser-driver agent of
this plugin. Playwright MCP controls that browser through a local port.

Exit codes: 0 done, started, or running, 1 error, 2 bad arguments, 3 not done,
4 timeout.
"""

import argparse
import contextlib
import ctypes
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tkinter as tk
import tomllib
import urllib.request
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from urllib.parse import quote, urlencode, urlsplit

SHIPPED_CONFIG = Path(__file__).with_name("config.toml")
USER_CONFIG = (
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    / "deploy-handoff"
    / "config.toml"
)
# The browser-driver agent uses a browser with its own profile. Playwright MCP controls it
# through this remote debugging port. .mcp.json at the root of the plugin uses the same port.
DEBUG_PORT = 9333
BROWSER_PROFILE = USER_CONFIG.with_name("browser")
# The time in seconds that a new browser gets to open DEBUG_PORT.
BROWSER_START_SECONDS = 30
# The browser listens on 127.0.0.1. A proxy must not get these requests.
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# GitHub refuses very long request lines. This limit keeps a margin.
MAX_PR_URL_LENGTH = 8000
EXIT_CODES = {"done": 0, "started": 0, "running": 0, "error": 1, "not_done": 3, "timeout": 4}
# ASD-STE100 Simplified Technical English allows 20 words in one instruction.
MAX_STEP_WORDS = 20
PR_STEPS = (
    "Make sure that the branches, the title, and the description are correct.",
    'Click "Create pull request".',
)
HEADING = "Do these steps in your browser:"
FINISH = (
    'When you finish, click "Done".\n'
    'If you cannot finish, write the reason in the note. Then click "Not done".'
)
WARNING = (
    "Claude does not click for you. Before you sign in, make sure that the address bar "
    "shows the site above. Do not type a password, key, or card number in this window."
)

# A plain DNS name in lowercase ASCII. The script refuses all other host forms,
# so the browser and this script always read the same host from a URL.
HOST_RE = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
# Printable ASCII without a space. Callers percent-encode all other characters.
URL_CHARS_RE = re.compile(r"[!-~]+")
REPO_RE = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
GITHUB_REMOTE_RE = re.compile(
    r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<repo>[A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?"
)


class HandoffError(Exception):
    """The script cannot start the handoff. The message tells the caller why."""


@dataclass(frozen=True)
class Request:
    """A page to open, and the steps that the user must do on it."""

    title: str
    url: str
    steps: tuple[str, ...]
    # For a pull request: the repository as "owner/name", and the head branch.
    pr: tuple[str, str] | None = None


def match_domain(host: str, domains: Iterable[str]) -> str | None:
    """Return the most specific domain that is host or a parent domain of host."""
    matches = [domain for domain in domains if host == domain or host.endswith("." + domain)]
    return max(matches, key=len, default=None)


def check_url(url: str, domains: Iterable[str]) -> str:
    """Return the domain that allows url. Raise HandoffError if the script must not open url."""
    if "\\" in url or not URL_CHARS_RE.fullmatch(url):
        raise HandoffError(
            f"The URL must be printable ASCII with no spaces or backslashes: {url!r}"
        )
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise HandoffError(f"The URL is not valid: {url}") from exc
    host = parts.hostname or ""
    # The netloc must be the host only: no user name, no password, and no port.
    if parts.scheme != "https" or parts.netloc.lower() != host or not HOST_RE.fullmatch(host):
        raise HandoffError(f"The URL must use https and a plain host name: {url}")
    domain = match_domain(host, domains)
    if domain is None:
        raise HandoffError(
            f"{host} is not an allowed host. Ask the user to add it to allowed_hosts in "
            f"{USER_CONFIG}. Do not add it yourself."
        )
    return domain


def check_text(title: str, steps: Iterable[str]) -> None:
    """Raise HandoffError if the title or a step is not short Simplified Technical English."""
    named = [("The title", title), *((f"Step {n}", step) for n, step in enumerate(steps, 1))]
    for name, text in named:
        words = len(text.split())
        if not 0 < words <= MAX_STEP_WORDS or ";" in text:
            raise HandoffError(
                f"{name} is not short Simplified Technical English ({words} words). "
                f"Give one action in 1 to {MAX_STEP_WORDS} words, with no semicolons."
            )


def read_hosts(path: Path) -> list[str]:
    """Return the allowed_hosts list of the TOML file at path."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HandoffError(f"Cannot read {path}: {exc}") from exc
    hosts = data.get("allowed_hosts", [])
    if not isinstance(hosts, list) or not all(
        isinstance(host, str) and HOST_RE.fullmatch(host) for host in hosts
    ):
        raise HandoffError(f"{path}: allowed_hosts must be a list of lowercase host names.")
    return hosts


def allowed_hosts() -> list[str]:
    """Return the hosts in the shipped file, and in the user file if it exists."""
    paths = [SHIPPED_CONFIG, USER_CONFIG] if USER_CONFIG.is_file() else [SHIPPED_CONFIG]
    return [host for path in paths for host in read_hosts(path)]


def open_page(url: str) -> None:
    """Open url in a new tab of the default browser. BROWSER can name a different browser."""
    if not webbrowser.open(url, new=2):
        raise HandoffError("No browser opened the page. Set the BROWSER environment variable.")


def browser_candidates() -> list[Path]:
    """Return the usual paths of Brave and Chrome on this system. Brave comes first."""
    if sys.platform == "win32":
        roots = [
            os.environ.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        ]
        programs = (
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Google\Chrome\Application\chrome.exe",
        )
        return [Path(root, program) for program in programs for root in roots if root]
    if sys.platform == "darwin":
        return [
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    names = ("brave-browser", "brave", "google-chrome", "chromium", "chromium-browser")
    return [Path(path) for name in names if (path := shutil.which(name))]


def find_browser(candidates: Iterable[Path]) -> Path:
    """Return the first candidate that is a file."""
    for path in candidates:
        if path.is_file():
            return path
    raise HandoffError("Found no Brave or Chrome. Give --exe PATH.")


def browser_command(exe: Path, profile: Path, port: int) -> list[str]:
    """Return the command that starts the browser of the browser-driver agent."""
    return [
        str(exe),
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
        # Start with no window. With this flag and a remote debugging port, Chromium keeps
        # running after its last window closes. Without it, the browser stops when a person or
        # a program closes its window, and the agent cannot connect to the port.
        "--no-startup-window",
        "--no-first-run",
        "--no-default-browser-check",
        # Keep the pages active when other windows cover the window of this browser.
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]


def debug_version(port: int) -> dict[str, object] | None:
    """Return the version data of the browser that listens on port, or None if none answers."""
    try:
        with LOCAL_OPENER.open(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
            data = json.load(response)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return data if isinstance(data, dict) else None


def start_browser(command: list[str]) -> None:
    """Start the browser in a new process group, so that it runs after this script ends."""
    devnull = subprocess.DEVNULL
    try:
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                command, stdin=devnull, stdout=devnull, stderr=devnull, creationflags=flags
            )
        else:
            subprocess.Popen(
                command, stdin=devnull, stdout=devnull, stderr=devnull, start_new_session=True
            )
    except OSError as exc:
        raise HandoffError(f"Cannot start {command[0]}: {exc}") from exc


def wait_for_browser(port: int, seconds: float) -> dict[str, object]:
    """Wait until a browser answers on port. Return its version data."""
    deadline = time.monotonic() + seconds
    while (version := debug_version(port)) is None:
        if time.monotonic() > deadline:
            raise HandoffError(
                f"The browser did not open port {port} in {seconds:g} seconds. If the browser "
                "of the agent runs without this port, close it. Then run this command again."
            )
        time.sleep(0.5)
    return version


def run_browser(exe: Path | None) -> dict[str, str | None]:
    """Start the browser of the browser-driver agent, or find it running."""
    status = "running"
    version = debug_version(DEBUG_PORT)
    if version is None:
        status = "started"
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        exe = exe or find_browser(browser_candidates())
        start_browser(browser_command(exe, BROWSER_PROFILE, DEBUG_PORT))
        version = wait_for_browser(DEBUG_PORT, BROWSER_START_SECONDS)
    endpoint = f"http://127.0.0.1:{DEBUG_PORT}"
    return {"status": status, "browser": str(version.get("Browser")), "endpoint": endpoint}


def github_repo(remote_url: str) -> str:
    """Return "owner/name" for the URL of a github.com remote."""
    match = GITHUB_REMOTE_RE.fullmatch(remote_url.strip())
    if match is None:
        raise HandoffError(f"{remote_url} is not a github.com remote. Give --repo OWNER/NAME.")
    return match["repo"]


def compare_url(repo: str, base: str | None, head: str, title: str, body: str) -> str:
    """Return the GitHub page that shows a new pull request form with title and body filled in."""
    # Without a base, GitHub compares head with the default branch.
    refs = quote(head) if base is None else f"{quote(base)}...{quote(head)}"
    query = urlencode({"expand": "1", "title": title, "body": body}, quote_via=quote)
    url = f"https://github.com/{repo}/compare/{refs}?{query}"
    if len(url) > MAX_PR_URL_LENGTH:
        raise HandoffError(
            f"The pull request URL has {len(url)} characters. The limit is {MAX_PR_URL_LENGTH}. "
            "Make the body shorter."
        )
    return url


def git(repo_dir: Path, *args: str) -> str:
    """Run git in repo_dir and return its output. Raise HandoffError if git fails."""
    command = ["git", "-C", str(repo_dir), *args]
    try:
        result = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError(f"{' '.join(command)} failed: {exc}") from exc
    if result.returncode != 0:
        raise HandoffError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_branch(repo_dir: Path) -> str:
    """Return the branch that HEAD is on."""
    branch = git(repo_dir, "branch", "--show-current")
    if not branch:
        raise HandoffError("HEAD is not on a branch. Give --head BRANCH.")
    return branch


def check_pushed(repo_dir: Path, remote: str, branch: str) -> None:
    """Raise HandoffError if remote does not have the commit of the local branch."""
    ref = f"refs/heads/{branch}"
    local = git(repo_dir, "rev-parse", "--verify", ref)
    lines = git(repo_dir, "ls-remote", remote, ref).splitlines()
    remote_commits = [line.split()[0] for line in lines if line.split()[1:] == [ref]]
    if remote_commits != [local]:
        raise HandoffError(
            f"{remote} does not have the local commit of {branch}. Push {branch} first."
        )


def find_open_pr(repo: str, head: str) -> str | None:
    """Return the URL of the open pull request from head, or None if gh cannot find one."""
    command = ["gh", "pr", "list", "--repo", repo, "--head", head, "--state", "open"]
    command += ["--json", "url", "--jq", ".[0].url // empty"]
    try:
        result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    url = result.stdout.strip()
    return url if result.returncode == 0 and url else None


def pr_request(args: argparse.Namespace) -> Request:
    """Make the request that opens the GitHub form for a new pull request."""
    repo_dir: Path = args.repo_dir
    repo: str = args.repo or github_repo(git(repo_dir, "remote", "get-url", args.remote))
    if not REPO_RE.fullmatch(repo):
        raise HandoffError(f"{repo!r} is not a repository name of the form OWNER/NAME.")
    head: str = args.head or current_branch(repo_dir)
    check_pushed(repo_dir, args.remote, head)
    try:
        body: str = args.body_file.read_text(encoding="utf-8") if args.body_file else args.body
    except OSError as exc:
        raise HandoffError(f"Cannot read {args.body_file}: {exc}") from exc
    url = compare_url(repo, args.base, head, args.title, body)
    return Request(f"Create pull request: {args.title}", url, PR_STEPS, pr=(repo, head))


class Dialog:
    """A small window on top of the browser. It shows the steps and records the answer."""

    def __init__(self, request: Request, timeout_minutes: float, reopen: Callable[[], None]):
        self.status = "not_done"
        self.note_text = ""
        if sys.platform == "win32":
            # Draw sharp text on high-DPI screens, as IDLE does. The call fails if the
            # process has already set the DPI awareness. That is not a problem.
            with contextlib.suppress(OSError):
                ctypes.OleDLL("shcore").SetProcessDpiAwareness(1)
        self.root = tk.Tk()
        scale = self.root.winfo_fpixels("1i") / 96
        wrap = round(420 * scale)
        self.root.title(f"Claude handoff: {request.title}")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        # Put the window in the bottom-left corner, above the taskbar. Deploy pages
        # usually put the final button on the right side.
        self.root.geometry(f"+{round(24 * scale)}-{round(80 * scale)}")
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.finish("not_done"))

        parts = urlsplit(request.url)
        shown = f"https://{parts.netloc}{parts.path}"
        if len(shown) > 80:
            shown = shown[:77] + "..."
        steps = "\n".join(f"{number}. {step}" for number, step in enumerate(request.steps, 1))
        # Tk deletes a font when its Python object goes away, so the dialog keeps it.
        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        frame = ttk.Frame(self.root, padding=round(12 * scale))
        frame.grid()
        # The user must see first what to do, and then where to do it.
        ttk.Label(frame, text=request.title, font=self.bold, wraplength=wrap).grid(sticky="w")
        ttk.Label(frame, text=HEADING, font=self.bold).grid(sticky="w", pady=(8, 0))
        ttk.Label(frame, text=steps, wraplength=wrap, justify="left").grid(sticky="w")
        site = ttk.Label(frame, text=f"Site: {parts.hostname}", font=self.bold)
        site.grid(sticky="w", pady=(8, 0))
        link = ttk.Label(frame, text=shown, foreground="blue", cursor="hand2", wraplength=wrap)
        link.grid(sticky="w")
        link.bind("<Button-1>", lambda _event: reopen())
        for text, color in ((FINISH, ""), (WARNING, "#b00020")):
            label = ttk.Label(frame, text=text, foreground=color, wraplength=wrap, justify="left")
            label.grid(sticky="w", pady=(8, 0))
        ttk.Label(frame, text="Note for Claude (optional):").grid(sticky="w", pady=(8, 0))
        self.note = ttk.Entry(frame)
        self.note.grid(sticky="ew")
        buttons = ttk.Frame(frame)
        buttons.grid(sticky="e", pady=(12, 0))
        self.done_button = ttk.Button(buttons, text="Done", command=lambda: self.finish("done"))
        self.done_button.grid(row=0, column=0, padx=(0, 8))
        self.not_done_button = ttk.Button(
            buttons, text="Not done", command=lambda: self.finish("not_done")
        )
        self.not_done_button.grid(row=0, column=1)
        self.timer = self.root.after(round(timeout_minutes * 60_000), self.finish, "timeout")

    def finish(self, status: str) -> None:
        """Record the answer and close the window."""
        self.root.after_cancel(self.timer)
        self.status = status
        self.note_text = self.note.get().strip()
        self.root.destroy()

    def run(self) -> tuple[str, str]:
        """Show the window until the user answers or the time ends."""
        self.root.mainloop()
        return self.status, self.note_text


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command line."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--timeout",
        type=float,
        default=30,
        metavar="MINUTES",
        help="the time to wait for the user (default: 30)",
    )
    parser = argparse.ArgumentParser(
        description="Open a web page and wait while the user does the final step."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    page = commands.add_parser("open", parents=[common], help="open a page and show the steps")
    page.add_argument("--url", required=True, help="the https URL of the page")
    page.add_argument("--title", required=True, help="the action, for example: Publish 1.2")
    page.add_argument(
        "--step", action="append", required=True, help="one step for the user (give it again)"
    )
    page.add_argument(
        "--no-open", action="store_true", help="show only the dialog: the page is already open"
    )
    pr = commands.add_parser("pr", parents=[common], help="open the GitHub pull request form")
    pr.add_argument("--title", required=True, help="the title of the pull request")
    body = pr.add_mutually_exclusive_group()
    body.add_argument("--body", default="", help="the description of the pull request")
    body.add_argument("--body-file", type=Path, help="a file with the description")
    pr.add_argument("--base", help="the branch to merge into (default: the default branch)")
    pr.add_argument("--head", help="the branch to merge (default: the current branch)")
    pr.add_argument("--repo", help="OWNER/NAME on GitHub (default: from the remote URL)")
    pr.add_argument("--remote", default="origin", help="the remote with the branch")
    pr.add_argument("--repo-dir", type=Path, default=Path(), help="the local repository")
    browser = commands.add_parser("browser", help="start the browser of the browser-driver agent")
    browser.add_argument("--exe", type=Path, help="the browser program (default: Brave or Chrome)")
    return parser.parse_args(argv)


def report(result: dict[str, str | None]) -> int:
    """Print result as JSON. Return the exit code for its status."""
    print(json.dumps(result))
    return EXIT_CODES[str(result["status"])]


def main(argv: list[str] | None = None) -> int:
    """Do the handoff. Return the exit code."""
    args = parse_args(argv)
    try:
        if args.command == "browser":
            return report(run_browser(args.exe))
        hosts = allowed_hosts()
        if args.command == "pr":
            request = pr_request(args)
        else:
            check_text(args.title, args.step)
            request = Request(args.title, args.url, tuple(args.step))
        check_url(request.url, hosts)
        # With --no-open, the caller drove a browser to the page already.
        if args.command == "pr" or not args.no_open:
            open_page(request.url)
    except HandoffError as exc:
        return report({"status": "error", "error": str(exc)})
    status, note = Dialog(request, args.timeout, lambda: open_page(request.url)).run()
    result: dict[str, str | None] = {"status": status, "note": note}
    if request.pr is not None and status == "done":
        result["pr_url"] = find_open_pr(*request.pr)
    return report(result)


if __name__ == "__main__":
    sys.exit(main())
