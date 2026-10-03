import type { ReactNode } from "react";
import type { Attachment, DocumentItem } from "@/api/types";
import { useDocuments, useMatter } from "@/api/resources";
import { Icon } from "@/components/common/primitives";
import { FileEdit, FileSearch, FileSpreadsheet, GitCompare, Scale, Search } from "lucide-react";

/** Open-matter suggestions are whole questions and send at once; task cards drop a starting prompt into the box. */
/** Starter cards for a conversation limited to one matter: its own documents and next steps. */
function matterCards(matter: { title: string }, docs: DocumentItem[]) {
  const shortTitle = (t: string) => t.replace(/\.(docx?|pdf|txt)$/i, "");
  return [
    {
      title: "Where the matter stands",
      query: `Summarise where ${matter.title} stands: the parties, the issues, and what is due next.`,
      icon: <Scale className="w-4 h-4 text-muted-foreground" />,
    },
    {
      title: "Draft a status note",
      query: `Draft a short status note to the client on ${matter.title}, citing the documents.`,
      icon: <FileEdit className="w-4 h-4 text-muted-foreground" />,
    },
    ...docs.slice(0, 4).map((d) => ({
      title: `Review ${shortTitle(d.title)}`,
      query: `Review ${shortTitle(d.title)} and list the key risks and obligations.`,
      icon: <FileSearch className="w-4 h-4 text-warning-ink" />,
      file: { document_id: d.document_id, filename: d.title } as Attachment,
    })),
  ];
}

export function EmptyThread({
  composer,
  suggestions,
  matterId,
  onPick,
  onInsert,
}: {
  /** The message box, shown under the greeting. */
  composer: ReactNode;
  suggestions: string[];
  matterId?: string | null;
  onPick: (s: string) => void;
  onInsert: (text: string, file?: Attachment) => void;
}) {
  const matter = useMatter(matterId ?? "");
  const matterDocs = useDocuments({ matter_id: matterId ?? undefined, limit: 4, enabled: !!matterId });
  const scoped = matterId && matter.data ? matterCards(matter.data.matter, matterDocs.data?.items ?? []) : null;
  const generic: { title: string; query: string; icon: React.ReactNode; file?: Attachment }[] = [
    {
      title: "Analyze a document",
      query: "Review this agreement and identify key risks.",
      icon: <FileSearch className="w-4 h-4 text-warning-ink" />,
    },
    {
      title: "Find a clause",
      query: "Find all termination clauses across this matter.",
      icon: <Search className="w-4 h-4 text-muted-foreground" />,
    },
    {
      title: "Compare documents",
      query: "Compare the latest SPA against the previous version.",
      icon: <GitCompare className="w-4 h-4 text-muted-foreground" />,
    },
    {
      title: "Legal research",
      query: "What Indian cases discuss specific performance in similar circumstances?",
      icon: <Scale className="w-4 h-4 text-muted-foreground" />,
    },
    {
      title: "Draft",
      query: "Draft a concise NDA based on the attached precedent.",
      icon: <FileEdit className="w-4 h-4 text-muted-foreground" />,
    },
    {
      title: "Summarize",
      query: "Summarize the key commercial terms of these contracts.",
      icon: <FileSpreadsheet className="w-4 h-4 text-muted-foreground" />,
    },
  ];

  const cards = scoped ?? generic;
  return (
    <div className="flex w-full flex-col items-center py-6 animate-in fade-in-50 duration-300">
      <div className="mb-6 max-w-lg text-center">
        <h2 className="font-display text-3xl font-normal tracking-tight text-ink">
          {scoped && matter.data ? `Working on ${matter.data.matter.matter_code}` : "What would you like to work on?"}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {scoped && matter.data ? matter.data.matter.title : "Ask the firm's records, review documents, research authorities or draft."}
        </p>
      </div>

      {composer}

      <div className="mt-6 w-full max-w-3xl px-4">
        <div className="sr-only" data-testid="chat-starters-label">
          {scoped && matter.data ? `Start on ${matter.data.matter.matter_code}` : "Start from a task"}
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {cards.map((card, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => onInsert(card.query, "file" in card ? card.file : undefined)}
              title={card.query}
              data-testid="chat-starter"
              className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-border bg-card px-3.5 py-2 text-[13px] text-foreground transition-colors hover:border-wine/40 hover:bg-wine-soft"
            >
              {card.icon}
              <span>{card.title}</span>
            </button>
          ))}
        </div>

        {!scoped && suggestions.length > 0 && (
          <div className="mx-auto mt-6 max-w-2xl">
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">From your open matters</div>
            <div className="divide-y divide-border border-y border-border">
              {suggestions.slice(0, 3).map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => onPick(q)}
                  data-testid="chat-suggestion"
                  className="group flex w-full cursor-pointer items-center gap-2 px-1 py-2.5 text-left text-[13.5px] transition-colors hover:bg-secondary/50"
                >
                  <Icon name="north_east" className="text-muted-foreground group-hover:text-wine" style={{ fontSize: 15 }} />
                  <span className="text-ink group-hover:text-wine">{q}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
