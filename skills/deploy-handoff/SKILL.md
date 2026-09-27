---
name: deploy-handoff
description: >-
  Gives the last step of a deploy, billing, or sign-in task to the user. Use it
  before you drive the browser: its browser-driver agent does the browser steps
  in the browser where the user is signed in. Then a dialog tells the user what
  to do: the final publish, pay, or submit click, a sign-in, an OAuth consent,
  or the creation of an API key. Examples: Stripe live mode, Google Play Console
  releases, F-Droid merge requests, hosting consoles. Also use it to open every
  GitHub pull request, instead of gh pr create or another pull request tool.
---

# deploy-handoff

`handoff.py` is in the base directory of this skill. In the commands below, replace `SKILL_DIR` with that directory. Run the script with Python 3.11 or later: `py -3` on Windows, `python3` on other systems.

Run the commands in a POSIX shell. On Windows, use Git Bash. Windows PowerShell 5.1 removes the double quotation marks inside the arguments.

The script shows a small dialog on top of the browser. The dialog tells the user what to do. The user does the last step and clicks **Done** or **Not done**. The script never clicks for the user.

## 0. Select the automation mode

Before you do the work, select one of these modes:

| Mode | Use it when |
|---|---|
| PowerShell command | A CLI or API does the step, for example `vercel deploy`, `gh release create`, or `stripe`. Run it with the PowerShell tool. |
| Brave with the Claude extension | The `mcp__claude-in-chrome__*` tools are available and Brave has the sign-in of the user. |
| Brave with Playwright | The `browser-driver` agent is available. It uses `handoff.py browser` and the Playwright MCP. |
| Fresh browser (built-in browser) | The step needs no sign-in, or the user will sign in again. Use the `mcp__Claude_Browser__*` tools. |
| Windows-MCP | The step is in a desktop app or an operating system dialog, not in a web page. |
| Dialog with instructions only | No automation tool is available, or the user wants to do all the steps. Run `handoff.py open` without `--no-open`. |

Guess the mode with these rules, in this order:

1. If the user named a mode in this session, use it.
2. If a command can do the step, use "PowerShell command".
3. If the step is not in a web page, use "Windows-MCP".
4. If only one browser mode has connected tools, use that mode.

If the rules do not give one mode, ask the user one time with the AskUserQuestion tool. Put your best guess first and mark it "(Recommended)". Use that mode for the rest of the session. If a mode fails, go to the next mode in the table. Tell the user in one sentence which mode you use.

## 1. Drive the browser to the last step

The user must do only the last step. Do all the other work first.

1. Do the work that needs no browser. For example, push the branch or upload the build with an API.
2. Give the browser steps to the `browser-driver` agent of this plugin. The next section tells how.
3. If you cannot use the agent, drive the browser yourself. Use the browser in which the user is signed in. Open the page of the last step. Fill in the fields that do not contain secrets. Stop before the last step.
4. Run `handoff.py open --no-open` with the URL of the current page.

If you have no browser tools, give `handoff.py` the URL of the deepest page that you know. Do not give the home page of the console.

Never do these steps yourself. Give them to the user:

- Type a password, a one-time code, an API key, a token, or a card number.
- Sign in, or create an account.
- Solve a CAPTCHA or another check that you are a human.
- Accept terms, a consent screen, or an OAuth consent.
- Create or show a secret, for example an API key or a webhook secret.
- Change a security setting, a payment method, or the access of a person.
- Click the final button that publishes, deploys, pays, buys, submits, merges, or deletes.

### The browser-driver agent

The agent does the browser steps in its own browser: a separate Brave or Chrome profile in its own window. Playwright MCP controls this browser through a local port, so the user can keep working. On Windows, the agent can also use Windows-MCP for a window of the operating system. The agent never does a human step.

The user signs in to each console one time in this browser. The browser keeps the sign-in. When the agent finds a sign-in page, it gives the sign-in to the user as a human step.

1. Start the browser. The command prints one JSON object with the status `started` or `running`:

   ```bash
   python3 SKILL_DIR/handoff.py browser
   ```

2. Tell the user in one sentence that the agent works in its own browser window. Ask the user not to close that window.
3. In Claude Code, start the agent with the Agent tool and `subagent_type: "deploy-handoff:browser-driver"`. Give it this information:
   - The title and the start URL.
   - All the steps in order, with the human step last.
   - The text for each field, and the absolute path of each file to upload. The files must be in the project folder.

The agent ends its answer with one JSON object:

| `status` | Meaning | What you do |
|---|---|---|
| `done` | The agent did all the steps. The task had no human step. | Check the result. Do not show the dialog. |
| `ready` | The page of a human step is open. | Run `handoff.py open --no-open` with its `url`, `title`, and `steps`. |
| `not_done` | The agent cannot continue. `note` gives the error. | Read the next paragraph. |

If the answer has no JSON object, treat it as `not_done`.

After `not_done`, read the note. If you can fix the cause, for example a wrong URL, fix it and start the agent again one time. If you cannot fix it, run `handoff.py open` without `--no-open`, with all the steps for the user. Tell the user the error in one sentence.

The `note` of a `ready` answer can name steps that remain after the human step. If the user answers `done` in the dialog, start the agent again for those steps.

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

## More than one task

A request can have more than one task, for example a web deploy, a store release, and a payment setup. A task is blocked when it gets to a human step, or to an error that you cannot fix. A blocked task does not stop the other tasks.

1. Stop the blocked task, and each task that needs its result.
2. If the blocked step has a web page, give it to the user with `handoff.py`. Run the command in the background.
3. Continue the other tasks while the dialog is open. Each dialog runs in its own process, so more than one dialog can be open at the same time.
4. After a `done` answer, check the result. Then continue the blocked task.
5. Put each question for the user at the end, after the other tasks are done or blocked. A question ends your turn and stops the other tasks.

At the end, give the result of each task. For a blocked task, give the cause and the step that the user must do.

If the user tells you to stop, stop all the tasks.

## Safety

- Never ask the user to type or paste a password, key, token, or card number into the chat or the note. Tell the user where to put a secret, for example in the secret store of the host.
- Never click the final button yourself with a browser tool.
