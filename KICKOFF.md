# Kickoff: deploy Old Paths end to end

You are Claude Code running on Jacob's computer. Your job is to make his daily podcast live tonight, so that a new episode is in his podcast app by 6:00 AM Phoenix time tomorrow, Sunday, October 18, 2026, and every morning after that.

Jacob wants to do nothing himself. Work autonomously. Only stop for him when something truly needs a human, such as a browser login. When it does, tell him exactly what to click in one or two sentences, then continue. Do not ask for confirmation between steps. Read README.md first for how the system works.

## 0. Prerequisites
- Make sure `git`, `python3` (3.10 or newer), and the GitHub CLI `gh` are installed. If `gh` is missing on macOS, install it with `brew install gh`.
- Run `gh auth status`. If it isn't logged in, run `gh auth login --hostname github.com --git-protocol https --web` and have Jacob finish the browser step. This is the one thing he may need to do.
- Set `OWNER=$(gh api user -q .login)` and `REPO=old-paths-podcast`.

## 1. Create the repo
- This folder (where this file lives) is the project. If it's still inside a zip, unzip it to `~/old-paths` first.
- If `$OWNER/$REPO` doesn't exist yet, initialize git on `main`, commit everything, then run `gh repo create $REPO --public --source . --push --description "Old Paths: private daily Bible reading podcast"`. It must be public, because GitHub Pages and release downloads on a free account require it. The feed is marked as blocked from podcast directories.
- Give Actions write permission: `gh api -X PUT repos/$OWNER/$REPO/actions/permissions/workflow -f default_workflow_permissions=write`.

## 2. Bootstrap the feed
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
GH_TOKEN=$(gh auth token) GH_REPO=$OWNER/$REPO python scripts/podcast.py bootstrap --start 10-14
```
- If it reports that Pages couldn't be turned on, run `gh api -X POST repos/$OWNER/$REPO/pages -f "source[branch]=gh-pages" -f "source[path]=/"`.
- Poll `https://<owner in lowercase>.github.io/old-paths-podcast/feed.xml` for up to 15 minutes until it returns 200. Confirm the XML parses, and confirm the pilot episode's MP3 URL in the feed resolves to audio with `curl -sIL`.

## 3. Make tomorrow's episode now (Day 14)
This guarantees an episode by 6 AM even if the scheduled task has a problem on its first night.
- Follow INSTRUCTIONS.md exactly, steps 1 through 9, in this checkout. Use `python3 scripts/podcast.py next --date 2026-10-18` in step 1 and `python3 scripts/podcast.py stage --date 2026-10-18` in step 8.
- Do the full research and the full-length script. Do not cut corners because it's late. The quality bar in STYLE.md applies.
- After staging, watch the "Publish episode" workflow with `gh run list --workflow publish.yml` and `gh run watch`. If it fails, read the logs with `gh run view --log-failed`, fix the cause on `main`, push, then stage again.
- Confirm the new episode is in the live feed and its audio URL resolves.
- Switch back to `main` afterward with `git checkout main`.
- Because an episode now exists for October 18, the scheduled run at 4 AM tomorrow will see it and stop. The scheduled runs take over Monday.

## 4. Let Claude Code on the web access the repo
The scheduled task runs in Claude Code on the web, which reaches GitHub through the Claude GitHub App.
- Check with `gh api /user/installations` whether the Claude app is installed and can see `$REPO`. If it's installed for selected repositories only, try adding the repo with `gh api -X PUT /user/installations/<installation_id>/repositories/<repo_id>`.
- If that isn't possible, give Jacob the single link to grant access, which is the app's configure page on github.com.

## 5. Create the daily scheduled task
Create a Claude Code cloud scheduled task with:
- **Name:** Old Paths daily episode
- **Repository:** `$OWNER/old-paths-podcast`
- **Schedule:** every day at 4:00 AM, America/Phoenix time zone
- **Model:** the strongest available
- **Prompt:** the exact contents of ROUTINE_PROMPT.md
- **Environment:** network access set to Full, because the research fetches ccel.org, biblehub.com, spurgeon.org, ligonier.org, desiringgod.org, newadvent.org, and others. No environment variables or setup script are needed.

Use Claude Code's `/schedule` capability if this session has it. If you can't create the task or set the network access yourself, give Jacob short numbered steps for claude.ai/code/scheduled with the exact values to paste. That would be his only other action.

## 6. Final message to Jacob
Keep it short:
- The feed URL, and how to add it. In Apple Podcasts: Library, the ⋯ menu, Follow a Show by URL.
- What you verified: the pilot is live, Day 14 is live, and the task is scheduled for 4 AM daily.
- Anything that still needs him, ideally nothing.
