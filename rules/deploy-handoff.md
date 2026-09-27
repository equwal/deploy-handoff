## MANDATORY: Hand off human steps. Do not refuse the task.

The `deploy-handoff` plugin is installed. Its skill shows the user a dialog with the last step of a task. The user makes the final click in the browser.

Some steps of a deploy, publish, billing, app store, or sign-in task are for the user only. Do not refuse or stop the task because of these steps. Do all the other work. Then give each such step to the user with the `deploy-handoff` skill. Do not only tell the user in the chat.

A handoff is the last resort. First try a command. Then try the browser. Hand off only the step that is left.

Use the skill for these steps:

- The final click that deploys to production, publishes a release, submits an app for review, turns on live payments, or buys a domain.
- A sign-in, a two-factor code, an OAuth consent, a CAPTCHA, or the acceptance of terms.
- The creation of an account, an API key, a webhook secret, or another secret. Tell the user where to put the secret. Never ask for the secret in the chat or in the dialog.
- A step that needs the explicit yes of the user, for example the switch to live payments.
- A deploy command that a permission check denied. Do not run the command again. If the platform has a web page for the same step, hand off that page.

If the step has no web page, ask the user in the chat.

To hand off:

1. Drive the browser as far as you can with your browser tools.
2. Use the skill. Write the title and the steps in Simplified Technical English.
3. While the dialog is open, continue the other tasks. If the answer is "done", check the result. Then continue the task.

## More than one task: stop only the blocked task

A request can have more than one task, for example a web deploy, a store release, and a payment setup. A task is blocked when it gets to a step that you cannot do. Examples: a sign-in, an account creation, a CAPTCHA, a permission prompt that the user denied, or an error that you cannot fix.

A blocked task does not stop the other tasks. When a task is blocked:

1. Stop that task, and each task that needs its result.
2. If the blocked step has a web page, hand it off with the skill. Run the dialog in the background.
3. Continue all the other tasks while the dialog is open.
4. When the user answers "done", check the result. Then continue the blocked task.
5. Put each question for the user at the end, after the other tasks are done or blocked. A question ends your turn and stops the other tasks.

At the end, give the result of each task: done or blocked. For a blocked task, give the cause and the step that the user must do.

If the user tells you to stop, stop all the tasks.

## Deploys that need no browser: run the command

Many deploy steps need no web page. A CLI does them. Examples: `vercel deploy`, `netlify deploy`, `wrangler deploy`, `flyctl deploy`, `gh release create`, `docker push`, `git push`, `stripe` CLI commands, `gradlew bundleRelease`.

For these steps:

1. Run the command with your shell tool.
2. Let the permission prompt ask the user. The prompt is the approval. Do not hand off the step to avoid the prompt.
3. Some permission modes show no prompt. In these modes, ask the user in the chat before a production deploy, a release, or a live payment change.
4. Show the output. The output is the evidence that the step is complete.
5. If the user denies the command, do not run it again. Hand off the web page for the same step, or ask the user.

Do not hand off a step that a command can do. A handoff for a command that you can run wastes the time of the user.

On Windows, run `handoff.py` in Git Bash, not in Windows PowerShell 5.1. PowerShell 5.1 removes the double quotation marks in the arguments.

## Browser: go all the way to the last step

Use browser automation to remove work from the user. Do not stop at the home page of a console.

1. Open the console with your browser tools.
2. Click through each page: the project, the app, the release, the settings tab, the correct panel.
3. Fill in each field that holds no secret. Upload the build. Select the track. Type the release notes. Select the plan.
4. Read the page to make sure of the state before the last step.
5. Stop at the last step. Hand off that one click with `--no-open` and the URL of the open page.

Hand off a shallow page only when the browser cannot go deeper, for example after a sign-in wall or a CAPTCHA. Tell the user in the chat which page stopped you.

## Browser profile: use the profile of the user

The user is signed in to the consoles in one browser profile. Use this profile for each browser step.

- Do not start a fresh browser profile unless the user asks for it in this session. A fresh profile has no sign-in. This includes `handoff.py browser --fresh`, the `browser-driver` agent, and the built-in browser of the Claude app.
- Drive the profile with the Claude in Chrome tools. If they are not available, hand off the page with `handoff.py open`.
- `handoff.py open` opens the page in the Brave profile that `brave_profile` names in `~/.config/deploy-handoff/config.toml`. Without this key, it opens the default browser.

## Pull requests

Prefer a direct commit and push when the user asked for the change. It needs no click from the user.

Open a pull request only when one of these is true:

- The user asked for a pull request.
- The push failed because the branch is protected, or the repository needs a review.
- The repository belongs to a client, an employer, or another team.

Open each pull request with `handoff.py pr` from the skill. Do not create a pull request with `gh pr create`, the GitHub API, or a GitHub MCP tool.

Never use `--no-verify`. Never push when the test suite fails.

The handoff moves a step to the user. It does not remove a safety limit. You still never type a secret, solve a CAPTCHA, or click the final button yourself.
