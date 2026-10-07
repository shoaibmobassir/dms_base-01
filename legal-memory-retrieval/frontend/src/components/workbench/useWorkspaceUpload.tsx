import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { ACCEPTED_TYPES, fileProblem, pathOf, uploadToWorkspace } from "@/api/uploads";
import { checkDuplicates, linkDocument, sha256Hex, type DuplicateMatch, type WorkspaceKind } from "@/api/workspaces";
import { useApp } from "@/context/AppContext";
import { DuplicatesDialog, type DuplicateDecision } from "./dialogs";

type Pending = { files: File[]; folder: string; dupes: { name: string; sha: string; matches: DuplicateMatch[]; file: File }[] };

/**
 * Upload into a workspace folder. Files that already exist as documents the person can read are offered as a link
 * to the existing document (one copy, one history) instead of a second upload.
 */
export function useWorkspaceUpload(kind: WorkspaceKind, id: string, onDone?: (documentIds: string[]) => void) {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const input = useRef<HTMLInputElement | null>(null);
  const folderRef = useRef("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("workspace") || q.queryKey.includes("projects") }),
    [queryClient],
  );

  const finish = useCallback(
    async (files: File[], folder: string, links: DuplicateMatch[]) => {
      setBusy(true);
      try {
        const ids: string[] = [];
        for (const m of links) {
          await linkDocument(m.document_id, { kind, id, folder });
          ids.push(m.document_id);
        }
        let failed = 0;
        let duplicates = 0;
        if (files.length) {
          const outcomes = await uploadToWorkspace(kind, id, files, { folderPrefix: folder });
          for (const o of outcomes) {
            if (o.status === "failed") failed += 1;
            if (o.status === "duplicate") duplicates += 1;
            if (o.documentId) ids.push(o.documentId);
          }
        }
        await refresh();
        const parts = [
          files.length - failed - duplicates > 0 ? `${files.length - failed - duplicates} uploaded` : null,
          links.length ? `${links.length} linked` : null,
          duplicates ? `${duplicates} already here` : null,
          failed ? `${failed} failed` : null,
        ].filter(Boolean);
        toast(parts.join(" · ") || "Nothing to upload");
        onDone?.(ids);
      } catch (err) {
        toast(firmError(err));
      } finally {
        setBusy(false);
      }
    },
    [kind, id, refresh, toast, onDone],
  );

  const start = useCallback(
    async (files: File[], folder: string) => {
      const bad = files.map((f) => [f, fileProblem(f)] as const).filter(([, p]) => p);
      if (bad.length) toast(`${bad.length} file${bad.length === 1 ? "" : "s"} skipped: ${bad[0][1]}`);
      const good = files.filter((f) => !fileProblem(f));
      if (!good.length) return;
      setBusy(true);
      try {
        const hashed = await Promise.all(good.map(async (f) => ({ file: f, sha: await sha256Hex(f) })));
        const { matches } = await checkDuplicates(kind, id, hashed.map((h) => h.sha));
        const dupes = hashed
          .filter((h) => matches[h.sha]?.length)
          .map((h) => ({ name: pathOf(h.file), sha: h.sha, matches: matches[h.sha], file: h.file }));
        if (dupes.length) {
          setPending({ files: good, folder, dupes });
          setBusy(false);
          return;
        }
        await finish(good, folder, []);
      } catch (err) {
        toast(firmError(err));
        setBusy(false);
      }
    },
    [kind, id, finish, toast],
  );

  const pick = useCallback((folder: string) => {
    folderRef.current = folder;
    input.current?.click();
  }, []);

  const resolve = (decision: DuplicateDecision) => {
    if (!pending) return;
    const skipFiles = new Set<File>();
    const links: DuplicateMatch[] = [];
    for (const d of pending.dupes) {
      const choice = decision[d.sha] ?? "link";
      if (choice === "upload") continue;
      skipFiles.add(d.file);
      if (choice === "link" && !d.matches.some((m) => m.already_here)) links.push(d.matches[0]);
    }
    const files = pending.files.filter((f) => !skipFiles.has(f));
    const folder = pending.folder;
    setPending(null);
    void finish(files, folder, links);
  };

  const element = (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_TYPES}
        className="hidden"
        data-testid="workspace-upload-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) void start(files, folderRef.current);
        }}
      />
      <DuplicatesDialog
        open={!!pending}
        files={pending?.dupes ?? []}
        onCancel={() => setPending(null)}
        onConfirm={resolve}
      />
    </>
  );

  return { pick, upload: start, busy, element };
}
