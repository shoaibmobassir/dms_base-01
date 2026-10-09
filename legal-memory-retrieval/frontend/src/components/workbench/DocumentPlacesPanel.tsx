import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { copyDocument, linkDocument, moveHome, unlinkDocument, useDocumentPlaces, workspaceHref, type Place } from "@/api/workspaces";
import { useConfirm } from "@/components/common/Confirm";
import { firmError } from "@/api/firm";
import { Chip, Icon, SectionLabel } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { LibraryShareDialog, TagsDialog, TargetDialog, type TargetChoice } from "./dialogs";

const PLACE_ICON: Record<Place["kind"], string> = { matter: "gavel", project: "folder_special", library: "person", firm: "library_books" };

/** Where a document lives (its home) and the other workspaces it is shown in, its tags, and how to add it elsewhere. */
export function DocumentPlacesPanel({ documentId, title }: { documentId: string; title: string }) {
  const places = useDocumentPlaces(documentId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast, me } = useApp();
  const confirm = useConfirm();
  const [asking, setAsking] = useState<"link" | "copy" | "file" | "tags" | "share" | null>(null);
  const data = places.data;
  if (!data) return null;
  const home = data.places.find((p) => p.home);
  const canFile = data.my_level !== "read" && home && !home.hidden && home.kind !== "matter";
  const mineInLibrary = home?.kind === "library" && home.id === me?.member_id;
  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("document-places") || q.queryKey.includes("workspace") });

  return (
    <div className="space-y-2" data-testid="document-places">
      <SectionLabel>Where it lives</SectionLabel>
      <ul className="space-y-1">
        {data.places.map((p, i) =>
          p.hidden ? (
            <li key={`hidden-${i}`} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Icon name="lock" style={{ fontSize: 14 }} /> A workspace you cannot open
            </li>
          ) : (
            <li key={`${p.kind}:${p.id}`} className="flex items-center gap-1.5">
              <Icon name={PLACE_ICON[p.kind]} className="text-muted-foreground" style={{ fontSize: 15 }} />
              {p.kind === "library" && p.id !== me?.member_id ? (
                // Someone else's library: it cannot be opened, only this document (shared with you).
                <span className="min-w-0 truncate">{p.label}</span>
              ) : (
                <Link
                  to={`${workspaceHref(p.kind, p.kind === "library" ? "me" : p.id!)}?doc=${encodeURIComponent(documentId)}`}
                  className="min-w-0 truncate text-wine hover:underline"
                  title="Open in the workbench"
                >
                  {p.label}
                </Link>
              )}
              {p.folder ? <span className="truncate text-xs text-muted-foreground">/ {p.folder}</span> : null}
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{p.home ? "lives here" : "also shown here"}</span>
              {!p.home && p.id && (
                <button type="button" aria-label={`Stop showing it in ${p.label}`} title={`Stop showing it in ${p.label}`}
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  onClick={async () => {
                    if (!(await confirm({ title: `Stop showing it in ${p.label}?`, description: "The document is not deleted; it stays where it lives.", confirmLabel: "Remove" }))) return;
                    try {
                      await unlinkDocument(documentId, p.kind, p.kind === "library" ? "me" : p.id!);
                      await refresh();
                    } catch (err) {
                      toast(firmError(err));
                    }
                  }}>
                  <Icon name="link_off" style={{ fontSize: 14 }} />
                </button>
              )}
            </li>
          ),
        )}
      </ul>
      {data.derived_from && (
        <p className="text-xs text-muted-foreground">
          Copied from{" "}
          <Link to={`/documents/${encodeURIComponent(data.derived_from.document_id)}`} className="text-wine hover:underline">
            {data.derived_from.title ?? data.derived_from.document_id}
          </Link>
        </p>
      )}
      <div className="flex flex-wrap gap-1">
        {data.tags.system.filter((t) => t.kind === "client" || t.kind === "type").map((t) => <Chip key={t.key}>{t.label}</Chip>)}
        {data.tags.user.map((t) => <Chip key={t} tone="accent">#{t}</Chip>)}
      </div>
      <div className="flex flex-wrap gap-1.5 pt-1">
        {mineInLibrary && (
          <Button variant="outline" size="sm" onClick={() => setAsking("share")} data-testid="document-share">
            <Icon name="person_add" style={{ fontSize: 15 }} /> Share
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => setAsking("link")} data-testid="document-add-to-workspace">
          <Icon name="add_link" style={{ fontSize: 15 }} /> Show elsewhere…
        </Button>
        <Button variant="outline" size="sm" onClick={() => setAsking("copy")}>
          <Icon name="content_copy" style={{ fontSize: 15 }} /> Copy
        </Button>
        {canFile && (
          <Button variant="outline" size="sm" onClick={() => setAsking("file")}>
            <Icon name="drive_file_move" style={{ fontSize: 15 }} /> {home?.kind === "library" ? "Move to matter or project…" : "File into a matter…"}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setAsking("tags")}>
          <Icon name="sell" style={{ fontSize: 15 }} /> Tags
        </Button>
      </div>

      <TargetDialog
        open={asking === "link"}
        onOpenChange={(o) => !o && setAsking(null)}
        title="Show in another workspace"
        description="Nothing is copied: the document shows in both places and stays one document with one history. People there see it only if they can already read it where it lives."
        confirm="Add"
        kinds={["project", "matter", "library"]}
        onConfirm={async (t: TargetChoice) => {
          await linkDocument(documentId, t);
          await refresh();
          toast("Added — it is the same document in both places");
        }}
      />
      <TargetDialog
        open={asking === "copy"}
        onOpenChange={(o) => !o && setAsking(null)}
        title="Make a copy"
        description="A separate document with its own history, starting from this version."
        confirm="Make copy"
        kinds={["library", "project", "matter"]}
        askTitle
        defaultTitle={title}
        onConfirm={async (t: TargetChoice) => {
          const made = await copyDocument(documentId, t);
          await refresh();
          toast("Copy made", { action: { label: "Open copy", onClick: () => navigate(`/documents/${encodeURIComponent(made.document_id)}`) } });
        }}
      />
      <TargetDialog
        open={asking === "file"}
        onOpenChange={(o) => !o && setAsking(null)}
        title={home?.kind === "library" ? "Move it to a matter or project" : "File it into a matter"}
        description="Its new home decides who can read it from now on. It stays visible where it was, as a link."
        confirm="Move"
        kinds={home?.kind === "library" ? ["matter", "project"] : ["matter"]}
        onConfirm={async (t: TargetChoice) => {
          await moveHome(documentId, t);
          await queryClient.invalidateQueries();
          toast("Filed");
        }}
      />
      {asking === "share" && <LibraryShareDialog documentId={documentId} title={title} open onOpenChange={(o) => !o && setAsking(null)} />}
      {asking === "tags" && <TagsDialog documentId={documentId} open onOpenChange={(o) => !o && setAsking(null)} onChanged={() => void refresh()} />}
    </div>
  );
}
