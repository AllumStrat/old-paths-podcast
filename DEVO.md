# Old Paths devo: style guide

The devo is a private written companion to the podcast, read in KOReader on a Kobo each morning. It covers the same four readings as the episode, in the order given in `today.json`. Theology follows `STYLE.md`. Everything else about the devo is set here, and where this file and `STYLE.md` differ, this file wins for the devo.

## Shape: commentary, then scripture, repeated

Each reading is split into chunks. Every chunk is one pair: a commentary section, then the scripture that commentary is about. The reader reads the commentary first and then reads the passage with it in mind.

```
# Title of the day

## John 12:1-11

Commentary 1, about John 12:1-8.

{{passage: John 12:1-8}}

Commentary 2, about John 12:9-11.

{{passage: John 12:9-11}}

## 1 John 4:7-21
...
```

- The first line is `# <title>`. Use the podcast episode's title when there is one.
- Each reading gets one `## <ref>` heading, written exactly as in `today.json`.
- A marker `{{passage: Book C:V-V}}` sits alone on its own line. You never type Bible text. The Action fetches the ESV and puts it in place of the marker.
- Every marker has commentary directly above it, and nothing comes after the last marker of a reading. Do not write commentary after a passage. Do not write a closing section.
- Chunks run in order and cover the whole reading with no gaps and no overlaps. Aim for 5 to 25 verses a chunk. A short reading can be one or two chunks. A long Old Testament reading like Daniel 1-2 may need six to ten. Cross-chapter ranges are fine (`{{passage: Daniel 1:17-2:13}}`). A whole chapter is `{{passage: Job 16}}`.
- `devo-check` enforces all of this.

## Whose commentary

The commentary comes directly from Presbyterian, Reformed, and Reformed Baptist pastors and commentators, quoted word for word. Your own sentences only connect the quotes and set them up.

Allowed voices:

- **Presbyterian and Reformed:** Tim Keller, R.C. Sproul, John Calvin, Matthew Henry, Charles Hodge, B.B. Warfield, James Montgomery Boice, Philip Ryken, Sinclair Ferguson, Derek Thomas, Iain Duguid, Kevin DeYoung, Robert Murray M'Cheyne, Samuel Rutherford, Horatius Bonar, Thomas Watson, the Westminster divines.
- **Reformed Baptist:** John Piper, Charles Spurgeon, John Gill, John Bunyan, Benjamin Keach, Andrew Fuller, Thomas Schreiner, Mark Dever.

No church fathers, Anglicans, Congregationalists, Methodists, Lutherans, or Catholic writers in the devo, even though the podcast uses some of them.

Priority: Keller, Piper, and Sproul first. Search for each of them on every reading every day (Gospel in Life for Keller, desiringgod.org for Piper, ligonier.org for Sproul). Use what they actually said about this passage. Then fill out with Spurgeon, Henry, Calvin, Gill, Boice, and the rest. Matthew Henry, Gill, and Spurgeon cover nearly every chapter, so no chunk ever has to go without a real voice.

Each commentary section has at least one direct quotation tied to that chunk. Most sections have two or three. Across the day aim for 10 to 18 quotations.

## Quotation rules

- Every quotation is copied word for word from a page you fetched, logged with its URL in `work/research.md`. Never quote from memory.
- No quote aggregators (Goodreads, BrainyQuote, AZQuotes, Pinterest, social media).
- Check attribution. Ligonier's Tabletalk daily studies are written by Ligonier staff, not by Sproul: attribute them to "Ligonier's Tabletalk" or leave them out. Only call something Sproul's when the page shows Sproul wrote or said it. Calvin's Ezekiel commentary stops at chapter 20, and he wrote no commentary on Job (he preached sermons on it).
- Introduce each quote by author and, where it helps, the work: "Piper, preaching on this verse in 1985, said:" or "Matthew Henry writes:". Put quotes of two sentences or more in a `>` blockquote.
- Length: Keller, Piper, Sproul, and other living or recent authors run up to about 120 words a quote. Public-domain authors (Calvin, Henry, Spurgeon, Gill, and older) can run up to about 200 words when the passage earns it.

## Your connecting sentences

Keep them short. Their jobs are to give the setting (who, when, where), to name what to watch for in the coming verses, and to move from one quote to the next. They do not retell the passage, and they do not add a lesson the quotes did not make.

Write them by these rules:

- Plain words. Use "is" and "has" instead of "serves as," "stands as," "represents," "boasts."
- Never use these words: delve, tapestry, vibrant, rich (figurative), profound, crucial, pivotal, vital, key (as an adjective), intricate, interplay, enduring, resonate, underscore, highlight (verb), emphasize, reflect (figurative), symbolize, testament, landscape, journey (figurative), Additionally, Furthermore, Moreover, "It is worth noting," "It is important to note."
- No em dashes. Use a comma, colon, parentheses, or a period.
- No sentence that ends in an -ing clause explaining why something matters ("..., showing God's faithfulness").
- No groups of three adjectives or three parallel phrases for rhythm.
- No "not only X but also Y" and no "It's not X, it's Y."
- No "from X to Y" ranges.
- No vague attribution ("scholars say," "many commentators"). Name the person or cut the claim.
- Repeat a noun rather than swapping in a synonym for variety.
- Headings in sentence case.

## Do not include

- No prayer.
- No application questions, "reflect on" prompts, or takeaways.
- No commentary after a passage, and no summary at the end.
- No greeting, no sign-off, no "today we."
- No reflexive "this points us to Jesus" lines. The Old Testament reading is taught in its own setting first, per `STYLE.md`.

## Length

Commentary, counting quotes and your own sentences, totals 1,800 to 3,200 words. Give the Old Testament reading the most, about 40 percent. Markers and headings do not count.

## Privacy

The devo goes only to the private Dropbox folder. Its source is never saved to `gh-pages`. Only its title and source list are kept in the series state.
