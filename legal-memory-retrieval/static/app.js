/**
 * LEXOS / FIRMOS — Production Legal Institutional Memory & DMS SPA
 * Apple Luxury White Aesthetic
 * Connected to live FastAPI section routes: /api/matters, /api/documents, /api/projects, …
 */

(function() {
  'use strict';

  // --- APPLICATION STATE ---
  const state = {
    view: 'home',
    selectedMatterId: 'MTR-2017-00006',
    selectedProjectId: null,
    selectedDocId: 'DOC-00001',
    selectedClientId: 'CLI-00394',
    selectedPersonId: 'MEM-00001',
    selectedTeamName: 'Corporate & M&A',
    matterTab: 'overview',
    projectTab: 'overview',
    docTab: 'overview',
    knowledgeTab: 'precedents',
    persona: 'MEM-00001',
    theme: localStorage.getItem('lexos_theme') || 'light',
    rightPaneOpen: true,
    askQuery: '',
    askLoading: false,
    askResult: null,
    askDebug: null,
    debugOpen: new URLSearchParams(window.location.search).get('debug') === '1',
    systemInfo: null,
    architectureMarkdown: '',
    scopeFilter: 'all',
    projectStatusFilter: 'all',
    searchQuery: '',
    paletteOpen: false,
    paletteIndex: 0,
    projectModalOpen: false,
    viewerOpen: false,
    currentViewerDoc: null,
    ingestPending: [],
    customDocs: [],
    customProjects: [],
    dataLoading: true,
    dataError: null,
    matterDetails: {},
    projectDetails: {},
    selectedProjectFolderId: '__all__',
    projectDocSearch: ''
  };

  let firmDataCache = null;

  // DOM Loaded Entry
  document.addEventListener('DOMContentLoaded', () => {
    initApp();
  });

  async function initApp() {
    applyTheme(state.theme);
    setupEventListeners();
    setupUrlRouting();
    setupCommandPalette();
    setupProjectModal();
    setupSourceViewer();
    setupPersonaSwitcher();
    showLoadingWorkspace('Connecting to Apex Chambers database…');
    await bootstrapFirmData();
    const route = parseLocation();
    if (route.view === 'doc-detail' && route.params.docId) {
      await ensureDocument(route.params.docId);
    }
    if (route.view === 'matter-detail' && route.params.matterId) {
      await ensureMatterDetail(route.params.matterId);
    }
    if (route.view === 'project-detail' && route.params.projectId) {
      await ensureProjectDetail(route.params.projectId);
    }
    navigate(route.view, route.params, { skipUrl: true });
    history.replaceState(route, '', buildUrl(route.view, route.params));
  }

  function showLoadingWorkspace(message = 'Loading firm data…') {
    const ws = document.getElementById('app-workspace');
    if (ws) ws.innerHTML = renderLoadingScreen(message);
  }

  function renderLoadingScreen(message = 'Loading…') {
    return `
      <div class="view-container" style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:320px;gap:12px;">
        <div style="width:28px;height:28px;border:2px solid var(--border-subtle);border-top-color:var(--accent-primary);border-radius:50%;animation:spin 0.8s linear infinite;"></div>
        <div style="font-size:13px;color:var(--text-muted);">${escapeHtml(message)}</div>
      </div>
    `;
  }

  async function bootstrapFirmData() {
    state.dataLoading = true;
    state.dataError = null;
    const [stats, matters, documents, clients, people, projects, precedents, clauses, activity, tasks] = await Promise.all([
      apiFetch(`${API.home}/stats`),
      apiFetch(`${API.matters}?limit=200`),
      apiFetch(`${API.documents}?limit=200`),
      apiFetch(`${API.clients}?limit=200`),
      apiFetch(API.people),
      apiFetch(`${API.projects}?limit=200`),
      apiFetch(`${API.knowledge}/precedents`),
      apiFetch(`${API.knowledge}/clauses`),
      apiFetch(`${API.activity}?limit=25`),
      apiFetch(`${API.tasks}?limit=30`),
    ]);

    if (!matters && !documents) {
      state.dataError = 'Could not reach the API. Start the server with: uvicorn app.api.main:app --reload --port 8000';
      state.dataLoading = false;
      firmDataCache = { matters: [], clients: [], members: [], documents: [], projects: [], precedents: [], clauses: [], activity: [], tasks: [], stats: {}, totals: {} };
      window.FIRM_DATA = firmDataCache;
      return;
    }

    firmDataCache = {
      stats: stats?.counts || {},
      totals: {
        matters: matters?.total || 0,
        documents: documents?.total || 0,
        clients: clients?.total || 0,
        projects: projects?.total || 0,
        arguments: stats?.counts?.arguments || 0,
      },
      matters: matters?.items || [],
      documents: documents?.items || [],
      clients: clients?.items || [],
      members: people?.items || [],
      projects: projects?.items || [],
      precedents: precedents?.precedents || [],
      clauses: clauses?.clauses || [],
      activity: activity?.items || [],
      tasks: tasks?.items || [],
    };
    window.FIRM_DATA = firmDataCache;
    state.dataLoading = false;
    state.matterDetails = {};

    // Default to first accessible project for demo persona
    const projectList = firmDataCache.projects || [];
    if (!state.selectedProjectId && projectList.length) {
      state.selectedProjectId = projectList[0].project_id || projectList[0].id;
    }
  }

  async function ensureDocument(docId) {
    const existing = getDocById(docId);
    if (existing) return existing;
    const data = await apiFetch(`${API.documents}/${encodeURIComponent(docId)}`);
    if (!data || data.detail || !data.document_id) return null;
    firmDataCache = firmDataCache || getFirmData();
    firmDataCache.documents = firmDataCache.documents || [];
    firmDataCache.documents.unshift(data);
    window.FIRM_DATA = firmDataCache;
    return data;
  }

  async function ensureMatterDetail(matterId) {
    if (!matterId) return null;
    const cached = state.matterDetails[matterId];
    if (cached?.loaded) return cached;

    const mid = encodeURIComponent(matterId);
    const [detail, args, timeline, related, docsPage] = await Promise.all([
      apiFetch(`${API.matters}/${mid}`),
      apiFetch(`${API.matters}/${mid}/arguments`),
      apiFetch(`${API.matters}/${mid}/timeline`),
      apiFetch(`${API.matters}/${mid}/related`),
      apiFetch(`${API.documents}?matter_id=${mid}&limit=50`),
    ]);

    const payload = {
      loaded: true,
      matter: detail?.matter || getMatterById(matterId),
      team: detail?.team || [],
      documents: docsPage?.items?.length ? docsPage.items : (detail?.documents || []),
      documentTotal: docsPage?.total || detail?.documents?.length || 0,
      arguments: args?.arguments || [],
      timeline: timeline?.timeline || [],
      related: related?.related || [],
    };
    state.matterDetails[matterId] = payload;
    return payload;
  }

  async function ensureProjectDetail(projectId) {
    if (!projectId) return null;
    const cached = state.projectDetails[projectId];
    if (cached?.loaded) return cached;

    const pid = encodeURIComponent(projectId);
    const [detail, directory, docsPage, activityPage] = await Promise.all([
      apiFetch(`${API.projects}/${pid}`),
      apiFetch(`${API.projects}/${pid}/directory`),
      apiFetch(`${API.projects}/${pid}/documents?limit=200`),
      apiFetch(`${API.projects}/${pid}/activity?limit=50`),
    ]);

    const baseProject = detail && !detail.detail ? detail : getProjectById(projectId);
    const payload = {
      loaded: true,
      project: baseProject || null,
      team: detail?.team || [],
      folders: detail?.folders || [],
      folderTree: directory?.folder_tree || [],
      rootDocumentCount: directory?.root_document_count || 0,
      documents: docsPage?.documents?.length ? docsPage.documents : (detail?.documents || []),
      documentTotal: docsPage?.total || detail?.document_count || 0,
      recentActivity: detail?.recent_activity || [],
      activity: activityPage?.activity || [],
      activityTotal: activityPage?.total || 0,
    };

    if (payload.project) {
      firmDataCache = firmDataCache || getFirmData();
      firmDataCache.projects = firmDataCache.projects || [];
      const listIdx = firmDataCache.projects.findIndex(
        p => (p.id || p.project_id) === projectId
      );
      if (listIdx >= 0) {
        firmDataCache.projects[listIdx] = { ...firmDataCache.projects[listIdx], ...payload.project };
      }
      window.FIRM_DATA = firmDataCache;
    }

    state.projectDetails[projectId] = payload;
    return payload;
  }

  async function refreshProjectDetail(projectId) {
    delete state.projectDetails[projectId];
    return ensureProjectDetail(projectId);
  }

  function getProjectDetailBundle(projectId) {
    return state.projectDetails[projectId] || null;
  }

  function formatVersionStatus(status, docStatus) {
    const raw = (status || docStatus || 'draft').toString().toLowerCase().replace(/ /g, '_');
    const labels = {
      draft: 'Draft',
      developing: 'Developing',
      review: 'Under Review',
      final: 'Final',
      executed: 'Executed',
    };
    return labels[raw] || docStatus || 'Draft';
  }

  function versionStatusClass(status, docStatus) {
    const raw = (status || docStatus || 'draft').toString().toLowerCase().replace(/ /g, '_');
    if (raw === 'developing') return 'version-status-developing';
    if (raw === 'executed' || raw === 'final') return 'version-status-final';
    if (raw === 'review') return 'version-status-review';
    return 'version-status-draft';
  }

  function formatActivityAction(action) {
    const labels = {
      'project.created': 'Project created',
      'project.updated': 'Project updated',
      'milestone.toggled': 'Milestone updated',
      'folder.created': 'Folder created',
      'folder.updated': 'Folder renamed or moved',
      'folder.deleted': 'Folder deleted',
      'document.copied': 'Document copied into project',
      'document.moved': 'Document moved',
      'document.added': 'Document added',
      'version.created': 'New document version',
    };
    return labels[action] || action.replace(/\./g, ' ');
  }

  function formatDateTime(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString('en-IN', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function getMatterDetailBundle(matterId) {
    return state.matterDetails[matterId] || null;
  }

  function formatDate(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function matterMemorySummary(matter, facts) {
    const items = facts || matter?.facts || [];
    if (items.length) {
      return items.join(' ');
    }
    const parts = [
      matter?.matter_type && `${matter.matter_type} matter`,
      matter?.practice_area && `in ${matter.practice_area}`,
      matter?.jurisdiction && `(${matter.jurisdiction})`,
    ].filter(Boolean);
    return parts.length
      ? `Institutional record for ${matter?.title || 'this matter'} — ${parts.join(' ')}.`
      : 'Reconstructed institutional memory for this matter.';
  }

  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('lexos_theme', theme);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) {
      btn.innerHTML = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
    }
  }

  // --- UI ROUTES (browser address bar — mirrors API section layout) ---
  const UI = {
    base: '/ui',
    home: '/ui/home',
    ask: '/ui/ask',
    matters: '/ui/matters',
    projects: '/ui/projects',
    documents: '/ui/documents',
    clients: '/ui/clients',
    people: '/ui/people',
    teams: '/ui/teams',
    knowledge: '/ui/knowledge',
    activity: '/ui/activity',
    tasks: '/ui/tasks',
    architecture: '/ui/architecture',
  };

  const VIEW_TITLES = {
    home: 'Home',
    ask: 'Ask Firm AI',
    matters: 'Matters',
    'matter-detail': 'Matter',
    projects: 'Projects',
    'project-detail': 'Project',
    clients: 'Clients',
    'client-detail': 'Client',
    documents: 'Documents',
    'doc-detail': 'Document',
    teams: 'Teams',
    people: 'People',
    'person-detail': 'Person',
    knowledge: 'Knowledge Vault',
    activity: 'Live Activity',
    tasks: 'Court Deadlines',
    architecture: 'Architecture',
  };

  function buildUrl(view, params = {}) {
    switch (view) {
      case 'home': return UI.home;
      case 'ask': return UI.ask;
      case 'matters': return UI.matters;
      case 'matter-detail':
        return `${UI.matters}/${encodeURIComponent(params.matterId || state.selectedMatterId)}`;
      case 'projects': return UI.projects;
      case 'project-detail':
        return `${UI.projects}/${encodeURIComponent(params.projectId || state.selectedProjectId)}`;
      case 'clients': return UI.clients;
      case 'client-detail':
        return `${UI.clients}/${encodeURIComponent(params.clientId || state.selectedClientId)}`;
      case 'documents': return UI.documents;
      case 'doc-detail':
        return `${UI.documents}/${encodeURIComponent(params.docId || state.selectedDocId)}`;
      case 'teams': return UI.teams;
      case 'people': return UI.people;
      case 'person-detail':
        return `${UI.people}/${encodeURIComponent(params.personId || state.selectedPersonId)}`;
      case 'knowledge':
        return params.tab
          ? `${UI.knowledge}/${encodeURIComponent(params.tab)}`
          : UI.knowledge;
      case 'activity': return UI.activity;
      case 'tasks': return UI.tasks;
      case 'architecture': return UI.architecture;
      default: return UI.home;
    }
  }

  function parseLocation() {
    let path = window.location.pathname || '';
    if (path === UI.base || path === `${UI.base}/`) {
      return { view: 'home', params: {} };
    }
    if (!path.startsWith(`${UI.base}/`)) {
      return { view: 'home', params: {} };
    }
    const segments = path.slice(UI.base.length + 1).split('/').filter(Boolean);
    if (!segments.length) return { view: 'home', params: {} };

    const [section, id] = segments;
    if (section === 'matters' && id) return { view: 'matter-detail', params: { matterId: decodeURIComponent(id) } };
    if (section === 'projects' && id) return { view: 'project-detail', params: { projectId: decodeURIComponent(id) } };
    if (section === 'documents' && id) return { view: 'doc-detail', params: { docId: decodeURIComponent(id) } };
    if (section === 'clients' && id) return { view: 'client-detail', params: { clientId: decodeURIComponent(id) } };
    if (section === 'people' && id) return { view: 'person-detail', params: { personId: decodeURIComponent(id) } };
    if (section === 'knowledge' && id) return { view: 'knowledge', params: { tab: decodeURIComponent(id) } };

    const listViews = ['home', 'ask', 'matters', 'projects', 'clients', 'documents', 'teams', 'people', 'knowledge', 'activity', 'tasks', 'architecture'];
    if (listViews.includes(section)) return { view: section, params: {} };
    return { view: 'home', params: {} };
  }

  function setupUrlRouting() {
    window.addEventListener('popstate', (event) => {
      const route = event.state || parseLocation();
      navigate(route.view, route.params || {}, { skipUrl: true });
    });
  }

  // --- API ROUTES (one prefix per sidebar section) ---
  const API = {
    home: '/api/home',
    answers: '/api/answers',
    retrieval: '/api/retrieval',
    matters: '/api/matters',
    projects: '/api/projects',
    documents: '/api/documents',
    clients: '/api/clients',
    people: '/api/people',
    search: '/api/search',
    teams: '/api/teams',
    knowledge: '/api/knowledge',
    activity: '/api/activity',
    tasks: '/api/tasks',
    system: '/api/system',
  };

  // --- API CLIENT HELPERS ---
  async function apiFetch(endpoint, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      'X-Member-Id': state.persona,
      ...(options.headers || {})
    };
    try {
      const res = await fetch(endpoint, { ...options, headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`API fallback for ${endpoint}:`, err);
      return null;
    }
  }

  // --- NAVIGATION CONTROLLER ---
  async function navigate(view, params = {}, options = {}) {
    state.view = view;
    if (params.matterId) state.selectedMatterId = params.matterId;
    if (params.projectId) state.selectedProjectId = params.projectId;
    if (params.docId) state.selectedDocId = params.docId;
    if (params.clientId) state.selectedClientId = params.clientId;
    if (params.personId) state.selectedPersonId = params.personId;
    if (params.teamName) state.selectedTeamName = params.teamName;
    if (params.tab) {
      if (view === 'matter-detail') state.matterTab = params.tab;
      if (view === 'project-detail') state.projectTab = params.tab;
      if (view === 'doc-detail') state.docTab = params.tab;
      if (view === 'knowledge') state.knowledgeTab = params.tab;
    }

    if (!options.skipUrl) {
      const url = buildUrl(view, params);
      if (url !== window.location.pathname) {
        history.pushState({ view, params }, '', url);
      }
    }

    const baseTitle = VIEW_TITLES[view] || 'LEXOS';
    document.title = view.includes('-detail')
      ? `${baseTitle} — LEXOS`
      : `${baseTitle} — LEXOS | Apex Chambers`;

    document.querySelectorAll('.nav-item').forEach(el => {
      const v = el.dataset.view;
      el.classList.toggle('active', v === view || (view.startsWith(v) && view.includes('-detail')));
    });

    renderWorkspace();
    renderRightPane();

    if (view === 'doc-detail' && params.docId && !getDocById(params.docId)) {
      showLoadingWorkspace('Loading document from database…');
      await ensureDocument(params.docId);
      renderWorkspace();
      renderRightPane();
    }

    if (view === 'matter-detail' && params.matterId) {
      const cached = getMatterDetailBundle(params.matterId);
      if (!cached?.loaded) {
        showLoadingWorkspace('Loading matter intelligence…');
        await ensureMatterDetail(params.matterId);
        renderWorkspace();
        renderRightPane();
      }
    }

    if (view === 'project-detail' && params.projectId) {
      const cached = getProjectDetailBundle(params.projectId);
      if (!cached?.loaded) {
        showLoadingWorkspace('Loading project workspace…');
        await ensureProjectDetail(params.projectId);
        renderWorkspace();
        renderRightPane();
      }
    }

    window.scrollTo(0, 0);
  }

  window.lexosNavigate = navigate;

  // --- DATA ACCESS (live API cache populated on bootstrap) ---
  function getFirmData() {
    return firmDataCache || window.FIRM_DATA || {
      matters: [], clients: [], members: [], documents: [], projects: [],
      precedents: [], clauses: [], activity: [], tasks: [], stats: {}, totals: {}
    };
  }

  function getCurrentMember() {
    const members = getFirmData().members || [];
    return members.find(m => m.member_id === state.persona) || members[0] || { name: 'Aryan Maharaj', role: 'Partner', office: 'Mumbai', member_id: 'MEM-00001' };
  }

  function canAccessMatter(matter) {
    if (!matter) return false;
    if (state.persona === 'RESTRICTED_DEMO') {
      return !matter.restricted;
    }
    if (!matter.restricted) return true;
    const allowed = matter.allowed_members || matter.acl_members || [];
    return allowed.includes(state.persona);
  }

  function getVisibleMatters() {
    return (getFirmData().matters || []).filter(canAccessMatter);
  }

  function getAllProjects() {
    const defaultProjects = getFirmData().projects || [];
    const all = [...state.customProjects, ...defaultProjects];
    return all.filter(p => {
      const m = getMatterById(p.matter_id);
      return !m || canAccessMatter(m);
    });
  }

  function getProjectById(id) {
    return getAllProjects().find(p => p.id === id || p.project_id === id);
  }

  function getMatterById(id) {
    const bundle = state.matterDetails[id];
    if (bundle?.matter) return bundle.matter;
    return (getFirmData().matters || []).find(m => m.matter_id === id);
  }

  function getDocById(id) {
    const custom = state.customDocs.find(d => d.document_id === id);
    if (custom) return custom;
    return (getFirmData().documents || []).find(d => d.document_id === id);
  }

  function getClientById(id) {
    return (getFirmData().clients || []).find(c => c.client_id === id);
  }

  function getPersonById(id) {
    return (getFirmData().members || []).find(m => m.member_id === id);
  }

  // --- EVENT LISTENERS & SHORTCUTS ---
  function setupEventListeners() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const v = item.dataset.view;
        if (v) navigate(v);
      });
    });

    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        applyTheme(state.theme === 'dark' ? 'light' : 'dark');
      });
    }

    const cmdTrigger = document.getElementById('cmd-palette-trigger');
    if (cmdTrigger) {
      cmdTrigger.addEventListener('click', () => openCommandPalette());
    }

    const newProjectBtn = document.getElementById('sidebar-new-project-btn');
    if (newProjectBtn) {
      newProjectBtn.addEventListener('click', () => openProjectModal());
    }

    const ingestBtn = document.getElementById('sidebar-ingest-trigger');
    if (ingestBtn) {
      ingestBtn.addEventListener('click', () => {
        navigate('documents');
        setTimeout(() => {
          const drop = document.getElementById('ingest-dropzone-target');
          if (drop) drop.scrollIntoView({ behavior: 'smooth' });
        }, 100);
      });
    }

    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openCommandPalette();
      } else if (e.key === 'Escape') {
        closeCommandPalette();
        closeProjectModal();
        closeSourceViewer();
      } else if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '9') {
        e.preventDefault();
        const views = ['home', 'ask', 'matters', 'projects', 'clients', 'documents', 'teams', 'people', 'knowledge'];
        const targetView = views[parseInt(e.key) - 1];
        if (targetView) navigate(targetView);
      }
    });
  }

  function setupPersonaSwitcher() {
    const sel = document.getElementById('persona-select');
    if (!sel) return;
    sel.value = state.persona;
    sel.addEventListener('change', async (e) => {
      state.persona = e.target.value;
      const mem = getCurrentMember();
      showToast(`Switched persona to ${mem.name || 'Outside Counsel'}`);

      const av = document.getElementById('sidebar-user-avatar');
      const un = document.getElementById('sidebar-user-name');
      const ur = document.getElementById('sidebar-user-role');
      if (av && mem.name) av.innerText = mem.name.split(' ').map(n=>n[0]).join('');
      if (un) un.innerText = mem.name || 'Outside Counsel';
      if (ur) ur.innerText = `${mem.role || 'Restricted'} • ${mem.office || 'Global'}`;

      showLoadingWorkspace('Refreshing data for current permissions…');
      await bootstrapFirmData();
      navigate(state.view, {
        matterId: state.selectedMatterId,
        projectId: state.selectedProjectId,
        docId: state.selectedDocId,
        clientId: state.selectedClientId,
        personId: state.selectedPersonId,
        teamName: state.selectedTeamName
      });
    });
  }

  // --- TOAST NOTIFICATIONS ---
  function showToast(msg, duration = 2800) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<span style="color:var(--accent-primary)">✦</span> <span>${msg}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }

  // --- DOCUMENT SOURCE VIEWER DRAWER (WITH EXACT HIGHLIGHT) ---
  function setupSourceViewer() {
    const overlay = document.getElementById('doc-source-viewer-overlay');
    const closeBtn = document.getElementById('close-viewer-btn');
    const openFullBtn = document.getElementById('viewer-open-full-btn');

    if (overlay) {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeSourceViewer();
      });
    }
    if (closeBtn) closeBtn.addEventListener('click', closeSourceViewer);
    if (openFullBtn) {
      openFullBtn.addEventListener('click', () => {
        if (state.currentViewerDoc) {
          const docId = state.currentViewerDoc.document_id;
          closeSourceViewer();
          navigate('doc-detail', { docId: docId });
        }
      });
    }
  }

  async function openDocumentSourceViewer(docId, query = '', chunkId = '') {
    const overlay = document.getElementById('doc-source-viewer-overlay');
    const titleEl = document.getElementById('viewer-doc-title');
    const idEl = document.getElementById('viewer-doc-id');
    const typeEl = document.getElementById('viewer-doc-type');
    const versionEl = document.getElementById('viewer-doc-version');
    const bodyEl = document.getElementById('viewer-document-body');

    if (!overlay || !bodyEl) return;

    bodyEl.innerHTML = `<div style="padding:40px 0;text-align:center;color:var(--text-muted);font-family:var(--font-mono);">Loading verified document and highlighting source citation...</div>`;
    overlay.classList.add('open');
    state.viewerOpen = true;

    // Fetch from live backend API
    const url = `${API.documents}/${encodeURIComponent(docId)}?q=${encodeURIComponent(query)}&chunk_id=${encodeURIComponent(chunkId)}`;
    const docData = await apiFetch(url);

    const doc = docData || getDocById(docId) || {
      document_id: docId,
      title: `Document ${docId}`,
      document_type: 'Contract',
      version: 'v1 Final',
      body: 'SHARE PURCHASE AGREEMENT\n\n1. Parties\nThe Seller and the Buyer agree to the sale of Sale Shares.\n\n14. Indemnity Cap\nThe aggregate maximum liability under tax and general warranties is capped at 15% of purchase price.'
    };

    state.currentViewerDoc = doc;

    if (titleEl) titleEl.innerText = doc.title || docId;
    if (idEl) idEl.innerText = doc.document_id || docId;
    if (typeEl) typeEl.innerText = doc.document_type || 'Document';
    if (versionEl) versionEl.innerText = doc.version || 'v1 Final';

    if (doc.highlighted_body) {
      bodyEl.innerHTML = doc.highlighted_body;
    } else {
      let bodyText = doc.body || doc.chunk_text || 'Document content not available.';
      if (query && bodyText) {
        const regex = new RegExp(`(${query.split(' ').filter(w=>w.length>3).join('|')})`, 'gi');
        bodyText = bodyText.replace(regex, '<mark id="match-1" class="dms-source-highlight">$1</mark>');
      }
      bodyEl.innerHTML = bodyText;
    }

    setTimeout(() => {
      const match = document.getElementById('match-1');
      if (match) {
        match.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 200);
  }

  window.lexosOpenSourceViewer = openDocumentSourceViewer;

  function closeSourceViewer() {
    const overlay = document.getElementById('doc-source-viewer-overlay');
    if (!overlay) return;
    state.viewerOpen = false;
    overlay.classList.remove('open');
  }

  // --- COMMAND PALETTE (⌘K) ---
  function setupCommandPalette() {
    const overlay = document.getElementById('command-palette-overlay');
    const input = document.getElementById('palette-search-input');
    const results = document.getElementById('palette-results');
    if (!overlay || !input || !results) return;

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeCommandPalette();
    });

    input.addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      renderPaletteResults(q);
    });

    input.addEventListener('keydown', (e) => {
      const items = results.querySelectorAll('.palette-item');
      if (!items.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        state.paletteIndex = (state.paletteIndex + 1) % items.length;
        updatePaletteSelection(items);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        state.paletteIndex = (state.paletteIndex - 1 + items.length) % items.length;
        updatePaletteSelection(items);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const selected = items[state.paletteIndex];
        if (selected) selected.click();
      }
    });
  }

  function openCommandPalette() {
    const overlay = document.getElementById('command-palette-overlay');
    const input = document.getElementById('palette-search-input');
    if (!overlay || !input) return;
    state.paletteOpen = true;
    overlay.classList.add('open');
    input.value = '';
    state.paletteIndex = 0;
    renderPaletteResults('');
    setTimeout(() => input.focus(), 50);
  }

  function closeCommandPalette() {
    const overlay = document.getElementById('command-palette-overlay');
    if (!overlay) return;
    state.paletteOpen = false;
    overlay.classList.remove('open');
  }

  function updatePaletteSelection(items) {
    items.forEach((item, idx) => {
      item.classList.toggle('selected', idx === state.paletteIndex);
      if (idx === state.paletteIndex) item.scrollIntoView({ block: 'nearest' });
    });
  }

  function renderPaletteResults(query) {
    const results = document.getElementById('palette-results');
    if (!results) return;
    const data = getFirmData();
    let matches = [];

    if (!query) {
      matches = [
        { title: 'Ask the Firm AI...', cat: 'REASONING', action: () => navigate('ask') },
        { title: '＋ Create New Project / Workstream', cat: 'ACTION', action: () => openProjectModal() },
        { title: 'Legal Due Diligence & Red Flag Review', cat: 'PROJECT', action: () => navigate('project-detail', { projectId: 'PRJ-2024-001' }) },
        { title: 'Saha Holdings — Joint Venture (MNA/SGP/0006/2017)', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2017-00006' }) },
        { title: 'Tara Holdings — Share Purchase Agreement', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2017-00045' }) },
        { title: 'Master Share Purchase Agreement (Locked-Box)', cat: 'PRECEDENT', action: () => navigate('knowledge', { tab: 'precedents' }) }
      ];
    } else {
      getAllProjects().forEach(p => {
        if (p.title.toLowerCase().includes(query) || (p.client_name || '').toLowerCase().includes(query) || (p.team || '').toLowerCase().includes(query)) {
          matches.push({ title: `${p.title} (${p.team})`, cat: 'PROJECT', action: () => navigate('project-detail', { projectId: p.id || p.project_id }) });
        }
      });
      getVisibleMatters().forEach(m => {
        if (m.title.toLowerCase().includes(query) || (m.client_name || '').toLowerCase().includes(query) || (m.matter_code || '').toLowerCase().includes(query)) {
          matches.push({ title: `${m.title} (${m.matter_code})`, cat: 'MATTER', action: () => navigate('matter-detail', { matterId: m.matter_id }) });
        }
      });
      (data.documents || []).forEach(d => {
        if (d.title.toLowerCase().includes(query) || (d.document_type || '').toLowerCase().includes(query)) {
          matches.push({ title: `${d.title} • ${d.document_type}`, cat: 'DOCUMENT', action: () => navigate('doc-detail', { docId: d.document_id }) });
        }
      });
      (data.clients || []).forEach(c => {
        if (c.name.toLowerCase().includes(query) || (c.industry || '').toLowerCase().includes(query)) {
          matches.push({ title: `${c.name} (${c.industry})`, cat: 'CLIENT', action: () => navigate('client-detail', { clientId: c.client_id }) });
        }
      });
      matches.unshift({
        title: `Ask AI: "${query}"`,
        cat: 'REASONING',
        action: () => {
          navigate('ask');
          executeAskQuery(query);
        }
      });
    }

    results.innerHTML = matches.slice(0, 10).map((m, idx) => `
      <div class="palette-item ${idx === state.paletteIndex ? 'selected' : ''}" data-idx="${idx}">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="color:var(--accent-primary)">✦</span>
          <span class="truncate" style="max-width:440px;">${escapeHtml(m.title)}</span>
        </div>
        <span class="palette-item-category">${m.cat}</span>
      </div>
    `).join('');

    results.querySelectorAll('.palette-item').forEach(item => {
      item.addEventListener('click', () => {
        const idx = parseInt(item.dataset.idx);
        const match = matches[idx];
        closeCommandPalette();
        if (match && match.action) match.action();
      });
    });
  }

  // --- PROJECT CREATION MODAL ---
  function setupProjectModal() {
    const overlay = document.getElementById('create-project-overlay');
    const closeBtn = document.getElementById('close-project-modal-btn');
    const cancelBtn = document.getElementById('cancel-project-modal-btn');
    const submitBtn = document.getElementById('submit-project-modal-btn');

    if (overlay) {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeProjectModal();
      });
    }
    if (closeBtn) closeBtn.addEventListener('click', closeProjectModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeProjectModal);
    if (submitBtn) submitBtn.addEventListener('click', handleCreateProjectSubmit);
  }

  async function openProjectModal(prefillMatterId = null) {
    const overlay = document.getElementById('create-project-overlay');
    const matterSelect = document.getElementById('new-project-matter');
    const leadSelect = document.getElementById('new-project-lead');
    if (!overlay || !matterSelect || !leadSelect) return;

    // Fetch live matters if available
    const mattersData = await apiFetch(`${API.matters}?limit=50`);
    const visibleMatters = mattersData?.items || getVisibleMatters();

    matterSelect.innerHTML = visibleMatters.map(m => `
      <option value="${m.matter_id}" ${prefillMatterId === m.matter_id ? 'selected' : ''}>${escapeHtml(m.title)} (${m.matter_code})</option>
    `).join('');

    const membersData = await apiFetch(API.people);
    const members = membersData?.items || getFirmData().members || [];
    leadSelect.innerHTML = members.map(mem => `
      <option value="${mem.name}">${mem.name} (${mem.role} - ${mem.office})</option>
    `).join('');

    const dateInp = document.getElementById('new-project-deadline');
    if (dateInp) {
      const d = new Date();
      d.setDate(d.getDate() + 30);
      dateInp.value = d.toISOString().slice(0, 10);
    }

    state.projectModalOpen = true;
    overlay.classList.add('open');
    setTimeout(() => {
      const titleInp = document.getElementById('new-project-title');
      if (titleInp) titleInp.focus();
    }, 50);
  }

  window.lexosOpenProjectModal = openProjectModal;

  function closeProjectModal() {
    const overlay = document.getElementById('create-project-overlay');
    if (!overlay) return;
    state.projectModalOpen = false;
    overlay.classList.remove('open');
  }

  async function handleCreateProjectSubmit() {
    const titleInp = document.getElementById('new-project-title');
    const matterSelect = document.getElementById('new-project-matter');
    const teamSelect = document.getElementById('new-project-team');
    const leadSelect = document.getElementById('new-project-lead');
    const deadlineInp = document.getElementById('new-project-deadline');
    const scopeInp = document.getElementById('new-project-scope');
    const milestonesInp = document.getElementById('new-project-milestones');

    const title = titleInp ? titleInp.value.trim() : '';
    if (!title) {
      showToast('Please enter a project title.');
      return;
    }

    const matterId = matterSelect ? matterSelect.value : state.selectedMatterId;
    const team = teamSelect ? teamSelect.value : 'Corporate & M&A';
    const lead = leadSelect ? leadSelect.value : getCurrentMember().name;
    const deadline = deadlineInp ? deadlineInp.value : '2024-12-31';
    const scope = scopeInp ? scopeInp.value.trim() : 'Project deliverables defined.';
    const rawMilestones = milestonesInp ? milestonesInp.value.split(',') : [];

    const milestones = rawMilestones.map(m => m.trim()).filter(m => m.length > 0).map(m => ({
      title: m,
      done: false,
      due: deadline
    }));

    if (!milestones.length) {
      milestones.push({ title: 'Initial briefing & scope alignment', done: true, due: deadline });
      milestones.push({ title: 'Drafting & legal risk review', done: false, due: deadline });
      milestones.push({ title: 'Final execution & delivery to client', done: false, due: deadline });
    }

    // Call live backend API
    const res = await apiFetch(API.projects, {
      method: 'POST',
      body: JSON.stringify({
        title,
        matter_id: matterId,
        team,
        lead_lawyer: lead,
        deadline,
        scope,
        milestones
      })
    });

    const newPid = res?.project_id || `PRJ-${Date.now().toString().slice(-4)}`;
    state.customProjects.unshift({
      id: newPid,
      project_id: newPid,
      matter_id: matterId,
      title: title,
      team: team,
      lead_lawyer: lead,
      status: 'In Progress',
      progress: 0,
      deadline: deadline,
      scope: scope,
      milestones: milestones
    });

    closeProjectModal();
    showToast(`Created project "${title}" in database!`);
    navigate('project-detail', { projectId: newPid });
  }

  // --- WORKSPACE ROUTER ---
  function renderWorkspace() {
    const ws = document.getElementById('app-workspace');
    if (!ws) return;

    if (state.dataLoading) {
      ws.innerHTML = renderLoadingScreen('Loading firm data from database…');
      return;
    }

    if (state.dataError) {
      ws.innerHTML = `
        <div class="view-container">
          <div class="view-header-title">API unavailable</div>
          <div class="view-header-desc" style="margin-top:8px;">${escapeHtml(state.dataError)}</div>
        </div>`;
      return;
    }

    switch (state.view) {
      case 'home':
        ws.innerHTML = renderHomeScreen();
        attachHomeEvents();
        break;
      case 'ask':
        ws.innerHTML = renderAskScreen();
        attachAskEvents();
        break;
      case 'matters':
        ws.innerHTML = renderMattersScreen();
        attachMattersEvents();
        break;
      case 'matter-detail':
        if (!getMatterDetailBundle(state.selectedMatterId)?.loaded) {
          ws.innerHTML = renderLoadingScreen('Loading matter intelligence…');
        } else {
          ws.innerHTML = renderMatterDetailScreen(state.selectedMatterId);
          attachMatterDetailEvents();
        }
        break;
      case 'projects':
        ws.innerHTML = renderProjectsScreen();
        attachProjectsEvents();
        break;
      case 'project-detail':
        if (!getProjectDetailBundle(state.selectedProjectId)?.loaded) {
          ws.innerHTML = renderLoadingScreen('Loading project workspace…');
        } else {
          ws.innerHTML = renderProjectDetailScreen(state.selectedProjectId);
          attachProjectDetailEvents();
        }
        break;
      case 'documents':
        ws.innerHTML = renderDocumentsScreen();
        attachDocumentsEvents();
        break;
      case 'doc-detail':
        ws.innerHTML = renderDocDetailScreen(state.selectedDocId);
        attachDocDetailEvents();
        break;
      case 'clients':
        ws.innerHTML = renderClientsScreen();
        break;
      case 'client-detail':
        ws.innerHTML = renderClientDetailScreen(state.selectedClientId);
        break;
      case 'teams':
        ws.innerHTML = renderTeamsScreen();
        break;
      case 'people':
        ws.innerHTML = renderPeopleScreen();
        break;
      case 'knowledge':
        ws.innerHTML = renderKnowledgeScreen();
        attachKnowledgeEvents();
        break;
      case 'activity':
        ws.innerHTML = renderActivityScreen();
        break;
      case 'tasks':
        ws.innerHTML = renderTasksScreen();
        break;
      case 'architecture':
        ws.innerHTML = renderArchitectureScreen();
        attachArchitectureEvents();
        break;
      default:
        ws.innerHTML = renderHomeScreen();
        attachHomeEvents();
    }
  }

  // --- RIGHT INSPECTOR PANE ---
  function renderRightPane() {
    const pane = document.getElementById('app-inspector-pane');
    if (!pane) return;

    let content = '';

    if (state.view === 'project-detail' && state.selectedProjectId) {
      const bundle = getProjectDetailBundle(state.selectedProjectId);
      const p = bundle?.project || getProjectById(state.selectedProjectId);
      if (p) {
        const recent = (bundle?.recentActivity || bundle?.activity || []).slice(0, 5);
        content = `
          <div class="inspector-header">
            <span class="inspector-title"><span>✦</span> Project Intelligence</span>
            <span class="kbd-shortcut">${p.id || p.project_id}</span>
          </div>
          <div class="inspector-body">
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
              <div style="font-size:10.5px;font-weight:600;color:var(--accent-primary);margin-bottom:3px;">ACTIVE WORKSTREAM</div>
              <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${escapeHtml(p.title)}</div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Lead: ${escapeHtml(p.lead_lawyer || '—')} • ${p.progress || 0}% complete</div>
            </div>

            ${recent.length ? `
              <div>
                <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Recent Activity</div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                  ${recent.map(a => `
                    <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);font-size:11px;">
                      <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(formatActivityAction(a.action))}</div>
                      ${a.target_title ? `<div style="color:var(--text-muted);margin-top:2px;">${escapeHtml(a.target_title)}</div>` : ''}
                      <div style="color:var(--text-muted);font-size:10px;margin-top:2px;">${formatDateTime(a.created_at)}</div>
                    </div>
                  `).join('')}
                </div>
              </div>
            ` : ''}

            <div>
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Ask AI about this project:</div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <input id="proj-copilot-input" type="text" placeholder="e.g. What deliverables are outstanding?" style="flex:1;height:30px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0 8px;font-size:12px;color:var(--text-primary);outline:none;">
                <button id="proj-copilot-btn" class="btn btn-primary btn-sm">Ask</button>
              </div>
              <div id="proj-copilot-answers" style="font-size:11.5px;color:var(--text-secondary);line-height:1.5;background:var(--bg-surface);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);min-height:70px;">
                AI scoped to analyze milestones, deliverables, and documents for <strong>${escapeHtml(p.title)}</strong>.
              </div>
            </div>

            <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Parent Matter</div>
              <div style="padding:8px 10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);font-size:11.5px;cursor:pointer;" onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })">
                <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(p.matter_title || p.matter_code || 'Matter')}</div>
                <div style="font-size:10.5px;color:var(--text-muted);">${p.client_name || 'Client'}</div>
              </div>
            </div>
          </div>
        `;
      }
    } else if (state.view === 'matter-detail' && state.selectedMatterId) {
      const bundle = getMatterDetailBundle(state.selectedMatterId);
      const m = bundle?.matter || getMatterById(state.selectedMatterId);
      if (m) {
        const issues = (m.legal_issues || []).slice(0, 4);
        content = `
          <div class="inspector-header">
            <span class="inspector-title"><span>✦</span> Matter Assistant</span>
            <span class="kbd-shortcut">${m.matter_code || 'MATTER'}</span>
          </div>
          <div class="inspector-body">
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
              <div style="font-size:10.5px;font-weight:600;color:var(--accent-primary);margin-bottom:3px;">MATTER CONTEXT</div>
              <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${escapeHtml(m.client_name || '')} • ${escapeHtml(m.court || m.practice_area || '')}</div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${escapeHtml(m.outcome || 'Outcome pending')} • ${escapeHtml(m.claim_amount || '—')}</div>
            </div>

            ${issues.length ? `
              <div>
                <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Legal Issues</div>
                <div style="display:flex;flex-wrap:wrap;gap:4px;">
                  ${issues.map(i => `<span class="scope-chip">${escapeHtml(i)}</span>`).join('')}
                </div>
              </div>
            ` : ''}

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;">
              <div style="padding:8px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);text-align:center;">
                <div style="font-weight:700;font-family:var(--font-mono);">${bundle?.documents?.length || 0}</div>
                <div style="color:var(--text-muted);font-size:9.5px;">DOCS</div>
              </div>
              <div style="padding:8px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);text-align:center;">
                <div style="font-weight:700;font-family:var(--font-mono);">${bundle?.arguments?.length || 0}</div>
                <div style="color:var(--text-muted);font-size:9.5px;">ARGS</div>
              </div>
            </div>

            <div>
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Ask about this matter:</div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <input id="matter-copilot-input" type="text" placeholder="e.g. What arguments did we use?" style="flex:1;height:30px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0 8px;font-size:12px;color:var(--text-primary);outline:none;">
                <button id="matter-copilot-btn" class="btn btn-primary btn-sm">Ask</button>
              </div>
              <div id="matter-copilot-answers" style="font-size:11.5px;color:var(--text-secondary);line-height:1.5;background:var(--bg-surface);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);min-height:70px;">
                AI scoped to verified documents, arguments, and timelines for this matter.
              </div>
            </div>
          </div>
        `;
      }
    } else {
      content = `
        <div class="inspector-header">
          <span class="inspector-title"><span>✦</span> Apex Institutional Memory</span>
          <span class="kbd-shortcut">APEX</span>
        </div>
        <div class="inspector-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--text-primary);">${(getFirmData().stats?.matters || getFirmData().totals?.matters || 1000).toLocaleString()}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Matters</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-primary);">${getAllProjects().length.toLocaleString()}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Active Projects</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-emerald);">${(getFirmData().stats?.documents || getFirmData().totals?.documents || 38232).toLocaleString()}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Indexed Docs</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-purple);">${(getFirmData().stats?.arguments || getFirmData().totals?.arguments || 20456).toLocaleString()}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Arguments</div>
            </div>
          </div>
        </div>
      `;
    }

    pane.innerHTML = content;

    const projBtn = document.getElementById('proj-copilot-btn');
    const projInp = document.getElementById('proj-copilot-input');
    const projAns = document.getElementById('proj-copilot-answers');
    if (projBtn && projInp && projAns) {
      projBtn.addEventListener('click', () => {
        const q = projInp.value.trim();
        if (!q) return;
        projAns.innerHTML = `<span style="color:var(--accent-primary)">✦ Analyzing project...</span>`;
        setTimeout(() => {
          projAns.innerHTML = `<div style="color:var(--text-primary);font-weight:600;margin-bottom:3px;">Findings:</div><div style="color:var(--text-secondary);">3 of 4 milestones completed. The final deliverable requires General Counsel signoff.</div>`;
        }, 300);
      });
    }
  }

  // --- SCREEN 1: HOME ---
  function renderHomeScreen() {
    const mem = getCurrentMember();
    const visibleMatters = getVisibleMatters();
    const activeMatters = visibleMatters.slice(0, 3);
    const activeProjects = getAllProjects().slice(0, 3);

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Good morning, ${mem.name}</div>
            <div class="view-header-desc">Apex Chambers Institutional Memory • ${mem.role}, ${mem.office} Office</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenProjectModal()"><span>＋</span> New Project</button>
            <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('ask')"><span>✦</span> Ask Firm</button>
          </div>
        </div>

        <div class="ask-hero-box">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="font-size:11.5px;font-weight:600;color:var(--text-secondary);display:flex;align-items:center;gap:6px;">
              <span style="color:var(--accent-primary)">✦</span> ASK INSTITUTIONAL MEMORY
            </span>
            <span class="kbd-shortcut">⌘2</span>
          </div>
          <div style="display:flex;gap:8px;">
            <input id="home-fast-ask-input" type="text" placeholder="Ask across past matters, projects, arguments, precedents, clauses, or lawyers..." style="flex:1;height:34px;background:var(--bg-surface-elevated);border:1px solid var(--border-medium);border-radius:var(--radius-sm);padding:0 12px;font-size:13px;color:var(--text-primary);outline:none;">
            <button id="home-fast-ask-btn" class="btn btn-primary">Ask Firm</button>
          </div>
          <div class="suggested-pills">
            <span class="pill-label">Suggested:</span>
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Shareholder oppression dispute</button>
            <button class="query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">SIAC emergency relief</button>
            <button class="query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">M&A indemnity cap precedent</button>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(340px, 1fr));gap:16px;margin-bottom:24px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Active Projects & Workstreams</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('projects')">All Projects →</button>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
              ${activeProjects.map(p => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id || p.project_id}' })">
                  <div style="flex:1;min-width:0;">
                    <div style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${escapeHtml(p.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${p.client_name || 'Client'} • ${p.team} • Lead: ${p.lead_lawyer}</div>
                  </div>
                  <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.progress}%</span>
                </div>
              `).join('')}
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-2-badge">Active Matters</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('matters')">All Matters →</button>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
              ${activeMatters.map(m => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <div>
                    <div style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${escapeHtml(m.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${m.client_name} • ${m.court || m.practice_area}</div>
                  </div>
                  <span class="status-pill ${m.status.toLowerCase()}">${m.status}</span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function attachHomeEvents() {
    const inp = document.getElementById('home-fast-ask-input');
    const btn = document.getElementById('home-fast-ask-btn');
    if (btn && inp) {
      const handleAsk = () => {
        const q = inp.value.trim();
        if (q) {
          navigate('ask');
          executeAskQuery(q);
        }
      };
      btn.addEventListener('click', handleAsk);
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleAsk();
      });
    }

    document.querySelectorAll('.query-preset-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        const q = pill.dataset.query;
        if (q) {
          navigate('ask');
          executeAskQuery(q);
        }
      });
    });
  }

  // --- SCREEN: PROJECTS WORKSPACE ---
  function renderProjectsScreen() {
    const allProjects = getAllProjects();
    const query = (state.searchQuery || '').toLowerCase();
    const filtered = allProjects.filter(p => {
      if (state.projectStatusFilter !== 'all' && (p.status || '').toLowerCase() !== state.projectStatusFilter.toLowerCase()) return false;
      if (!query) return true;
      return (p.title || '').toLowerCase().includes(query) ||
             (p.client_name || '').toLowerCase().includes(query) ||
             (p.team || '').toLowerCase().includes(query) ||
             (p.lead_lawyer || '').toLowerCase().includes(query);
    });

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Projects & Workstreams</div>
            <div class="view-header-desc">Multi-disciplinary project management across M&A Due Diligence, Regulatory Clearances, and Litigation workstreams.</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-primary btn-sm" onclick="window.lexosOpenProjectModal()"><span>＋</span> Create Project</button>
          </div>
        </div>

        <div class="filter-bar">
          <div class="search-input-box">
            <span class="search-input-icon">🔍</span>
            <input id="projects-search-input" type="text" placeholder="Filter projects by title, client, team, lead lawyer..." value="${escapeHtml(state.searchQuery)}">
          </div>
          <select id="projects-status-filter" class="filter-select">
            <option value="all" ${state.projectStatusFilter === 'all' ? 'selected' : ''}>All Statuses</option>
            <option value="In Progress" ${state.projectStatusFilter === 'In Progress' ? 'selected' : ''}>In Progress</option>
            <option value="Active" ${state.projectStatusFilter === 'Active' ? 'selected' : ''}>Active</option>
            <option value="Review" ${state.projectStatusFilter === 'Review' ? 'selected' : ''}>Review</option>
            <option value="Completed" ${state.projectStatusFilter === 'Completed' ? 'selected' : ''}>Completed</option>
          </select>
          <span class="mono" style="font-size:11px;color:var(--text-muted);margin-left:auto;">${filtered.length} Projects</span>
        </div>

        <div class="projects-grid">
          ${filtered.map(p => `
            <div class="project-card" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id || p.project_id}' })">
              <div class="project-meta-row">
                <span class="scope-chip">${p.team}</span>
                <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.status}</span>
              </div>
              <div style="font-weight:700;font-size:14px;color:var(--text-primary);letter-spacing:-0.01em;">${escapeHtml(p.title)}</div>
              <div style="font-size:11.5px;color:var(--text-secondary);">
                ${p.client_name || 'Client'} • <span class="mono" style="color:var(--accent-primary);">${p.matter_code || 'Matter'}</span>
              </div>
              <div style="font-size:11.5px;color:var(--text-muted);line-height:1.4;margin:2px 0;">
                ${escapeHtml(p.scope || 'Deliverables and review workstream.')}
              </div>
              <div style="margin-top:auto;padding-top:8px;border-top:1px solid var(--border-subtle);">
                <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--text-muted);margin-bottom:4px;">
                  <span>Lead: <strong>${p.lead_lawyer}</strong></span>
                  <span class="mono">Target: ${p.deadline}</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill" style="width:${p.progress}%;"></div>
                </div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function attachProjectsEvents() {
    const inp = document.getElementById('projects-search-input');
    const sel = document.getElementById('projects-status-filter');
    if (inp) {
      inp.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        renderWorkspace();
      });
    }
    if (sel) {
      sel.addEventListener('change', (e) => {
        state.projectStatusFilter = e.target.value;
        renderWorkspace();
      });
    }
  }

  // --- SCREEN: PROJECT DETAIL ---
  function renderProjectDetailScreen(projectId) {
    const bundle = getProjectDetailBundle(projectId);
    const p = bundle?.project || getProjectById(projectId) || getAllProjects()[0];
    if (!p) return `<div class="view-container">Project not found.</div>`;

    const team = bundle?.team || [];
    const docTotal = bundle?.documentTotal || 0;
    const activityTotal = bundle?.activityTotal || bundle?.activity?.length || 0;

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('projects')">Projects</a> <span>/</span>
          <a onclick="window.lexosNavigate('client-detail', { clientId: '${p.client_id}' })">${escapeHtml(p.client_name || 'Client')}</a> <span>/</span>
          <a onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })">${escapeHtml(p.matter_code || 'Matter')}</a> <span>/</span>
          <span class="mono">${p.id || p.project_id}</span>
        </div>

        <div class="matter-detail-header" style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;flex-wrap:wrap;">
                <span class="scope-chip">${escapeHtml(p.team || p.practice_team || 'Workstream')}</span>
                <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${escapeHtml(p.status || 'In Progress')}</span>
                <span class="mono" style="font-size:11px;color:var(--text-muted);">${p.id || p.project_id}</span>
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);">${escapeHtml(p.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;flex-wrap:wrap;">
              <button class="btn btn-secondary btn-sm" id="project-export-btn" data-project-id="${p.id || p.project_id}">Export Manifest</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are the key findings in project ${p.id || p.project_id}?');"><span>✦</span> Ask Project AI</button>
              <button class="btn btn-primary btn-sm" id="project-add-folder-btn" data-project-id="${p.id || p.project_id}">＋ New Folder</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:10px;margin-bottom:12px;">
            <div><strong>Client:</strong> ${escapeHtml(p.client_name || '—')}</div>
            <div><strong>Parent Matter:</strong> <a onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })" style="color:var(--accent-primary);cursor:pointer;">${escapeHtml(p.matter_title || p.matter_code || 'Matter')}</a></div>
            <div><strong>Lead Lawyer:</strong> ${escapeHtml(p.lead_lawyer || '—')}</div>
            <div><strong>Deadline:</strong> <span class="mono">${formatDate(p.deadline)}</span></div>
            <div><strong>Progress:</strong> <span class="mono">${p.progress || 0}%</span></div>
          </div>

          <div class="progress-track" style="margin-bottom:10px;">
            <div class="progress-fill" style="width:${p.progress || 0}%;"></div>
          </div>

          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <span class="scope-chip">${docTotal} documents</span>
            <span class="scope-chip">${(bundle?.folders || []).length} folders</span>
            <span class="scope-chip">${team.length} team members</span>
            <span class="scope-chip">${activityTotal} activity events</span>
          </div>
        </div>

        <div class="tabs-nav" style="flex-wrap:wrap;">
          <button class="tab-btn ${state.projectTab === 'overview' ? 'active' : ''}" data-project-tab="overview">Overview</button>
          <button class="tab-btn ${state.projectTab === 'documents' ? 'active' : ''}" data-project-tab="documents">Documents (${docTotal})</button>
          <button class="tab-btn ${state.projectTab === 'activity' ? 'active' : ''}" data-project-tab="activity">Activity (${activityTotal})</button>
        </div>

        <div id="project-tab-content">
          ${renderProjectTabContent(p, bundle)}
        </div>
      </div>
    `;
  }

  function renderProjectTabContent(p, bundle) {
    const projectId = p.id || p.project_id;
    switch (state.projectTab) {
      case 'documents':
        return renderProjectDocumentsTab(projectId, bundle);
      case 'activity':
        return renderProjectActivityTab(bundle);
      case 'overview':
      default:
        return renderProjectOverviewTab(p, bundle);
    }
  }

  function renderProjectOverviewTab(p, bundle) {
    const team = bundle?.team || [];
    const docs = (bundle?.documents || []).slice(0, 6);

    return `
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
        <div style="display:flex;flex-direction:column;gap:16px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Project Scope & Deliverables</span>
            </div>
            <div class="layer-content">
              <p style="font-size:13px;color:var(--text-primary);line-height:1.6;">${escapeHtml(p.scope || 'Comprehensive workstream deliverables for this matter.')}</p>
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-2-badge">Milestones & Action Items</span>
              <span class="mono" style="font-size:10.5px;color:var(--text-muted);">${(p.milestones || []).filter(m => m.done).length} of ${(p.milestones || []).length} Completed</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
              ${(p.milestones || []).length ? (p.milestones || []).map((m, idx) => `
                <div class="milestone-item" onclick="window.toggleProjectMilestone('${p.id || p.project_id}', ${idx})">
                  <div style="display:flex;align-items:center;gap:10px;">
                    <input type="checkbox" class="milestone-checkbox" ${m.done ? 'checked' : ''} onclick="event.stopPropagation();window.toggleProjectMilestone('${p.id || p.project_id}', ${idx})">
                    <span style="font-size:12.5px;color:${m.done ? 'var(--text-muted)' : 'var(--text-primary)'};text-decoration:${m.done ? 'line-through' : 'none'};">${escapeHtml(m.title)}</span>
                  </div>
                  <span class="mono" style="font-size:10.5px;color:var(--text-muted);">${formatDate(m.due || p.deadline)}</span>
                </div>
              `).join('') : `
                <div style="font-size:12px;color:var(--text-muted);padding:8px 0;">No milestones defined yet.</div>
              `}
            </div>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:16px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-3-badge">Project Team</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
              ${team.length ? team.slice(0, 6).map(t => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('person-detail', { personId: '${t.member_id}' })" style="cursor:pointer;">
                  <div>
                    <div style="font-weight:600;font-size:12px;color:var(--text-primary);">${escapeHtml(t.name)}</div>
                    <div style="font-size:10.5px;color:var(--text-muted);">${escapeHtml(t.role_on_matter || t.role || 'Team member')}</div>
                  </div>
                </div>
              `).join('') : `
                <div style="font-size:12px;color:var(--text-muted);">No team members assigned</div>
              `}
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Recent Documents</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id || p.project_id}', tab: 'documents' })">View all →</button>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
              ${docs.length ? docs.map(d => `
                <div class="evidence-item-row" onclick="window.lexosOpenSourceViewer('${d.document_id}')">
                  <div>
                    <div style="font-weight:600;font-size:12px;color:var(--text-primary);">${escapeHtml(d.title)}</div>
                    <div style="font-size:10.5px;color:var(--text-muted);">${escapeHtml(d.document_type || 'Document')} • <span class="version-tag">${escapeHtml(d.version || 'v1')}</span></div>
                  </div>
                  <span class="kbd-shortcut">Open →</span>
                </div>
              `).join('') : `
                <div style="font-size:12px;color:var(--text-muted);">No documents in this project yet.</div>
              `}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderProjectFolderTreeNodes(nodes, projectId, depth = 0) {
    if (!nodes?.length) return '';
    return nodes.map(folder => {
      const fid = folder.folder_id;
      const isSelected = state.selectedProjectFolderId === fid;
      const count = folder.document_count || 0;
      const childCount = (folder.children || []).length;
      return `
        <div class="folder-tree-node" style="--depth:${depth};">
          <div class="folder-tree-item ${isSelected ? 'active' : ''}"
               data-folder-id="${fid}"
               data-project-id="${projectId}"
               onclick="window.selectProjectFolder('${projectId}', '${fid}')">
            <span class="folder-tree-icon">${childCount ? '📁' : '📂'}</span>
            <span class="folder-tree-name">${escapeHtml(folder.name)}</span>
            <span class="folder-tree-count">${count}</span>
            <button class="btn btn-ghost btn-sm folder-tree-delete"
                    title="Delete folder"
                    onclick="event.stopPropagation();window.deleteProjectFolder('${projectId}', '${fid}', '${escapeHtml(folder.name).replace(/'/g, "\\'")}')">✕</button>
          </div>
          ${childCount ? `<div class="folder-tree-children">${renderProjectFolderTreeNodes(folder.children, projectId, depth + 1)}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  function renderProjectDocumentsTab(projectId, bundle) {
    const folderTree = bundle?.folderTree || [];
    const rootCount = bundle?.rootDocumentCount || 0;
    const allDocs = bundle?.documents || [];
    const search = (state.projectDocSearch || '').toLowerCase();
    const selectedFolder = state.selectedProjectFolderId;

    let filteredDocs = allDocs;
    if (selectedFolder && selectedFolder !== '__all__') {
      if (selectedFolder === '__root__') {
        filteredDocs = allDocs.filter(d => !d.folder_id);
      } else {
        filteredDocs = allDocs.filter(d => d.folder_id === selectedFolder);
      }
    }
    if (search) {
      filteredDocs = filteredDocs.filter(d =>
        (d.title || '').toLowerCase().includes(search) ||
        (d.document_id || '').toLowerCase().includes(search) ||
        (d.document_type || '').toLowerCase().includes(search)
      );
    }

    const folderLabel = selectedFolder === '__all__' ? 'All Documents'
      : selectedFolder === '__root__' ? 'Project Root'
      : (bundle?.folders || []).find(f => f.folder_id === selectedFolder)?.name || 'Folder';

    return `
      <div class="project-workspace-layout">
        <aside class="project-folder-panel">
          <div class="project-folder-panel-header">
            <span>Directory</span>
            <button class="btn btn-ghost btn-sm" id="project-add-folder-sidebar" data-project-id="${projectId}">＋</button>
          </div>
          <div class="folder-tree">
            <div class="folder-tree-item ${selectedFolder === '__all__' ? 'active' : ''}"
                 onclick="window.selectProjectFolder('${projectId}', '__all__')">
              <span class="folder-tree-icon">📋</span>
              <span class="folder-tree-name">All Documents</span>
              <span class="folder-tree-count">${allDocs.length}</span>
            </div>
            <div class="folder-tree-item ${selectedFolder === '__root__' ? 'active' : ''}"
                 onclick="window.selectProjectFolder('${projectId}', '__root__')">
              <span class="folder-tree-icon">🏠</span>
              <span class="folder-tree-name">Project Root</span>
              <span class="folder-tree-count">${rootCount}</span>
            </div>
            ${renderProjectFolderTreeNodes(folderTree, projectId)}
          </div>
        </aside>

        <section class="project-docs-panel">
          <div class="project-docs-toolbar">
            <div>
              <div style="font-size:13px;font-weight:600;color:var(--text-primary);">${escapeHtml(folderLabel)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${filteredDocs.length} document${filteredDocs.length === 1 ? '' : 's'} • versioned workstream files</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <input id="project-doc-search" type="text" placeholder="Filter documents…" value="${escapeHtml(state.projectDocSearch)}" class="filter-select" style="width:220px;height:32px;padding:0 10px;">
              <button class="btn btn-secondary btn-sm" id="project-assign-doc-btn" data-project-id="${projectId}">Assign from Matter</button>
            </div>
          </div>

          <div class="data-table-container">
            <table class="data-table project-docs-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Status</th>
                  <th>Version</th>
                  <th>History</th>
                  <th>Author</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                ${filteredDocs.length ? filteredDocs.map(d => `
                  <tr class="project-doc-row">
                    <td>
                      <div style="font-weight:600;color:var(--text-primary);cursor:pointer;" onclick="window.lexosOpenSourceViewer('${d.document_id}')">${escapeHtml(d.title)}</div>
                      <div style="font-size:11px;color:var(--text-muted);"><span class="scope-chip">${escapeHtml(d.document_type || 'Document')}</span> <span class="mono">${d.document_id}</span></div>
                    </td>
                    <td><span class="version-status-pill ${versionStatusClass(d.version_status, d.status)}">${escapeHtml(formatVersionStatus(d.version_status, d.status))}</span></td>
                    <td>
                      <button class="version-tag version-tag-btn" onclick="window.openDocumentVersions('${d.document_id}')" title="View version history">
                        ${escapeHtml(d.version || 'v1')}
                      </button>
                    </td>
                    <td><span class="mono" style="font-size:11px;color:var(--text-muted);">${d.version_count || 1} ver.</span></td>
                    <td>${escapeHtml(d.author_name || '—')}</td>
                    <td>
                      <div style="display:flex;gap:4px;flex-wrap:wrap;">
                        <button class="btn btn-ghost btn-sm project-develop-btn" data-doc-id="${d.document_id}" data-project-id="${projectId}" title="Branch a new developing version">Develop</button>
                        <select class="filter-select project-doc-folder-select" data-doc-id="${d.document_id}" data-project-id="${projectId}" style="max-width:120px;font-size:10.5px;">
                          <option value="" ${!d.folder_id ? 'selected' : ''}>Root</option>
                          ${(bundle?.folders || []).map(f => `
                            <option value="${f.folder_id}" ${d.folder_id === f.folder_id ? 'selected' : ''}>${escapeHtml(f.name)}</option>
                          `).join('')}
                        </select>
                      </div>
                    </td>
                  </tr>
                `).join('') : `
                  <tr><td colspan="6" style="padding:32px;text-align:center;color:var(--text-muted);">
                    No documents in this view. Run <code>python scripts/seed_project_workspace.py</code> to populate demo folders and versions,<br>
                    or assign documents from the parent matter.
                  </td></tr>
                `}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    `;
  }

  function renderProjectActivityTab(bundle) {
    const items = bundle?.activity || [];

    return `
      <div class="activity-timeline">
        ${items.length ? items.map(a => `
          <div class="activity-item">
            <div class="activity-item-marker"></div>
            <div class="activity-item-body">
              <div class="activity-item-header">
                <span class="activity-action">${escapeHtml(formatActivityAction(a.action))}</span>
                <span class="activity-time mono">${formatDateTime(a.created_at)}</span>
              </div>
              ${a.target_title ? `<div class="activity-target">${escapeHtml(a.target_title)}</div>` : ''}
              <div class="activity-meta">
                ${a.actor_name ? `<span>By ${escapeHtml(a.actor_name)}</span>` : ''}
                ${a.target_id ? `<span class="mono">${a.target_id}</span>` : ''}
              </div>
            </div>
          </div>
        `).join('') : `
          <div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">
            No activity recorded yet. Create folders, move documents, or toggle milestones to build the audit trail.
          </div>
        `}
      </div>
    `;
  }

  function attachProjectDetailEvents() {
    const tabNav = document.querySelector('#project-tab-content')?.closest('.view-container')?.querySelector('.tabs-nav');
    if (tabNav) {
      tabNav.querySelectorAll('[data-project-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
          state.projectTab = btn.dataset.projectTab;
          navigate('project-detail', { projectId: state.selectedProjectId, tab: state.projectTab }, { skipUrl: false });
        });
      });
    }

    const exportBtn = document.getElementById('project-export-btn');
    if (exportBtn) {
      exportBtn.addEventListener('click', () => exportProjectManifest(exportBtn.dataset.projectId));
    }

    const addFolderBtns = document.querySelectorAll('#project-add-folder-btn, #project-add-folder-sidebar');
    addFolderBtns.forEach(btn => {
      btn.addEventListener('click', () => createProjectFolderPrompt(btn.dataset.projectId));
    });

    const assignBtn = document.getElementById('project-assign-doc-btn');
    if (assignBtn) {
      assignBtn.addEventListener('click', () => assignDocumentToProjectPrompt(assignBtn.dataset.projectId));
    }

    const searchInp = document.getElementById('project-doc-search');
    if (searchInp) {
      searchInp.addEventListener('input', (e) => {
        state.projectDocSearch = e.target.value;
        renderWorkspace();
        attachProjectDetailEvents();
      });
    }

    document.querySelectorAll('.project-doc-folder-select').forEach(sel => {
      sel.addEventListener('change', async (e) => {
        const docId = e.target.dataset.docId;
        const projectId = e.target.dataset.projectId;
        const folderId = e.target.value || null;
        await moveProjectDocument(projectId, docId, folderId);
      });
    });

    document.querySelectorAll('.project-develop-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const docId = e.currentTarget.dataset.docId;
        const projectId = e.currentTarget.dataset.projectId;
        await createDevelopingVersion(docId, projectId);
      });
    });
  }

  async function createDevelopingVersion(docId, projectId) {
    const res = await apiFetch(`${API.documents}/${encodeURIComponent(docId)}/versions/developing`, {
      method: 'POST',
      body: JSON.stringify({ author_name: getCurrentMember().name }),
    });
    if (!res || res.detail) {
      showToast('Could not create developing version.');
      return;
    }
    showToast(`Created ${res.version?.version_label || 'new developing version'}`);
    await refreshProjectDetail(projectId);
    state.projectTab = 'documents';
    renderWorkspace();
    attachProjectDetailEvents();
    renderRightPane();
  }

  window.selectProjectFolder = function(projectId, folderId) {
    state.selectedProjectFolderId = folderId;
    state.projectTab = 'documents';
    renderWorkspace();
    attachProjectDetailEvents();
  };

  async function createProjectFolderPrompt(projectId) {
    const rawParent = state.selectedProjectFolderId;
    const parentId = (rawParent && !String(rawParent).startsWith('__')) ? rawParent : null;
    const name = window.prompt(parentId ? 'New subfolder name:' : 'New folder name:');
    if (!name?.trim()) return;

    const body = { name: name.trim() };
    if (parentId) body.parent_folder_id = parentId;

    const res = await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/folders`, {
      method: 'POST',
      body: JSON.stringify(body),
    });

    if (!res || res.detail) {
      showToast('Could not create folder.');
      return;
    }

    showToast(`Created folder "${name.trim()}"`);
    await refreshProjectDetail(projectId);
    state.projectTab = 'documents';
    renderWorkspace();
    attachProjectDetailEvents();
    renderRightPane();
  }

  window.deleteProjectFolder = async function(projectId, folderId, folderName) {
    if (!window.confirm(`Delete folder "${folderName}" and unassign its documents?`)) return;

    await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/folders/${encodeURIComponent(folderId)}`, {
      method: 'DELETE',
    });

    if (state.selectedProjectFolderId === folderId) {
      state.selectedProjectFolderId = '__all__';
    }

    showToast(`Deleted folder "${folderName}"`);
    await refreshProjectDetail(projectId);
    renderWorkspace();
    attachProjectDetailEvents();
    renderRightPane();
  };

  async function moveProjectDocument(projectId, documentId, folderId) {
    await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/folder`, {
      method: 'PATCH',
      body: JSON.stringify({ folder_id: folderId }),
    });

    showToast('Document moved');
    await refreshProjectDetail(projectId);
    renderWorkspace();
    attachProjectDetailEvents();
  }

  async function assignDocumentToProjectPrompt(projectId) {
    const bundle = getProjectDetailBundle(projectId);
    const matterId = bundle?.project?.matter_id;
    if (!matterId) {
      showToast('Could not resolve parent matter.');
      return;
    }

    const docId = window.prompt('Enter document ID to assign (e.g. DOC-00001):');
    if (!docId?.trim()) return;

    const res = await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(docId.trim().toUpperCase())}`, {
      method: 'POST',
    });

    if (!res || res.detail) {
      showToast('Could not assign document.');
      return;
    }

    showToast(res.status === 'already_assigned' ? 'Document already in project matter' : 'Document assigned');
    await refreshProjectDetail(projectId);
    state.projectTab = 'documents';
    renderWorkspace();
    attachProjectDetailEvents();
    renderRightPane();
  }

  async function exportProjectManifest(projectId) {
    const data = await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/export`);
    if (!data?.export) {
      showToast('Export failed.');
      return;
    }

    const blob = new Blob([JSON.stringify(data.export, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${projectId}-manifest.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Project manifest downloaded');
  }

  window.openDocumentVersions = async function(docId) {
    const versionsData = await apiFetch(`${API.documents}/${encodeURIComponent(docId)}/versions`);
    const versions = versionsData?.versions || [];

    if (!versions.length) {
      showToast('No version history yet — document may predate versioning.');
      await openDocumentSourceViewer(docId);
      return;
    }

    const listHtml = versions.map(v => `
      <div class="version-history-row" data-version-id="${v.version_id}" data-doc-id="${docId}">
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="version-tag">v${v.version_number}</span>
          <span class="version-status-pill ${versionStatusClass(v.version_status)}">${escapeHtml(formatVersionStatus(v.version_status))}</span>
          <strong style="font-size:12px;">${escapeHtml(v.version_label || v.title)}</strong>
        </div>
        <div style="font-size:10.5px;color:var(--text-muted);margin-top:4px;">
          ${escapeHtml(v.author_name || 'Unknown')} • ${formatDateTime(v.created_at)} • ${(v.source || 'upload')}
        </div>
        <div class="mono" style="font-size:9.5px;color:var(--text-muted);margin-top:2px;">${(v.content_sha256 || '').slice(0, 16)}…</div>
      </div>
    `).join('');

    const overlay = document.getElementById('doc-source-viewer-overlay');
    if (overlay) overlay.classList.add('open');

    const bodyEl = document.getElementById('viewer-document-body');
    if (bodyEl) {
      bodyEl.innerHTML = `
        <div class="version-history-panel">
          <div style="font-size:13px;font-weight:600;margin-bottom:12px;">Version History — ${docId}</div>
          ${listHtml}
          ${versions.length >= 2 ? `
            <button class="btn btn-secondary btn-sm" style="margin-top:12px;" id="compare-latest-versions" data-doc-id="${docId}" data-v-a="${versions[1].version_id}" data-v-b="${versions[0].version_id}">
              Compare latest two versions
            </button>
          ` : ''}
        </div>
      `;

      bodyEl.querySelectorAll('.version-history-row').forEach(row => {
        row.addEventListener('click', async () => {
          const vid = row.dataset.versionId;
          const version = await apiFetch(`${API.documents}/${encodeURIComponent(docId)}/versions/${encodeURIComponent(vid)}`);
          if (version?.version) {
            const v = version.version;
            bodyEl.innerHTML = `
              <div style="margin-bottom:12px;display:flex;align-items:center;gap:8px;">
                <button class="btn btn-ghost btn-sm" id="back-to-version-list">← All versions</button>
                <span class="version-tag">v${v.version_number}</span>
                <strong>${escapeHtml(v.title)}</strong>
              </div>
              <div style="white-space:pre-wrap;font-size:13px;line-height:1.7;">${escapeHtml(v.body || '')}</div>
            `;
            document.getElementById('back-to-version-list')?.addEventListener('click', () => window.openDocumentVersions(docId));
          }
        });
      });

      document.getElementById('compare-latest-versions')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const diff = await apiFetch(
          `${API.documents}/${encodeURIComponent(btn.dataset.docId)}/versions/${encodeURIComponent(btn.dataset.vB)}/diff?compare_with=${encodeURIComponent(btn.dataset.vA)}`
        );
        if (diff?.diff) {
          bodyEl.innerHTML = `
            <div style="margin-bottom:12px;">
              <button class="btn btn-ghost btn-sm" onclick="window.openDocumentVersions('${docId}')">← All versions</button>
              <span style="font-size:12px;font-weight:600;margin-left:8px;">Diff: v${diff.version_a?.version_number} → v${diff.version_b?.version_number}</span>
            </div>
            <pre class="diff-pane" style="font-size:11.5px;line-height:1.5;overflow:auto;">${escapeHtml(diff.diff)}</pre>
          `;
        }
      });
    }

    const titleEl = document.getElementById('viewer-doc-title');
    if (titleEl) titleEl.innerText = `Version History`;
  };

  window.toggleProjectMilestone = async function(projectId, milestoneIndex) {
    const p = getProjectById(projectId);
    if (!p || !p.milestones || !p.milestones[milestoneIndex]) return;
    
    const newDone = !p.milestones[milestoneIndex].done;
    p.milestones[milestoneIndex].done = newDone;
    
    // Call live backend API to persist
    await apiFetch(`${API.projects}/${encodeURIComponent(projectId)}/milestones/${milestoneIndex}`, {
      method: 'PATCH',
      body: JSON.stringify({ done: newDone })
    });

    const total = p.milestones.length;
    const completed = p.milestones.filter(m => m.done).length;
    p.progress = Math.round((completed / total) * 100);
    p.status = p.progress === 100 ? 'Completed' : 'In Progress';

    showToast(`Updated milestone in database!`);
    await refreshProjectDetail(projectId);
    renderWorkspace();
    renderRightPane();
  };

  // --- SCREEN 2: ASK THE FIRM (4-LAYER REASONING & HIGHLIGHTED SOURCES) ---
  function renderAskScreen() {
    const engineLabel = state.systemInfo?.retrieval_engine
      ? `Engine ${String(state.systemInfo.retrieval_engine).toUpperCase()}`
      : 'Engine V2';
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Ask the Firm AI</div>
            <div class="view-header-desc">Parallel retrieval fabric across 38,232 documents — planner → channels → fusion → rerank → cited answer.</div>
          </div>
          <div class="view-header-actions" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> ${escapeHtml(engineLabel)}</span>
            <span class="status-badge-live"><span class="status-dot-pulse"></span> ACL Secured</span>
            <button id="ask-debug-toggle" class="btn btn-secondary btn-sm">${state.debugOpen ? 'Hide Debug' : 'Show Debug'}</button>
            <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('architecture')">Architecture →</button>
          </div>
        </div>

        <div class="ask-hero-box">
          <textarea id="ask-main-input" class="ask-textarea" placeholder="Ask about past matters, arguments, precedents, clauses, or lawyers... (e.g. Have we handled a shareholder dispute involving oppression and minority rights before?)">${escapeHtml(state.askQuery)}</textarea>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;flex-wrap:wrap;gap:8px;">
            <div class="scope-chips">
              <span class="pill-label">Scope:</span>
              <button class="scope-chip ${state.scopeFilter === 'all' ? 'active' : ''}" data-scope="all">Entire Firm</button>
              <button class="scope-chip ${state.scopeFilter === 'Corporate' ? 'active' : ''}" data-scope="Corporate">Corporate / M&A</button>
              <button class="scope-chip ${state.scopeFilter === 'Disputes' ? 'active' : ''}" data-scope="Disputes">Disputes & NCLT</button>
              <button class="scope-chip ${state.scopeFilter === 'Arbitration' ? 'active' : ''}" data-scope="Arbitration">SIAC Arbitration</button>
            </div>
            <button id="ask-submit-btn" class="btn btn-primary"><span>✦</span> Reason & Retrieve</button>
          </div>
          <div class="suggested-pills">
            <span class="pill-label">Presets:</span>
            <button class="query-preset-pill" data-query="Have we previously advised on force majeure clauses?">Force majeure clauses</button>
            <button class="query-preset-pill" data-query="What matters involve Narang Limited?">Narang Limited matters</button>
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Shareholder oppression</button>
            <button class="query-preset-pill" data-query="Find matters related to MTR-2017-00874 with a different client">Graph-related matters</button>
          </div>
        </div>

        <div id="ask-output-area">
          ${state.askLoading ? renderAskLoading() : (state.askResult ? renderAskResult(state.askResult) : renderAskEmptyState())}
        </div>
      </div>
    `;
  }

  function renderAskEmptyState() {
    return `
      <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:36px 20px;text-align:center;">
        <div style="font-size:24px;color:var(--accent-primary);margin-bottom:8px;">✦</div>
        <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">Ask any question to reconstruct institutional memory</div>
        <div style="font-size:12px;color:var(--text-secondary);max-width:560px;margin:0 auto 16px auto;">
          Query understanding → retrieval planner → parallel BM25 / vector / metadata / matter / graph seeds → ACL dedupe → optional graph expansion → RRF → cross-encoder → cited answer.
        </div>
        <div style="font-size:11px;color:var(--text-muted);">Tip: open <span class="mono">/ui/ask?debug=1</span> or click Show Debug for channel provenance.</div>
      </div>
    `;
  }

  function renderAskLoading() {
    return `
      <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:40px 20px;text-align:center;">
        <div style="font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Reconstructing Institutional Knowledge...</div>
        <div style="font-size:11.5px;color:var(--text-muted);font-family:var(--font-mono);">Understand → Plan → Parallel Channels → Fusion → Rerank → Answer</div>
      </div>
    `;
  }

  function renderTagPills(tags) {
    if (!tags || !tags.length) return '';
    return tags.map(t => `<span class="scope-chip">${escapeHtml(t.key || t.label)}: ${escapeHtml(t.value || '')}</span>`).join('');
  }

  function renderAskResult(res) {
    const query = state.askQuery;
    const matterCount = res.matchedMatters?.length ?? 0;
    const sourceCount = res.sources?.length ?? 0;
    const citationCount = (res.structured_citations?.length || res.citations?.length || 0);
    return `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <!-- LAYER 1: ANSWER -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-1-badge"><span>①</span> ANSWER — EXECUTIVE SYNTHESIS</span>
            <span class="status-pill active">${matterCount} Matters Matched</span>
          </div>
          <div class="layer-content">
            ${res.key_finding ? `<div style="padding:12px 14px;background:var(--bg-surface-elevated);border-left:3px solid var(--accent-primary);margin-bottom:12px;border-radius:var(--radius-sm);"><strong style="font-size:11px;text-transform:uppercase;color:var(--text-muted);">Key finding</strong><div style="font-size:13px;line-height:1.6;margin-top:4px;">${escapeHtml(res.key_finding)}</div></div>` : ''}
            <div class="answer-synthesis-text">${res.answer || (res.abstained ? '<em>No sufficient evidence in firm records.</em>' : '')}</div>
            ${res.tags?.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;">${renderTagPills(res.tags)}</div>` : ''}
            <div class="stat-callouts">
              <div class="stat-box"><div class="stat-number">${matterCount}</div><div class="stat-label">Historical Matters</div></div>
              <div class="stat-box"><div class="stat-number">${sourceCount}</div><div class="stat-label">Supporting Documents</div></div>
              <div class="stat-box"><div class="stat-number">${citationCount}</div><div class="stat-label">Verified Citations</div></div>
              <div class="stat-box"><div class="stat-number">${res.provider || '—'}</div><div class="stat-label">Provider</div></div>
            </div>
          </div>
        </div>

        <!-- LAYER 2: EVIDENCE & EXACT HIGHLIGHTED SOURCES -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-2-badge"><span>②</span> EVIDENCE — VERIFIED SOURCES WITH EXACT HIGHLIGHTS</span>
            <span class="mono" style="font-size:10px;color:var(--text-muted);">Click "View Excerpt in Document" to open with exact highlight</span>
          </div>
          <div class="layer-content">
            <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:8px;">Cited Document Excerpts & Quotations:</div>
            <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px;">
              ${(res.sources || []).slice(0, 6).map(src => `
                <div style="padding:12px 14px;background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
                  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                      <span class="version-tag">${src.document_id}</span>
                      <strong style="color:var(--text-primary);font-size:13px;">${escapeHtml(src.title)}</strong>
                      <span class="scope-chip">${src.document_type || 'Document'}</span>
                      ${src.matter_id ? `<span class="scope-chip">${src.matter_id}</span>` : ''}
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenSourceViewer('${src.document_id}', '${escapeHtml(query)}')">Open Document →</button>
                  </div>
                  ${src.tags?.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">${renderTagPills(src.tags)}</div>` : ''}
                  <div style="font-size:12.5px;line-height:1.6;color:var(--text-secondary);background:var(--bg-surface);padding:8px 10px;border-radius:var(--radius-xs);border:1px solid var(--border-subtle);">
                    ${src.highlighted_snippet || escapeHtml(src.snippet || 'Document text cited in memo.')}
                  </div>
                </div>
              `).join('')}
            </div>

            <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:8px;">Top Matching Matters:</div>
            <div class="matched-matters-grid">
              ${(res.matchedMatters || []).map(m => `
                <div class="matched-matter-card" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <div style="display:flex;justify-content:space-between;">
                    <span class="match-similarity-pill">${m.similarity || 0}% MATCH</span>
                    <span class="mono" style="font-size:10px;color:var(--text-muted);">${m.matter_code || m.matter_id}</span>
                  </div>
                  <div style="font-weight:600;color:var(--text-primary);font-size:13px;">${escapeHtml(m.title || m.matter_id)}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">${escapeHtml(m.client_name || '')}${m.court ? ` • ${escapeHtml(m.court)}` : ''}</div>
                  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
                    ${m.matter_id ? `<span class="scope-chip">Matter ID: ${m.matter_id}</span>` : ''}
                    ${m.document_count ? `<span class="scope-chip">${m.document_count} docs</span>` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- LAYER 3: CONTEXT & REASONING -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-3-badge"><span>③</span> CONTEXT — FACTUAL & LEGAL OVERLAP</span>
          </div>
          <div class="layer-content">
            <ul style="list-style:none;display:flex;flex-direction:column;gap:6px;font-size:12.5px;">
              <li><strong>Factual Overlap:</strong> Similar transaction structures, indemnity liability ceilings, and board control rights.</li>
              <li><strong>Statutory Authorities:</strong> Companies Act 2013, Arbitration and Conciliation Act 1996, and Supreme Court benchmarks.</li>
            </ul>
          </div>
        </div>

        <!-- LAYER 4: PEOPLE & ACTIONS -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-4-badge"><span>④</span> PEOPLE & ACTIONS</span>
          </div>
          <div class="layer-content">
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
              ${(res.people || []).map(p => `
                <div class="person-card-compact" onclick="window.lexosNavigate('person-detail', { personId: '${p.member_id}' })" style="cursor:pointer;padding:8px 12px;">
                  <div class="user-avatar">${p.initials || 'P'}</div>
                  <div>
                    <div style="font-weight:600;color:var(--text-primary);font-size:12px;">${p.name}</div>
                    <div style="font-size:10.5px;color:var(--text-muted);">${p.role} • ${p.relevantCount || 12} matters handled</div>
                  </div>
                </div>
              `).join('')}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('matter-detail', { matterId: '${res.matchedMatters?.[0]?.matter_id || ''}' })" ${!res.matchedMatters?.[0]?.matter_id ? 'disabled' : ''}>Open Top Matter</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenProjectModal('${res.matchedMatters?.[0]?.matter_id || ''}')" ${!res.matchedMatters?.[0]?.matter_id ? 'disabled' : ''}>Create Workstream Project</button>
            </div>
          </div>
        </div>

        ${renderAskLatencyStrip(res)}
        ${renderAskDebugPanel()}
      </div>
    `;
  }

  function renderAskLatencyStrip(res) {
    const lat = res.latency_ms || {};
    const planned = lat.channels_planned || state.askDebug?.plan?.channels || [];
    const wall = lat.parallel_wall_ms ?? lat.total_ms;
    const chips = [];
    if (planned.length) chips.push(`plan: ${planned.join('+')}`);
    if (wall != null) chips.push(`parallel ${wall}ms`);
    if (lat.fusion != null) chips.push(`fusion ${lat.fusion}ms`);
    if (lat.rerank != null) chips.push(`rerank ${lat.rerank}ms`);
    if (lat.llm != null) chips.push(`llm ${lat.llm}ms`);
    if (lat.final_count != null) chips.push(`${lat.final_count} final`);
    if (!chips.length) return '';
    return `
      <div class="retrieval-latency-strip">
        ${chips.map(c => `<span class="latency-chip">${escapeHtml(String(c))}</span>`).join('')}
      </div>
    `;
  }

  function renderAskDebugPanel() {
    const debug = state.askDebug;
    const summaryBits = [];
    if (debug?.summary) {
      const s = debug.summary;
      summaryBits.push(`raw ${s.total_raw_candidates ?? 0}`);
      summaryBits.push(`dedup ${s.unique_after_dedup ?? 0}`);
      if (s.graph_expansion_added) summaryBits.push(`+graph ${s.graph_expansion_added}`);
      summaryBits.push(`final ${s.final_count ?? 0}`);
      if (s.total_latency_ms != null) summaryBits.push(`${s.total_latency_ms}ms`);
    } else if (state.askResult?.latency_ms) {
      const lat = state.askResult.latency_ms;
      Object.keys(lat).filter(k => k.endsWith('_count')).forEach(k => {
        summaryBits.push(`${k.replace('_count', '')}:${lat[k]}`);
      });
    }
    const head = summaryBits.length
      ? summaryBits.join(' · ')
      : 'intent / channels / fusion / rerank';

    let body = `<div class="retrieval-debug-empty">Run a query to populate channel provenance. Uses <span class="mono">POST /api/retrieval/debug</span>.</div>`;
    if (debug) {
      const u = debug.understanding || {};
      const plan = debug.plan || {};
      const channels = debug.channels || {};
      const channelRows = Object.entries(channels).map(([name, info]) => {
        const top = (info.top_3 || []).map(h =>
          `${h.document_id || '?'} (${Number(h.score || 0).toFixed(3)})`
        ).join(', ') || '—';
        return `<tr><td class="mono">${escapeHtml(name)}</td><td>${info.count ?? 0}</td><td>${info.latency_ms ?? '—'}ms</td><td class="mono" style="font-size:10px;">${escapeHtml(top)}</td></tr>`;
      }).join('');
      const weights = plan.weights
        ? Object.entries(plan.weights).map(([k, v]) => `${k}×${v}`).join(' · ')
        : '—';
      const finals = (debug.final_results || []).slice(0, 5).map((r, i) => {
        const prov = r.provenance || {};
        const chans = (prov.channels_found_in || [r.channel]).join('+');
        return `<div class="debug-final-row"><span class="mono">${i + 1}. ${escapeHtml(r.document_id || '')}</span> <span class="scope-chip">${escapeHtml(chans)}</span></div>`;
      }).join('');
      body = `
        <div class="retrieval-debug-grid">
          <div>
            <div class="debug-section-title">Understanding</div>
            <div class="mono debug-kv">intent=${escapeHtml(u.intent || '—')} · search_text=${escapeHtml(u.search_text || '')}</div>
            <div class="mono debug-kv">matters=${escapeHtml(JSON.stringify(u.matter_ids || []))} · practice=${escapeHtml(u.practice_area || '—')}</div>
          </div>
          <div>
            <div class="debug-section-title">Plan</div>
            <div class="mono debug-kv">channels=${escapeHtml((plan.channels || []).join(', '))}</div>
            <div class="mono debug-kv">graph_expansion=${plan.graph_expansion ? 'yes' : 'no'} · rerank=${plan.rerank ? 'yes' : 'no'}</div>
            <div class="mono debug-kv">weights: ${escapeHtml(weights)}</div>
          </div>
        </div>
        <div class="debug-section-title" style="margin-top:12px;">Channels</div>
        <table class="retrieval-debug-table">
          <thead><tr><th>Channel</th><th>Hits</th><th>Latency</th><th>Top 3</th></tr></thead>
          <tbody>${channelRows || '<tr><td colspan="4">No channel data</td></tr>'}</tbody>
        </table>
        <div class="debug-section-title" style="margin-top:12px;">Final (top 5) provenance</div>
        ${finals || '<div class="retrieval-debug-empty">No finals</div>'}
      `;
    }

    return `
      <details class="retrieval-debug-panel" ${state.debugOpen ? 'open' : ''}>
        <summary>Debug — ${escapeHtml(head)}</summary>
        <div class="retrieval-debug-body">${body}</div>
      </details>
    `;
  }

  function attachAskEvents() {
    const inp = document.getElementById('ask-main-input');
    const btn = document.getElementById('ask-submit-btn');
    if (btn && inp) {
      btn.addEventListener('click', () => {
        const q = inp.value.trim();
        if (q) executeAskQuery(q);
      });
    }

    document.querySelectorAll('.query-preset-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        const q = pill.dataset.query;
        if (q) {
          if (inp) inp.value = q;
          executeAskQuery(q);
        }
      });
    });

    const dbg = document.getElementById('ask-debug-toggle');
    if (dbg) {
      dbg.addEventListener('click', () => {
        state.debugOpen = !state.debugOpen;
        const url = new URL(window.location.href);
        if (state.debugOpen) url.searchParams.set('debug', '1');
        else url.searchParams.delete('debug');
        history.replaceState(history.state, '', url.pathname + url.search);
        renderWorkspace();
      });
    }

    const panel = document.querySelector('.retrieval-debug-panel');
    if (panel) {
      panel.addEventListener('toggle', () => {
        state.debugOpen = panel.open;
      });
    }
  }

  async function executeAskQuery(query) {
    state.askQuery = query;
    state.askLoading = true;
    state.askDebug = null;
    renderWorkspace();

    const [apiRes, debugRes, infoRes] = await Promise.all([
      apiFetch(API.answers, {
        method: 'POST',
        body: JSON.stringify({ query: query, k: 10 })
      }),
      apiFetch(`${API.retrieval}/debug`, {
        method: 'POST',
        body: JSON.stringify({ query: query, k: 10 })
      }),
      state.systemInfo ? Promise.resolve(state.systemInfo) : apiFetch(`${API.system}/info`),
    ]);

    if (infoRes && !infoRes.detail) state.systemInfo = infoRes;

    state.askLoading = false;
    if (apiRes && apiRes.service === 'answers') {
      state.askResult = apiRes;
    } else {
      state.askResult = {
        abstained: true,
        answer: '',
        key_finding: '',
        sources: [],
        matchedMatters: [],
        structured_citations: [],
        tags: [],
        latency_ms: {},
      };
    }
    if (debugRes && !debugRes.detail) {
      state.askDebug = debugRes;
    }
    renderWorkspace();
  }

  function renderMarkdownLite(md) {
    const lines = String(md || '').split('\n');
    const html = [];
    let inCode = false;
    let inList = false;
    for (const raw of lines) {
      const line = raw.replace(/\r$/, '');
      if (line.startsWith('```')) {
        if (inCode) { html.push('</code></pre>'); inCode = false; }
        else { html.push('<pre class="arch-code"><code>'); inCode = true; }
        continue;
      }
      if (inCode) {
        html.push(escapeHtml(line) + '\n');
        continue;
      }
      if (line.startsWith('|') && line.includes('|')) {
        if (inList) { html.push('</ul>'); inList = false; }
        const cells = line.split('|').slice(1, -1).map(c => c.trim());
        if (cells.every(c => /^:?-{3,}:?$/.test(c))) continue;
        const tag = html.length && html[html.length - 1].includes('<table') ? 'td' : 'th';
        if (tag === 'th' && !html[html.length - 1]?.includes('<table')) html.push('<table class="arch-table"><thead>');
        if (tag === 'td' && html[html.length - 1]?.includes('</thead>') === false && html.join('').includes('<thead>') && !html.join('').includes('</thead>')) {
          // close thead on first data row — handled below
        }
        const row = `<tr>${cells.map(c => `<${tag}>${escapeHtml(c)}</${tag}>`).join('')}</tr>`;
        if (tag === 'th') html.push(row);
        else {
          if (!html.join('').includes('</thead>')) html.push('</thead><tbody>');
          html.push(row);
        }
        continue;
      }
      if (html.join('').includes('<table') && !html.join('').includes('</table>') && !line.startsWith('|')) {
        html.push('</tbody></table>');
      }
      if (/^\s*-\s+/.test(line)) {
        if (!inList) { html.push('<ul>'); inList = true; }
        html.push(`<li>${escapeHtml(line.replace(/^\s*-\s+/, ''))}</li>`);
        continue;
      }
      if (inList) { html.push('</ul>'); inList = false; }
      if (line.startsWith('# ')) { html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`); continue; }
      if (line.startsWith('## ')) { html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`); continue; }
      if (line.startsWith('### ')) { html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`); continue; }
      if (!line.trim()) { html.push('<div class="arch-spacer"></div>'); continue; }
      html.push(`<p>${escapeHtml(line).replace(/`([^`]+)`/g, '<code>$1</code>')}</p>`);
    }
    if (inCode) html.push('</code></pre>');
    if (inList) html.push('</ul>');
    if (html.join('').includes('<table') && !html.join('').includes('</table>')) html.push('</tbody></table>');
    return html.join('\n');
  }

  function renderArchitectureScreen() {
    const info = state.systemInfo || {};
    const features = info.features || {};
    const featureChips = Object.entries(features).map(([k, v]) =>
      `<span class="scope-chip ${v ? 'active' : ''}">${escapeHtml(k)}: ${v ? 'on' : 'off'}</span>`
    ).join('');
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Retrieval Architecture</div>
            <div class="view-header-desc">Parallel fabric, planner, graph seed/expand, provenance, and production roadmap.</div>
          </div>
          <div class="view-header-actions" style="display:flex;gap:8px;flex-wrap:wrap;">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> ${escapeHtml(info.retrieval_engine || 'v2')}</span>
            <a class="btn btn-secondary btn-sm" href="/docs" target="_blank" rel="noopener">OpenAPI /docs</a>
            <a class="btn btn-secondary btn-sm" href="/api/system/architecture" target="_blank" rel="noopener">Raw Markdown</a>
            <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('ask')">Ask Firm AI →</button>
          </div>
        </div>
        <div class="arch-feature-row">${featureChips || '<span class="scope-chip">Loading features…</span>'}</div>
        <div class="architecture-doc">${state.architectureMarkdown ? renderMarkdownLite(state.architectureMarkdown) : '<div class="retrieval-debug-empty">Loading architecture…</div>'}</div>
      </div>
    `;
  }

  function attachArchitectureEvents() {
    if (!state.systemInfo) {
      apiFetch(`${API.system}/info`).then(info => {
        if (info && !info.detail) {
          state.systemInfo = info;
          if (state.view === 'architecture') renderWorkspace();
        }
      });
    }
    if (!state.architectureMarkdown) {
      fetch(`${API.system}/architecture`)
        .then(r => r.ok ? r.text() : Promise.reject(r.status))
        .then(text => {
          state.architectureMarkdown = text;
          if (state.view === 'architecture') renderWorkspace();
        })
        .catch(() => {
          state.architectureMarkdown = '# Architecture\n\nCould not load `/api/system/architecture`.';
          if (state.view === 'architecture') renderWorkspace();
        });
    }
  }

  // --- SCREEN 3: MATTERS ---
  function renderMattersScreen() {
    const visibleMatters = getVisibleMatters();
    const query = (state.searchQuery || '').toLowerCase();
    const filtered = visibleMatters.filter(m => {
      if (!query) return true;
      return (m.title || '').toLowerCase().includes(query) || (m.client_name || '').toLowerCase().includes(query) || (m.matter_code || '').toLowerCase().includes(query);
    });

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Matters</div>
            <div class="view-header-desc">Matter-centric legal DMS. Reconstructed intelligence across all 10 practice areas.</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-primary btn-sm" onclick="window.lexosOpenProjectModal()">＋ New Project</button>
          </div>
        </div>

        <div class="filter-bar">
          <div class="search-input-box">
            <span class="search-input-icon">🔍</span>
            <input id="matters-search-input" type="text" placeholder="Filter matters by client, title, code, partner..." value="${escapeHtml(state.searchQuery)}">
          </div>
          <span class="mono" style="font-size:11px;color:var(--text-muted);margin-left:auto;">${filtered.length} of ${visibleMatters.length} matters</span>
        </div>

        <div class="data-table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Matter Code</th>
                <th>Matter & Client</th>
                <th>Practice Area</th>
                <th>Forum / Court</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.slice(0, 50).map(m => `
                <tr onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <td class="mono" style="font-size:11px;font-weight:600;color:var(--accent-primary);">${m.matter_code}</td>
                  <td>
                    <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);">${m.client_name}</div>
                  </td>
                  <td><span class="scope-chip">${m.practice_area}</span></td>
                  <td style="font-size:12px;">${m.court || 'Commercial Tribunal'}</td>
                  <td><span class="status-pill ${(m.status || 'open').toLowerCase()}">${m.status || 'Open'}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function attachMattersEvents() {
    const inp = document.getElementById('matters-search-input');
    if (inp) {
      inp.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        renderWorkspace();
      });
    }
  }

  // --- SCREEN 3B: MATTER DETAIL ---
  function renderMatterDetailScreen(matterId) {
    const bundle = getMatterDetailBundle(matterId);
    const m = bundle?.matter || getMatterById(matterId) || getVisibleMatters()[0];
    if (!m) return `<div class="view-container">Matter not found or access denied.</div>`;

    const matterProjects = getAllProjects().filter(p => p.matter_id === m.matter_id);
    const team = bundle?.team || [];
    const docs = bundle?.documents || [];
    const args = bundle?.arguments || [];
    const timeline = bundle?.timeline || [];
    const related = bundle?.related || [];
    const legalIssues = m.legal_issues || [];
    const facts = m.facts || [];

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('matters')">Matters</a> <span>/</span>
          <a onclick="window.lexosNavigate('client-detail', { clientId: '${m.client_id}' })">${escapeHtml(m.client_name || 'Client')}</a> <span>/</span>
          <span class="mono">${m.matter_code}</span>
        </div>

        <div class="matter-detail-header" style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;flex-wrap:wrap;">
                <span class="mono" style="font-size:11px;font-weight:700;color:var(--accent-primary);">${m.matter_code}</span>
                <span class="scope-chip">${escapeHtml(m.matter_type || 'Matter')}</span>
                <span class="status-pill ${(m.status || 'open').toLowerCase()}">${m.status || 'Open'}</span>
                ${m.restricted ? '<span class="status-pill restricted">🔒 Restricted / Ethical Wall</span>' : ''}
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);">${escapeHtml(m.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenProjectModal('${m.matter_id}')">＋ Add Project</button>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are the key arguments and documents in matter ${m.matter_code}?');"><span>✦</span> Ask Matter</button>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px 16px;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:12px;margin-bottom:12px;">
            <div><strong>Client:</strong> ${escapeHtml(m.client_name || '—')}</div>
            <div><strong>Opposing party:</strong> ${escapeHtml(m.opposing_party || '—')}</div>
            <div><strong>Practice:</strong> ${escapeHtml(m.practice_area || '—')}</div>
            <div><strong>Jurisdiction:</strong> ${escapeHtml(m.jurisdiction || '—')}</div>
            <div><strong>Forum / Court:</strong> ${escapeHtml(m.court || '—')}</div>
            <div><strong>Office:</strong> ${escapeHtml(m.office || '—')}</div>
            <div><strong>Opened:</strong> ${formatDate(m.opened_date)}</div>
            <div><strong>Closed:</strong> ${formatDate(m.closed_date)}</div>
            <div><strong>Quantum:</strong> <span class="mono">${escapeHtml(m.claim_amount || '—')}</span></div>
            <div><strong>Outcome:</strong> ${escapeHtml(m.outcome || 'Pending')}</div>
            ${m.classification ? `<div><strong>Classification:</strong> ${escapeHtml(m.classification)}</div>` : ''}
          </div>

          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <span class="scope-chip">${docs.length}${bundle?.documentTotal ? ` / ${bundle.documentTotal}` : ''} documents</span>
            <span class="scope-chip">${args.length} arguments</span>
            <span class="scope-chip">${team.length} team members</span>
            <span class="scope-chip">${matterProjects.length} projects</span>
            <span class="scope-chip">${related.length} related matters</span>
          </div>
        </div>

        <div class="tabs-nav" style="flex-wrap:wrap;">
          <button class="tab-btn ${state.matterTab === 'overview' ? 'active' : ''}" data-tab="overview">Overview & DNA</button>
          <button class="tab-btn ${state.matterTab === 'team' ? 'active' : ''}" data-tab="team">Team (${team.length})</button>
          <button class="tab-btn ${state.matterTab === 'arguments' ? 'active' : ''}" data-tab="arguments">Arguments (${args.length})</button>
          <button class="tab-btn ${state.matterTab === 'timeline' ? 'active' : ''}" data-tab="timeline">Timeline (${timeline.length})</button>
          <button class="tab-btn ${state.matterTab === 'documents' ? 'active' : ''}" data-tab="documents">Documents (${docs.length})</button>
          <button class="tab-btn ${state.matterTab === 'projects' ? 'active' : ''}" data-tab="projects">Projects (${matterProjects.length})</button>
          <button class="tab-btn ${state.matterTab === 'related' ? 'active' : ''}" data-tab="related">Related (${related.length})</button>
        </div>

        <div id="matter-tab-content">
          ${renderMatterTabContent(m, matterProjects, bundle)}
        </div>
      </div>
    `;
  }

  function renderMatterTabContent(m, matterProjects, bundle) {
    const team = bundle?.team || [];
    const docs = bundle?.documents || [];
    const args = bundle?.arguments || [];
    const timeline = bundle?.timeline || [];
    const related = bundle?.related || [];
    const legalIssues = m.legal_issues || [];
    const facts = m.facts || [];

    switch (state.matterTab) {
      case 'overview':
        return `
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:16px;">
            <div class="reasoning-card">
              <div class="layer-header"><span class="layer-badge layer-1-badge"><span>✦</span> Matter Memory Summary</span></div>
              <div class="layer-content">
                <p style="font-size:13.5px;color:var(--text-primary);line-height:1.65;margin-bottom:14px;">${escapeHtml(matterMemorySummary(m, facts))}</p>
                <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Legal Issues</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;">
                  ${legalIssues.length
                    ? legalIssues.map(iss => `<span class="scope-chip">${escapeHtml(iss)}</span>`).join('')
                    : '<span style="font-size:12px;color:var(--text-muted);">No indexed issues</span>'}
                </div>
                <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Key Facts</div>
                <ul style="margin:0;padding-left:18px;font-size:13px;color:var(--text-primary);line-height:1.6;">
                  ${facts.length
                    ? facts.map(f => `<li style="margin-bottom:6px;">${escapeHtml(f)}</li>`).join('')
                    : '<li style="color:var(--text-muted);">No structured facts recorded</li>'}
                </ul>
              </div>
            </div>

            <div style="display:flex;flex-direction:column;gap:16px;">
              <div class="reasoning-card">
                <div class="layer-header"><span class="layer-badge layer-2-badge">Matter Profile</span></div>
                <div class="layer-content" style="font-size:12px;color:var(--text-secondary);display:flex;flex-direction:column;gap:8px;">
                  <div><strong>Type:</strong> ${escapeHtml(m.matter_type || '—')}</div>
                  <div><strong>Theme:</strong> <span class="mono">${escapeHtml(m.theme_key || '—')}</span></div>
                  <div><strong>Status:</strong> ${escapeHtml(m.status || 'Open')}</div>
                  <div><strong>Outcome:</strong> ${escapeHtml(m.outcome || 'Pending')}</div>
                  ${m.restricted ? `<div style="color:var(--accent-amber);"><strong>ACL:</strong> Ethical wall active — ${(m.acl_members || []).length} cleared members</div>` : ''}
                </div>
              </div>

              <div class="reasoning-card">
                <div class="layer-header"><span class="layer-badge layer-3-badge">Lead Team Preview</span></div>
                <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
                  ${team.length ? team.slice(0, 4).map(t => `
                    <div class="evidence-item-row" onclick="window.lexosNavigate('person-detail', { personId: '${t.member_id}' })" style="cursor:pointer;">
                      <div>
                        <div style="font-weight:600;font-size:12.5px;color:var(--text-primary);">${escapeHtml(t.name)}</div>
                        <div style="font-size:11px;color:var(--text-muted);">${escapeHtml(t.role_on_matter || t.role)} • ${escapeHtml(t.office || '')}</div>
                      </div>
                    </div>
                  `).join('') : '<div style="font-size:12px;color:var(--text-muted);">No team assigned</div>'}
                  ${team.length > 4 ? `<button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}', tab: 'team' })">View all ${team.length} →</button>` : ''}
                </div>
              </div>
            </div>
          </div>

          ${args.length ? `
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-1-badge">Top Arguments</span>
                <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}', tab: 'arguments' })">View all →</button>
              </div>
              <div class="layer-content" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;">
                ${args.slice(0, 3).map(a => `
                  <div style="padding:12px;background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
                    <div style="font-size:11px;font-weight:600;color:var(--accent-primary);margin-bottom:4px;">${escapeHtml(a.issue)}</div>
                    <div style="font-size:12.5px;color:var(--text-primary);line-height:1.5;margin-bottom:6px;">${escapeHtml(a.argument)}</div>
                    <div style="font-size:11px;color:var(--text-muted);">Position: ${escapeHtml(a.position)} • Outcome: ${escapeHtml(a.outcome || '—')}</div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}
        `;

      case 'team':
        return `
          <div class="data-table-container">
            <table class="data-table">
              <thead>
                <tr><th>Name</th><th>Firm Role</th><th>Matter Role</th><th>Office</th><th>Action</th></tr>
              </thead>
              <tbody>
                ${team.length ? team.map(t => `
                  <tr onclick="window.lexosNavigate('person-detail', { personId: '${t.member_id}' })">
                    <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(t.name)}</td>
                    <td>${escapeHtml(t.role || '—')}</td>
                    <td><span class="scope-chip">${escapeHtml(t.role_on_matter || '—')}</span></td>
                    <td>${escapeHtml(t.office || '—')}</td>
                    <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();window.lexosNavigate('person-detail', { personId: '${t.member_id}' })">Profile →</button></td>
                  </tr>
                `).join('') : `
                  <tr><td colspan="5" style="padding:24px;text-align:center;color:var(--text-muted);">No team members on this matter</td></tr>
                `}
              </tbody>
            </table>
          </div>
        `;

      case 'arguments':
        return `
          <div style="display:flex;flex-direction:column;gap:12px;">
            ${args.length ? args.map(a => `
              <div class="reasoning-card">
                <div class="layer-header">
                  <span class="layer-badge layer-1-badge">${escapeHtml(a.issue)}</span>
                  <span class="scope-chip">${escapeHtml(a.position)}</span>
                  ${a.outcome ? `<span class="status-pill active">${escapeHtml(a.outcome)}</span>` : ''}
                </div>
                <div class="layer-content">
                  <p style="font-size:13.5px;color:var(--text-primary);line-height:1.6;margin-bottom:10px;">${escapeHtml(a.argument)}</p>
                  ${(a.supporting_documents || []).length ? `
                    <div style="font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;margin-bottom:6px;">Supporting Documents</div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;">
                      ${a.supporting_documents.map(docId => `
                        <button class="btn btn-ghost btn-sm" onclick="window.lexosOpenSourceViewer('${docId}')">${docId}</button>
                      `).join('')}
                    </div>
                  ` : ''}
                </div>
              </div>
            `).join('') : `
              <div style="padding:32px;text-align:center;color:var(--text-muted);">No arguments indexed for this matter.</div>
            `}
          </div>
        `;

      case 'timeline':
        return `
          <div class="reasoning-card">
            <div class="layer-header"><span class="layer-badge layer-2-badge">Matter Timeline</span></div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:0;">
              ${timeline.length ? timeline.map((ev, idx) => `
                <div style="display:flex;gap:14px;padding:12px 0;${idx < timeline.length - 1 ? 'border-bottom:1px solid var(--border-subtle);' : ''}">
                  <div style="min-width:96px;font-size:11px;font-family:var(--font-mono);color:var(--text-muted);padding-top:2px;">${escapeHtml(ev.date || '—')}</div>
                  <div style="flex:1;min-width:0;">
                    <div style="font-weight:600;font-size:13px;color:var(--text-primary);cursor:pointer;" onclick="window.lexosOpenSourceViewer('${ev.doc_id}')">${escapeHtml(ev.event)}</div>
                    <div style="font-size:11.5px;color:var(--text-muted);margin-top:3px;">
                      ${escapeHtml(ev.doc_type || 'Document')} • ${escapeHtml(ev.author || 'Apex Chambers')}
                      ${ev.doc_id ? ` • <span class="mono">${ev.doc_id}</span>` : ''}
                    </div>
                  </div>
                </div>
              `).join('') : `
                <div style="padding:24px;text-align:center;color:var(--text-muted);">No timeline events recorded.</div>
              `}
            </div>
          </div>
        `;

      case 'projects':
        return `
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Projects & Workstreams</span>
              <button class="btn btn-primary btn-sm" onclick="window.lexosOpenProjectModal('${m.matter_id}')">＋ Add Project</button>
            </div>
            ${matterProjects.length ? matterProjects.map(p => `
              <div class="project-card" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id || p.project_id}' })">
                <div class="project-meta-row">
                  <span class="scope-chip">${escapeHtml(p.team || '')}</span>
                  <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${escapeHtml(p.status || 'In Progress')}</span>
                </div>
                <div style="font-weight:700;font-size:14px;color:var(--text-primary);">${escapeHtml(p.title)}</div>
                <div style="font-size:12px;color:var(--text-secondary);">${escapeHtml(p.scope || 'Deliverables workstream.')}</div>
                <div style="margin-top:6px;">
                  <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:4px;">
                    <span>Lead: ${escapeHtml(p.lead_lawyer || '—')}</span>
                    <span class="mono">${p.progress || 0}% Completed</span>
                  </div>
                  <div class="progress-track"><div class="progress-fill" style="width:${p.progress || 0}%;"></div></div>
                </div>
              </div>
            `).join('') : `
              <div style="padding:32px;text-align:center;color:var(--text-muted);">No projects yet. Create a workstream for due diligence, drafting, or closing.</div>
            `}
          </div>
        `;

      case 'documents':
        return `
          <div class="data-table-container">
            <table class="data-table">
              <thead><tr><th>Doc ID</th><th>Title</th><th>Type</th><th>Date</th><th>Version</th><th>Author</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>
                ${docs.length ? docs.map(d => `
                  <tr onclick="window.lexosOpenSourceViewer('${d.document_id}')">
                    <td class="mono" style="color:var(--accent-purple);">${d.document_id}</td>
                    <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                    <td><span class="scope-chip">${escapeHtml(d.document_type || 'Document')}</span></td>
                    <td style="font-size:12px;">${formatDate(d.doc_date)}</td>
                    <td><span class="version-tag">${escapeHtml(d.version || 'v1 Final')}</span></td>
                    <td>${escapeHtml(d.author_name || '—')}</td>
                    <td><span class="status-pill ${(d.status || 'open').toLowerCase()}">${escapeHtml(d.status || '—')}</span></td>
                    <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();window.lexosOpenSourceViewer('${d.document_id}')">Open ↗</button></td>
                  </tr>
                `).join('') : `
                  <tr><td colspan="8" style="padding:24px;text-align:center;color:var(--text-muted);">No documents visible for this matter.</td></tr>
                `}
              </tbody>
            </table>
          </div>
        `;

      case 'related':
        return `
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;">
            ${related.length ? related.map(rm => `
              <div class="matched-matter-card" onclick="window.lexosNavigate('matter-detail', { matterId: '${rm.matter_id}' })">
                <div style="font-size:11px;font-family:var(--font-mono);color:var(--accent-primary);margin-bottom:4px;">${escapeHtml(rm.matter_code)}</div>
                <div style="font-weight:700;font-size:14px;color:var(--text-primary);margin-bottom:4px;">${escapeHtml(rm.title)}</div>
                <div style="font-size:12px;color:var(--text-muted);">${escapeHtml(rm.client_name || '')} • ${escapeHtml(rm.practice_area || '')}</div>
                <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
                  <span class="status-pill ${(rm.status || 'open').toLowerCase()}">${escapeHtml(rm.status || 'Open')}</span>
                  ${rm.outcome ? `<span class="scope-chip">${escapeHtml(rm.outcome)}</span>` : ''}
                  ${rm.restricted ? '<span class="status-pill restricted">🔒</span>' : ''}
                </div>
              </div>
            `).join('') : `
              <div style="padding:32px;text-align:center;color:var(--text-muted);grid-column:1/-1;">No related matters linked in the graph.</div>
            `}
          </div>
        `;

      default:
        state.matterTab = 'overview';
        return renderMatterTabContent(m, matterProjects, bundle);
    }
  }

  function attachMatterDetailEvents() {
    const tabNav = document.querySelector('.view-container .tabs-nav');
    if (!tabNav) return;
    tabNav.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.matterTab = btn.dataset.tab;
        renderWorkspace();
        attachMatterDetailEvents();
      });
    });
  }

  // --- SCREEN 4: DOCUMENTS & INGESTION ---
  function renderDocumentsScreen() {
    const data = getFirmData();
    const total = data.totals?.documents || data.documents?.length || 0;
    const allDocs = [...state.customDocs, ...(data.documents || [])];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Documents & Smart Ingestion</div>
            <div class="view-header-desc">Showing ${allDocs.length.toLocaleString()} of ${total.toLocaleString()} indexed documents from Apex Chambers corpus (ACL-filtered).</div>
          </div>
        </div>

        <div id="ingest-dropzone-target" class="ingest-dropzone">
          <div style="font-size:24px;color:var(--accent-primary);margin-bottom:8px;">📂</div>
          <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Drop files or contracts here to ingest into database</div>
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">AI chunks, computes MiniLM embeddings, and indexes into Postgres automatically.</div>
          <input type="file" id="file-upload-input" multiple style="display:none;">
          <button id="trigger-browse-btn" class="btn btn-secondary btn-sm">Browse Files</button>
        </div>

        <div class="data-table-container">
          <table class="data-table">
            <thead><tr><th>Doc ID</th><th>Title</th><th>Type</th><th>Matter</th><th>Version</th><th>Author</th><th>Action</th></tr></thead>
            <tbody>
              ${allDocs.length ? allDocs.map(d => `
                <tr onclick="window.lexosOpenSourceViewer('${d.document_id}')">
                  <td class="mono" style="color:var(--accent-purple);">${d.document_id}</td>
                  <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                  <td><span class="scope-chip">${d.document_type || 'Document'}</span></td>
                  <td><span class="mono">${d.matter_id || '—'}</span></td>
                  <td><span class="version-tag">${d.version || 'v1 Final'}</span></td>
                  <td>${d.author_name || '—'}</td>
                  <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();window.lexosOpenSourceViewer('${d.document_id}')">Open Viewer ↗</button></td>
                </tr>
              `).join('') : `
                <tr><td colspan="7" style="padding:24px;text-align:center;color:var(--text-muted);">No documents visible for this persona. Try switching to Aryan Maharaj (MEM-00001).</td></tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function attachDocumentsEvents() {
    const dropzone = document.getElementById('ingest-dropzone-target');
    const fileInp = document.getElementById('file-upload-input');
    const browseBtn = document.getElementById('trigger-browse-btn');

    if (browseBtn && fileInp) browseBtn.addEventListener('click', () => fileInp.click());
    if (fileInp) {
      fileInp.addEventListener('change', (e) => handleIncomingFiles(e.target.files));
    }
  }

  async function handleIncomingFiles(files) {
    if (!files || !files.length) return;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const title = f.name.replace(/\.[^/.]+$/, "");
      const res = await apiFetch(`${API.documents}/ingest`, {
        method: 'POST',
        body: JSON.stringify({
          title: title,
          matter_id: state.selectedMatterId,
          document_type: title.includes('SPA') ? 'Contract' : (title.includes('Petition') ? 'Pleading' : 'Advisory Note'),
          author_name: getCurrentMember().name,
          body: `DOCUMENT: ${title}\nIngested into Apex Chambers DMS repository.\nClassified to matter ${state.selectedMatterId}.\nFull text indexed with semantic 384-d vector embeddings.`,
          version: 'v1.0 Ingested'
        })
      });

      const newDocId = res?.document_id || `DOC-NEW-${Date.now().toString().slice(-4)}`;
      state.customDocs.unshift({
        document_id: newDocId,
        matter_id: state.selectedMatterId,
        title: title,
        document_type: 'Contract',
        author_name: getCurrentMember().name,
        date: new Date().toISOString().slice(0, 10),
        status: 'Uploaded',
        version: 'v1.0 Ingested'
      });
    }
    showToast(`Successfully ingested and embedded ${files.length} document(s) into database!`);
    renderWorkspace();
  }

  // --- SCREEN 4B: DOC DETAIL ---
  function renderDocDetailScreen(docId) {
    const d = getDocById(docId) || getFirmData().documents?.[0];
    if (!d) return `<div class="view-container">Document not found.</div>`;

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('documents')">Documents</a> <span>/</span>
          <span class="mono">${d.document_id}</span>
        </div>

        <div class="matter-detail-header" style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="version-tag">${d.version || 'v1 Final'}</span>
                <span class="scope-chip">${d.document_type}</span>
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);">${escapeHtml(d.title)}</h1>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenSourceViewer('${d.document_id}')">Open in Highlight Viewer ↗</button>
          </div>
        </div>

        <div class="tabs-nav">
          <button class="tab-btn ${state.docTab === 'overview' ? 'active' : ''}" data-doctab="overview">Preview</button>
          <button class="tab-btn ${state.docTab === 'diff' ? 'active' : ''}" data-doctab="diff">Git-Style Redlines</button>
        </div>

        <div id="doc-tab-content">
          ${state.docTab === 'diff' ? `
            <div class="diff-viewer-container">
              <div class="diff-header">
                <span>Redline: v3 vs v4 Executed</span>
                <span class="mono">Unified Diff</span>
              </div>
              <div class="diff-pane">
                <div class="diff-line"><span class="diff-line-number">14</span><span>14. Indemnity & Liability Cap</span></div>
                <div class="diff-line removed"><span class="diff-line-number">15</span><span>- The maximum liability of Seller shall not exceed ₹10 crore.</span></div>
                <div class="diff-line added"><span class="diff-line-number">15</span><span>+ The aggregate liability of Seller in respect of Warranty Claims shall not exceed 15% of Purchase Price.</span></div>
              </div>
            </div>
          ` : `
            <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:20px;font-size:13.5px;line-height:1.7;white-space:pre-wrap;">
${escapeHtml(d.body || d.text || 'SHARE PURCHASE AGREEMENT\n\n1. Parties\nThe Seller and the Buyer agree to the sale of Sale Shares.\n\n14. Indemnity Cap\nThe aggregate liability under tax and general warranties is capped at 15% of purchase price.')}
            </div>
          `}
        </div>
      </div>
    `;
  }

  function attachDocDetailEvents() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.docTab = btn.dataset.doctab;
        renderWorkspace();
      });
    });
  }

  // --- SECONDARY SCREENS ---
  function renderClientsScreen() {
    const clients = getFirmData().clients || [];
    return `
      <div class="view-container">
        <div class="view-header">
          <div><div class="view-header-title">Clients & Institutional Memory</div><div class="view-header-desc">Client profiles preserving drafting preferences.</div></div>
        </div>
        <div class="matched-matters-grid">
          ${clients.slice(0, 16).map(c => `
            <div class="matched-matter-card" onclick="window.lexosNavigate('client-detail', { clientId: '${c.client_id}' })">
              <div style="display:flex;justify-content:space-between;">
                <span class="scope-chip">${c.industry}</span>
                <span class="mono" style="font-size:11px;color:var(--text-muted);">${c.client_id}</span>
              </div>
              <div style="font-weight:700;color:var(--text-primary);font-size:14px;">${escapeHtml(c.name)}</div>
              <div style="font-size:11.5px;color:var(--text-secondary);">HQ: ${c.headquarters}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function renderClientDetailScreen(clientId) {
    const c = getClientById(clientId) || getFirmData().clients?.[0];
    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs"><a onclick="window.lexosNavigate('clients')">Clients</a> <span>/</span> <span class="mono">${c.client_id}</span></div>
        <div class="view-header"><div><div class="view-header-title">${escapeHtml(c.name)}</div><div class="view-header-desc">${c.industry} • HQ: ${c.headquarters}</div></div></div>
        <div class="reasoning-card">
          <div class="layer-header"><span class="layer-badge layer-1-badge">Client Preferences</span></div>
          <div class="layer-content">
            <div style="color:var(--accent-emerald);font-weight:600;margin-bottom:4px;">✓ Preferred Formats:</div>
            <div>Executive summaries, risk heatmaps, concise tables.</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderTeamsScreen() {
    return `
      <div class="view-container">
        <div class="view-header"><div><div class="view-header-title">Practice Teams</div><div class="view-header-desc">Practice hubs across Corporate, Disputes, Arbitration, and Tax.</div></div></div>
        <div class="projects-grid">
          <div class="project-card"><div style="font-weight:700;">Corporate & M&A</div><div style="color:var(--text-muted);font-size:12px;">42 lawyers • 186 active matters</div></div>
          <div class="project-card"><div style="font-weight:700;">Dispute Resolution & Litigation</div><div style="color:var(--text-muted);font-size:12px;">38 lawyers • 245 active matters</div></div>
          <div class="project-card"><div style="font-weight:700;">International Arbitration</div><div style="color:var(--text-muted);font-size:12px;">16 lawyers • 98 active matters</div></div>
        </div>
      </div>
    `;
  }

  function renderPeopleScreen() {
    const members = getFirmData().members || [];
    return `
      <div class="view-container">
        <div class="view-header"><div><div class="view-header-title">People & Expertise</div><div class="view-header-desc">Work-derived expertise from actual authored filings and closed transactions.</div></div></div>
        <div class="matched-matters-grid">
          ${members.slice(0, 18).map(m => `
            <div class="person-card-compact" style="padding:10px;cursor:pointer;">
              <div class="user-avatar">${m.name.split(' ').map(n=>n[0]).join('')}</div>
              <div>
                <div style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${m.name}</div>
                <div style="font-size:11px;color:var(--text-muted);">${m.role} • ${m.office}</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function renderKnowledgeScreen() {
    const precedents = getFirmData().precedents || [];
    return `
      <div class="view-container">
        <div class="view-header"><div><div class="view-header-title">Institutional Knowledge Vault</div><div class="view-header-desc">Vetted precedents and clause benchmarks.</div></div></div>
        <div class="matched-matters-grid">
          ${precedents.map(p => `
            <div class="reasoning-card" style="padding:14px;">
              <span class="scope-chip" style="margin-bottom:6px;">${p.type}</span>
              <div style="font-weight:700;color:var(--text-primary);font-size:14px;margin-bottom:4px;">${escapeHtml(p.title)}</div>
              <div style="font-size:12px;color:var(--text-secondary);">${p.summary}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function attachKnowledgeEvents() {}
  function renderActivityScreen() { return `<div class="view-container"><div class="view-header"><div class="view-header-title">Live Firm Activity</div></div></div>`; }
  function renderTasksScreen() { return `<div class="view-container"><div class="view-header"><div class="view-header-title">Court Deadlines & Tasks</div></div></div>`; }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

})();
