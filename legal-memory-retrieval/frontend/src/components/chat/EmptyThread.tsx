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
      icon: <Scale className="w-4 h-4 text-success-ink" />,
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
  suggestions,
  matterId,
  onPick,
  onInsert,
}: {
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
      icon: <Scale className="w-4 h-4 text-success-ink" />,
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

  return (
    <div className="select-none py-6 animate-in fade-in-50 duration-300">
      <div className="mx-auto mb-6 max-w-lg text-center">
        <h2 className="font-display text-2xl font-normal tracking-tight text-ink">
          What would you like to work on?
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Ask questions, analyze documents, research authorities, or draft.
        </p>
      </div>

      {!scoped && suggestions.length > 0 && (
        <div className="mb-6">
          <div className="meta-label mb-1.5 text-xs uppercase tracking-wider text-muted-foreground">
            From your open matters
          </div>
          <div className="space-y-0.5">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPick(s)}
                data-testid="chat-suggestion"
                className="group flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors hover:bg-secondary"
              >
                <Icon name="chevron_right" className="text-muted-foreground group-hover:text-wine" style={{ fontSize: 14 }} />
                <span className="text-ink group-hover:text-wine">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="meta-label mb-1.5 text-xs uppercase tracking-wider text-muted-foreground" data-testid="chat-starters-label">
        {scoped && matter.data ? `Start on ${matter.data.matter.matter_code}` : "Start from a task"}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
        {(scoped ?? generic).map((card, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onInsert(card.query, "file" in card ? card.file : undefined)}
            title="Put this prompt in the message box"
            data-testid="chat-starter"
            className="group flex cursor-pointer flex-col justify-between rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-wine/30 hover:bg-secondary/50"
          >
            <div className="mb-1.5 flex items-center gap-2">
              <span className="rounded-md bg-secondary p-1">{card.icon}</span>
              <h3 className="text-[13px] font-semibold text-ink group-hover:text-primary">{card.title}</h3>
            </div>
            <p className="line-clamp-2 text-[12px] leading-snug text-muted-foreground">&ldquo;{card.query}&rdquo;</p>
          </button>
        ))}
      </div>

    </div>
  );
}
