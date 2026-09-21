# deploy-handoff

A Claude Code plugin for the steps that an AI agent must not do alone.

An agent can build, test, and upload a release. Some steps must come from a person: publish the release, turn on live payments, accept an OAuth consent, or create a pull request. The agent drives the browser as far as it can. Then deploy-handoff shows a small dialog on top of the browser. The dialog tells you what to do, in short steps in [Simplified Technical English](https://asd-ste100.org). You do the final click. Then you click **Done** or **Not done**, and the agent continues.

deploy-handoff never clicks for you. It never asks for a password or a key.

## Install

In Claude Code:

```
/plugin marketplace add equwal/deploy-handoff
/plugin install deploy-handoff@deploy-handoff
```

Requirements:

- Python 3.11 or later, with Tk. The python.org installers for Windows and macOS include Tk. On Debian and Ubuntu, install `python3-tk`.
- `git` for the `pr` command. `gh` is optional. If `gh` is available, the `pr` command gives the URL of the new pull request.

## How it works

The plugin adds the skill `deploy-handoff`. Claude uses the skill when a task reaches a human step, and when it opens a GitHub pull request. The skill runs `skills/deploy-handoff/handoff.py`. Other tools can run the script in the same way.

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

On Windows, use `.venv\Scripts\python`. `pip install --group` needs pip 25.1 or later. The dialog tests show small windows for a short time.

## License

MIT
