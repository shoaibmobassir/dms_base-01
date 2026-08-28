/**
 * LEXOS / FIRMOS — Enterprise Legal Institutional Memory & DMS
 * Luxury Minimalist SPA Architecture (Apple Pro / Porsche Design Aesthetic)
 * Multi-Project & Workstream Support
 */

(function() {
  'use strict';

  // --- APPLICATION STATE ---
  const state = {
    view: 'home',
    selectedMatterId: 'MTR-2019-00001',
    selectedProjectId: 'PRJ-2024-002',
    selectedDocId: 'DOC-00004',
    selectedClientId: 'CLI-00055',
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
    scopeFilter: 'all',
    projectStatusFilter: 'all',
    searchQuery: '',
    paletteOpen: false,
    paletteIndex: 0,
    projectModalOpen: false,
    ingestPending: [],
    customDocs: [],
    customProjects: []
  };

  // DOM Loaded Entry
  document.addEventListener('DOMContentLoaded', () => {
    initApp();
  });

  function initApp() {
    applyTheme(state.theme);
    setupEventListeners();
    setupCommandPalette();
    setupProjectModal();
    setupPersonaSwitcher();
    navigate('home');
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

  // --- NAVIGATION CONTROLLER ---
  function navigate(view, params = {}) {
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

    // Update active nav item in sidebar
    document.querySelectorAll('.nav-item').forEach(el => {
      const v = el.dataset.view;
      el.classList.toggle('active', v === view || (view.startsWith(v) && view.includes('-detail')));
    });

    renderWorkspace();
    renderRightPane();
    window.scrollTo(0, 0);
  }

  window.lexosNavigate = navigate;

  // --- DATA ACCESS & ACL ---
  function getFirmData() {
    return window.FIRM_DATA || { matters: [], clients: [], members: [], documents: [], arguments: [], clauses: [], precedents: [], projects: [] };
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
    const allowed = matter.allowed_members || [];
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
    return getAllProjects().find(p => p.id === id);
  }

  function getMatterById(id) {
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
    sel.addEventListener('change', (e) => {
      state.persona = e.target.value;
      const mem = getCurrentMember();
      showToast(`Switched active persona to ${mem.name || 'Restricted Persona'}`);
      
      const av = document.getElementById('sidebar-user-avatar');
      const un = document.getElementById('sidebar-user-name');
      const ur = document.getElementById('sidebar-user-role');
      if (av && mem.name) av.innerText = mem.name.split(' ').map(n=>n[0]).join('');
      if (un) un.innerText = mem.name || 'Outside Counsel';
      if (ur) ur.innerText = `${mem.role || 'Restricted'} • ${mem.office || 'Global'}`;

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

  // --- TOAST SYSTEM ---
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
        { title: 'SPA Negotiation & Locked-Box Structuring', cat: 'PROJECT', action: () => navigate('project-detail', { projectId: 'PRJ-2024-002' }) },
        { title: 'Legal Due Diligence & Red Flag Review', cat: 'PROJECT', action: () => navigate('project-detail', { projectId: 'PRJ-2024-001' }) },
        { title: 'Singh-Srinivas Holdings — Share Purchase Agreement', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2019-00001' }) },
        { title: 'ABC Holdings — Shareholder Dispute (Bombay HC)', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2020-00045' }) },
        { title: 'Master Share Purchase Agreement (Locked-Box)', cat: 'PRECEDENT', action: () => navigate('knowledge', { tab: 'precedents' }) }
      ];
    } else {
      getAllProjects().forEach(p => {
        if (p.title.toLowerCase().includes(query) || (p.client_name || '').toLowerCase().includes(query) || (p.team || '').toLowerCase().includes(query)) {
          matches.push({ title: `${p.title} (${p.team})`, cat: 'PROJECT', action: () => navigate('project-detail', { projectId: p.id }) });
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

    if (!matches.length) {
      results.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">No matching entities found. Press Enter to ask AI.</div>`;
      return;
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

  function openProjectModal(prefillMatterId = null) {
    const overlay = document.getElementById('create-project-overlay');
    const matterSelect = document.getElementById('new-project-matter');
    const leadSelect = document.getElementById('new-project-lead');
    if (!overlay || !matterSelect || !leadSelect) return;

    // Populate matters
    const visibleMatters = getVisibleMatters();
    matterSelect.innerHTML = visibleMatters.map(m => `
      <option value="${m.matter_id}" ${prefillMatterId === m.matter_id ? 'selected' : ''}>${escapeHtml(m.title)} (${m.matter_code})</option>
    `).join('');

    // Populate leads
    const members = getFirmData().members || [];
    leadSelect.innerHTML = members.map(mem => `
      <option value="${mem.name}">${mem.name} (${mem.role} - ${mem.office})</option>
    `).join('');

    // Set default deadline 30 days ahead
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

  function handleCreateProjectSubmit() {
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
    const parentMatter = getMatterById(matterId) || getVisibleMatters()[0];
    const team = teamSelect ? teamSelect.value : 'Corporate & M&A';
    const lead = leadSelect ? leadSelect.value : getCurrentMember().name;
    const deadline = deadlineInp ? deadlineInp.value : '2024-12-31';
    const scope = scopeInp ? scopeInp.value.trim() : 'Project deliverables and legal strategy defined.';
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

    const newProjId = `PRJ-${Date.now().toString().slice(-4)}`;
    const newProject = {
      id: newProjId,
      matter_id: parentMatter.matter_id,
      matter_code: parentMatter.matter_code,
      matter_title: parentMatter.title,
      client_id: parentMatter.client_id,
      client_name: parentMatter.client_name,
      title: title,
      team: team,
      lead_lawyer: lead,
      status: 'In Progress',
      progress: 25,
      deadline: deadline,
      quantum: parentMatter.claim_amount || '—',
      scope: scope,
      milestones: milestones,
      documents_count: 2,
      doc_ids: ['DOC-00004']
    };

    state.customProjects.unshift(newProject);
    closeProjectModal();
    showToast(`Created project "${title}" in ${parentMatter.matter_code}`);
    navigate('project-detail', { projectId: newProjId });
  }

  // --- WORKSPACE ROUTER ---
  function renderWorkspace() {
    const ws = document.getElementById('app-workspace');
    if (!ws) return;

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
        ws.innerHTML = renderMatterDetailScreen(state.selectedMatterId);
        attachMatterDetailEvents();
        break;
      case 'projects':
        ws.innerHTML = renderProjectsScreen();
        attachProjectsEvents();
        break;
      case 'project-detail':
        ws.innerHTML = renderProjectDetailScreen(state.selectedProjectId);
        attachProjectDetailEvents();
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
        attachClientsEvents();
        break;
      case 'client-detail':
        ws.innerHTML = renderClientDetailScreen(state.selectedClientId);
        attachClientDetailEvents();
        break;
      case 'teams':
        ws.innerHTML = renderTeamsScreen();
        break;
      case 'people':
        ws.innerHTML = renderPeopleScreen();
        break;
      case 'person-detail':
        ws.innerHTML = renderPersonDetailScreen(state.selectedPersonId);
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
      const p = getProjectById(state.selectedProjectId);
      if (p) {
        content = `
          <div class="inspector-header">
            <span class="inspector-title"><span>✦</span> Project Intelligence</span>
            <span class="kbd-shortcut">${p.id}</span>
          </div>
          <div class="inspector-body">
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
              <div style="font-size:10.5px;font-weight:600;color:var(--accent-primary);margin-bottom:3px;">ACTIVE WORKSTREAM</div>
              <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${escapeHtml(p.title)}</div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Lead: ${p.lead_lawyer} • Team: ${p.team}</div>
            </div>

            <div>
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Ask AI about this project:</div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <input id="proj-copilot-input" type="text" placeholder="e.g. What deliverables are outstanding?" style="flex:1;height:30px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0 8px;font-size:12px;color:var(--text-primary);outline:none;">
                <button id="proj-copilot-btn" class="btn btn-primary btn-sm">Ask</button>
              </div>
              <div id="proj-copilot-answers" style="font-size:11.5px;color:var(--text-secondary);line-height:1.5;background:var(--bg-surface);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);min-height:70px;">
                Ready to analyze scope, milestones, and documents scoped to <strong>${escapeHtml(p.title)}</strong>.
              </div>
            </div>

            <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Parent Matter Context</div>
              <div style="padding:8px 10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);font-size:11.5px;cursor:pointer;" onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })">
                <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(p.matter_title || p.matter_code)}</div>
                <div style="font-size:10.5px;color:var(--text-muted);">${p.client_name}</div>
              </div>
            </div>
          </div>
        `;
      }
    } else if (state.view === 'matter-detail' && state.selectedMatterId) {
      const m = getMatterById(state.selectedMatterId);
      if (m) {
        content = `
          <div class="inspector-header">
            <span class="inspector-title"><span>✦</span> Matter Assistant</span>
            <span class="kbd-shortcut">${m.matter_code || 'MATTER'}</span>
          </div>
          <div class="inspector-body">
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
              <div style="font-size:10.5px;font-weight:600;color:var(--accent-primary);margin-bottom:3px;">MATTER CONTEXT</div>
              <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${m.client_name} • ${m.court || m.practice_area}</div>
            </div>

            <div>
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Ask about this matter:</div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <input id="matter-copilot-input" type="text" placeholder="e.g. What arguments did we use?" style="flex:1;height:30px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0 8px;font-size:12px;color:var(--text-primary);outline:none;">
                <button id="matter-copilot-btn" class="btn btn-primary btn-sm">Ask</button>
              </div>
              <div id="matter-copilot-answers" style="font-size:11.5px;color:var(--text-secondary);line-height:1.5;background:var(--bg-surface);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);min-height:70px;">
                AI scoped to 14 documents, arguments, and timelines for this matter.
              </div>
            </div>
          </div>
        `;
      }
    } else {
      const summary = getFirmData().summary || { total_matters: 1000, total_documents: 38232, total_clients: 500, total_arguments: 20456 };
      content = `
        <div class="inspector-header">
          <span class="inspector-title"><span>✦</span> Apex Institutional Memory</span>
          <span class="kbd-shortcut">APEX</span>
        </div>
        <div class="inspector-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--text-primary);">${summary.total_matters || 1000}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Matters</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-primary);">${getAllProjects().length}</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Active Projects</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-emerald);">38,232</div>
              <div style="font-size:9.5px;color:var(--text-muted);text-transform:uppercase;">Indexed Docs</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-purple);">20,456</div>
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
        projAns.innerHTML = `<span style="color:var(--accent-primary)">✦ Analyzing project workstream...</span>`;
        setTimeout(() => {
          projAns.innerHTML = `<div style="color:var(--text-primary);font-weight:600;margin-bottom:3px;">Findings:</div><div style="color:var(--text-secondary);">3 of 4 milestones completed. The final deliverable requires General Counsel signoff on escrow retention terms.</div>`;
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

        <!-- Fast Ask Input Hero Box -->
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
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Minority oppression disputes</button>
            <button class="query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">SIAC emergency relief</button>
            <button class="query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">M&A indemnity cap precedent</button>
          </div>
        </div>

        <!-- 2 Grid Work Columns: Active Projects & Active Matters -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(340px, 1fr));gap:16px;margin-bottom:24px;">
          <!-- Active Projects / Workstreams -->
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Active Projects & Workstreams</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('projects')">All Projects →</button>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
              ${activeProjects.map(p => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id}' })">
                  <div style="flex:1;min-width:0;">
                    <div style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${escapeHtml(p.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${p.client_name} • ${p.team} • Lead: ${p.lead_lawyer}</div>
                  </div>
                  <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.progress}%</span>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- Active Matters -->
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
                    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${m.client_name} • ${m.court || m.practice_area} • Lead: ${m.lead_partner}</div>
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

  // --- SCREEN: PROJECTS WORKSPACE (FIRST CLASS) ---
  function renderProjectsScreen() {
    const allProjects = getAllProjects();
    const query = (state.searchQuery || '').toLowerCase();
    const filtered = allProjects.filter(p => {
      if (state.projectStatusFilter !== 'all' && p.status.toLowerCase() !== state.projectStatusFilter.toLowerCase()) return false;
      if (!query) return true;
      return p.title.toLowerCase().includes(query) ||
             (p.client_name || '').toLowerCase().includes(query) ||
             (p.team || '').toLowerCase().includes(query) ||
             (p.lead_lawyer || '').toLowerCase().includes(query) ||
             (p.matter_title || '').toLowerCase().includes(query);
    });

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Projects & Workstreams</div>
            <div class="view-header-desc">Multi-disciplinary project management across M&A Due Diligence, Regulatory Clearances, Litigation workstreams, and Closing.</div>
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
            <div class="project-card" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id}' })">
              <div class="project-meta-row">
                <span class="scope-chip">${p.team}</span>
                <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.status}</span>
              </div>
              <div style="font-weight:700;font-size:14px;color:var(--text-primary);letter-spacing:-0.01em;">${escapeHtml(p.title)}</div>
              <div style="font-size:11.5px;color:var(--text-secondary);">
                ${p.client_name} • <span class="mono" style="color:var(--accent-primary);">${p.matter_code || 'Matter'}</span>
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
    const p = getProjectById(projectId) || getAllProjects()[0];
    if (!p) return `<div class="view-container">Project not found.</div>`;

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('projects')">Projects</a> <span>/</span>
          <a onclick="window.lexosNavigate('client-detail', { clientId: '${p.client_id}' })">${p.client_name}</a> <span>/</span>
          <a onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })">${p.matter_code || 'Matter'}</a> <span>/</span>
          <span class="mono">${p.id}</span>
        </div>

        <div class="matter-detail-header" style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="scope-chip">${p.team}</span>
                <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.status}</span>
                <span class="mono" style="font-size:11px;color:var(--text-muted);">${p.id}</span>
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);">${escapeHtml(p.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are the key findings and milestones in project ${p.id}?');"><span>✦</span> Ask Project AI</button>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('documents')">＋ Add Document</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:10px;">
            <div><strong>Client:</strong> ${p.client_name}</div>
            <div><strong>Parent Matter:</strong> <a onclick="window.lexosNavigate('matter-detail', { matterId: '${p.matter_id}' })" style="color:var(--accent-primary);cursor:pointer;">${escapeHtml(p.matter_title || p.matter_code)}</a></div>
            <div><strong>Lead Lawyer:</strong> ${p.lead_lawyer}</div>
            <div><strong>Deadline:</strong> <span class="mono">${p.deadline}</span></div>
            <div><strong>Progress:</strong> <span class="mono">${p.progress}%</span></div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
          <div style="display:flex;flex-direction:column;gap:16px;">
            <!-- Scope & Objectives -->
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-1-badge">Project Scope & Deliverables</span>
              </div>
              <div class="layer-content">
                <p style="font-size:13px;color:var(--text-primary);line-height:1.6;">${escapeHtml(p.scope || 'Comprehensive workstream management.')}</p>
              </div>
            </div>

            <!-- Milestones Checklist -->
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-2-badge">Interactive Milestones & Tasks</span>
                <span class="mono" style="font-size:10.5px;color:var(--text-muted);">${(p.milestones || []).filter(m=>m.done).length} of ${(p.milestones || []).length} Completed</span>
              </div>
              <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
                ${(p.milestones || []).map((m, idx) => `
                  <div class="milestone-item" onclick="window.toggleProjectMilestone('${p.id}', ${idx})">
                    <div style="display:flex;align-items:center;gap:10px;">
                      <input type="checkbox" class="milestone-checkbox" ${m.done ? 'checked' : ''} onclick="event.stopPropagation();window.toggleProjectMilestone('${p.id}', ${idx})">
                      <span style="font-size:12.5px;color:${m.done ? 'var(--text-muted)' : 'var(--text-primary)'};text-decoration:${m.done ? 'line-through' : 'none'};">${escapeHtml(m.title)}</span>
                    </div>
                    <span class="mono" style="font-size:10.5px;color:var(--text-muted);">${m.due}</span>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>

          <div style="display:flex;flex-direction:column;gap:16px;">
            <!-- Attached Documents -->
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-3-badge">Workstream Documents</span>
              </div>
              <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
                <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00004' })">
                  <div>
                    <div style="font-weight:600;font-size:12px;color:var(--text-primary);">Share Purchase Agreement (v4 Executed)</div>
                    <div style="font-size:10.5px;color:var(--text-muted);">Contract • Final</div>
                  </div>
                  <span class="kbd-shortcut">Open →</span>
                </div>
                <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00003' })">
                  <div>
                    <div style="font-weight:600;font-size:12px;color:var(--text-primary);">Due Diligence Red Flag Report</div>
                    <div style="font-size:10.5px;color:var(--text-muted);">Advisory • Alka Wable</div>
                  </div>
                  <span class="kbd-shortcut">Open →</span>
                </div>
              </div>
            </div>

            <!-- Team Allocation -->
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-4-badge">Staffed Team</span>
              </div>
              <div class="layer-content" style="font-size:12px;color:var(--text-secondary);">
                <div style="margin-bottom:8px;"><strong>Lead Partner:</strong> ${p.lead_lawyer}</div>
                <div style="margin-bottom:8px;"><strong>Practice Group:</strong> ${p.team}</div>
                <div><strong>Quantum / Value:</strong> <span class="mono">${p.quantum}</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function attachProjectDetailEvents() {}

  window.toggleProjectMilestone = function(projectId, milestoneIndex) {
    const p = getProjectById(projectId);
    if (!p || !p.milestones || !p.milestones[milestoneIndex]) return;
    p.milestones[milestoneIndex].done = !p.milestones[milestoneIndex].done;
    
    // Recalculate progress
    const total = p.milestones.length;
    const completed = p.milestones.filter(m => m.done).length;
    p.progress = Math.round((completed / total) * 100);
    if (p.progress === 100) p.status = 'Completed';
    else if (p.status === 'Completed') p.status = 'In Progress';

    showToast(`Updated milestone: "${p.milestones[milestoneIndex].title}"`);
    renderWorkspace();
    renderRightPane();
  };

  // --- SCREEN 2: ASK THE FIRM (4-LAYER REASONING) ---
  function renderAskScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Ask the Firm AI</div>
            <div class="view-header-desc">Natural-language institutional reasoning across 38,232 documents, 1,000 matters, and projects.</div>
          </div>
          <div class="view-header-actions">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> ACL Secured</span>
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
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Shareholder oppression dispute</button>
            <button class="query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">SIAC emergency relief</button>
            <button class="query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">M&A indemnity cap & locked-box</button>
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
        <div style="font-size:12px;color:var(--text-secondary);max-width:520px;margin:0 auto 16px auto;">
          LEXOS executes hybrid semantic retrieval, permission gating, cross-document reranking, and SQL graph synthesis.
        </div>
      </div>
    `;
  }

  function renderAskLoading() {
    return `
      <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:40px 20px;text-align:center;">
        <div style="font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Reconstructing Institutional Knowledge...</div>
        <div style="font-size:11.5px;color:var(--text-muted);font-family:var(--font-mono);">Query Understanding → ACL Verification → Hybrid RRF → Cross-Encoder Rerank</div>
      </div>
    `;
  }

  function renderAskResult(res) {
    return `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <!-- LAYER 1: ANSWER -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-1-badge"><span>①</span> ANSWER — EXECUTIVE SYNTHESIS</span>
            <span class="status-pill active">${res.matchCount || 7} Matters Matched</span>
          </div>
          <div class="layer-content">
            <div class="answer-synthesis-text">${res.answer}</div>
            <div class="stat-callouts">
              <div class="stat-box"><div class="stat-number">${res.matchCount || 7}</div><div class="stat-label">Historical Matters</div></div>
              <div class="stat-box"><div class="stat-number">${res.documentsCount || 23}</div><div class="stat-label">Supporting Documents</div></div>
              <div class="stat-box"><div class="stat-number">${res.authoritiesCount || 14}</div><div class="stat-label">Authorities</div></div>
              <div class="stat-box"><div class="stat-number">${res.winRate || '86%'}</div><div class="stat-label">Favorable / Settled</div></div>
            </div>
          </div>
        </div>

        <!-- LAYER 2: EVIDENCE -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-2-badge"><span>②</span> EVIDENCE — CLOSEST MATTERS & PLEADINGS</span>
          </div>
          <div class="layer-content">
            <div class="matched-matters-grid">
              ${(res.matchedMatters || []).map(m => `
                <div class="matched-matter-card" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <div style="display:flex;justify-content:space-between;">
                    <span class="match-similarity-pill">${m.similarity}% MATCH</span>
                    <span class="mono" style="font-size:10px;color:var(--text-muted);">${m.matter_code}</span>
                  </div>
                  <div style="font-weight:600;color:var(--text-primary);font-size:13px;">${escapeHtml(m.title)}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">${m.court} • ${m.date_range}</div>
                  <div style="font-size:11px;color:var(--text-muted);background:var(--bg-surface);padding:4px 6px;border-radius:var(--radius-xs);">
                    ${m.similarity_reason}
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
              ${(res.contextPoints || []).map(pt => `
                <li><strong>${escapeHtml(pt.title)}:</strong> ${escapeHtml(pt.desc)}</li>
              `).join('')}
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
                    <div style="font-size:10.5px;color:var(--text-muted);">${p.role} • ${p.relevantCount} matters</div>
                  </div>
                </div>
              `).join('')}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('matter-detail', { matterId: '${res.matchedMatters?.[0]?.matter_id || 'MTR-2019-00001'}' })">Open Top Matter</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenProjectModal('${res.matchedMatters?.[0]?.matter_id || 'MTR-2019-00001'}')">Create Workstream Project</button>
            </div>
          </div>
        </div>
      </div>
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
  }

  function executeAskQuery(query) {
    state.askQuery = query;
    state.askLoading = true;
    renderWorkspace();

    setTimeout(() => {
      state.askLoading = false;
      state.askResult = synthesizeReasoningResponse(query);
      renderWorkspace();
    }, 400);
  }

  function synthesizeReasoningResponse(query) {
    const q = query.toLowerCase();
    const visibleMatters = getVisibleMatters();

    if (q.includes('shareholder') || q.includes('oppression') || q.includes('minority')) {
      const m1 = visibleMatters.find(m => m.matter_id === 'MTR-2020-00045') || visibleMatters[0];
      const m2 = visibleMatters.find(m => m.matter_id === 'MTR-2021-00033') || visibleMatters[1];

      return {
        answer: "Yes. The firm has handled 7 matters with similar factual and legal characteristics concerning minority shareholder oppression, board mismanagement, and exit valuation disputes under Sections 241 and 242 of the Companies Act, 2013.",
        matchCount: 7,
        documentsCount: 23,
        authoritiesCount: 14,
        winRate: '86%',
        matchedMatters: [
          {
            matter_id: m1.matter_id,
            matter_code: m1.matter_code,
            title: 'ABC Holdings — Shareholder Dispute & Board Control',
            court: 'Bombay High Court / NCLT',
            date_range: '2023–2024',
            similarity: 86,
            similarity_reason: 'Identical claims of promoter siphoning and board exclusion.'
          },
          {
            matter_id: m2.matter_id,
            matter_code: m2.matter_code,
            title: 'XYZ Technologies — Minority Oppression & Pre-emption',
            court: 'NCLT Delhi',
            date_range: '2022–2023',
            similarity: 81,
            similarity_reason: 'Dispute over promoter share transfers breaching tag-along rights.'
          }
        ],
        contextPoints: [
          { title: 'Similar Shareholder Structure', desc: '40/60 promoter vs investor equity distribution.' },
          { title: 'Minority Oppression Claims', desc: 'Promoters passed unilateral resolutions stripping minority rights.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', initials: 'AM', relevantCount: 14 },
          { member_id: 'MEM-00002', name: 'Udant Dewan', role: 'Partner', initials: 'UD', relevantCount: 9 }
        ]
      };
    } else {
      const m = visibleMatters[0];
      return {
        answer: `Identified relevant institutional precedent records matching "${escapeHtml(query)}".`,
        matchCount: 5,
        documentsCount: 16,
        authoritiesCount: 8,
        winRate: '88%',
        matchedMatters: [
          {
            matter_id: m.matter_id,
            matter_code: m.matter_code,
            title: m.title,
            court: m.court || 'High Court',
            date_range: '2022–2024',
            similarity: 88,
            similarity_reason: 'Factual and legal alignment with query terms.'
          }
        ],
        contextPoints: [
          { title: 'Precedent Alignment', desc: 'Consistent with firm-wide positions approved by practice leads.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', initials: 'AM', relevantCount: 12 }
        ]
      };
    }
  }

  // --- SCREEN 3: MATTERS ---
  function renderMattersScreen() {
    const visibleMatters = getVisibleMatters();
    const query = (state.searchQuery || '').toLowerCase();
    const filtered = visibleMatters.filter(m => {
      if (!query) return true;
      return m.title.toLowerCase().includes(query) || (m.client_name || '').toLowerCase().includes(query) || (m.matter_code || '').toLowerCase().includes(query);
    });

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Matters</div>
            <div class="view-header-desc">Matter-centric legal DMS. Reconstructed intelligence across all 10 practice areas and 4 offices.</div>
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
                <th>Lead Partner</th>
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
                  <td>${m.lead_partner}</td>
                  <td><span class="status-pill ${m.status.toLowerCase()}">${m.status}</span></td>
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
    const m = getMatterById(matterId) || getVisibleMatters()[0];
    if (!m) return `<div class="view-container">Matter not found.</div>`;

    const matterProjects = getAllProjects().filter(p => p.matter_id === m.matter_id);

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('matters')">Matters</a> <span>/</span>
          <a onclick="window.lexosNavigate('client-detail', { clientId: '${m.client_id}' })">${m.client_name}</a> <span>/</span>
          <span class="mono">${m.matter_code}</span>
        </div>

        <div class="matter-detail-header" style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:18px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="mono" style="font-size:11px;font-weight:700;color:var(--accent-primary);">${m.matter_code}</span>
                <span class="status-pill ${m.status.toLowerCase()}">${m.status}</span>
                ${m.restricted ? '<span class="status-pill restricted">🔒 Restricted / Ethical Wall</span>' : ''}
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);">${escapeHtml(m.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosOpenProjectModal('${m.matter_id}')">＋ Add Project</button>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are the key arguments and documents in matter ${m.matter_code}?');"><span>✦</span> Ask Matter</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:10px;">
            <div><strong>Client:</strong> ${m.client_name}</div>
            <div><strong>Practice:</strong> ${m.practice_area}</div>
            <div><strong>Lead Partner:</strong> ${m.lead_partner}</div>
            <div><strong>Quantum:</strong> <span class="mono">${m.claim_amount || '—'}</span></div>
          </div>
        </div>

        <div class="tabs-nav">
          <button class="tab-btn ${state.matterTab === 'overview' ? 'active' : ''}" data-tab="overview">Overview & DNA</button>
          <button class="tab-btn ${state.matterTab === 'projects' ? 'active' : ''}" data-tab="projects">Projects / Workstreams (${matterProjects.length})</button>
          <button class="tab-btn ${state.matterTab === 'timeline' ? 'active' : ''}" data-tab="timeline">Matter Timeline</button>
          <button class="tab-btn ${state.matterTab === 'documents' ? 'active' : ''}" data-tab="documents">Documents (14)</button>
          <button class="tab-btn ${state.matterTab === 'graph' ? 'active' : ''}" data-tab="graph">Knowledge Graph</button>
        </div>

        <div id="matter-tab-content">
          ${renderMatterTabContent(m, matterProjects)}
        </div>
      </div>
    `;
  }

  function renderMatterTabContent(m, matterProjects) {
    switch (state.matterTab) {
      case 'overview':
        return `
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-1-badge"><span>✦</span> Matter Memory Summary</span>
              </div>
              <div class="layer-content">
                <p style="font-size:13.5px;color:var(--text-primary);line-height:1.6;margin-bottom:12px;">${m.ai_memory?.summary || 'Reconstructed institutional memory for this active matter.'}</p>
                <div style="font-size:11.5px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Legal Issues:</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">
                  ${(m.legal_issues || ['Indemnity cap', 'Locked-box leakage']).map(iss => `<span class="scope-chip">${iss}</span>`).join('')}
                </div>
              </div>
            </div>

            <div class="reasoning-card">
              <div class="layer-header">
                <span class="layer-badge layer-3-badge">Client Preferences</span>
              </div>
              <div class="layer-content" style="font-size:12px;color:var(--text-secondary);">
                <div style="color:var(--accent-emerald);font-weight:600;margin-bottom:4px;">✓ Preferred:</div>
                <div style="margin-bottom:8px;">Executive summaries, risk heatmaps, liability tables.</div>
              </div>
            </div>
          </div>
        `;
      case 'projects':
        return `
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Active Projects in this Matter:</span>
              <button class="btn btn-primary btn-sm" onclick="window.lexosOpenProjectModal('${m.matter_id}')">＋ Add Project</button>
            </div>
            ${matterProjects.map(p => `
              <div class="project-card" onclick="window.lexosNavigate('project-detail', { projectId: '${p.id}' })">
                <div class="project-meta-row">
                  <span class="scope-chip">${p.team}</span>
                  <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.status}</span>
                </div>
                <div style="font-weight:700;font-size:14px;color:var(--text-primary);">${escapeHtml(p.title)}</div>
                <div style="font-size:12px;color:var(--text-secondary);">${escapeHtml(p.scope || 'Deliverables workstream.')}</div>
                <div style="margin-top:6px;">
                  <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);margin-bottom:4px;">
                    <span>Lead: ${p.lead_lawyer}</span>
                    <span class="mono">${p.progress}% Completed</span>
                  </div>
                  <div class="progress-track"><div class="progress-fill" style="width:${p.progress}%;"></div></div>
                </div>
              </div>
            `).join('')}
          </div>
        `;
      case 'timeline':
        return `
          <div class="timeline-stream">
            ${(m.timeline || []).map(tl => `
              <div class="timeline-node">
                <div class="timeline-node-dot"></div>
                <div class="timeline-node-content">
                  <div class="timeline-date">${tl.date} • ${tl.author}</div>
                  <div class="timeline-event-title">${escapeHtml(tl.event)}</div>
                </div>
              </div>
            `).join('')}
          </div>
        `;
      case 'documents':
        const docs = (getFirmData().documents || []).slice(0, 6);
        return `
          <div class="data-table-container">
            <table class="data-table">
              <thead><tr><th>Doc ID</th><th>Title</th><th>Type</th><th>Version</th><th>Author</th><th>Date</th></tr></thead>
              <tbody>
                ${docs.map(d => `
                  <tr onclick="window.lexosNavigate('doc-detail', { docId: '${d.document_id}' })">
                    <td class="mono" style="color:var(--accent-purple);">${d.document_id}</td>
                    <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                    <td><span class="scope-chip">${d.document_type}</span></td>
                    <td><span class="version-tag">${d.version || 'v1 Final'}</span></td>
                    <td>${d.author_name}</td>
                    <td class="mono">${d.date}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      case 'graph':
        return `
          <div class="graph-canvas-container">
            <canvas id="matter-graph-canvas" class="graph-canvas"></canvas>
          </div>
        `;
      default:
        return `<div>Overview</div>`;
    }
  }

  function attachMatterDetailEvents() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.matterTab = btn.dataset.tab;
        renderWorkspace();
        if (state.matterTab === 'graph') {
          setTimeout(() => initMatterKnowledgeGraph(state.selectedMatterId), 100);
        }
      });
    });
  }

  // --- SCREEN 4: DOCUMENTS & INGESTION ---
  function renderDocumentsScreen() {
    const data = getFirmData();
    const allDocs = [...state.customDocs, ...(data.documents || []).slice(0, 50)];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Documents & Smart Ingestion</div>
            <div class="view-header-desc">AI auto-classification without tedious metadata forms.</div>
          </div>
        </div>

        <div id="ingest-dropzone-target" class="ingest-dropzone">
          <div style="font-size:24px;color:var(--accent-primary);margin-bottom:8px;">📂</div>
          <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Drop files, emails, or zip packages here</div>
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">AI extracts Client, Matter, Team, Doc Type, Authors, and Dates with high confidence.</div>
          <input type="file" id="file-upload-input" multiple style="display:none;">
          <button id="trigger-browse-btn" class="btn btn-secondary btn-sm">Browse Files</button>
        </div>

        <div class="data-table-container">
          <table class="data-table">
            <thead><tr><th>Doc ID</th><th>Title</th><th>Type</th><th>Matter</th><th>Version</th><th>Author</th><th>Date</th></tr></thead>
            <tbody>
              ${allDocs.map(d => `
                <tr onclick="window.lexosNavigate('doc-detail', { docId: '${d.document_id}' })">
                  <td class="mono" style="color:var(--accent-purple);">${d.document_id}</td>
                  <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                  <td><span class="scope-chip">${d.document_type}</span></td>
                  <td><span class="mono">${d.matter_id}</span></td>
                  <td><span class="version-tag">${d.version || 'v1 Final'}</span></td>
                  <td>${d.author_name}</td>
                  <td class="mono">${d.date}</td>
                </tr>
              `).join('')}
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

  function handleIncomingFiles(files) {
    if (!files || !files.length) return;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const newDocId = `DOC-UP-${Date.now().toString().slice(-4)}`;
      state.customDocs.unshift({
        document_id: newDocId,
        matter_id: state.selectedMatterId,
        title: f.name.replace(/\.[^/.]+$/, ""),
        document_type: 'Contract Draft',
        author_name: getCurrentMember().name,
        date: new Date().toISOString().slice(0, 10),
        status: 'Uploaded',
        version: 'v1.0 Ingested'
      });
    }
    showToast(`Ingested ${files.length} document(s) with AI classification.`);
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
            <button class="btn btn-secondary btn-sm" onclick="showToast('Exported redline package.')">Export Redline</button>
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
${escapeHtml(d.text || 'SHARE PURCHASE AGREEMENT\n\n1. Parties\nThe Seller and the Buyer agree to the sale of Sale Shares.\n\n14. Indemnity Cap\nThe aggregate liability under tax and general warranties is capped at 15% of purchase price.')}
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

  // --- SCREEN 5: CLIENTS ---
  function renderClientsScreen() {
    const clients = getFirmData().clients || [];
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Clients & Institutional Memory</div>
            <div class="view-header-desc">Client profiles preserving drafting preferences and historical positions.</div>
          </div>
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
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('clients')">Clients</a> <span>/</span>
          <span class="mono">${c.client_id}</span>
        </div>
        <div class="view-header">
          <div>
            <div class="view-header-title">${escapeHtml(c.name)}</div>
            <div class="view-header-desc">${c.industry} • HQ: ${c.headquarters}</div>
          </div>
        </div>
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

  // --- SECONDARY SCREENS ---
  function renderTeamsScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div><div class="view-header-title">Practice Teams</div><div class="view-header-desc">Practice hubs across Corporate, Disputes, Arbitration, and Tax.</div></div>
        </div>
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
        <div class="view-header">
          <div><div class="view-header-title">People & Expertise</div><div class="view-header-desc">Work-derived expertise from actual authored filings and closed transactions.</div></div>
        </div>
        <div class="matched-matters-grid">
          ${members.slice(0, 18).map(m => `
            <div class="person-card-compact" onclick="window.lexosNavigate('person-detail', { personId: '${m.member_id}' })" style="padding:10px;cursor:pointer;">
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

  function renderPersonDetailScreen(personId) {
    const m = getPersonById(personId) || getCurrentMember();
    return `
      <div class="view-container">
        <div class="view-header">
          <div><div class="view-header-title">${m.name}</div><div class="view-header-desc">${m.role} • ${m.office} Office</div></div>
        </div>
      </div>
    `;
  }

  function renderKnowledgeScreen() {
    const precedents = getFirmData().precedents || [];
    return `
      <div class="view-container">
        <div class="view-header">
          <div><div class="view-header-title">Institutional Knowledge Vault</div><div class="view-header-desc">Vetted precedents and clause market benchmarks.</div></div>
        </div>
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

  function renderActivityScreen() {
    return `<div class="view-container"><div class="view-header"><div class="view-header-title">Live Firm Activity</div></div></div>`;
  }

  function renderTasksScreen() {
    return `<div class="view-container"><div class="view-header"><div class="view-header-title">Court Deadlines & Tasks</div></div></div>`;
  }

  // --- KNOWLEDGE GRAPH RENDERER ---
  function initMatterKnowledgeGraph(matterId) {
    const canvas = document.getElementById('matter-graph-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;

    const m = getMatterById(matterId) || getVisibleMatters()[0];

    const nodes = [
      { id: 'matter', label: m.matter_code, color: '#3b82f6', radius: 18, x: canvas.width / 2, y: canvas.height / 2 },
      { id: 'client', label: m.client_name, color: '#10b981', radius: 14, x: canvas.width / 2 - 120, y: canvas.height / 2 - 80 },
      { id: 'lead', label: m.lead_partner, color: '#8b5cf6', radius: 13, x: canvas.width / 2 + 120, y: canvas.height / 2 - 80 },
      { id: 'doc1', label: 'SPA (v4)', color: '#a78bfa', radius: 11, x: canvas.width / 2 - 140, y: canvas.height / 2 + 70 },
      { id: 'arg1', label: 'Indemnity Cap', color: '#f59e0b', radius: 11, x: canvas.width / 2 + 130, y: canvas.height / 2 + 70 }
    ];

    const edges = [
      ['matter', 'client'],
      ['matter', 'lead'],
      ['matter', 'doc1'],
      ['matter', 'arg1'],
      ['doc1', 'arg1']
    ];

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = state.theme === 'dark' ? '#2a334d' : '#cbd5e1';
      ctx.lineWidth = 1.5;
      edges.forEach(([sId, tId]) => {
        const s = nodes.find(n => n.id === sId);
        const t = nodes.find(n => n.id === tId);
        if (s && t) {
          ctx.beginPath();
          ctx.moveTo(s.x, s.y);
          ctx.lineTo(t.x, t.y);
          ctx.stroke();
        }
      });

      nodes.forEach(n => {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();

        ctx.fillStyle = state.theme === 'dark' ? '#f1f5f9' : '#0f172a';
        ctx.font = '10px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(n.label, n.x, n.y + n.radius + 12);
      });
    }

    draw();
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

})();
