// A question for the Assistant raised from inside a document (e.g. "compare this clause with the firm's precedents",
// plan 22 W3.4). The workbench registers itself and answers in its Assistant side view; elsewhere the question
// opens the Assistant page with the document attached.

export type AssistantRequest = { prompt: string; documentId: string };
type Handler = (r: AssistantRequest) => void;

let handler: Handler | null = null;

export function registerAssistantRequests(h: Handler): () => void {
  handler = h;
  return () => {
    if (handler === h) handler = null;
  };
}

/** Hand the question to the workbench Assistant if one is open; otherwise return the Assistant page URL to open. */
export function askAssistant(r: AssistantRequest): string | null {
  if (handler) {
    handler(r);
    return null;
  }
  const q = new URLSearchParams({ q: r.prompt, send: "1" });
  q.append("doc", r.documentId);
  return `/chat?${q.toString()}`;
}

export function comparePrompt(title: string, quote: string, page?: number | null): string {
  const where = page ? ` (page ${page})` : "";
  return (
    `Compare this clause from “${title}”${where} with the firm's precedents on the same point (use find_precedents) ` +
    `and note, point by point, where it departs from them:\n\n“${quote.trim()}”`
  );
}
