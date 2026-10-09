import type { Attachment } from "@/api/types";

/** Drag type for a page (or part) of a document dragged out of the viewer into the Assistant. */
export const PAGE_DRAG_TYPE = "application/x-precentis-page";

export type PageDrag = {
  document_id: string;
  filename: string;
  unit: "page" | "part";
  number: number;
  version_id?: string;
  part_size?: number;
  /** The page as the viewer renders it (Pages mode), not the stored text's page. */
  rendered?: boolean;
};

export function pageLabel(p: Pick<PageDrag, "unit" | "number">) {
  return `${p.unit === "page" ? "Page" : "Part"} ${p.number}`;
}

/** Start dragging a page: the drop carries a reference, plus a plain-text label for anything else it lands on. */
export function startPageDrag(e: { dataTransfer: DataTransfer }, page: PageDrag) {
  e.dataTransfer.setData(PAGE_DRAG_TYPE, JSON.stringify(page));
  e.dataTransfer.setData("text/plain", `${pageLabel(page)} of ${page.filename}`);
  e.dataTransfer.effectAllowed = "copy";
}

export function hasPageDrag(e: { dataTransfer: DataTransfer }) {
  return Array.from(e.dataTransfer.types).includes(PAGE_DRAG_TYPE);
}

export function readPageDrag(e: { dataTransfer: DataTransfer }): PageDrag | null {
  try {
    const raw = e.dataTransfer.getData(PAGE_DRAG_TYPE);
    if (!raw) return null;
    const p = JSON.parse(raw) as PageDrag;
    return p.document_id && p.number >= 1 && (p.unit === "page" || p.unit === "part") ? p : null;
  } catch {
    return null;
  }
}

/** A page as a message attachment: the document, pointing at one page of it. */
export function pageAttachment(p: PageDrag): Attachment {
  return {
    document_id: p.document_id,
    filename: p.filename,
    reference: { unit: p.unit, number: p.number, version_id: p.version_id, part_size: p.part_size, rendered: p.rendered },
  };
}

/** Two attachments are the same when they name the same document and the same page (or both none). */
export function attachmentKey(a: Attachment) {
  return `${a.document_id}:${a.reference ? `${a.reference.unit}-${a.reference.number}` : ""}`;
}

export function attachmentLabel(a: Attachment) {
  return a.reference ? `${pageLabel(a.reference)} · ${a.filename}` : a.filename;
}
