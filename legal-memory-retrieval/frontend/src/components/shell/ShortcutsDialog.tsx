import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = MAC ? "⌘" : "Ctrl";

const GROUPS: { title: string; rows: [string, string][] }[] = [
  {
    title: "Anywhere",
    rows: [
      [`${MOD} K`, "Search and commands"],
      ["?", "Show this list"],
    ],
  },
  {
    title: "Assistant and Ask",
    rows: [
      ["Enter", "Send"],
      ["Shift Enter", "New line"],
      [MAC ? "⌥ H" : "Alt H", "Show or hide conversation history (Assistant)"],
      ["Esc", "Close the document panel"],
    ],
  },
  {
    title: "Reading a document",
    rows: [
      ["← →", "Previous or next page"],
      ["Home End", "First or last page"],
      ["G", "Go to a page"],
      ["/", "Find in the document"],
    ],
  },
];

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="shortcuts">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts that type into a field are off while you are typing.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {GROUPS.map((g) => (
            <section key={g.title}>
              <h3 className="meta-label mb-2">{g.title}</h3>
              <dl className="divide-y divide-border">
                {g.rows.map(([keys, what]) => (
                  <div key={keys} className="flex items-baseline justify-between gap-4 py-2 text-sm">
                    <dt className="text-foreground">{what}</dt>
                    <dd>
                      <kbd className="rounded border border-border bg-secondary px-1.5 py-0.5 font-mono-id text-xs">{keys}</kbd>
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
