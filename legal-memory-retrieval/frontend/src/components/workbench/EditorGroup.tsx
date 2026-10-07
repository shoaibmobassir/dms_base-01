import { Suspense, lazy, useCallback, useEffect, type Dispatch } from "react";
import { useDocument } from "@/api/resources";
import { DocumentWorkspace } from "@/components/document-workspace/DocumentWorkspace";
import { EmptyState, Icon } from "@/components/common/primitives";
import { cn } from "@/lib/utils";
import { iconFor } from "./Explorer";
import { useReview } from "@/api/tabular";
import { ReviewTable } from "./ReviewTable";
import type { OpenRequest } from "./Explorer";
import { useTabParams, type Action, type DocumentTab, type Group, type Tab, type WorkbenchState } from "./state";

type Dispatcher = Dispatch<Action>;
const FullWordEditor = lazy(() => import("@/components/editor/FullWordEditor").then((m) => ({ default: m.FullWordEditor })));

/** One editor group: a strip of tabs and the active tab's document. */
export function EditorGroup({
  group,
  index,
  state,
  dispatch,
  onOpen,
}: {
  group: Group;
  index: number;
  state: WorkbenchState;
  dispatch: Dispatcher;
  onOpen: (r: OpenRequest) => void;
}) {
  const focused = state.focused === index;
  const active = group.tabs.find((t) => t.id === group.active) ?? null;
  const many = state.groups.length > 1;

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
        {group.tabs.map((t) =>
          t.kind === "write" ? (
            <TabButton key={t.id} tab={{ ...t, kind: "document" }} writing active={t.id === group.active} groupFocused={focused} index={index} dispatch={dispatch} />
          ) : t.kind === "review" ? (
            <ReviewTabButton key={t.id} tab={t} active={t.id === group.active} groupFocused={focused} index={index} dispatch={dispatch} />
          ) : (
            <TabButton key={t.id} tab={t} active={t.id === group.active} groupFocused={focused} index={index} dispatch={dispatch} />
          ),
        )}
        </div>
        <div className="flex-1" />
        {active && (
          <div className="flex items-center gap-0.5 px-1.5">
            <ToolbarButton icon="vertical_split" label="Split editor" onClick={() => dispatch({ type: "split" })} testId="split-editor" />
            {many && (
              <ToolbarButton icon="close_fullscreen" label="Close this group" onClick={() => dispatch({ type: "closeAll", group: index })} />
            )}
          </div>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        {active ? (
          active.kind === "review" ? (
            <ReviewTable key={active.id} reviewId={active.reviewId} onOpenSource={onOpen} />
          ) : active.kind === "write" ? (
            <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Opening the Word editor…</div>}>
              <FullWordEditor key={active.id} documentId={active.documentId} />
            </Suspense>
          ) : (
            <TabBody key={active.id} tab={active} index={index} focused={focused} dispatch={dispatch} />
          )
        ) : (
          <div className="flex h-full items-center justify-center p-6">
            <EmptyState
              icon="description"
              title="No document open"
              description="Open a document from the explorer, or press ⌘P to find one by name."
            />
          </div>
        )}
      </div>
    </section>
  );
}

function TabButton({
  tab,
  active,
  groupFocused,
  index,
  dispatch,
  writing = false,
}: {
  tab: DocumentTab;
  active: boolean;
  groupFocused: boolean;
  index: number;
  dispatch: Dispatcher;
  writing?: boolean;
}) {
  const doc = useDocument(tab.documentId, { lean: true });
  const title = doc.data?.title ?? tab.title ?? tab.documentId;
  useEffect(() => {
    if (doc.data?.title && doc.data.title !== tab.title) dispatch({ type: "title", documentId: tab.documentId, title: doc.data.title });
  }, [doc.data?.title, tab.title, tab.documentId, dispatch]);
  return (
    <div
      role="presentation"
      className={cn(
        "group relative flex max-w-[240px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border pl-3 pr-1 text-[13px]",
        active ? "bg-card text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
      onClick={() => dispatch({ type: "activate", group: index, tabId: tab.id })}
      onDoubleClick={() => dispatch({ type: "pin", group: index, tabId: tab.id })}
      onAuxClick={(e) => {
        if (e.button === 1) dispatch({ type: "close", group: index, tabId: tab.id });
      }}
      data-testid="workbench-tab"
      data-document-id={tab.documentId}
    >
      {active && <span className={cn("absolute inset-x-0 top-0 h-0.5", groupFocused ? "bg-wine" : "bg-border")} />}
      <button type="button" aria-current={active ? "true" : undefined} title={title} className="flex min-w-0 items-center gap-1.5 py-2 text-left">
        <Icon name={writing ? "edit_document" : iconFor({ mime_type: doc.data?.mime_type, title })} className={writing ? "text-wine" : "text-muted-foreground"} style={{ fontSize: 15 }} />
        <span className={cn("truncate", tab.preview && "italic")}>{writing ? `${title} (editing)` : title}</span>
      </button>
      <button
        type="button"
        aria-label={`Close ${title}`}
        className={cn("ml-0.5 rounded p-0.5 hover:bg-secondary", active ? "opacity-100" : "opacity-0 group-hover:opacity-100")}
        onClick={(e) => {
          e.stopPropagation();
          dispatch({ type: "close", group: index, tabId: tab.id });
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

function ReviewTabButton({ tab, active, groupFocused, index, dispatch }: {
  tab: Extract<Tab, { kind: "review" }>; active: boolean; groupFocused: boolean; index: number; dispatch: Dispatcher;
}) {
  const review = useReview(tab.reviewId);
  const title = review.data?.title ?? tab.title ?? "Review";
  return (
    <div
      role="presentation"
      className={cn(
        "group relative flex max-w-[240px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border pl-3 pr-1 text-[13px]",
        active ? "bg-card text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
      onClick={() => dispatch({ type: "activate", group: index, tabId: tab.id })}
      onAuxClick={(e) => { if (e.button === 1) dispatch({ type: "close", group: index, tabId: tab.id }); }}
      data-testid="workbench-tab"
      data-review-id={tab.reviewId}
    >
      {active && <span className={cn("absolute inset-x-0 top-0 h-0.5", groupFocused ? "bg-wine" : "bg-border")} />}
      <button type="button" aria-current={active ? "true" : undefined} title={title} className="flex min-w-0 items-center gap-1.5 py-2 text-left">
        <Icon name="table_chart" className="text-muted-foreground" style={{ fontSize: 15 }} />
        <span className="truncate">{title}</span>
      </button>
      <button type="button" aria-label={`Close ${title}`}
        className={cn("ml-0.5 rounded p-0.5 hover:bg-secondary", active ? "opacity-100" : "opacity-0 group-hover:opacity-100")}
        onClick={(e) => { e.stopPropagation(); dispatch({ type: "close", group: index, tabId: tab.id }); }}>
        <Icon name="close" style={{ fontSize: 14 }} />
      </button>
    </div>
  );
}
