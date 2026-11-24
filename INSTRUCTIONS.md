# Old Paths: daily production run

You are producing today's episode of Old Paths. Work through every step in order. Do not skip the research, including the separate devo research pass in step 6. Do not edit any file in this repository. Everything you write goes in `work/`, which is ignored by git. The only git operation is the one `stage` performs in step 9. No tokens, environment variables, or package installs are needed for your part.

## 1. Set up

```bash
mkdir -p work
python3 scripts/podcast.py next
```

- If `next` exits with status 3 (`already_published_today`), stop. Report that today's episode already exists.
- If it cannot read the series state, stop and report the error.
- Otherwise read `work/today.json`. It contains today's plan day, the four readings, the next plan day's readings, recent episodes with their summaries and open threads, and which authors were quoted recently.
- Read `STYLE.md`, `DEVO.md`, and `SOURCES.md` in full.
- Read yesterday's script with `python3 scripts/podcast.py transcript last` so you build on it and do not repeat it.

## 2. Read the passages

Fetch and read every verse of all four readings in the ESV. Note the structure of each passage, its key verses, and the questions it raises. For the Old Testament reading, also reread the end of the previous chapter so you know where the story stands.

## 3. Research (spend real effort here)

Build `work/research.md` with these sections:

1. **Setting and background**, for each reading: date, historical situation, place in the book's structure, and relevant archaeology or culture. Go deepest on the Old Testament reading.
2. **Outline** of each passage with its key verses.
3. **Interpretive questions**, the two or three hardest or most interesting questions in each passage and how the voices answer them.
4. **Quote bank.** Every candidate quotation goes here, copied word for word from a fetched page, with author, work, and URL. Note which verse it comments on.

Minimum research per episode:
- Old Testament reading: at least six distinct voices, including at least one Reformer or Puritan commentary (Calvin, Henry, Poole, Trapp, or Gill), a Spurgeon search on the passage's key verses, a check for any church father on the passage, and at least one modern conservative (for example Ryken, Sproul, Piper, or MacArthur).
- Each of the other three readings: at least three distinct voices, including a church father where one exists (they are plentiful for the Gospels, Psalms, and epistles).
- Search Ligonier (Sproul) and Desiring God (Piper) for the passages every day, and use them when they truly engage the text.
- Prefer voices not overused in `authors_quoted_in_last_12_episodes`.

Gather roughly twice as many quotes as you will use, then choose the best.

## 4. Outline the episode

Using the structure and word budget in `STYLE.md`, write a short outline at the top of `work/research.md`. List the segments, the main point of each, the quotes assigned to each, the thread from yesterday you will pick up, and any real cross-reading connection for the close.

## 5. Write the script

Write `work/script.txt` following `STYLE.md` exactly. Plain spoken text only. Target 2,300 to 2,600 words, about 15 minutes.

## 6. Write the devo

The devo is a separate job from the podcast and has its own research pass. Read `DEVO.md` again and follow it exactly. Do not reuse the podcast's quote bank as the devo's quotes, because the devo draws on Presbyterian, Reformed, and Reformed Baptist voices only.

**Devo research pass.** For each of the four readings, every day:

1. Search Gospel in Life for Tim Keller, desiringgod.org for John Piper, and ligonier.org for R.C. Sproul. Fetch the pages and use what they said about this passage. Check attribution: Ligonier's Tabletalk studies are by Ligonier staff, not Sproul.
2. Then fill out with Spurgeon, Matthew Henry, Calvin, Gill, Boice, and the other voices listed in `DEVO.md`. Henry, Gill, and Spurgeon cover nearly every chapter, so no chunk goes without a real voice.
3. Log every devo quote word for word with its author, work, verse, and URL in a `## Devo quote bank` section of `work/research.md`. Never quote from memory and never use quote aggregators.

**Write `work/devo.md`** in the commentary, then scripture shape:

- `# <title>`, then one `## <ref>` heading per reading, as written in `today.json`.
- Split each reading into chunks. Each chunk is commentary followed by its `{{passage: Book C:V-V}}` marker. Every marker has commentary directly above it, and nothing comes after the last marker of a reading.
- The commentary is quotes from the devo quote bank, introduced by author, with your own short sentences only to set the scene and connect the quotes. Each chunk has at least one quote, and the day has 10 to 18.
- Quotes of two sentences or more go in a `>` blockquote. Keep quotes to about 120 words for Keller, Piper, Sproul, and other recent authors, and about 200 for public-domain authors.
- Your own sentences follow the connecting-sentence rules in `DEVO.md`: plain words, no em dashes, none of the banned words, no -ing clause that explains why something matters.
- Never type any Bible text. The publishing Action fetches the ESV for each marker.
- No prayer, application questions, closing section, greeting, or sign-off. Total commentary is 1,800 to 3,200 words, with about 40 percent on the Old Testament reading.

Then check it and fix every error:

```bash
python3 scripts/podcast.py devo-check work/devo.md
```

## 7. Review and revise

Check each of these and fix anything that fails:

- [ ] `wc -w work/script.txt` is between 2,300 and 2,600.
- [ ] Every quotation in the script appears word for word in the quote bank with a URL. Remove or paraphrase anything that does not.
- [ ] No quote is attributed to an author who did not write on that book. For example, Calvin wrote no commentary on Ecclesiastes or Song of Songs.
- [ ] The Old Testament segment teaches the Old Testament passage in its own setting, with no more than two New Testament moves, each one warranted.
- [ ] No segment ends with a reflexive "this points us to Jesus" line.
- [ ] There are 5 to 8 quotations, with at least one father and at least one Puritan, Reformer, Baptist, or Presbyterian, and the four traditions are rotated across the week rather than all forced into one episode. Sproul, Spurgeon, or Piper appears if they genuinely addressed the passages.
- [ ] The opening picks up a thread from the recent episodes, and the close previews the next plan day.
- [ ] The script follows the text-to-speech rules: no markdown, lists, parentheses, URLs, em dashes, abbreviations, or "LORD" in capitals, and references are written as speech.
- [ ] Nothing from yesterday's script is repeated, whether an illustration, quote, or application.
- [ ] `python3 scripts/podcast.py devo-check work/devo.md` passes with no errors. Every marker has commentary above it, nothing follows a reading's last marker, the markers cover each reading with no gaps or overlaps, and the commentary is between 1,800 and 3,200 words.
- [ ] Every quotation in `work/devo.md` is in the `## Devo quote bank` word for word with a URL, comes from an allowed voice in `DEVO.md`, and the file contains no Bible text.
- [ ] The devo has no prayer, no application-question list, no greeting or sign-off, and no commentary after a passage. Its Old Testament section is the deepest, and Keller, Piper, and Sproul were searched for every reading.

## 8. Write the metadata

Create `work/meta.json`:

```json
{
  "title": "A short evocative title: main passages, for example 'The Scroll and the Knife: Jeremiah 36-38, Ecclesiastes 11, John 4, 1 Peter 1'",
  "summary": "Four to seven sentences recording what this episode actually taught, passage by passage, including key claims and which voices were used. Future episodes read this, so make it informative.",
  "threads": ["Things to pick up in later episodes: unfinished arcs, promised follow-ups, where each book is heading."],
  "sources": [{"author": "John Calvin", "work": "Commentary on Jeremiah, Lecture 140", "url": "https://..."}],
  "show_notes": "Two or three sentences for the podcast app's episode description."
}
```

List every quoted source in `sources`.

## 9. Stage for publishing

```bash
python3 scripts/podcast.py stage
```

This copies your script, metadata, devo, and research into `incoming/DATE/` and pushes them to a `claude/episode-DATE` branch. A GitHub Action on that branch then builds the devo EPUB (fetching the ESV text itself) and delivers it to Dropbox, makes the audio, attaches it to a GitHub Release, updates the feed and series state on `gh-pages`, deletes audio older than 60 days, and removes the branch.

- If it rejects the script as too short, expand the script with more substance from your research, not padding, and run it again.
- If it rejects the script as too long, cut whole points rather than squeezing sentences, and run it again.
- If `stage` warns that `work/devo.md` is missing or failed `devo-check`, the podcast is still staged but the devo is not. Fix the devo and run `stage` again.
- If the push fails, run it once more. If it fails again, stop and report the error.
- Optionally, if you can reach the feed URL printed by `stage`, wait up to 15 minutes and confirm today's title appears in it.

## 10. Report

Finish with a short report: the episode title, the plan day, the word count, the number of quotes and the authors used, the staging branch, whether the devo was staged (with its commentary word count), and whether you confirmed the episode in the feed.
