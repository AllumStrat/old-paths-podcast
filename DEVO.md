# Old Paths devo: style guide

The devo is a written companion to the podcast, read on an e-reader in the morning. It covers the same four readings as the episode, in the same order as `today.json`. Read `STYLE.md` first. Its theology, its "stay in the text" rule, its voices, and its quotation integrity rules all apply here. This file covers only what changes when the words are read instead of heard.

## Format

`work/devo.md` is plain markdown:

```
# Title of the day

## John 4:43-54

Commentary paragraphs.

{{passage: John 4:43-45}}

More commentary.

{{passage: John 4:46-54}}

Commentary after the last chunk.

## 1 Peter 1:10-16
...
```

- The first line is `# <title>`. Use the podcast episode's title, or a shorter variant.
- Each reading gets one `## <ref>` heading, written exactly as in `today.json`.
- A marker `{{passage: Book C:V-V}}` sits alone on its own line. You never type the Bible text. The Action fetches the ESV and puts it there.
- Split each reading into chunks of roughly a paragraph or a pericope, about 5 to 25 verses each. Short readings can have two chunks. Long Old Testament readings such as Jeremiah 35-38 may need six to ten.
- The chunks under a heading must run in order and cover the whole reading, with no gaps and no overlaps. Cross-chapter ranges are fine: `{{passage: Jeremiah 35:1-36:10}}`. A whole chapter is `{{passage: Ecclesiastes 11}}`.
- Commentary goes before the first chunk, between chunks, and after the last chunk.
- Markdown allowed: paragraphs, `*italic*`, `**bold**`, `> blockquotes` for quotations from the quote bank, `### subheads` (sparingly), and `---` for a break. No tables, images, or links.

## Length

1,800 to 2,800 words of commentary in total (markers and headings are not counted). Give the Old Testament reading the most depth, about 40 to 50 percent of the words. Give each of the other three readings about 15 to 20 percent.

## Voice

It is the same theology and voice as STYLE.md, written for the eye.

- Normal written punctuation. Parentheses, dashes, numerals, and verse references like "Jer. 36:23" are fine. There are no text-to-speech rules.
- Written, not spoken: no "welcome back," no "today we," no sign-off, no greeting fluff. Start with the substance.
- Do not repeat the podcast script. Where the podcast leans on an idea, the devo can add the detail a reader wants to slow down over: the Hebrew or Greek word, the date, the cross-reference, the hard question.

## What commentary does

- **Before a chunk, orient.** Give the setting (who, where, when), where this sits in the book's flow, and what to watch for. Two to five sentences is usually enough.
- **After a chunk, explain.** Take up key words, the hard questions, and what the voices say. This is where quotations belong.
- Do not retell the passage. The reader is about to read it, or just did.
- Do not quote the ESV in your commentary beyond a key word or two, in italics. Paraphrase, and point to the verse by number.
- Stay in the text, per STYLE.md. In the Old Testament reading, teach the Old Testament passage in its own setting. Make at most two New Testament moves, and only the warranted kinds.
- Quotations come only from the quote bank in `work/research.md`, word for word, and are named in prose ("Calvin, in his commentary on this verse, says..."). Quote 4 to 8 times in all, with the most in the Old Testament reading. Use blockquotes for quotations longer than a sentence.
- Never put a quote on an author who did not write on that book.

## Do not include

- No prayer, not even a closing line.
- No application-question lists, "reflect on" prompts, or "take-aways" sections.
- No reflexive "this points us to Jesus" endings.
- No summary of the whole devo at the end.
