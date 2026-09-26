"""Tests for handoff.py. README.md tells how to run them.

The dialog tests show small windows for a short time. BrowserWindowTest starts Brave or
Chrome with a temporary profile, and shows its window for a short time.
"""

import http.server
import json
import socket
import subprocess
import tempfile
import threading
import tkinter as tk
import unittest
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tkinter import ttk
from typing import TypeVar
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from hypothesis import assume, given
from hypothesis import strategies as st

import handoff
from handoff import HandoffError, Request

T = TypeVar("T")

DOMAINS = ["github.com", "stripe.com", "google.com", "play.google.com"]
LABEL = st.from_regex(r"[a-z0-9-]{1,12}", fullmatch=True)
DOMAIN = st.lists(LABEL, min_size=2, max_size=3).map(".".join)
ALLOWED_HOST = st.builds(
    lambda prefix, domain: ".".join([*prefix, domain]),
    st.lists(LABEL, max_size=3),
    st.sampled_from(DOMAINS),
)
# A path and a query in printable ASCII. They contain "@" and ":", which must not change the host.
REST = st.from_regex(
    r"(/[A-Za-z0-9._~%!$&'()*+,;=:@-]*)*(\?[A-Za-z0-9._~%!$&'()*+,;=:@/?-]*)?", fullmatch=True
)
ALLOWED_URL = st.builds(lambda host, rest: f"https://{host}{rest}", ALLOWED_HOST, REST)
TEXT = st.text(st.characters(codec="utf-8"), max_size=100)
REPO = st.from_regex(r"[A-Za-z0-9-]{1,10}/[A-Za-z0-9_-]{1,10}", fullmatch=True)
OWNER = st.from_regex(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,10}[A-Za-z0-9])?", fullmatch=True)
NAME = st.from_regex(r"[A-Za-z0-9._-]{1,12}", fullmatch=True).filter(
    lambda name: name not in {".", ".."} and not name.endswith(".git")
)
REMOTE_FORMS = [
    "https://github.com/{}.git",
    "https://github.com/{}",
    "https://github.com/{}/",
    "https://user:token@github.com/{}.git",
    "git@github.com:{}.git",
    "git@github.com:{}",
    "ssh://git@github.com/{}.git",
]
WORD = st.from_regex(r"[A-Za-z0-9\"'.,:()-]{1,10}", fullmatch=True)
# Characters that git allows in a branch name, other than "/". See git check-ref-format.
REF_CHAR = st.characters(codec="utf-8", exclude_categories=["Cc"], exclude_characters=" ~^:?*[\\/")


@st.composite
def branches(draw: st.DrawFn) -> str:
    """Make a branch name that git accepts."""
    parts = draw(st.lists(st.text(REF_CHAR, min_size=1, max_size=6), min_size=1, max_size=3))
    name = "/".join(parts)
    assume(".." not in name and "@{" not in name and name != "@" and not name.endswith(".lock"))
    assume(not any(part.startswith(".") or part.endswith(".") for part in parts))
    return name


@st.composite
def host_and_domains(draw: st.DrawFn) -> tuple[str, list[str]]:
    """Make a host near an allowed domain: the domain, a subdomain, or a look-alike."""
    domains = draw(st.lists(DOMAIN, min_size=1, max_size=4))
    domain = draw(st.sampled_from(domains))
    label = draw(LABEL)
    glue = draw(st.sampled_from([".", "", "-"]))
    host = draw(st.sampled_from([domain, label + glue + domain, domain + glue + label]))
    return host, domains


def reference_match(host: str, domains: list[str]) -> str | None:
    """Do the work of match_domain slowly: compare the labels from the right."""
    labels = host.split(".")
    found = [d for d in domains if labels[-len(d.split(".")) :] == d.split(".")]
    return max(found, key=len, default=None)


def label_texts(widget: tk.Misc) -> list[str]:
    """Return the text of each label in widget, in the order in which the dialog made them."""
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            texts.append(str(child.cget("text")))
        texts.extend(label_texts(child))
    return texts


def run_git(*args: str) -> None:
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", *identity, *args], check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    """Make a repository with one commit on main, and a bare remote with the name origin."""
    remote, work = root / "remote.git", root / "work"
    run_git("init", "--bare", str(remote))
    run_git("init", "-b", "main", str(work))
    run_git("-C", str(work), "commit", "--allow-empty", "-m", "first")
    run_git("-C", str(work), "remote", "add", "origin", str(remote))
    return work


class MatchDomainTest(unittest.TestCase):
    @given(host_and_domains())
    def test_same_as_reference(self, case: tuple[str, list[str]]) -> None:
        host, domains = case
        self.assertEqual(handoff.match_domain(host, domains), reference_match(host, domains))

    @given(st.lists(LABEL, max_size=3), DOMAIN)
    def test_allows_subdomains(self, prefix: list[str], domain: str) -> None:
        self.assertEqual(handoff.match_domain(".".join([*prefix, domain]), [domain]), domain)

    @given(LABEL, DOMAIN)
    def test_refuses_look_alikes(self, label: str, domain: str) -> None:
        self.assertIsNone(handoff.match_domain(label + domain, [domain]))

    def test_most_specific_domain_wins(self) -> None:
        self.assertEqual(handoff.match_domain("a.play.google.com", DOMAINS), "play.google.com")


class CheckUrlTest(unittest.TestCase):
    @given(ALLOWED_HOST, REST)
    def test_accepts_allowed_hosts(self, host: str, rest: str) -> None:
        domain = handoff.match_domain(host, DOMAINS)
        self.assertEqual(handoff.check_url(f"https://{host}{rest}", DOMAINS), domain)

    @given(
        ALLOWED_URL,
        st.integers(min_value=0),
        st.sampled_from(["\\", " ", "\t", "\n", "\x00", "\x7f", "\u00e9", "\u3002", "\u200b"]),
    )
    def test_refuses_unsafe_characters(self, url: str, index: int, char: str) -> None:
        index %= len(url) + 1
        with self.assertRaises(HandoffError):
            handoff.check_url(url[:index] + char + url[index:], DOMAINS)

    @given(ALLOWED_HOST, st.from_regex(r"[A-Za-z0-9._~!$&'()*+,;=:-]{0,12}", fullmatch=True))
    def test_refuses_user_info(self, host: str, user: str) -> None:
        with self.assertRaises(HandoffError):
            handoff.check_url(f"https://{user}@{host}/", DOMAINS)

    @given(ALLOWED_HOST, st.integers(min_value=0, max_value=65535))
    def test_refuses_ports(self, host: str, port: int) -> None:
        with self.assertRaises(HandoffError):
            handoff.check_url(f"https://{host}:{port}/", DOMAINS)

    def test_refuses_known_attacks(self) -> None:
        for url in [
            "",
            "http://github.com/",
            "https://evil.com/",
            "https://evilgithub.com/",
            "https://github.com.evil.com/",
            "https://github.com@evil.com/",
            "https://evil.com\\@github.com/",
            "https://evil.com\\.github.com/",
            "https://evil.com%2F.github.com/",
            "https://github.com./",
            "https://gith\u0443b.com/",
            "https:github.com/",
            "https:///github.com/",
            "https://[::1]/",
            "https://[github.com/",
            "//github.com/",
            "javascript:alert(1)//github.com/",
        ]:
            with self.subTest(url=url), self.assertRaises(HandoffError):
                handoff.check_url(url, DOMAINS)

    def test_ignores_the_case_of_the_host(self) -> None:
        self.assertEqual(handoff.check_url("https://GitHub.COM/equwal", DOMAINS), "github.com")


class CheckTextTest(unittest.TestCase):
    @given(st.lists(WORD, min_size=1, max_size=20))
    def test_accepts_short_text(self, words: list[str]) -> None:
        handoff.check_text(" ".join(words), [" ".join(words)])

    @given(st.lists(WORD, min_size=21, max_size=40))
    def test_refuses_long_steps(self, words: list[str]) -> None:
        with self.assertRaises(HandoffError):
            handoff.check_text("Publish 1.4.0", ["Click it.", " ".join(words)])

    def test_refuses_long_titles_semicolons_and_empty_text(self) -> None:
        for title, steps in [
            (" ".join(["word"] * 21), ["Click it."]),
            ("Publish 1.4.0", ["Open the page; click it."]),
            ("Publish 1.4.0", ["   "]),
            ("", ["Click it."]),
        ]:
            with self.subTest(title=title, steps=steps), self.assertRaises(HandoffError):
                handoff.check_text(title, steps)


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, text: str) -> Path:
        path = self.folder / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_shipped_file_allows_github(self) -> None:
        self.assertIn("github.com", handoff.read_hosts(handoff.SHIPPED_CONFIG))

    def test_refuses_bad_files(self) -> None:
        for text in [
            'allowed_hosts = ["https://github.com"]\n',
            'allowed_hosts = ["GitHub.com"]\n',
            "allowed_hosts = [1]\n",
            'allowed_hosts = "github.com"\n',
            "not toml\n",
        ]:
            with self.subTest(text=text), self.assertRaises(HandoffError):
                handoff.read_hosts(self.write(text))

    def test_refuses_a_missing_file(self) -> None:
        with self.assertRaises(HandoffError):
            handoff.read_hosts(self.folder / "missing.toml")

    def test_user_file_adds_hosts(self) -> None:
        user = self.write('allowed_hosts = ["example.com"]\n')
        with mock.patch.object(handoff, "USER_CONFIG", user):
            hosts = handoff.allowed_hosts()
        self.assertIn("example.com", hosts)
        self.assertIn("github.com", hosts)

    def test_user_file_is_optional(self) -> None:
        with mock.patch.object(handoff, "USER_CONFIG", self.folder / "missing.toml"):
            self.assertEqual(handoff.allowed_hosts(), handoff.read_hosts(handoff.SHIPPED_CONFIG))


class OpenPageTest(unittest.TestCase):
    def test_opens_a_new_tab(self) -> None:
        with mock.patch("webbrowser.open", return_value=True) as browser:
            handoff.open_page("https://github.com/")
        browser.assert_called_once_with("https://github.com/", new=2)

    def test_error_if_no_browser_opens(self) -> None:
        with mock.patch("webbrowser.open", return_value=False), self.assertRaises(HandoffError):
            handoff.open_page("https://github.com/")


class VersionHandler(http.server.BaseHTTPRequestHandler):
    """Answer like the remote debugging port of a browser."""

    def do_GET(self) -> None:
        body = json.dumps({"Browser": "Chrome/140.0"}).encode()
        self.send_response(200 if self.path == "/json/version" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Write no log lines during the tests."""


class BrowserTest(unittest.TestCase):
    def test_command_uses_its_own_profile_and_the_debug_port(self) -> None:
        command = handoff.browser_command(Path("brave.exe"), Path("profile"), 9333)
        self.assertEqual(command[0], "brave.exe")
        self.assertIn(f"--user-data-dir={Path('profile')}", command)
        self.assertIn("--remote-debugging-port=9333", command)

    def test_find_browser_takes_the_first_file(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        missing, chrome = Path(folder.name, "brave.exe"), Path(folder.name, "chrome.exe")
        chrome.write_bytes(b"")
        self.assertEqual(handoff.find_browser([missing, chrome]), chrome)
        with self.assertRaises(HandoffError):
            handoff.find_browser([missing])

    def test_debug_version_reads_the_browser_on_the_port(self) -> None:
        server = http.server.HTTPServer(("127.0.0.1", 0), VersionHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            self.assertEqual(handoff.debug_version(server.server_port), {"Browser": "Chrome/140.0"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertIsNone(handoff.debug_version(server.server_port))

    def test_mcp_json_uses_the_debug_port(self) -> None:
        path = Path(__file__).resolve().parents[2] / ".mcp.json"
        server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["browser"]
        self.assertIn(f"http://127.0.0.1:{handoff.DEBUG_PORT}", server["args"])


def free_port() -> int:
    """Return a port on 127.0.0.1 that no program uses now."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def devtools(port: int, path: str, method: str = "GET") -> str:
    """Send one HTTP request to the remote debugging port of a browser. Return the body."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with handoff.LOCAL_OPENER.open(request, timeout=10) as response:
        body: bytes = response.read()
    return body.decode()


class BrowserWindowTest(unittest.TestCase):
    def test_command_starts_without_a_window(self) -> None:
        command = handoff.browser_command(Path("brave.exe"), Path("profile"), 9333)
        self.assertIn("--no-startup-window", command)

    def test_keeps_running_when_its_last_window_closes(self) -> None:
        # On 2026-09-26 the browser stopped two times, because its window closed. Then the
        # agent got "Failed to open a new tab" and "connect ECONNREFUSED 127.0.0.1:9333".
        try:
            exe = handoff.find_browser(handoff.browser_candidates())
        except HandoffError:
            self.skipTest("Found no Brave or Chrome.")
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        port = free_port()
        browser = subprocess.Popen(
            handoff.browser_command(exe, Path(folder.name), port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(browser.wait, 30)
        self.addCleanup(browser.kill)
        handoff.wait_for_browser(port, handoff.BROWSER_START_SECONDS)
        # The agent opens a page. Then the user closes each tab, as the close button does.
        devtools(port, "/json/new?about:blank", "PUT")
        for target in json.loads(devtools(port, "/json/list")):
            if target["type"] == "page":
                devtools(port, f"/json/close/{target['id']}")
        with self.assertRaises(subprocess.TimeoutExpired):
            browser.wait(timeout=5)
        self.assertIn("about:blank", devtools(port, "/json/new?about:blank", "PUT"))


class GithubRepoTest(unittest.TestCase):
    @given(OWNER, NAME, st.sampled_from(REMOTE_FORMS))
    def test_round_trip(self, owner: str, name: str, form: str) -> None:
        self.assertEqual(handoff.github_repo(form.format(f"{owner}/{name}")), f"{owner}/{name}")

    def test_refuses_other_remotes(self) -> None:
        for remote in [
            "https://gitlab.com/o/r.git",
            "git@github-work:o/r.git",
            "https://github.com.evil.com/o/r",
            "https://github.com/o",
            "https://github.com/o/r/extra",
            "C:/repos/r.git",
        ]:
            with self.subTest(remote=remote), self.assertRaises(HandoffError):
                handoff.github_repo(remote)


class CompareUrlTest(unittest.TestCase):
    @given(REPO, st.none() | branches(), branches(), TEXT, TEXT)
    def test_round_trip(
        self, repo: str, base: str | None, head: str, title: str, body: str
    ) -> None:
        url = handoff.compare_url(repo, base, head, title, body)
        self.assertEqual(handoff.check_url(url, ["github.com"]), "github.com")
        parts = urlsplit(url)
        prefix = f"/{repo}/compare/"
        self.assertTrue(parts.path.startswith(prefix))
        refs = [unquote(ref) for ref in parts.path.removeprefix(prefix).split("...")]
        self.assertEqual(refs, [head] if base is None else [base, head])
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        self.assertEqual(query, {"expand": ["1"], "title": [title], "body": [body]})

    def test_refuses_long_urls(self) -> None:
        with self.assertRaises(HandoffError):
            handoff.compare_url("o/r", None, "b", "t", "x" * handoff.MAX_PR_URL_LENGTH)


class GitTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.work = make_repo(Path(folder.name))

    def test_current_branch(self) -> None:
        self.assertEqual(handoff.current_branch(self.work), "main")
        run_git("-C", str(self.work), "checkout", "--detach")
        with self.assertRaises(HandoffError):
            handoff.current_branch(self.work)

    def test_check_pushed(self) -> None:
        with self.assertRaises(HandoffError):
            handoff.check_pushed(self.work, "origin", "main")
        run_git("-C", str(self.work), "push", "origin", "main")
        handoff.check_pushed(self.work, "origin", "main")
        run_git("-C", str(self.work), "commit", "--allow-empty", "-m", "second")
        with self.assertRaises(HandoffError):
            handoff.check_pushed(self.work, "origin", "main")


class DialogTest(unittest.TestCase):
    def make_dialog(self, timeout_minutes: float = 1) -> handoff.Dialog:
        request = Request("Test handoff", "https://github.com/equwal", ("Look at the page.",))
        return handoff.Dialog(request, timeout_minutes, lambda: None)

    def test_done_returns_the_note(self) -> None:
        dialog = self.make_dialog()

        def answer() -> None:
            dialog.note.insert(0, "  shipped  ")
            dialog.done_button.invoke()

        dialog.root.after(50, answer)
        self.assertEqual(dialog.run(), ("done", "shipped"))

    def test_not_done(self) -> None:
        dialog = self.make_dialog()
        dialog.root.after(50, dialog.not_done_button.invoke)
        self.assertEqual(dialog.run(), ("not_done", ""))

    def test_closing_the_window_means_not_done(self) -> None:
        dialog = self.make_dialog()
        close = dialog.root.protocol("WM_DELETE_WINDOW")
        dialog.root.after(50, dialog.root.tk.call, close)
        self.assertEqual(dialog.run(), ("not_done", ""))

    def test_timeout(self) -> None:
        self.assertEqual(self.make_dialog(timeout_minutes=0.001).run(), ("timeout", ""))

    def test_shows_the_steps_under_a_heading(self) -> None:
        # The smoke test on 2026-09-21 showed this request. The user could not see what to do.
        request = Request(
            "Smoke test: deploy-handoff",
            "https://github.com/equwal",
            ("No action needed. This window closes itself.",),
        )
        dialog = handoff.Dialog(request, 1, lambda: None)
        texts = label_texts(dialog.root)
        dialog.finish("not_done")
        expected = [
            "Smoke test: deploy-handoff",
            "Do these steps in your browser:",
            "1. No action needed. This window closes itself.",
        ]
        self.assertEqual(texts[:3], expected)
        self.assertIn("Site: github.com", texts)


class MainTest(unittest.TestCase):
    """Test main with a fake browser and a fake dialog."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        config = self.root / "config.toml"
        config.write_text('allowed_hosts = ["github.com"]\n', encoding="utf-8")
        self.patch("SHIPPED_CONFIG", config)
        self.patch("USER_CONFIG", self.root / "missing.toml")
        self.open_page = self.patch("open_page", mock.MagicMock())
        self.dialog = self.patch("Dialog", mock.MagicMock())
        self.dialog.return_value.run.return_value = ("done", "ok")

    def patch(self, name: str, value: T) -> T:
        patcher = mock.patch.object(handoff, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def run_main(self, *argv: str) -> tuple[int, dict[str, object]]:
        output = StringIO()
        with redirect_stdout(output):
            code = handoff.main(list(argv))
        result: dict[str, object] = json.loads(output.getvalue())
        return code, result

    def open_url(self, url: str) -> tuple[int, dict[str, object]]:
        return self.run_main("open", "--url", url, "--title", "Do it", "--step", "Click it.")

    def test_open(self) -> None:
        self.assertEqual(
            self.open_url("https://github.com/o"), (0, {"status": "done", "note": "ok"})
        )
        self.open_page.assert_called_once_with("https://github.com/o")

    def test_exit_codes_for_other_answers(self) -> None:
        for status, expected in [("not_done", 3), ("timeout", 4)]:
            self.dialog.return_value.run.return_value = (status, "")
            code, result = self.open_url("https://github.com/o")
            self.assertEqual((code, result["status"]), (expected, status))

    def test_no_open_shows_only_the_dialog(self) -> None:
        code, result = self.run_main(
            "open",
            "--no-open",
            "--url",
            "https://github.com/o",
            "--title",
            "Do it",
            "--step",
            "Go.",
        )
        self.assertEqual((code, result["status"]), (0, "done"))
        self.open_page.assert_not_called()
        self.dialog.assert_called_once()

    def test_open_refuses_long_steps(self) -> None:
        code, result = self.run_main(
            "open", "--url", "https://github.com/o", "--title", "Do it", "--step", "word " * 21
        )
        self.assertEqual((code, result["status"]), (1, "error"))
        self.open_page.assert_not_called()

    def test_open_refuses_hosts_that_are_not_allowed(self) -> None:
        code, result = self.open_url("https://evil.example/")
        self.assertEqual((code, result["status"]), (1, "error"))
        self.open_page.assert_not_called()
        self.dialog.assert_not_called()

    def test_pr(self) -> None:
        work = make_repo(self.root)
        run_git("-C", str(work), "push", "origin", "main")
        find_open_pr = self.patch("find_open_pr", mock.MagicMock())
        find_open_pr.return_value = "https://github.com/o/r/pull/1"
        code, result = self.run_main(
            "pr", "--repo", "o/r", "--repo-dir", str(work), "--title", "Add X", "--body", "Why"
        )
        expected = {"status": "done", "note": "ok", "pr_url": "https://github.com/o/r/pull/1"}
        self.assertEqual((code, result), (0, expected))
        self.open_page.assert_called_once_with(
            "https://github.com/o/r/compare/main?expand=1&title=Add%20X&body=Why"
        )
        find_open_pr.assert_called_once_with("o/r", "main")

    def test_browser_that_runs(self) -> None:
        self.patch("debug_version", mock.MagicMock(return_value={"Browser": "Chrome/140.0"}))
        start = self.patch("start_browser", mock.MagicMock())
        code, result = self.run_main("browser")
        endpoint = f"http://127.0.0.1:{handoff.DEBUG_PORT}"
        expected = {"status": "running", "browser": "Chrome/140.0", "endpoint": endpoint}
        self.assertEqual((code, result), (0, expected))
        start.assert_not_called()

    def test_browser_starts(self) -> None:
        self.patch("debug_version", mock.MagicMock(side_effect=[None, None, {"Browser": "C/1"}]))
        profile = self.patch("BROWSER_PROFILE", self.root / "browser")
        start = self.patch("start_browser", mock.MagicMock())
        with mock.patch("time.sleep"):
            code, result = self.run_main("browser", "--exe", "brave.exe")
        self.assertEqual((code, result["status"]), (0, "started"))
        command = handoff.browser_command(Path("brave.exe"), profile, handoff.DEBUG_PORT)
        start.assert_called_once_with(command)
        self.assertTrue(profile.is_dir())

    def test_browser_that_does_not_open_the_port(self) -> None:
        self.patch("debug_version", mock.MagicMock(return_value=None))
        self.patch("BROWSER_PROFILE", self.root / "browser")
        self.patch("BROWSER_START_SECONDS", 0)
        self.patch("start_browser", mock.MagicMock())
        with mock.patch("time.sleep"):
            code, result = self.run_main("browser", "--exe", "brave.exe")
        self.assertEqual((code, result["status"]), (1, "error"))
        self.assertIn(f"port {handoff.DEBUG_PORT}", str(result["error"]))

    def test_pr_refuses_a_branch_that_is_not_pushed(self) -> None:
        work = make_repo(self.root)
        code, result = self.run_main("pr", "--repo", "o/r", "--repo-dir", str(work), "--title", "X")
        self.assertEqual((code, result["status"]), (1, "error"))
        self.assertIn("Push main first", str(result["error"]))
        self.open_page.assert_not_called()


if __name__ == "__main__":
    unittest.main()
