import { Suspense, lazy, useCallback, useEffect, type Dispatch } from "react";
import { useDocument } from "@/api/resources";
import { displayTitle } from "@/api/workspaces";
import { DocumentWorkspace } from "@/components/document-workspace/DocumentWorkspace";
import { EmptyState, Icon } from "@/components/common/primitives";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { Button } from "@/components/ui/button";
import { useDirtyDocs } from "@/lib/dirtyDocs";
import { WorkbenchHostContext } from "@/lib/workbenchHost";
import { keys } from "@/lib/keys";
import { cn } from "@/lib/utils";
import { iconFor } from "./Explorer";
import { useReview } from "@/api/tabular";
import { ReviewTable } from "./ReviewTable";
import type { OpenRequest } from "./Explorer";
import { useTabParams, type Action, type DocumentTab, type Group, type Tab, type WorkbenchState, type WriteTab } from "./state";

type Dispatcher = Dispatch<Action>;
type CloseAction = Extract<Action, { type: "close" } | { type: "closeAll" }>;
const TAB_DRAG = "application/x-precentis-tab";
const FullWordEditor = lazy(() => import("@/components/editor/FullWordEditor").then((m) => ({ default: m.FullWordEditor })));

/** One editor group: a strip of tabs and the active tab's document. */
export function EditorGroup({
  group,
  index,
  state,
  dispatch,
  onClose,
  onOpen,
}: {
  group: Group;
  index: number;
  state: WorkbenchState;
  dispatch: Dispatcher;
  /** Closing goes through the workbench, which asks first when a tab has unsaved edits. */
  onClose: (a: CloseAction) => void;
  onOpen: (r: OpenRequest) => void;
}) {
  const focused = state.focused === index;
  const active = group.tabs.find((t) => t.id === group.active) ?? null;
  const many = state.groups.length > 1;
  const dirty = useDirtyDocs();
  // Word editors stay mounted while another tab is shown, so switching tabs never drops typing or the edit lock.
  const writers = group.tabs.filter((t): t is WriteTab => t.kind === "write");
  const closeTab = (t: Tab) => onClose({ type: "close", group: index, tabId: t.id });

  return (
    <section
      className={cn("flex min-h-0 min-w-0 flex-1 flex-col", many && !focused && "opacity-[0.97]")}
      onMouseDownCapture={() => dispatch({ type: "focus", group: index })}
      onFocusCapture={() => dispatch({ type: "focus", group: index })}
      aria-label={`Editor group ${index + 1}`}
      data-testid={`editor-group-${index}`}
    >
      <div
        className={cn("flex h-9 shrink-0 items-stretch border-b border-border bg-paper", focused && many && "shadow-[inset_0_-2px_0_0_var(--tw-shadow-color)] shadow-wine/30")}
      >
        <div className="flex min-w-0 items-stretch overflow-x-auto" role="group" aria-label="Open documents">
          {group.tabs.map((t) => (
            <TabButton
              key={t.id}
              tab={t}
              active={t.id === group.active}
              dirty={t.kind === "write" && dirty.has(t.documentId)}
              groupFocused={focused}
              onActivate={() => dispatch({ type: "activate", group: index, tabId: t.id })}
              onKeep={() => dispatch({ type: "pin", group: index, tabId: t.id })}
              onClose={() => closeTab(t)}
              onTitle={(title) => t.kind !== "review" && dispatch({ type: "title", documentId: t.documentId, title })}
              onDropTab={(dragged) => dispatch({ type: "reorder", group: index, tabId: dragged, before: t.id })}
            />
          ))}
        </div>
        <div className="flex-1" />
        {active && (
          <div className="flex items-center gap-0.5 px-1.5">
            <ToolbarButton icon="vertical_split" label={`Split editor (${keys("⌘\\")})`} onClick={() => dispatch({ type: "split" })} testId="split-editor" />
            {many && (
              <ToolbarButton icon="close_fullscreen" label="Close this group" onClick={() => onClose({ type: "closeAll", group: index })} />
            )}
          </div>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        {writers.map((t) => (
          <div key={t.id} className={cn("absolute inset-0", t.id !== active?.id && "invisible")} aria-hidden={t.id !== active?.id}>
            <TabErrorBoundary tab={t} onClose={() => closeTab(t)}>
              <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Opening the Word editor…</div>}>
                <FullWordEditor documentId={t.documentId} />
              </Suspense>
            </TabErrorBoundary>
          </div>
        ))}
        {active && active.kind !== "write" ? (
          <TabErrorBoundary tab={active} onClose={() => closeTab(active)}>
            {active.kind === "review" ? (
              <ReviewTable key={active.id} reviewId={active.reviewId} onOpenSource={onOpen} />
            ) : (
              <WorkbenchHostContext.Provider value={{ openWordEditor: (documentId, title) => onOpen({ documentId, title, write: true }) }}>
                <TabBody key={active.id} tab={active} index={index} focused={focused} dispatch={dispatch} />
              </WorkbenchHostContext.Provider>
            )}
          </TabErrorBoundary>
        ) : !active ? (
          <div className="flex h-full items-center justify-center p-6">
            <EmptyState
              icon="description"
              title="No document open"
              description={`Open a document from the explorer, or press ${keys("⌘P")} to find one by name.`}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function TabErrorBoundary({ tab, onClose, children }: { tab: Tab; onClose: () => void; children: React.ReactNode }) {
  return (
    <ErrorBoundary what="This tab" resetKey={tab.id} actions={<Button variant="outline" onClick={onClose}>Close tab</Button>}>
      {children}
    </ErrorBoundary>
  );
}

function TabButton({
  tab,
  active,
  dirty,
  groupFocused,
  onActivate,
  onKeep,
  onClose,
  onTitle,
  onDropTab,
}: {
  tab: Tab;
  active: boolean;
  dirty: boolean;
  groupFocused: boolean;
  onActivate: () => void;
  onKeep: () => void;
  onClose: () => void;
  onTitle: (title: string) => void;
  /** Another tab of this group was dropped on this one: it moves in front of it. */
  onDropTab: (tabId: string) => void;
}) {
  const doc = useDocument(tab.kind === "review" ? "" : tab.documentId, { lean: true });
  const review = useReview(tab.kind === "review" ? tab.reviewId : "");
  const raw = (tab.kind === "review" ? review.data?.title : doc.data?.title) ?? tab.title;
  const title = (tab.kind === "review" ? raw : displayTitle(raw)) || (tab.kind === "review" ? "Review" : tab.documentId);
  const docTitle = doc.data?.title;
  useEffect(() => {
    if (docTitle && docTitle !== tab.title) onTitle(docTitle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docTitle, tab.title]);
  const writing = tab.kind === "write";
  const icon = tab.kind === "review" ? "table_chart" : writing ? "edit_document" : iconFor({ mime_type: doc.data?.mime_type, title });
  const label = writing ? `${title} (editing)` : title;
  return (
    <div
      role="presentation"
      className={cn(
        "group relative flex max-w-[240px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border pl-3 pr-1 text-[13px]",
        active ? "bg-card text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
      onClick={onActivate}
      onDoubleClick={onKeep}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(TAB_DRAG, tab.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(TAB_DRAG)) e.preventDefault();
      }}
      onDrop={(e) => {
        const id = e.dataTransfer.getData(TAB_DRAG);
        if (id) {
          e.preventDefault();
          onDropTab(id);
        }
      }}
      onAuxClick={(e) => {
        if (e.button === 1) onClose();
      }}
      data-testid="workbench-tab"
      data-document-id={tab.kind === "review" ? undefined : tab.documentId}
      data-review-id={tab.kind === "review" ? tab.reviewId : undefined}
    >
      {active && <span className={cn("absolute inset-x-0 top-0 h-0.5", groupFocused ? "bg-wine" : "bg-border")} />}
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        title={dirty ? `${title} — unsaved changes` : title}
        className="flex min-w-0 items-center gap-1.5 py-2 text-left"
        onKeyDown={(e) => {
          if (e.key === "Delete") {
            e.preventDefault();
            onClose();
          }
        }}
      >
        <Icon name={icon} className={cn("shrink-0", writing ? "text-wine" : "text-muted-foreground")} style={{ fontSize: 15 }} />
        <span className={cn("truncate", tab.preview && "italic")}>{label}</span>
      </button>
      {dirty && (
        <span className="ml-0.5 h-2 w-2 shrink-0 rounded-full bg-wine group-hover:hidden" aria-label="Unsaved changes" data-testid="tab-dirty" />
      )}
      <button
        type="button"
        aria-label={`Close ${title}`}
        className={cn(
          "ml-0.5 shrink-0 rounded p-0.5 hover:bg-secondary [@media(hover:none)]:opacity-100",
          active && !dirty ? "opacity-100" : "opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
          dirty && "hidden group-hover:block",
        )}
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
      >
        <Icon name="close" style={{ fontSize: 14 }} />
      </button>
    </div>
  );
}

function TabBody({ tab, index, focused, dispatch }: { tab: DocumentTab; index: number; focused: boolean; dispatch: Dispatcher }) {
  const onChange = useCallback(
    (params: string) => dispatch({ type: "params", group: index, tabId: tab.id, params }),
    [dispatch, index, tab.id],
  );
  const paramsState = useTabParams(tab.params, onChange);
  return (
    <div className="absolute inset-0 flex flex-col overflow-hidden">
      <DocumentWorkspace documentId={tab.documentId} paramsState={paramsState} keyboardActive={focused} />
    </div>
  );
}

function ToolbarButton({ icon, label, onClick, testId }: { icon: string; label: string; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
      data-testid={testId}
    >
      <Icon name={icon} style={{ fontSize: 17 }} />
    </button>
  );
}
