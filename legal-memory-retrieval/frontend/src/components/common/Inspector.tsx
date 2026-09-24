import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Icon, MonoId, SectionLabel, StatusLabel, Hairline } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { useClient, useDocument, useMatter, usePerson } from "@/api/resources";

export type InspectorTarget = {
  type: "matter" | "person" | "client" | "document";
  id: string;
  /** Optional highlight for document peeks (chunk from a citation). */
  chunkId?: string;
};

type InspectorContextValue = {
  open: (target: InspectorTarget) => void;
  close: () => void;
};

const InspectorContext = createContext<InspectorContextValue | null>(null);

export function useInspector() {
  return useContext(InspectorContext);
}

export function InspectorProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<InspectorTarget | null>(null);
  const open = useCallback((t: InspectorTarget) => setTarget(t), []);
  const close = useCallback(() => setTarget(null), []);
  const value = useMemo(() => ({ open, close }), [open, close]);

  return (
    <InspectorContext.Provider value={value}>
      {children}
      <Sheet open={!!target} onOpenChange={(v) => !v && close()}>
        <SheetContent
          side="right"
          className="w-[360px] overflow-y-auto border-l border-border bg-card p-0 sm:max-w-[360px]"
          data-testid="entity-inspector"
        >
          {target && <InspectorBody target={target} onClose={close} />}
        </SheetContent>
      </Sheet>
    </InspectorContext.Provider>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-3 py-2.5 text-sm">
      <div className="meta-label pt-0.5">{label}</div>
      <div className="col-span-2 text-foreground">{children}</div>
    </div>
  );
}

function Header({
  type,
  title,
  sub,
  to,
  onClose,
}: {
  type: string;
  title: string;
  sub?: ReactNode;
  to?: string;
  onClose: () => void;
}) {
  return (
    <div className="sticky top-0 z-10 border-b border-border bg-card px-6 pb-4 pt-6">
      <div className="flex items-start justify-between">
        <div className="eyebrow text-wine">{type}</div>
        <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground" data-testid="inspector-close">
          <Icon name="close" style={{ fontSize: 18 }} />
        </button>
      </div>
      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">{title}</h3>
      {sub && <div className="mt-1">{sub}</div>}
      {to && (
        <Link
          to={to}
          onClick={onClose}
          className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-wine hover:underline"
          data-testid="inspector-open-full"
        >
          Open full record <Icon name="arrow_forward" style={{ fontSize: 16 }} />
        </Link>
      )}
    </div>
  );
}

function InspectorBody({ target, onClose }: { target: InspectorTarget; onClose: () => void }) {
  switch (target.type) {
    case "matter":
      return <MatterPeek id={target.id} onClose={onClose} />;
    case "person":
      return <PersonPeek id={target.id} onClose={onClose} />;
    case "client":
      return <ClientPeek id={target.id} onClose={onClose} />;
    case "document":
      return <DocumentPeek id={target.id} chunkId={target.chunkId} onClose={onClose} />;
  }
}

function Padded({ children }: { children: ReactNode }) {
  return <div className="px-6 py-6">{children}</div>;
}

function MatterPeek({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useMatter(id);
  return (
    <QueryState query={q} loading={<Padded>Loading…</Padded>}>
      {({ matter: m, team }) => (
        <div>
          <Header type="Matter" title={m.title} sub={<MonoId>{m.matter_code}</MonoId>} to={`/matters/${m.matter_id}`} onClose={onClose} />
          <div className="px-6 py-4">
            {m.client_name && <Row label="Client">{m.client_name}</Row>}
            <Row label="Practice">{m.practice_area}</Row>
            {m.court && <Row label="Forum">{m.court}</Row>}
            <Row label="Status">
              <StatusLabel status={m.restricted ? "Restricted" : m.status || "Open"} />
            </Row>
            {team.length > 0 && (
              <>
                <Hairline className="my-3" />
                <SectionLabel>Team</SectionLabel>
                <ul className="space-y-1.5 text-sm">
                  {team.map((t) => (
                    <li key={t.member_id} className="flex justify-between">
                      <span>{t.name}</span>
                      <span className="text-xs text-muted-foreground">{t.role_on_matter}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {m.legal_issues.length > 0 && (
              <>
                <Hairline className="my-3" />
                <SectionLabel>Key issues</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {m.legal_issues.map((k) => (
                    <span key={k} className="rounded-full bg-secondary px-2.5 py-0.5 text-xs">
                      {k}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </QueryState>
  );
}

function PersonPeek({ id, onClose }: { id: string; onClose: () => void }) {
  const q = usePerson(id);
  return (
    <QueryState query={q} loading={<Padded>Loading…</Padded>}>
      {({ person: p, matters }) => (
        <div>
          <Header
            type="Person"
            title={p.name}
            sub={<span className="text-sm text-muted-foreground">{[p.role, p.office].filter(Boolean).join(" · ")}</span>}
            to={`/people/${p.member_id}`}
            onClose={onClose}
          />
          <div className="px-6 py-4">
            {p.practice_areas.length > 0 && <Row label="Practices">{p.practice_areas.join(" · ")}</Row>}
            {p.specializations.length > 0 && <Row label="Focus">{p.specializations.join(" · ")}</Row>}
            {p.joined_year && <Row label="Joined">{p.joined_year}</Row>}
            <Row label="Matters">{matters.length} in your scope</Row>
          </div>
        </div>
      )}
    </QueryState>
  );
}

function ClientPeek({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useClient(id);
  return (
    <QueryState query={q} loading={<Padded>Loading…</Padded>}>
      {(c) => (
        <div>
          <Header type="Client" title={c.name} sub={<MonoId>{c.client_id}</MonoId>} to={`/clients/${c.client_id}`} onClose={onClose} />
          <div className="px-6 py-4">
            {c.industry && <Row label="Industry">{c.industry}</Row>}
            {c.headquarters && <Row label="HQ">{c.headquarters}</Row>}
            <Row label="Matters">{c.matters.length} in your scope</Row>
            {c.notes.length > 0 && (
              <>
                <Hairline className="my-3" />
                <SectionLabel>Client memory</SectionLabel>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {c.notes.slice(0, 3).map((n) => (
                    <li key={n.note_id}>{n.text}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </QueryState>
  );
}

function DocumentPeek({ id, chunkId, onClose }: { id: string; chunkId?: string; onClose: () => void }) {
  const q = useDocument(id, { chunk_id: chunkId });
  return (
    <QueryState query={q} loading={<Padded>Loading…</Padded>}>
      {(d) => {
        const passage =
          d.chunks.find((c) => c.chunk_id === (chunkId || d.highlight_chunk_id))?.text ??
          d.chunks[0]?.text ??
          (d.body ?? "").slice(0, 600);
        return (
          <div>
            <Header type={d.document_type} title={d.title} sub={<MonoId>{d.document_id}</MonoId>} to={`/documents/${d.document_id}`} onClose={onClose} />
            <div className="px-6 py-4">
              {d.matter_id && (
                <Row label="Matter">
                  <Link to={`/matters/${d.matter_id}`} onClick={onClose} className="text-wine hover:underline">
                    {d.matter_info?.title ?? d.matter_code}
                  </Link>
                </Row>
              )}
              {d.author_name && <Row label="Author">{d.author_name}</Row>}
              {d.doc_date && <Row label="Date">{d.doc_date}</Row>}
              <Hairline className="my-3" />
              <SectionLabel>{chunkId ? "Cited passage" : "Opening passage"}</SectionLabel>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{passage}</p>
              <div className="mt-4 flex flex-col gap-2">
                <Link to={`/documents/${d.document_id}`} onClick={onClose} className="text-sm font-semibold text-wine hover:underline">
                  Open document
                </Link>
                <Link to={`/documents/${d.document_id}/history`} onClick={onClose} className="text-sm font-semibold text-wine hover:underline">
                  View version history
                </Link>
              </div>
            </div>
          </div>
        );
      }}
    </QueryState>
  );
}
