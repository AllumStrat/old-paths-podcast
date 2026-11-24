# Old Paths

This is a private daily podcast that follows the Navigators Bible Reading Plan. Every morning a Claude Code scheduled task researches that day's four readings, writes a script of about 15 minutes, converts it to audio, and publishes it to a podcast feed your app subscribes to. Everything is hosted on GitHub for free.

## How it works

1. **Scheduled task (Claude Code on the web, 4 AM daily).** Claude reads the plan day and series memory, researches, writes the script, and runs `python3 scripts/podcast.py stage`. That pushes the episode to a `claude/episode-DATE` branch. This step needs no tokens or setup.
2. **GitHub Action (`.github/workflows/publish.yml`).** The Action triggers on that branch. It converts the script to audio, attaches the MP3 to a GitHub Release, updates the feed and series state on `gh-pages`, deletes audio older than 60 days, and deletes the staging branch. It uses GitHub's built-in token, so nothing expires.
3. **GitHub Pages** serves `feed.xml` and the cover art from `gh-pages`. Your podcast app follows that feed.

Audio lives in Releases because deleting a release actually frees the space. Committed files would stay in git history forever. The `gh-pages` branch holds only small text files: the feed, transcripts, notes, and `state/series.json`, which is the series memory each episode builds on.

**The repo must be public.** On a free GitHub account, Pages and anonymous release downloads only work for public repos, and your podcast app can't sign in. The feed is marked as blocked from podcast directories.

## Setup

Hand `KICKOFF.md` to Claude Code on your computer. It creates the repo, bootstraps the feed, produces the first episode, and schedules the daily task. The only things that may need you are a GitHub browser login, if `gh` isn't signed in, and adding the feed URL to your podcast app.

## Day to day

- **Jump to a different plan day:** edit `plan/jump_to.txt` on `main`, put a plan day like `11-3` on the last line, and commit. The GitHub mobile app works for this. The next run jumps there once and continues forward.
- **Change the voice, speed, length, or retention:** edit `config.json`.
- **Moving to Denver:** change `timezone` in `config.json` to `America/Denver` and update the schedule's time zone.
- **Check what was quoted:** each episode's show notes in your podcast app list the sources with links. Full research notes are on the `gh-pages` branch under `notes/`.
- **Rebuild the feed by hand:** `GH_TOKEN=$(gh auth token) python scripts/podcast.py feed`.
- **If a morning's episode is missing:** check the repo's Actions tab for a failed "Publish episode" run, and the scheduled task's history at claude.ai/code/scheduled.

## Kobo devo

The same daily run also writes a devo for the day's four readings. Each reading is split into chunks of commentary followed by the passage, repeated through the reading, with no prayer and nothing after the last passage. The commentary is word-for-word quotes from Presbyterian, Reformed, and Reformed Baptist writers (Keller, Piper, and Sproul first, then Spurgeon, Henry, Calvin, Gill, and others), joined by short connecting sentences. `DEVO.md` is the style guide. It arrives as an EPUB in Dropbox, ready for KOReader on a Kobo.

- Claude writes `work/devo.md` with commentary and `{{passage: Jeremiah 35:1-11}}` markers only. `podcast.py devo-check` verifies that every marker has commentary above it, that nothing follows a reading's last marker, that the markers cover each reading with no gaps or overlaps (using `plan/verse_counts.json`), and that the commentary is within `devo_words_min` and `devo_words_max` (1,800 to 3,200).
- The Action fetches the ESV text from the ESV API, builds the EPUB, and uploads it to Dropbox before it starts the audio. A devo failure never blocks the podcast, but it fails the run's last step so you notice.
- **No public archive.** The devo quotes recent authors at length, so its source is not published. It sits only on the short-lived `claude/episode-DATE` staging branch, which the Action deletes. `gh-pages` keeps just the devo's title and whether it was delivered. ESV text never goes in this repo.
- **Backfills and reruns:** put each day in `<root>/YYYY-MM-DD/` with `devo.md` and `plan.json` (`{"date": "...", "plan_day": "11-18", "readings": ["John 12:1-11", ...]}`). Run `python3 scripts/podcast.py devo-stage <root>`. It runs devo-check on every day, refuses if any fail, and pushes a `claude/devo-TIMESTAMP` branch that adds only `incoming-devo/DATE/`. Add `--dry-run` to check and see what would be pushed without pushing. The "Publish devo" workflow (`.github/workflows/publish-devo.yml`) then runs `podcast.py publish-devos`, which builds each EPUB with the real ESV, delivers it to Dropbox, and deletes the branch. It exits non-zero if any day failed, after trying all of them.
- **Build by hand:** `ESV_API_KEY=... python scripts/podcast.py devo-build devo.md --out out.epub --date DATE --plan-day 10-14`. To test with no network, add `--fixture scripts/fixtures`. The EPUB title reads like "Old Paths Devo · Day 11-18 · Mon Nov 16" and carries the devo date.
- **One-command setup:** create a Dropbox app (Scoped access, App folder) and, before authorizing, enable files.metadata.read, files.content.read, and files.content.write on its Permissions tab. Plug in the Kobo (it mounts at `/Volumes/KOBOeReader`), then run `python3 scripts/podcast.py devo-setup`. It checks `gh auth status`, prompts for the ESV API key (Enter to skip), the Dropbox app key and secret, and opens the Dropbox authorize page for you to paste the code. It then sets the GitHub secrets `ESV_API_KEY`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` (sent to `gh` on stdin), checks Dropbox access, and writes an "Old Paths Devo" Dropbox entry into KOReader's `cloudstorage.lua` on the Kobo (the old file is backed up) and creates `Devo/`. Nothing is printed or saved anywhere else. Eject the Kobo, then in KOReader: Cloud storage, long-press "Old Paths Devo", Sync now. If the Kobo was not plugged in, re-run `python3 scripts/podcast.py devo-setup --kobo-only` later (it mints a fresh refresh token; older ones stay valid). `dropbox-auth` is an alias. If a secret is missing at run time, the devo is skipped with a warning.
- **Where files land:** `dropbox_devo_path` is `""`, the root of the app folder, so EPUBs appear in `Apps/<app name>/` as `YYYY-MM-DD-old-paths-devo-<planday>.epub`. Set it to `/Folder` to use a subfolder.
- **Retention:** EPUBs older than `devo_retention_days` (14) are deleted from the Dropbox app folder each run, counted from the real current date, so a backfill of an old day is not deleted by its own run's date. This keeps stored ESV text small as the ESV API terms ask.
- **Config:** `devo_words_min`, `devo_words_max`, `dropbox_devo_path`, `devo_retention_days`.

## Costs

- **GitHub:** free. Releases older than 60 days are deleted, so roughly 60 episodes at about 11 MB each are stored at any time. Each publish uses a few minutes of free Actions time.
- **Text-to-speech:** free. It uses the open Kokoro-82M model (voice `am_michael`), which runs on the GitHub Actions CPU, so no outside service is involved. To go back to Microsoft Edge's online voices, set `"tts": "edge"` in `config.json`.
- **Claude:** each run counts against your Claude plan's usage.

## Files

| File | Purpose |
|---|---|
| `KICKOFF.md` | One-time deployment instructions for Claude Code |
| `ROUTINE_PROMPT.md` | Prompt for the scheduled task |
| `.github/workflows/publish.yml` | Makes the audio and publishes staged episodes |
| `.github/workflows/publish-devo.yml` | Builds and delivers devo-only days staged by `devo-stage` |
| `INSTRUCTIONS.md` | Step-by-step workflow Claude follows each run |
| `STYLE.md` | Host voice, theology, structure, quote rules, text-to-speech rules |
| `DEVO.md` | Style guide for the written Kobo devo |
| `SOURCES.md` | Where to find the fathers, Reformers, Puritans, Spurgeon, Sproul, Piper, and others |
| `plan/navigators.json` | All 300 days of the Navigators Bible Reading Plan |
| `plan/jump_to.txt` | Manual jump to a plan day |
| `plan/verse_counts.json` | Verses per chapter (versification only, no text), used to check devo coverage |
| `config.json` | Show metadata, voice, length, time zone, retention |
| `scripts/podcast.py` | `next`, `transcript`, `stage`, `publish-incoming`, `publish`, `feed`, `bootstrap`, `devo-check`, `devo-build`, `devo-stage`, `publish-devos`, `devo-setup` (alias `dropbox-auth`) |
| `scripts/devo.py` | Devo parsing, validation, EPUB build, Dropbox delivery |
| `scripts/devo_setup.py` | `devo-setup`: GitHub secrets and Kobo KOReader config |
| `seed/` | Cover art and the pilot episode |
