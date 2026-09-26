# deploy-handoff

A Claude Code plugin for the steps that an AI agent must not do alone.

An agent can build, test, and upload a release. Some steps must come from a person: publish the release, turn on live payments, accept an OAuth consent, or create a pull request. The agent drives the browser as far as it can. Then deploy-handoff shows a small dialog on top of the browser. The dialog tells you what to do, in short steps in [Simplified Technical English](https://asd-ste100.org). You do the final click. Then you click **Done** or **Not done**, and the agent continues.

deploy-handoff never makes the final click for you. It never asks for a password or a key.

## Install

In Claude Code:

```
/plugin marketplace add equwal/deploy-handoff
/plugin install deploy-handoff@deploy-handoff
```

Requirements:

- Python 3.11 or later, with Tk. The python.org installers for Windows and macOS include Tk. On Debian and Ubuntu, install `python3-tk`.
- `git` for the `pr` command. `gh` is optional. If `gh` is available, the `pr` command gives the URL of the new pull request.
- For the browser driver: Brave or Chrome, and Node.js with `npx`. The plugin starts [Playwright MCP](https://github.com/microsoft/playwright-mcp) with `npx`.

## How it works

The plugin adds the skill `deploy-handoff` and the agent `browser-driver`. Claude uses the skill when a task reaches a human step, and when it opens a GitHub pull request. The skill starts the agent for the browser steps, then runs `skills/deploy-handoff/handoff.py`. Other tools can run the script in the same way.

Open a page and show the steps:

```bash
python3 skills/deploy-handoff/handoff.py open \
  --url https://play.google.com/console \
  --title "Send version 1.4.0 for review" \
  --step 'Open "Publishing overview".' \
  --step 'Click "Send changes for review".'
```

If the agent already drove a browser to the page, it adds `--no-open`. Then the script shows only the dialog. The script refuses a title or a step with more than 20 words or with a semicolon.

Open the pull request form for the current branch:

```bash
python3 skills/deploy-handoff/handoff.py pr --title "Add CSV export" --body-file body.md
```

The script prints one JSON object, for example `{"status": "done", "note": ""}`. [SKILL.md](skills/deploy-handoff/SKILL.md) lists all statuses and exit codes.

## Browser

The script opens pages in a new tab of your default browser. To use a different browser, set the `BROWSER` environment variable. The Python `webbrowser` module reads it.

## Browser driver

The agent [browser-driver](agents/browser-driver.md) does the browser steps before the dialog. It stops at the first human step. Then the dialog shows only that step.

The agent works in its own browser, not in your browser. Start that browser with this command:

```bash
python3 skills/deploy-handoff/handoff.py browser
```

The command starts Brave, or Chrome if Brave is not installed. `--exe PATH` names a different Chromium browser. The browser uses its own profile in `~/.config/deploy-handoff/browser` and opens the remote debugging port 9333 on 127.0.0.1. If the browser runs already, the command only prints its status.

[Playwright MCP](https://github.com/microsoft/playwright-mcp) controls this browser through the port. Thus the agent works when the window is behind other windows, and you can keep working. It also fills in file dialogs without the mouse. On Windows, the agent can use [Windows-MCP](https://github.com/CursorTouch/Windows-MCP) for a window of the operating system, if you have it.

Sign in to each console one time in this browser. The profile keeps the sign-in. When the agent finds a sign-in page, it gives the sign-in to you as a human step.

The browser starts with no window. The agent opens a window when it opens a page. If you close the window, the browser does not stop, and the agent can open a new window.

Any program on your computer can control this browser through the port. Use the profile only for deploy consoles. When you do not need the browser, stop its process: the `brave.exe` or `chrome.exe` process with `--remote-debugging-port=9333` in its command line. On Windows, Task Manager shows the command line on the Details tab when you add the "Command line" column. On macOS and Linux, run `pkill -f -- --remote-debugging-port=9333`.

The agent gets only the tools that look at the page and act on it. It gets no tool that runs code in the page or reads the network traffic, and no shell, file, registry, or clipboard tool. It can upload only files in the project folder.

The agent never types a password, a code, a key, or a card number. It never signs in, solves a CAPTCHA, accepts terms, or makes the final click. If it cannot continue, it gives the status `not_done` and the error to the agent that started it.

## Allowed hosts

The script opens only `https` pages on allowed hosts. This stops an agent that follows bad instructions from sending you to a fake sign-in page. The dialog also shows the host of the page.

[config.toml](skills/deploy-handoff/config.toml) has the default list: GitHub, GitLab, Stripe, Google Play, F-Droid, App Store Connect, and some cloud and hosting consoles. An entry also allows its subdomains.

To add hosts, make the file `~/.config/deploy-handoff/config.toml`. If `XDG_CONFIG_HOME` is set, the file is `$XDG_CONFIG_HOME/deploy-handoff/config.toml`.

```toml
allowed_hosts = ["dashboard.example.com"]
```

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --group dev
.venv/bin/python -m ruff format --check
.venv/bin/python -m ruff check
.venv/bin/python -m mypy skills/deploy-handoff
.venv/bin/python -m unittest discover -s skills/deploy-handoff
```

On Windows, use `.venv\Scripts\python`. `pip install --group` needs pip 25.1 or later. The dialog tests show small windows for a short time. One browser test starts Brave or Chrome with a temporary profile. If you have neither, unittest skips that test.

## More projects

- [SubRead](https://subread.space/): read along with an audiobook, in the browser.
  Also [for Android](https://github.com/equwal/subread-android/releases/latest),
  [for YouTube](https://github.com/equwal/subread-extension/releases/latest)
  and [for KOReader](https://github.com/equwal/subread.koplugin).
- [SubRead Overlay](https://github.com/equwal/subread-overlay/releases/latest): subtitle lines over any Android media player.
- [SubRead Dictionary](https://github.com/equwal/subread-dictionary/releases/latest): a pop-up dictionary for Android that reads Yomitan dictionaries.
- [SubRead Anki](https://github.com/equwal/subread-anki): one tap makes an Anki card from any Android app.
- [Subrep](https://github.com/equwal/subrep-android/releases/latest): live captions of the sound of your phone.
- [Book Simulator](https://booksimulator.com/): a reading room for Aozora Bunko and Project Gutenberg books.
- [honjimaku.com](https://honjimaku.com/): subtitles for Japanese audiobooks.
- [sbm Sync](https://sbmsync.com/): your bookmarks, the same on every device,
  with [sbm](https://github.com/equwal/sbm) for dmenu,
  [sbm for Android](https://github.com/equwal/sbm-android/releases/latest)
  and the [sbm add-on](https://github.com/equwal/sbm-extension/releases/latest) for Firefox and Chrome.
- [Rebind](https://github.com/equwal/rebind/releases): remap the hardware buttons of e-ink readers and Android,
  with [Ink Recents](https://github.com/equwal/ink-recents/releases/latest),
  [Ink Dim](https://github.com/equwal/ink-dim/releases/latest)
  and [Ink Update](https://github.com/equwal/ink-update/releases/latest).
- [dickt.store](https://dickt.store/): language-learning tools, flashcards and web toys.
- [hentaibun.online](https://hentaibun.online/): learn kanbun and kobun.
- [Recently Written](https://recentlywritten.com/): the blog, and a list of [all projects](https://recentlywritten.com/projects.html).

## License

MIT
