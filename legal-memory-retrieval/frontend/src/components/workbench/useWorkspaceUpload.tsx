import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { ACCEPTED_TYPES, fileProblem, pathOf, uploadToWorkspace } from "@/api/uploads";
import { checkDuplicates, linkDocument, sha256Hex, type DuplicateMatch, type WorkspaceKind } from "@/api/workspaces";
import { useApp } from "@/context/AppContext";
import { DuplicatesDialog, type DuplicateDecision } from "./dialogs";

type Pending = { files: File[]; folder: string; dupes: { name: string; sha: string; matches: DuplicateMatch[]; file: File }[] };

/** What the upload is doing now, for a progress line ("Checking 3 files…", "Uploading 2 of 5…"). */
export type UploadProgress = { phase: "checking" | "uploading"; done: number; total: number } | null;

/**
 * Upload into a workspace folder. Files that already exist as documents the person can read are offered as a link
 * to the existing document (one copy, one history) instead of a second upload.
 */
export function useWorkspaceUpload(kind: WorkspaceKind, id: string, onDone?: (documentIds: string[]) => void, testId = "workspace-upload-input") {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const input = useRef<HTMLInputElement | null>(null);
  const folderRef = useRef("");
  const [progress, setProgress] = useState<UploadProgress>(null);
  const [pending, setPending] = useState<Pending | null>(null);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("workspace") || q.queryKey.includes("projects") }),
    [queryClient],
  );

  const finish = useCallback(
    async (files: File[], folder: string, links: DuplicateMatch[]) => {
      setProgress({ phase: "uploading", done: 0, total: files.length + links.length });
      try {
        const ids: string[] = [];
        for (const m of links) {
          await linkDocument(m.document_id, { kind, id, folder });
          ids.push(m.document_id);
        }
        const failures: string[] = [];
        let duplicates = 0;
        if (files.length) {
          const outcomes = await uploadToWorkspace(kind, id, files, {
            folderPrefix: folder,
            onProgress: (done, total) => setProgress({ phase: "uploading", done: done + links.length, total: total + links.length }),
          });
          for (const o of outcomes) {
            if (o.status === "failed") failures.push(`${pathOf(o.file)}: ${o.error ?? "could not be read"}`);
            if (o.status === "duplicate") duplicates += 1;
            if (o.documentId) ids.push(o.documentId);
          }
        }
        await refresh();
        const uploaded = files.length - failures.length - duplicates;
        const parts = [
          uploaded > 0 ? `${uploaded} uploaded` : null,
          links.length ? `${links.length} added from where ${links.length === 1 ? "it lives" : "they live"}` : null,
          duplicates ? `${duplicates} already here` : null,
        ].filter(Boolean);
        if (failures.length) {
          toast(`${failures.length} ${failures.length === 1 ? "file" : "files"} not uploaded — ${failures.slice(0, 2).join("; ")}${failures.length > 2 ? "; …" : ""}`);
        }
        if (parts.length) toast(parts.join(" · "));
        onDone?.(ids);
      } catch (err) {
        toast(firmError(err));
      } finally {
        setProgress(null);
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
      setProgress({ phase: "checking", done: 0, total: good.length });
      try {
        // One file at a time, so a large batch never holds every file in memory at once.
        const hashed: { file: File; sha: string }[] = [];
        for (const f of good) {
          hashed.push({ file: f, sha: await sha256Hex(f) });
          setProgress({ phase: "checking", done: hashed.length, total: good.length });
        }
        const { matches } = await checkDuplicates(kind, id, hashed.map((h) => h.sha));
        const dupes = hashed
          .filter((h) => matches[h.sha]?.length)
          .map((h) => ({ name: pathOf(h.file), sha: h.sha, matches: matches[h.sha], file: h.file }));
        if (dupes.length) {
          setPending({ files: good, folder, dupes });
          setProgress(null);
          return;
        }
        await finish(good, folder, []);
      } catch (err) {
        toast(firmError(err));
        setProgress(null);
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
      const choice = decision[d.sha]?.choice ?? "skip";
      if (choice === "upload") continue;
      skipFiles.add(d.file);
      if (choice === "link" && !d.matches.some((m) => m.already_here)) {
        links.push(d.matches.find((m) => m.document_id === decision[d.sha]?.documentId) ?? d.matches[0]);
      }
    }
    const files = pending.files.filter((f) => !skipFiles.has(f));
    const folder = pending.folder;
    setPending(null);
    if (!files.length && !links.length) return;
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
        data-testid={testId}
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

  return { pick, upload: start, busy: progress !== null, progress, element };
}
