import type { Citation } from "@/api/types";
import { displayQuote } from "@/components/chat/CitationDocumentPanel";

/** A quote in curly quotation marks, unless the text already opens with one. */
export function quoted(text: string): string {
  const t = displayQuote(text);
  return /^["“]/.test(t) ? t : `“${t}”`;
}

/** Every verified quote behind a citation (a compound claim can rest on two or three). */
export function citationQuotes(c: Citation): string[] {
  const quotes = Array.isArray(c.quotes)
    ? (c.quotes as { quote?: unknown }[]).map((q) => (typeof q?.quote === "string" ? q.quote : "")).filter(Boolean)
    : [];
  if (quotes.length) return quotes.slice(0, 3);
  return typeof c.quote === "string" && c.quote ? [c.quote] : [];
}
