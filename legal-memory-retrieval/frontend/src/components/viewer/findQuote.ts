/**
 * Locate a cited quote among the text runs of one PDF page.
 *
 * PDF text arrives as runs (roughly one per line or phrase). We join the runs
 * into one normalised string, remember which run every character came from,
 * and search there. The result is the list of run indexes to highlight.
 */

export type RunMatch = { runs: number[]; exact: boolean };

const QUOTES = /[‘’‚‛′]/g;
const DQUOTES = /[“”„‟″]/g;
const DASHES = /[‐-―−]/g;

function normChar(ch: string): string {
  return ch.replace(QUOTES, "'").replace(DQUOTES, '"').replace(DASHES, "-").toLowerCase();
}

/** Normalise free text the same way runs are normalised (used for the needle). */
export function normaliseText(text: string): string {
  return text
    .replace(/\[\[PAGE_BREAK\]\]/g, " ")
    .replace(/\[Page \d+\]/g, " ")
    .replace(/-\s*\n\s*/g, "")
    .split("")
    .map(normChar)
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

type Haystack = { text: string; owner: number[] };

function buildHaystack(runs: string[]): Haystack {
  let text = "";
  const owner: number[] = [];
  let lastSpace = true;
  runs.forEach((run, index) => {
    for (const raw of run) {
      const ch = normChar(raw);
      if (/\s/.test(ch)) {
        if (lastSpace) continue;
        text += " ";
        owner.push(index);
        lastSpace = true;
      } else {
        text += ch;
        owner.push(index);
        lastSpace = false;
      }
    }
    // Runs are separate words/lines: keep a boundary between them.
    if (!lastSpace) {
      text += " ";
      owner.push(index);
      lastSpace = true;
    }
  });
  return { text, owner };
}

function runsBetween(hay: Haystack, start: number, length: number): number[] {
  const set = new Set<number>();
  for (let i = start; i < start + length && i < hay.owner.length; i++) set.add(hay.owner[i]);
  return [...set].sort((a, b) => a - b);
}

/** Candidate needles, strongest first: whole quote, then shrinking word windows. */
function needles(quote: string): { text: string; exact: boolean }[] {
  const full = normaliseText(quote);
  if (!full) return [];
  const words = full.split(" ");
  const out = [{ text: full, exact: true }];
  for (const size of [14, 9, 6]) {
    if (words.length > size) {
      out.push({ text: words.slice(0, size).join(" "), exact: false });
      out.push({ text: words.slice(-size).join(" "), exact: false });
    }
  }
  return out;
}

/** Find `quote` in the runs of one page. Also tries without the hyphen/space noise of PDF text. */
export function findQuoteInRuns(runs: string[], quote: string): RunMatch | null {
  const hay = buildHaystack(runs);
  for (const needle of needles(quote)) {
    if (needle.text.length < 12 && !needle.exact) continue;
    const at = hay.text.indexOf(needle.text);
    if (at >= 0) {
      const runsHit = runsBetween(hay, at, needle.text.length);
      if (needle.exact) return { runs: runsHit, exact: true };
      // A partial window matched: widen to the quote's approximate length.
      const approx = normaliseText(quote).length;
      const from = needles(quote)[0].text.startsWith(needle.text) ? at : Math.max(0, at + needle.text.length - approx);
      return { runs: runsBetween(hay, from, approx), exact: false };
    }
  }
  return null;
}

/** Order in which to search pages: cited page, its neighbours, then the rest. */
export function pageSearchOrder(cited: number | null, pageCount: number): number[] {
  const order: number[] = [];
  const push = (p: number) => {
    if (p >= 1 && p <= pageCount && !order.includes(p)) order.push(p);
  };
  if (cited) {
    push(cited);
    push(cited + 1);
    push(cited - 1);
  }
  for (let p = 1; p <= pageCount; p++) push(p);
  return order;
}

/** First page number in a citation page value such as 3, "3", or "41-42". */
export function firstPage(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) return Math.floor(value);
  if (typeof value === "string") {
    const m = value.match(/\d+/);
    if (m) return Number(m[0]) || null;
  }
  return null;
}
