import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { SetURLSearchParams } from "react-router-dom";
import { getWorkbenchState, putWorkbenchState, type WorkspaceKind } from "@/api/workspaces";

// The workbench's layout (plan 22, W1): up to two editor groups of tabs, a side panel, which group has focus.
// Saved per person per workspace on the server (ids only; the server drops tabs the person can no longer read).

export type DocumentTab = {
  id: string;
  kind: "document";
  documentId: string;
  title?: string;
  /** The document page's place (version, page, panel) as a query string, kept per tab. */
  params?: string;
  /** A preview tab is replaced by the next single-click open; editing or double-clicking keeps it. */
  preview?: boolean;
};
export type WriteTab = { id: string; kind: "write"; documentId: string; title?: string; preview?: boolean; params?: string };
export type ReviewTab = { id: string; kind: "review"; reviewId: string; title?: string; preview?: boolean; params?: string; documentId?: undefined };
export type Tab = DocumentTab | ReviewTab | WriteTab;
type TabInput = Omit<DocumentTab, "id"> | Omit<ReviewTab, "id"> | Omit<WriteTab, "id">;

const sameTab = (a: TabInput | Tab, b: TabInput | Tab) =>
  a.kind === b.kind && (a.kind === "review" ? a.reviewId === (b as ReviewTab).reviewId : a.documentId === (b as DocumentTab | WriteTab).documentId);

export type Group = { tabs: Tab[]; active: string | null };
export type SideView = "explorer" | "search" | "changes" | "reviews" | "playbooks" | "assistant";

export type WorkbenchState = {
  groups: Group[];
  focused: number;
  side: SideView | null;
  sideWidth: number;
};

export const EMPTY: WorkbenchState = { groups: [{ tabs: [], active: null }], focused: 0, side: "explorer", sideWidth: 280 };

export type Action =
  | { type: "load"; state: WorkbenchState }
  | { type: "open"; tab: TabInput; toSide?: boolean; preview?: boolean }
  | { type: "activate"; group: number; tabId: string }
  | { type: "close"; group: number; tabId: string }
  | { type: "closeAll"; group?: number }
  | { type: "pin"; group: number; tabId: string }
  | { type: "moveToOtherGroup"; group: number; tabId: string }
  | { type: "split" }
  | { type: "focus"; group: number }
  | { type: "params"; group: number; tabId: string; params: string }
  | { type: "title"; documentId: string; title: string }
  | { type: "side"; side: SideView | null }
  | { type: "sideWidth"; width: number };

let counter = 0;
const newId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

function withGroup(state: WorkbenchState, i: number, fn: (g: Group) => Group): WorkbenchState {
  return { ...state, groups: state.groups.map((g, j) => (j === i ? fn(g) : g)) };
}

/** Remove empty groups past the first, keeping focus on a group that exists. */
function tidy(state: WorkbenchState): WorkbenchState {
  let groups = state.groups;
  if (groups.length > 1) groups = groups.filter((g, i) => i === 0 || g.tabs.length > 0);
  if (groups.length > 1 && groups[0].tabs.length === 0) groups = groups.slice(1);
  const focused = Math.min(state.focused, groups.length - 1);
  return { ...state, groups, focused };
}

function openIn(g: Group, tab: TabInput, preview: boolean): Group {
  const existing = g.tabs.find((t) => sameTab(t, tab));
  if (existing) {
    const tabs = g.tabs.map((t) =>
      t.id === existing.id ? { ...t, preview: preview && t.preview, params: tab.params ?? t.params } : t,
    );
    return { tabs, active: existing.id };
  }
  const id = newId();
  const next = { ...tab, id, preview } as Tab;
  const at = g.tabs.findIndex((t) => t.preview);
  if (preview && at >= 0) {
    const tabs = [...g.tabs];
    tabs[at] = next;
    return { tabs, active: id };
  }
  const activeAt = g.tabs.findIndex((t) => t.id === g.active);
  const tabs = [...g.tabs];
  tabs.splice(activeAt >= 0 ? activeAt + 1 : tabs.length, 0, next);
  return { tabs, active: id };
}

export function reducer(state: WorkbenchState, a: Action): WorkbenchState {
  switch (a.type) {
    case "load":
      return tidy({ ...EMPTY, ...a.state, groups: a.state.groups?.length ? a.state.groups.slice(0, 2) : EMPTY.groups });
    case "open": {
      let s = state;
      let target = state.focused;
      if (a.toSide) {
        if (s.groups.length < 2) s = { ...s, groups: [...s.groups, { tabs: [], active: null }] };
        target = s.focused === 0 ? 1 : 0;
      }
      s = withGroup(s, target, (g) => openIn(g, a.tab, !!a.preview));
      return { ...s, focused: target };
    }
    case "activate":
      return { ...withGroup(state, a.group, (g) => ({ ...g, active: a.tabId })), focused: a.group };
    case "close": {
      const s = withGroup(state, a.group, (g) => {
        const i = g.tabs.findIndex((t) => t.id === a.tabId);
        const tabs = g.tabs.filter((t) => t.id !== a.tabId);
        const active = g.active === a.tabId ? (tabs[Math.min(i, tabs.length - 1)]?.id ?? null) : g.active;
        return { tabs, active };
      });
      return tidy(s);
    }
    case "closeAll":
      return tidy(
        a.group === undefined
          ? { ...state, groups: [{ tabs: [], active: null }], focused: 0 }
          : withGroup(state, a.group, () => ({ tabs: [], active: null })),
      );
    case "pin":
      return withGroup(state, a.group, (g) => ({ ...g, tabs: g.tabs.map((t) => (t.id === a.tabId ? { ...t, preview: false } : t)) }));
    case "moveToOtherGroup": {
      const tab = state.groups[a.group]?.tabs.find((t) => t.id === a.tabId);
      if (!tab) return state;
      let s = state.groups.length < 2 ? { ...state, groups: [...state.groups, { tabs: [], active: null }] } : state;
      const other = a.group === 0 ? 1 : 0;
      s = withGroup(s, a.group, (g) => {
        const tabs = g.tabs.filter((t) => t.id !== a.tabId);
        return { tabs, active: g.active === a.tabId ? (tabs[0]?.id ?? null) : g.active };
      });
      s = withGroup(s, other, (g) => openIn(g, { ...tab, preview: false }, false));
      return tidy({ ...s, focused: other });
    }
    case "split": {
      const g = state.groups[state.focused];
      const tab = g?.tabs.find((t) => t.id === g.active);
      if (!tab) return state;
      let s = state.groups.length < 2 ? { ...state, groups: [...state.groups, { tabs: [], active: null }] } : state;
      const other = state.focused === 0 ? 1 : 0;
      s = withGroup(s, other, (og) => openIn(og, { ...tab, preview: false }, false));
      return { ...s, focused: other };
    }
    case "focus":
      return state.focused === a.group ? state : { ...state, focused: a.group };
    case "params":
      return withGroup(state, a.group, (g) => ({
        ...g,
        tabs: g.tabs.map((t) => (t.id === a.tabId && t.params !== a.params ? { ...t, params: a.params } : t)),
      }));
    case "title":
      return {
        ...state,
        groups: state.groups.map((g) => ({
          ...g,
          tabs: g.tabs.map((t) => (t.kind === "document" && t.documentId === a.documentId && t.title !== a.title ? { ...t, title: a.title } : t)),
        })),
      };
    case "side":
      return { ...state, side: a.side };
    case "sideWidth":
      return { ...state, sideWidth: Math.max(200, Math.min(520, Math.round(a.width))) };
  }
}

/** Layout state for one workspace, loaded from and saved to the server. */
export function useWorkbench(kind: WorkspaceKind, id: string) {
  const [state, dispatch] = useReducer(reducer, EMPTY);
  const [loaded, setLoaded] = useState(false);
  const scope = `${kind}:${id}`;
  const loadedScope = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    loadedScope.current = null;
    getWorkbenchState(kind, id)
      .then((r) => {
        if (cancelled) return;
        const saved = r.state as Partial<WorkbenchState>;
        dispatch({ type: "load", state: { ...EMPTY, ...saved } as WorkbenchState });
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: "load", state: EMPTY });
      })
      .finally(() => {
        if (!cancelled) {
          loadedScope.current = scope;
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [kind, id, scope]);

  // Save a second after the last change (only once this workspace's saved layout has loaded).
  useEffect(() => {
    if (!loaded || loadedScope.current !== scope) return;
    const t = window.setTimeout(() => {
      void putWorkbenchState(kind, id, state).catch(() => undefined);
    }, 1000);
    return () => window.clearTimeout(t);
  }, [state, loaded, kind, id, scope]);

  return { state, dispatch, loaded };
}

/** The [params, setParams] pair a document page expects, backed by a tab's saved query string. */
export function useTabParams(params: string | undefined, onChange: (next: string) => void): [URLSearchParams, SetURLSearchParams] {
  const current = useMemo(() => new URLSearchParams(params ?? ""), [params]);
  const latest = useRef(current);
  latest.current = current;
  const set = useCallback<SetURLSearchParams>(
    (next) => {
      const value = typeof next === "function" ? next(new URLSearchParams(latest.current)) : (next ?? "");
      const sp = value instanceof URLSearchParams ? value : new URLSearchParams(value as Record<string, string>);
      onChange(sp.toString());
    },
    [onChange],
  );
  return [current, set];
}
