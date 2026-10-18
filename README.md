# Old Paths

This is a private daily podcast that follows the Navigators Bible Reading Plan. Every morning a Claude Code scheduled task researches that day's four readings, writes a script of about 30 minutes, converts it to audio, and publishes it to a podcast feed your app subscribes to. Everything is hosted on GitHub for free.

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

## Costs

- **GitHub:** free. Releases older than 60 days are deleted, so roughly 60 episodes at about 11 MB each are stored at any time. Each publish uses a few minutes of free Actions time.
- **Text-to-speech:** free. It uses Microsoft Edge's online voices through the `edge-tts` library. That service is unofficial and could change. If it ever stops working, swap `synthesize()` in `scripts/podcast.py` for a paid TTS API.
- **Claude:** each run counts against your Claude plan's usage.

## Files

| File | Purpose |
|---|---|
| `KICKOFF.md` | One-time deployment instructions for Claude Code |
| `ROUTINE_PROMPT.md` | Prompt for the scheduled task |
| `.github/workflows/publish.yml` | Makes the audio and publishes staged episodes |
| `INSTRUCTIONS.md` | Step-by-step workflow Claude follows each run |
| `STYLE.md` | Host voice, theology, structure, quote rules, text-to-speech rules |
| `SOURCES.md` | Where to find the fathers, Reformers, Puritans, Spurgeon, Sproul, Piper, and others |
| `plan/navigators.json` | All 300 days of the Navigators Bible Reading Plan |
| `plan/jump_to.txt` | Manual jump to a plan day |
| `config.json` | Show metadata, voice, length, time zone, retention |
| `scripts/podcast.py` | `next`, `transcript`, `stage`, `publish-incoming`, `publish`, `feed`, `bootstrap` |
| `seed/` | Cover art and the pilot episode |
