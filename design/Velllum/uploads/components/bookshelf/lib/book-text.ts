/**
 * Plain-text book parsing for the reader: chapter detection + paragraphs.
 * Works for Project Gutenberg dumps, .txt/.md imports and extracted EPUB text.
 */

export type BookChapter = {
  title: string;
  paragraphs: string[];
};

const HEADING_WORDS =
  /^(chapter|chap\.|part|book|act|scene|prologue|epilogue|preface|foreword|prefatory|introduction|introductory|afterword|conclusion|interlude|letter|canto|stanza|episode|volume|stave|adventure|cene)\b/i;

const LONE_NUMERAL = /^(?:[IVXLCDM]{1,8}|\d{1,3})\.?$/;
const TOC_ENTRY_LINE = /^\s*(?:[IVXLCDM]{1,8}|\d{1,3})\.?\s+\S/;

function firstLineOf(block: string): string {
  return block.split("\n")[0].trim();
}

function isTocListBlock(block: string): boolean {
  const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length < 4) return false;
  // "I\nII\nIII…" style bare-numeral lists (e.g. The Great Gatsby contents).
  const bare = lines.filter((line) => LONE_NUMERAL.test(line)).length;
  if (bare / lines.length >= 0.6) return true;
  // "I. THE EVE OF THE WAR.\nII. …" style numbered entry lists.
  const numbered = lines.filter((line) => TOC_ENTRY_LINE.test(` ${line}`)).length;
  return numbered / lines.length >= 0.6;
}

function isHeadingBlock(block: string): boolean {
  const line = block.trim();
  if (!line || line.length > 90) return false;
  // Bracketed blocks are captions/illustrations, never chapter headings.
  if (line.includes("[") || line.includes("]")) return false;
  const head = firstLineOf(line);
  if (
    head.length > 4 &&
    head === head.toUpperCase() &&
    /[A-Z]/.test(head) &&
    HEADING_WORDS.test(head)
  ) {
    return true;
  }
  if (HEADING_WORDS.test(head) && head.length < 80) return true;
  // Lone numeral ("I.", "XII", "7") — alone or followed by the chapter name
  // inside the same block ("I.\nTHE EVE OF THE WAR.").
  if (LONE_NUMERAL.test(head)) return true;
  // Uppercase numeral-prefixed heading on its own block
  // ("II. THE RED-HEADED LEAGUE").
  if (
    line === line.toUpperCase() &&
    /[A-Z]/.test(line) &&
    line.length < 80 &&
    /^(?:[IVXLCDM]{1,8}|\d{1,3})\.?\s+\S/.test(head)
  ) {
    return true;
  }
  // Markdown heading
  if (/^#{1,3}\s+\S/.test(head)) return true;
  return false;
}

function headingTitle(block: string): string {
  const line = block.trim();
  const head = firstLineOf(line);
  const rest = line
    .split("\n")
    .slice(1)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  // "I.\nTHE EVE OF THE WAR." → "I. — THE EVE OF THE WAR"
  if (LONE_NUMERAL.test(head) && rest) {
    return `${head} — ${rest}`.slice(0, 80).trim();
  }

  const md = head.match(/^#{1,3}\s+(.*)$/);
  const raw = (md ? md[1] : head).replace(/\s+/g, " ").slice(0, 80);
  // Tidy Gutenberg artifacts: trailing brackets, stray periods, hanging dashes.
  return raw
    .replace(/\s*\]+$/, "")
    .replace(/^\[+\s*/, "")
    .replace(/[.\s]+$/, "")
    .trim();
}

function toParagraphs(blocks: string[]): string[] {
  return blocks
    .map((block) => block.replace(/\s*\n\s*/g, " ").replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

/**
 * Split a full book text into chapters. Falls back to a single
 * "Full text" chapter when no headings are detected.
 */
export function splitBookIntoChapters(text: string): BookChapter[] {
  // Normalize Windows line endings — Gutenberg dumps use \r\n, which would
  // otherwise break the \n{2,} paragraph-block splitting.
  const normalized = text.replace(/\r\n?/g, "\n");
  const allBlocks = normalized
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  if (allBlocks.length === 0) {
    return [{ title: "Full text", paragraphs: [] }];
  }

  // Drop "Contents" listings (blocks of numbered entries) plus any heading
  // that immediately introduces one — real chapter starts live in the body.
  const blocks: string[] = [];
  for (let i = 0; i < allBlocks.length; i++) {
    const block = allBlocks[i];
    const next = i + 1 < allBlocks.length ? allBlocks[i + 1] : "";
    if (isTocListBlock(block)) {
      i += 0; // drop the list itself
      continue;
    }
    if (isHeadingBlock(block) && isTocListBlock(next)) {
      i += 1; // drop the heading + its list
      continue;
    }
    blocks.push(block);
  }

  const chapterStarts: number[] = [];
  blocks.forEach((block, index) => {
    if (index === 0) return; // first block is always content, not a boundary
    if (isHeadingBlock(block)) chapterStarts.push(index);
  });

  if (chapterStarts.length < 2) {
    return [
      {
        title: "Full text",
        paragraphs: toParagraphs(blocks),
      },
    ];
  }

  const chapters: BookChapter[] = [];
  // Content before the first heading (title page, preface, etc.)
  if (chapterStarts[0] > 0) {
    const opening = toParagraphs(blocks.slice(0, chapterStarts[0]));
    if (opening.length > 0) {
      chapters.push({ title: "Front matter", paragraphs: opening });
    }
  }

  chapterStarts.forEach((start, i) => {
    const end = i + 1 < chapterStarts.length ? chapterStarts[i + 1] : blocks.length;
    const headingBlock = blocks[start];
    let title = headingTitle(headingBlock);

    // Gutenberg style: "CHAPTER I." followed by an ALL-CAPS chapter name.
    const next = start + 1 < end ? blocks[start + 1] : "";
    if (
      next &&
      next.length <= 80 &&
      next === next.toUpperCase() &&
      /[A-Z]/.test(next) &&
      !isHeadingBlock(next)
    ) {
      title = `${title} — ${next}`
        .replace(/^CHAPTER\s+/i, "Chapter ")
        .replace(/\s+/g, " ");
      const body = toParagraphs(blocks.slice(start + 2, end));
      chapters.push({ title, paragraphs: body.length ? body : [next] });
      return;
    }

    const body = toParagraphs(blocks.slice(start + 1, end));
    // Merge stray headings that produced empty chapters into the previous one.
    if (body.length === 0 && chapters.length > 0) {
      chapters[chapters.length - 1].title += ` · ${title}`;
      return;
    }
    chapters.push({ title, paragraphs: body });
  });

  // Drop empty trailing artifacts
  const cleaned = chapters.filter((chapter) => chapter.paragraphs.length > 0);
  return cleaned.length > 0 ? cleaned : [{ title: "Full text", paragraphs: toParagraphs(blocks) }];
}

export function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}
