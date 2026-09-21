---
name: deploy-handoff
description: >-
  Gives the last step of a deploy, billing, or sign-in task to the user. Drive
  the browser as far as you can, then use this skill. It shows the user a
  dialog that tells what to do: the final publish, pay, or submit click, a
  sign-in, an OAuth consent, or the creation of an API key. Examples: Stripe
  live mode, Google Play Console releases, F-Droid merge requests, hosting
  consoles. Also use it to open every GitHub pull request, instead of gh pr
  create or another pull request tool.
---

# deploy-handoff

`handoff.py` is in the base directory of this skill. In the commands below, replace `SKILL_DIR` with that directory. Run the script with Python 3.11 or later: `py -3` on Windows, `python3` on other systems.

Run the commands in a POSIX shell. On Windows, use Git Bash. Windows PowerShell 5.1 removes the double quotation marks inside the arguments.

The script shows a small dialog on top of the browser. The dialog tells the user what to do. The user does the last step and clicks **Done** or **Not done**. The script never clicks for the user.

## 1. Drive the browser to the last step

The user must do only the last step. Do all the other work first.

1. Do the work that needs no browser. For example, push the branch or upload the build with an API.
2. If you have browser tools, go to the page of the last step. Examples of browser tools are Claude in Chrome and a Playwright MCP server. Use the browser in which the user is signed in, if you can.
3. Open the correct app, release, or settings page. Fill in the fields that do not contain secrets.
4. Stop before the last step. Then run `handoff.py open --no-open` with the URL of the current page.

If you have no browser tools, give `handoff.py` the URL of the deepest page that you know. Do not give the home page of the console.

Never do these steps yourself. Give them to the user:

- Type a password, a one-time code, an API key, or a card number.
- Solve a CAPTCHA.
- Accept terms or an OAuth consent screen.
- Click the final button that publishes, pays, submits, merges, or deletes.

## 2. Write the steps in Simplified Technical English

The user reads the title and the steps in the dialog. Write them in ASD-STE100 Simplified Technical English:

- Start each step with a verb in the imperative, for example Click, Open, Select, or Make sure.
- Give one action in each step. Use 20 words or fewer. Do not use semicolons.
- Write the exact name of each button or menu item in quotation marks.
- Put a condition before its action: 'If the page asks for a code, type the code from your phone.'
- Make the title the result of the steps, for example 'Send version 1.4.0 for review'.

The script refuses a title or a step that has more than 20 words or a semicolon.

- Good: `Click "Send changes for review".`
- Bad: `Review everything, then submit it and tell me when it is done; check the release notes too.`

## 3. Run the handoff

```bash
python3 SKILL_DIR/handoff.py open --no-open \
  --url "https://play.google.com/console/u/0/developers/123/app/456/publishing" \
  --title "Send version 1.4.0 for review" \
  --step 'Make sure that the page shows version 1.4.0.' \
  --step 'Click "Send changes for review".'
```

- Do not give `--no-open` if you did not open the page. Then the script opens the URL in a new tab of the default browser.
- The URL must use `https` and printable ASCII. Percent-encode all other characters.
- The host must be an allowed host. If the script refuses the host, ask the user to add it. Do not add it yourself.

Useful start pages:

| Service | Page |
|---|---|
| Stripe API keys | `https://dashboard.stripe.com/apikeys` (test mode: `https://dashboard.stripe.com/test/apikeys`) |
| Google Play Console | `https://play.google.com/console` |
| F-Droid merge requests | `https://gitlab.com/fdroid/fdroiddata/-/merge_requests` |
| GitHub device sign-in | `https://github.com/login/device` |

## Open a pull request

Push the branch first. Then run this command in the repository:

```bash
python3 SKILL_DIR/handoff.py pr --title "Add CSV export" --body-file pr-body.md
```

The script opens the GitHub form with the title and the description filled in. The user only clicks "Create pull request".

- The head is the current branch. The base is the default branch on GitHub. Use `--head` and `--base` to change them.
- The script refuses the branch if the remote does not have the local commit.
- The script gets OWNER/NAME from the URL of `origin`. Use `--remote` or `--repo OWNER/NAME` to change it.
- Do not create a pull request with `gh pr create`, the GitHub API, or another tool.

## 4. Wait for the answer

The user can take many minutes. Run the command in the background (in Claude Code: `run_in_background: true`). Tell the user in one sentence that the dialog is open. The default time limit is 30 minutes. `--timeout MINUTES` changes it.

The script prints one JSON object:

| `status` | Exit code | Meaning |
|---|---|---|
| `done` | 0 | The user did the steps. |
| `not_done` | 3 | The user did not do the steps. `note` can give the reason. |
| `timeout` | 4 | The user did not answer in time. |
| `error` | 1 | The script did not show the dialog. `error` gives the reason. |

Exit code 2 means bad arguments. Then the script writes the usage to stderr.

After `pr`, a `done` answer also has `pr_url`. It is the open pull request that `gh` found for the branch, or `null` if `gh` is not available or found none.

## 5. After the answer

- `done`: Check the result with the API or CLI of the service when you can, for example `gh pr view`. Then continue.
- `not_done`: Read the note. Do not show the same steps again without a change. Ask the user what to do next.
- `timeout`: Ask the user before you try again.
- `error`: Fix the cause. If the host is not allowed, ask the user.

## Safety

- Never ask the user to type or paste a password, key, token, or card number into the chat or the note. Tell the user where to put a secret, for example in the secret store of the host.
- Never click the final button yourself with a browser tool.
