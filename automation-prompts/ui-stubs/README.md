# Automation UI stubs

These files are **short instructions** to paste into the Cursor Automations
editor. They point at full prompt files in this repo so you can iterate on
behavior by editing markdown here instead of re-pasting long prompts in the UI.

**Note:** The Automations `@` picker is for tools (Slack, MCP, PR comment, etc.),
not repo files. If you type `@automation-prompts/…` you may see "No actions
match …". Use plain paths in the stub text instead; the cloud agent reads those
files from the repo checkout at run time.

## Setup (once per automation)

1. Open the automation at [cursor.com/automations](https://cursor.com/automations).
2. Under **Repositories**, select this repo and the branch you deploy from
   (usually `main`). This is required — without a checkout the agent cannot read
   prompt files.
3. Replace the inline **Instructions** with the contents of the matching stub
   file below (plain paste; no `@` file mentions).
4. Save. On each run the agent checks out the branch and reads the latest
   committed prompt files.

`AGENTS.md` and `.cursor/CLOUD.md` are also loaded automatically for cloud
runs and reinforce which prompt file to follow.

## Which stub to use

| Automation | Trigger | Stub file | Full prompt |
|------------|---------|-----------|-------------|
| Assignment listing | Your listing trigger (e.g. schedule, webhook) | `assignment-listing.md` | `../assignment-listing.md` |
| Fit analysis | Slack thread reply starting with `fit` | `fit-analysis.md` | `../fit-analysis.md` |
| CV generation | Slack thread reply starting with `generate` | `cv-generation.md` | `../cv-generation.md` |

## Iteration workflow

1. Edit the full prompt under `automation-prompts/` (not the stub, unless
   trigger wiring changes).
2. Commit and push to the branch the automation uses.
3. Run **Test** in the Automations UI — no need to update the stub.

Change a stub only when trigger context, enabled tools, or which files to read
need to change.
