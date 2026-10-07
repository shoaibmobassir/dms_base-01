import { useParams } from "react-router-dom";
import { FullWordEditor } from "@/components/editor/FullWordEditor";

/** The full Word editor on its own page (plan 22, W2b). */
export function FullEditorPage() {
  const { id = "" } = useParams();
  return <FullWordEditor documentId={id} />;
}
