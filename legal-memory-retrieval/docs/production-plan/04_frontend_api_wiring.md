# 04 — Wire every page to the API

## Problems

- `AppContext` fetches matters/documents/clients/people/projects (200 rows each) on load and on every
  persona change; pages filter that in memory. Lists silently truncate at 200.
- Errors are swallowed (`.catch(() => ({items: []}))`) so a broken endpoint looks like "no data".
- React Query is installed but unused.

## Steps

1. `AppContext` keeps only session-level state: persona/member, firm profile, auth mode.
2. One hook per resource in `src/api/*` using React Query, keyed by member id so a persona switch
   invalidates everything: `useMatters({q,status})`, `useMatter(id)`, `useDocuments({q,type})`,
   `useClients`, `usePeople`, `useDeadlines`, `useArguments({q})`, `useTeams`, `useHomeStats`.
3. Server-side search/filter: pass `q`/`status` to the API instead of filtering 200 rows locally
   (backend already supports `q` on matters/documents; add where missing).
4. Shared `<QueryState>` component: loading skeleton, error with retry (shows HTTP status), empty.
5. Command palette uses `GET /api/search?q=` (debounced) instead of the preloaded lists.
6. API client: sends `X-Api-Key` when present (auth-on) else `X-Member-Id`; 401 → key prompt.

## Done when

- `AppContext` has no entity lists.
- Stopping the API shows an error state with retry on every page (not an empty table).
- Every page's data is traceable to one endpoint (listed in `frontend/README.md`).
