import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { copyDocument, linkDocument, moveHome, useDocumentPlaces, workspaceHref, type Place } from "@/api/workspaces";
import { Chip, Icon, SectionLabel } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { TagsDialog, TargetDialog, type TargetChoice } from "./dialogs";

const PLACE_ICON: Record<Place["kind"], string> = { matter: "gavel", project: "folder_special", library: "person", firm: "library_books" };

/** Where a document lives (its home) and the other workspaces it is shown in, its tags, and how to add it elsewhere. */
export function DocumentPlacesPanel({ documentId, title }: { documentId: string; title: string }) {
  const places = useDocumentPlaces(documentId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useApp();
  const [asking, setAsking] = useState<"link" | "copy" | "file" | "tags" | null>(null);
  const data = places.data;
  if (!data) return null;
  const home = data.places.find((p) => p.home);
  const canFile = data.my_level !== "read" && home && !home.hidden && home.kind !== "matter";
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
              <Link
                to={`${workspaceHref(p.kind, p.kind === "library" ? "me" : p.id!)}?doc=${encodeURIComponent(documentId)}`}
                className="min-w-0 truncate text-wine hover:underline"
                title="Open in the workbench"
              >
                {p.label}
              </Link>
              {p.folder ? <span className="truncate text-xs text-muted-foreground">/ {p.folder}</span> : null}
              <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{p.home ? "home" : "linked"}</span>
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
        <Button variant="outline" size="sm" onClick={() => setAsking("link")} data-testid="document-add-to-workspace">
          <Icon name="add_link" style={{ fontSize: 15 }} /> Add to…
        </Button>
        <Button variant="outline" size="sm" onClick={() => setAsking("copy")}>
          <Icon name="content_copy" style={{ fontSize: 15 }} /> Copy
        </Button>
        {canFile && (
          <Button variant="outline" size="sm" onClick={() => setAsking("file")}>
            <Icon name="gavel" style={{ fontSize: 15 }} /> File
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setAsking("tags")}>
          <Icon name="sell" style={{ fontSize: 15 }} /> Tags
        </Button>
      </div>

      <TargetDialog
        open={asking === "link"}
        onOpenChange={(o) => !o && setAsking(null)}
        title="Add to another workspace"
        description="The document is not copied: it shows in both places and stays one document with one history. People there see it only if they can already read it."
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
          toast("Copy made");
          navigate(`/documents/${encodeURIComponent(made.document_id)}`);
        }}
      />
      <TargetDialog
        open={asking === "file"}
        onOpenChange={(o) => !o && setAsking(null)}
        title={home?.kind === "library" ? "Move to a matter or project" : "File into a matter"}
        description="The matter becomes the document's home and its access rules apply from now on. It stays visible where it was as a link."
        confirm="File"
        kinds={home?.kind === "library" ? ["matter", "project"] : ["matter"]}
        onConfirm={async (t: TargetChoice) => {
          await moveHome(documentId, t);
          await queryClient.invalidateQueries();
          toast("Filed");
        }}
      />
      {asking === "tags" && <TagsDialog documentId={documentId} open onOpenChange={(o) => !o && setAsking(null)} onChanged={() => void refresh()} />}
    </div>
  );
}
