import { createContext, useContext } from "react";

/**
 * Set when a document page runs inside a workbench tab: its actions (edit in Word, …) open as workbench tabs instead
 * of leaving the workbench for a full page.
 */
export type WorkbenchHost = { openWordEditor: (documentId: string, title: string) => void };

export const WorkbenchHostContext = createContext<WorkbenchHost | null>(null);

export const useWorkbenchHost = () => useContext(WorkbenchHostContext);
