import type { ChatMessage, Citation } from "@/api/types";

function stamp(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** A conversation as Markdown: who said what and when, with each answer's sources listed under it. */
export function conversationAsMarkdown(title: string, messages: ChatMessage[]): string {
  const out: string[] = [`# ${title}`, ""];
  for (const m of messages) {
    if (m.role === "system" || !m.content.trim()) continue;
    const who = m.role === "user" ? "You" : "Assistant";
    const when = stamp(m.created_at);
    out.push(`## ${who}${when ? ` (${when})` : ""}`, "", m.content.trim(), "");
    const cites = (m.citations ?? []) as Citation[];
    if (m.role === "assistant" && cites.length) {
      out.push("Sources", "");
      for (const c of cites) out.push(`- [${String(c.ref ?? "")}] ${String(c.title ?? c.document_id ?? "Document")}${c.page != null ? `, p. ${String(c.page)}` : ""}`);
      out.push("");
    }
  }
  return out.join("\n");
}

export function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function safeFilename(title: string) {
  return (title.replace(/[^\w\s.-]/g, "").trim().replace(/\s+/g, "-").slice(0, 60) || "conversation") + ".md";
}
