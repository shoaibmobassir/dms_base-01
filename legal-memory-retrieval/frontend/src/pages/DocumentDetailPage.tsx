import { Navigate, useParams } from "react-router-dom";
import { DocumentWorkspace } from "@/components/document-workspace/DocumentWorkspace";

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  return <DocumentWorkspace documentId={id} />;
}

/** Old history route — versions live in the workspace rail. */
export function DocumentHistoryRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/documents/${encodeURIComponent(id)}?panel=versions`} replace />;
}
