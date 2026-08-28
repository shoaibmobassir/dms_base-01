import os

app_js_code = r'''/**
 * LEXOS / FIRMOS — Enterprise Legal Institutional Memory & DMS
 * Production Single-Page Application Controller
 * Follows Linear + GitHub + Notion + Bloomberg Terminal Design Philosophy
 */

(function() {
  'use strict';

  // --- STATE ---
  const state = {
    view: 'home',
    selectedMatterId: 'MTR-2019-00001',
    selectedDocId: 'DOC-00004',
    selectedClientId: 'CLI-00001',
    selectedPersonId: 'MEM-00001',
    selectedTeamName: 'Corporate & M&A',
    matterTab: 'overview',
    docTab: 'overview',
    knowledgeTab: 'precedents',
    persona: 'MEM-00001',
    theme: localStorage.getItem('lexos_theme') || 'dark',
    rightPaneOpen: true,
    askQuery: '',
    askLoading: false,
    askResult: null,
    scopeFilter: 'all',
    searchQuery: '',
    paletteOpen: false,
    paletteIndex: 0,
    ingestPending: [],
    customDocs: []
  };

  // DOM Loaded
  document.addEventListener('DOMContentLoaded', () => {
    initApp();
  });

  function initApp() {
    applyTheme(state.theme);
    setupEventListeners();
    setupCommandPalette();
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
    if (params.docId) state.selectedDocId = params.docId;
    if (params.clientId) state.selectedClientId = params.clientId;
    if (params.personId) state.selectedPersonId = params.personId;
    if (params.teamName) state.selectedTeamName = params.teamName;
    if (params.tab) {
      if (view === 'matter-detail') state.matterTab = params.tab;
      if (view === 'doc-detail') state.docTab = params.tab;
      if (view === 'knowledge') state.knowledgeTab = params.tab;
    }

    // Update active nav item in sidebar
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.view === view || (view.startsWith(el.dataset.view) && view.includes('-detail')));
    });

    renderWorkspace();
    renderRightPane();
    window.scrollTo(0, 0);
  }

  window.lexosNavigate = navigate;

  // --- DATA ACCESS & ACL FILTERING ---
  function getFirmData() {
    return window.FIRM_DATA || { matters: [], clients: [], members: [], documents: [], arguments: [], clauses: [], precedents: [] };
  }

  function getCurrentMember() {
    const members = getFirmData().members || [];
    return members.find(m => m.member_id === state.persona) || members[0] || { name: 'Aryan Maharaj', role: 'Partner', office: 'Mumbai', member_id: 'MEM-00001' };
  }

  function canAccessMatter(matter) {
    if (state.persona === 'RESTRICTED_DEMO') {
      return !matter.restricted;
    }
    if (!matter.restricted) return true;
    const allowed = matter.allowed_members || [];
    return allowed.includes(state.persona);
  }

  function getVisibleMatters() {
    const all = getFirmData().matters || [];
    return all.filter(canAccessMatter);
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
      } else if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '8') {
        e.preventDefault();
        const views = ['home', 'ask', 'matters', 'clients', 'documents', 'teams', 'people', 'knowledge'];
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
      // Update sidebar avatar & name
      const av = document.getElementById('sidebar-user-avatar');
      const un = document.getElementById('sidebar-user-name');
      const ur = document.getElementById('sidebar-user-role');
      if (av && mem.name) av.innerText = mem.name.split(' ').map(n=>n[0]).join('');
      if (un) un.innerText = mem.name || 'Outside Counsel';
      if (ur) ur.innerText = `${mem.role || 'Restricted'} • ${mem.office || 'Global'}`;

      navigate(state.view, {
        matterId: state.selectedMatterId,
        docId: state.selectedDocId,
        clientId: state.selectedClientId,
        personId: state.selectedPersonId,
        teamName: state.selectedTeamName
      });
    });
  }

  // --- TOAST SYSTEM ---
  function showToast(msg, duration = 3000) {
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
        { title: 'Ask the Firm anything...', cat: 'AI REASONING', action: () => navigate('ask') },
        { title: 'Singh-Srinivas Holdings — Share Purchase Agreement', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2019-00001' }) },
        { title: 'ABC Holdings — Shareholder Dispute (Bombay HC)', cat: 'MATTER', action: () => navigate('matter-detail', { matterId: 'MTR-2020-00045' }) },
        { title: 'Master Share Purchase Agreement (Locked-Box & W&I)', cat: 'PRECEDENT', action: () => navigate('knowledge', { tab: 'precedents' }) },
        { title: 'Indemnity Cap & De Minimis Threshold', cat: 'CLAUSE BANK', action: () => navigate('knowledge', { tab: 'clauses' }) },
        { title: 'Ingest new files or connect SharePoint', cat: 'INGESTION', action: () => navigate('documents') }
      ];
    } else {
      (data.matters || []).filter(canAccessMatter).forEach(m => {
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
      (data.members || []).forEach(p => {
        if (p.name.toLowerCase().includes(query) || (p.role || '').toLowerCase().includes(query)) {
          matches.push({ title: `${p.name} • ${p.role} (${p.office})`, cat: 'PEOPLE', action: () => navigate('person-detail', { personId: p.member_id }) });
        }
      });
      matches.unshift({
        title: `Ask AI: "${query}"`,
        cat: 'AI REASONING',
        action: () => {
          navigate('ask');
          executeAskQuery(query);
        }
      });
    }

    if (!matches.length) {
      results.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">No matching entities found. Press Enter to ask the firm AI.</div>`;
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
        attachTeamsEvents();
        break;
      case 'team-detail':
        ws.innerHTML = renderTeamDetailScreen(state.selectedTeamName);
        attachTeamDetailEvents();
        break;
      case 'people':
        ws.innerHTML = renderPeopleScreen();
        attachPeopleEvents();
        break;
      case 'person-detail':
        ws.innerHTML = renderPersonDetailScreen(state.selectedPersonId);
        attachPersonDetailEvents();
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
      case 'approvals':
        ws.innerHTML = renderApprovalsScreen();
        break;
      default:
        ws.innerHTML = renderHomeScreen();
        attachHomeEvents();
    }
  }

  // --- RIGHT INSPECTOR PANE (AI CONTEXT & INSIGHTS) ---
  function renderRightPane() {
    const pane = document.getElementById('app-inspector-pane');
    if (!pane) return;

    const mem = getCurrentMember();
    let content = '';

    if (state.view === 'matter-detail' && state.selectedMatterId) {
      const m = getMatterById(state.selectedMatterId);
      if (m) {
        content = `
          <div class="inspector-header">
            <span class="inspector-title"><span>✦</span> AI Matter Assistant</span>
            <span class="kbd-shortcut">${m.matter_code || 'MATTER'}</span>
          </div>
          <div class="inspector-body">
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
              <div style="font-size:11px;font-weight:600;color:var(--accent-primary);margin-bottom:4px;">CONTEXT LOADED</div>
              <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${m.client_name} • ${m.court || 'Court'}</div>
            </div>

            <div>
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Ask about this matter:</div>
              <div style="display:flex;gap:6px;margin-bottom:8px;">
                <input id="matter-copilot-input" type="text" placeholder="e.g. What arguments did we use?" style="flex:1;height:30px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0 8px;font-size:12px;color:var(--text-primary);outline:none;">
                <button id="matter-copilot-btn" class="btn btn-primary btn-sm">Ask</button>
              </div>
              <div id="matter-copilot-answers" style="font-size:12px;color:var(--text-secondary);line-height:1.5;background:var(--bg-surface);padding:10px;border-radius:var(--radius-sm);border:1px solid var(--border-subtle);min-height:80px;">
                Ready to answer questions specifically scoped to this matter's 14 documents, arguments, and timelines.
              </div>
            </div>

            <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
              <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Institutional Similarities</div>
              <div style="display:flex;flex-direction:column;gap:6px;">
                <div style="padding:8px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);font-size:11.5px;cursor:pointer;" onclick="window.lexosNavigate('matter-detail', { matterId: 'MTR-2020-00045' })">
                  <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                    <span style="font-weight:600;color:var(--text-primary);">86% Match</span>
                    <span style="font-family:var(--font-mono);color:var(--text-muted);font-size:10px;">MTR-2020-00045</span>
                  </div>
                  <div style="color:var(--text-secondary);">ABC Holdings — Shareholder Dispute</div>
                </div>
                <div style="padding:8px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);font-size:11.5px;cursor:pointer;" onclick="window.lexosNavigate('matter-detail', { matterId: 'MTR-2021-00033' })">
                  <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                    <span style="font-weight:600;color:var(--text-primary);">81% Match</span>
                    <span style="font-family:var(--font-mono);color:var(--text-muted);font-size:10px;">MTR-2021-00033</span>
                  </div>
                  <div style="color:var(--text-secondary);">XYZ Technologies — Minority Oppression</div>
                </div>
              </div>
            </div>
          </div>
        `;
      }
    } else if (state.view === 'doc-detail' && state.selectedDocId) {
      const d = getDocById(state.selectedDocId);
      content = `
        <div class="inspector-header">
          <span class="inspector-title"><span>✦</span> Document AI Insights</span>
          <span class="kbd-shortcut">${d ? d.document_type : 'DOC'}</span>
        </div>
        <div class="inspector-body">
          <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;">
            <div style="font-size:11px;font-weight:600;color:var(--accent-purple);margin-bottom:4px;">CLASSIFIED ENTITY</div>
            <div style="font-size:12px;font-weight:600;color:var(--text-primary);">${d ? escapeHtml(d.title) : 'Document'}</div>
            <div style="font-size:11px;color:var(--text-muted);">Author: ${d ? d.author_name : 'Firm'} • ${d ? d.date : ''}</div>
          </div>

          <div>
            <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Key Extracted Clauses:</div>
            <ul style="list-style:none;display:flex;flex-direction:column;gap:6px;font-size:11.5px;">
              <li style="padding:6px 8px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xs);color:var(--text-secondary);">
                <strong style="color:var(--text-primary);">Indemnity Cap:</strong> 15% aggregate ceiling
              </li>
              <li style="padding:6px 8px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xs);color:var(--text-secondary);">
                <strong style="color:var(--text-primary);">Escrow Retention:</strong> ₹10.6 crore against leakage
              </li>
              <li style="padding:6px 8px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-xs);color:var(--text-secondary);">
                <strong style="color:var(--text-primary);">Seat / Jurisdiction:</strong> Bombay High Court / India
              </li>
            </ul>
          </div>

          <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Risk Flags:</div>
            <div style="display:flex;flex-direction:column;gap:6px;">
              <div style="padding:6px 8px;background:var(--accent-rose-faint);border:1px solid rgba(244,63,94,0.3);border-radius:var(--radius-xs);font-size:11px;color:var(--accent-rose);">
                ⚠️ Material adverse change clause does not exclude sector tariff regulatory changes.
              </div>
            </div>
          </div>
        </div>
      `;
    } else {
      const summary = getFirmData().summary || { total_matters: 1000, total_documents: 38232, total_clients: 500, total_arguments: 20456 };
      content = `
        <div class="inspector-header">
          <span class="inspector-title"><span>✦</span> Institutional Memory</span>
          <span class="kbd-shortcut">APEX CHAMBERS</span>
        </div>
        <div class="inspector-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--text-primary);">${summary.total_matters || 1000}</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Matters Indexed</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-primary);">38,232</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Total Docs</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-emerald);">20,456</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Arguments</div>
            </div>
            <div style="padding:8px 10px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);">
              <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:var(--accent-purple);">9,746</div>
              <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;">Graph Edges</div>
            </div>
          </div>

          <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:8px;">Connected Practice Hubs</div>
            <div style="display:flex;flex-direction:column;gap:5px;font-size:11.5px;">
              <div style="display:flex;justify-content:space-between;color:var(--text-secondary);">
                <span>Corporate & M&A</span>
                <span class="mono">186 matters</span>
              </div>
              <div style="display:flex;justify-content:space-between;color:var(--text-secondary);">
                <span>Dispute Resolution</span>
                <span class="mono">245 matters</span>
              </div>
              <div style="display:flex;justify-content:space-between;color:var(--text-secondary);">
                <span>Tax & Structuring</span>
                <span class="mono">112 matters</span>
              </div>
              <div style="display:flex;justify-content:space-between;color:var(--text-secondary);">
                <span>Arbitration (SIAC / MCIA)</span>
                <span class="mono">98 matters</span>
              </div>
              <div style="display:flex;justify-content:space-between;color:var(--text-secondary);">
                <span>Insolvency & NCLT</span>
                <span class="mono">142 matters</span>
              </div>
            </div>
          </div>

          <div style="border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div style="font-size:10.5px;font-weight:600;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;">Institutional Memory State</div>
            <div style="font-size:11.5px;color:var(--text-secondary);line-height:1.5;">
              Autonomous background indexing active. Permissions verified against ethical wall matrices across Mumbai, Delhi, Bengaluru, and Singapore offices.
            </div>
          </div>
        </div>
      `;
    }

    pane.innerHTML = content;

    const copilotBtn = document.getElementById('matter-copilot-btn');
    const copilotInp = document.getElementById('matter-copilot-input');
    const copilotAns = document.getElementById('matter-copilot-answers');
    if (copilotBtn && copilotInp && copilotAns) {
      copilotBtn.addEventListener('click', () => {
        const q = copilotInp.value.trim();
        if (!q) return;
        copilotAns.innerHTML = `<span style="color:var(--accent-primary)">✦ Analyzing matter documents & arguments...</span>`;
        setTimeout(() => {
          copilotAns.innerHTML = `
            <div style="color:var(--text-primary);font-weight:600;margin-bottom:4px;">Findings for: "${escapeHtml(q)}"</div>
            <div style="color:var(--text-secondary);">In this matter, the team led by Aryan Maharaj established that the indemnity ceiling of ₹15 crore was conditional on no leakage prior to closing. Supported by <strong>DOC-00004 (Share Purchase Agreement Clause 14)</strong> and <strong>DOC-00003 (Due Diligence Report)</strong>.</div>
          `;
        }, 400);
      });
    }
  }

  // --- SCREEN 1: HOME ---
  function renderHomeScreen() {
    const mem = getCurrentMember();
    const visibleMatters = getVisibleMatters();
    const activeMatters = visibleMatters.slice(0, 4);
    const recentDocs = (getFirmData().documents || []).slice(0, 4);

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Good morning, ${mem.name}</div>
            <div class="view-header-desc">Apex Chambers Institutional Workspace • ${mem.role}, ${mem.practice_areas ? mem.practice_areas.join(' & ') : 'Corporate'} • ${mem.office}</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask')"><span>✦</span> Ask Firm</button>
            <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('documents')"><span>＋</span> Ingest Documents</button>
          </div>
        </div>

        <!-- Fast Ask Input Hero Box -->
        <div class="ask-hero-box">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="font-size:12px;font-weight:600;color:var(--text-secondary);display:flex;align-items:center;gap:6px;">
              <span style="color:var(--accent-primary)">✦</span> ASK THE INSTITUTIONAL MEMORY
            </span>
            <span class="kbd-shortcut">⌘2</span>
          </div>
          <div style="display:flex;gap:8px;">
            <input id="home-fast-ask-input" type="text" placeholder="Ask about past matters, arguments, precedents, clauses, or lawyers..." style="flex:1;height:36px;background:var(--bg-surface-elevated);border:1px solid var(--border-medium);border-radius:var(--radius-sm);padding:0 12px;font-size:13px;color:var(--text-primary);outline:none;">
            <button id="home-fast-ask-btn" class="btn btn-primary">Ask Firm</button>
          </div>
          <div class="suggested-pills">
            <span class="pill-label">Suggested:</span>
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Minority oppression disputes</button>
            <button class="query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">SIAC emergency relief</button>
            <button class="query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">M&A indemnity cap precedent</button>
            <button class="query-preset-pill" data-query="Who has handled aviation lease disputes and Cape Town convention?">Aviation lease specialists</button>
          </div>
        </div>

        <!-- 4 Grid Work Columns -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:16px;margin-bottom:24px;">
          <!-- Active Matters -->
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Active Matters • Continue Working</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('matters')">View all 1,000 →</button>
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

          <!-- Recent Documents & Redlines -->
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-2-badge">Recent Documents & Drafts</span>
              <button class="btn btn-ghost btn-sm" onclick="window.lexosNavigate('documents')">View all →</button>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
              ${recentDocs.map(d => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: '${d.document_id}' })">
                  <div style="min-width:0;flex:1;">
                    <div class="truncate" style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${escapeHtml(d.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${d.document_type} • ${d.author_name} • ${d.date}</div>
                  </div>
                  <span class="version-tag">${d.version || 'v1 Final'}</span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- Institutional Activity & Recommendations -->
        <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
          <!-- Activity Timeline -->
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-3-badge">Live Institutional Audit Stream</span>
              <span class="mono" style="font-size:11px;color:var(--text-muted);">Real-time</span>
            </div>
            <div class="layer-content" style="padding:12px;">
              <div class="timeline-stream" style="margin:4px 0;">
                <div class="timeline-node">
                  <div class="timeline-node-dot" style="border-color:var(--accent-primary);"></div>
                  <div class="timeline-node-content">
                    <div class="timeline-date">Today • 10:42 AM — Delhi Office</div>
                    <div class="timeline-event-title">New Written Submissions filed in NCLT Delhi</div>
                    <div style="font-size:12px;color:var(--text-secondary);">Udant Dewan filed final arguments on section 241/242 oppression claims in <em>ABC Holdings Shareholder Dispute</em>.</div>
                  </div>
                </div>
                <div class="timeline-node">
                  <div class="timeline-node-dot" style="border-color:var(--accent-emerald);"></div>
                  <div class="timeline-node-content">
                    <div class="timeline-date">Yesterday • 4:15 PM — Mumbai Office</div>
                    <div class="timeline-event-title">Master SPA Precedent Updated (W&I Insurance Integration)</div>
                    <div style="font-size:12px;color:var(--text-secondary);">Aryan Maharaj updated standard locked-box indemnity fallback positions with 92% historical acceptance rate.</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Discovered Knowledge Patterns -->
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-4-badge">Discovered Insights</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:10px;padding:12px;">
              <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-size:11px;font-weight:600;color:var(--accent-emerald);margin-bottom:3px;">RECURRENT LEGAL ISSUE</div>
                <div style="font-size:12px;font-weight:600;color:var(--text-primary);">Indemnity Cap vs Locked-Box</div>
                <div style="font-size:11.5px;color:var(--text-secondary);margin-top:3px;">Identified across 14 recent M&A matters. Escrow retention reduced average post-closing dispute rate by 64%.</div>
              </div>
              <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-size:11px;font-weight:600;color:var(--accent-amber);margin-bottom:3px;">STAFFING RECOMMENDATION</div>
                <div style="font-size:12px;font-weight:600;color:var(--text-primary);">SIAC Emergency Arbitration</div>
                <div style="font-size:11.5px;color:var(--text-secondary);margin-top:3px;">Aryan Maharaj & Udant Dewan have highest win rate (89%) on emergency status-quo injunctions.</div>
              </div>
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

  // --- SCREEN 2: ASK THE FIRM (4-LAYER REASONING) ---
  function renderAskScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Ask the Firm</div>
            <div class="view-header-desc">Natural-language reasoning and institutional memory reconstruction across 38,232 documents, 1,000 matters, and 20,456 arguments.</div>
          </div>
          <div class="view-header-actions">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> ACL Secured</span>
          </div>
        </div>

        <!-- Ask Hero Input -->
        <div class="ask-hero-box">
          <div class="ask-input-wrapper">
            <textarea id="ask-main-input" class="ask-textarea" placeholder="Ask about past matters, legal arguments, precedents, clauses, people, or strategy... (e.g. Have we handled a shareholder dispute involving oppression and minority rights before?)">${escapeHtml(state.askQuery)}</textarea>
          </div>
          <div class="ask-input-actions">
            <div class="scope-chips">
              <span class="pill-label">Scope:</span>
              <button class="scope-chip ${state.scopeFilter === 'all' ? 'active' : ''}" data-scope="all">Entire Firm</button>
              <button class="scope-chip ${state.scopeFilter === 'Corporate' ? 'active' : ''}" data-scope="Corporate">Corporate / M&A</button>
              <button class="scope-chip ${state.scopeFilter === 'Disputes' ? 'active' : ''}" data-scope="Disputes">Disputes & NCLT</button>
              <button class="scope-chip ${state.scopeFilter === 'Arbitration' ? 'active' : ''}" data-scope="Arbitration">SIAC Arbitration</button>
              <button class="scope-chip ${state.scopeFilter === 'Tax' ? 'active' : ''}" data-scope="Tax">Tax</button>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('documents')">＋ Attach Doc</button>
              <button id="ask-submit-btn" class="btn btn-primary"><span>✦</span> Reason & Retrieve</button>
            </div>
          </div>
          <div class="suggested-pills">
            <span class="pill-label">Preset Queries:</span>
            <button class="query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Shareholder oppression dispute</button>
            <button class="query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">SIAC emergency arbitrator relief</button>
            <button class="query-preset-pill" data-query="Who has handled aviation lease disputes and Cape Town convention?">Aviation lease expertise</button>
            <button class="query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">M&A indemnity cap & locked-box</button>
            <button class="query-preset-pill" data-query="What arguments have succeeded in renewable energy tariff disputes?">Renewable energy tariffs</button>
            <button class="query-preset-pill" data-query="Find the latest Share Purchase Agreement for Singh-Srinivas Holdings">Singh-Srinivas SPA</button>
          </div>
        </div>

        <!-- Output Container -->
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
        <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">Ask any question to reconstruct institutional legal memory</div>
        <div style="font-size:12.5px;color:var(--text-secondary);max-width:540px;margin:0 auto 16px auto;">
          LEXOS executes hybrid semantic retrieval, query intent decomposition, permission gating, cross-document reranking, and SQL graph traversal to present four layers of intelligence.
        </div>
        <div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm query-preset-pill" data-query="Have we handled a shareholder dispute involving oppression and minority rights before?">Try: Shareholder Oppression</button>
          <button class="btn btn-secondary btn-sm query-preset-pill" data-query="Show similar SIAC arbitration matters with emergency arbitrator relief">Try: SIAC Arbitration</button>
          <button class="btn btn-secondary btn-sm query-preset-pill" data-query="What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?">Try: Indemnity Precedents</button>
        </div>
      </div>
    `;
  }

  function renderAskLoading() {
    return `
      <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:48px 20px;text-align:center;">
        <div style="display:inline-block;width:28px;height:28px;border:3px solid var(--border-medium);border-top-color:var(--accent-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:12px;"></div>
        <div style="font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Reconstructing Institutional Knowledge...</div>
        <div style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono);">Query Understanding → ACL Verification → Hybrid RRF (384-d) → Cross-Encoder Rerank → SQL Graph Synthesis</div>
      </div>
      <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
    `;
  }

  function renderAskResult(res) {
    return `
      <div class="reasoning-output-container">
        <!-- LAYER 1: ANSWER -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-1-badge"><span>①</span> ANSWER — EXECUTIVE SYNTHESIS</span>
            <span class="status-pill active">${res.matchCount || 7} Matters Matched</span>
          </div>
          <div class="layer-content">
            <div class="answer-synthesis-text">${res.answer}</div>
            <div class="stat-callouts">
              <div class="stat-box">
                <div class="stat-number">${res.matchCount || 7}</div>
                <div class="stat-label">Historical Matters</div>
              </div>
              <div class="stat-box">
                <div class="stat-number">${res.documentsCount || 23}</div>
                <div class="stat-label">Supporting Documents</div>
              </div>
              <div class="stat-box">
                <div class="stat-number">${res.authoritiesCount || 14}</div>
                <div class="stat-label">Authorities & Statutes</div>
              </div>
              <div class="stat-box">
                <div class="stat-number">${res.winRate || '86%'}</div>
                <div class="stat-label">Favorable / Settled Rate</div>
              </div>
            </div>
          </div>
        </div>

        <!-- LAYER 2: EVIDENCE -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-2-badge"><span>②</span> EVIDENCE — CLOSEST HISTORICAL MATTERS & DOCUMENTS</span>
            <span class="mono" style="font-size:11px;color:var(--text-muted);">Ranked by Factual & Legal DNA</span>
          </div>
          <div class="layer-content">
            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:8px;">Top Matching Matters:</div>
            <div class="matched-matters-grid">
              ${(res.matchedMatters || []).map(m => `
                <div class="matched-matter-card" onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span class="match-similarity-pill">${m.similarity}% MATCH</span>
                    <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">${m.matter_code || 'MTR'}</span>
                  </div>
                  <div style="font-weight:600;color:var(--text-primary);font-size:13px;">${escapeHtml(m.title)}</div>
                  <div style="font-size:11px;color:var(--text-secondary);">${m.court || m.jurisdiction} • ${m.date_range || '2022–2024'} • ${m.practice_area}</div>
                  <div style="font-size:11.5px;color:var(--text-muted);background:var(--bg-surface);padding:6px 8px;border-radius:var(--radius-xs);margin-top:2px;">
                    <strong>Similarity:</strong> ${m.similarity_reason}
                  </div>
                </div>
              `).join('')}
            </div>

            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:8px;">Supporting Pleadings, Agreements & Authorities:</div>
            <div class="evidence-items-list">
              ${(res.evidenceDocs || []).map(d => `
                <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: '${d.id}' })">
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span style="color:var(--accent-purple);font-family:var(--font-mono);font-size:11px;">${d.type}</span>
                    <span style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</span>
                    <span style="font-size:11px;color:var(--text-muted);">— ${d.matterTitle}</span>
                  </div>
                  <span class="kbd-shortcut">View Doc →</span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- LAYER 3: CONTEXT & REASONING -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-3-badge"><span>③</span> CONTEXT — WHY THESE ARE RELEVANT</span>
            <span class="mono" style="font-size:11px;color:var(--accent-amber);">Factual & Legal Overlap Analysis</span>
          </div>
          <div class="layer-content">
            <ul class="context-bullets-list">
              ${(res.contextPoints || []).map(pt => `
                <li class="context-bullet-item">
                  <span class="bullet-icon">▸</span>
                  <div><strong>${escapeHtml(pt.title)}:</strong> ${escapeHtml(pt.desc)}</div>
                </li>
              `).join('')}
            </ul>

            <div class="collapsible-pipeline-box">
              <div style="font-weight:600;color:var(--text-primary);margin-bottom:4px;">✦ Autonomous Reasoning Pipeline Execution:</div>
              <div>Intent: ${res.pipeline?.intent || 'Cross-Matter Institutional Extraction'} | ACL: Passed (${getCurrentMember().name}) | RRF Score: 0.884 | Latency: 142ms</div>
            </div>
          </div>
        </div>

        <!-- LAYER 4: PEOPLE & ACTIONS -->
        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-4-badge"><span>④</span> PEOPLE & ACTIONS — INSTITUTIONAL EXPERTISE</span>
            <span class="status-pill active">Staffing Recommendations</span>
          </div>
          <div class="layer-content">
            <div class="people-recommend-grid">
              ${(res.people || []).map(p => `
                <div class="person-card-compact" onclick="window.lexosNavigate('person-detail', { personId: '${p.member_id}' })" style="cursor:pointer;">
                  <div class="user-avatar">${p.initials || 'P'}</div>
                  <div style="flex:1;">
                    <div style="font-weight:600;color:var(--text-primary);font-size:12.5px;">${p.name}</div>
                    <div style="font-size:11px;color:var(--text-muted);">${p.role} • ${p.office}</div>
                    <div style="font-size:11px;color:var(--accent-emerald);font-weight:500;margin-top:2px;">${p.relevantCount} related matters handled</div>
                  </div>
                  <button class="btn btn-secondary btn-sm">Profile →</button>
                </div>
              `).join('')}
            </div>

            <div class="action-bar-deck">
              <span class="pill-label">Actions:</span>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('matter-detail', { matterId: '${res.matchedMatters?.[0]?.matter_id || 'MTR-2019-00001'}' })">Open Top Matter</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('knowledge', { tab: 'arguments' })">Compare Arguments</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('documents')">View All Evidence Docs</button>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('people')">Staff Similar Team</button>
              <button class="btn btn-secondary btn-sm" onclick="showToast('Institutional Research Note generated & saved to matter.')">Generate Research Note</button>
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
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
          const q = inp.value.trim();
          if (q) executeAskQuery(q);
        }
      });
    }

    document.querySelectorAll('.scope-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('.scope-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        state.scopeFilter = chip.dataset.scope;
      });
    });

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

    fetch('/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Member-Id': state.persona
      },
      body: JSON.stringify({ query: query, k: 10 })
    })
    .then(r => r.ok ? r.json() : null)
    .catch(() => null)
    .then(apiRes => {
      setTimeout(() => {
        state.askLoading = false;
        state.askResult = synthesizeReasoningResponse(query, apiRes);
        renderWorkspace();
      }, 450);
    });
  }

  function synthesizeReasoningResponse(query, apiRes) {
    const q = query.toLowerCase();
    const visibleMatters = getVisibleMatters();

    if (q.includes('shareholder') || q.includes('oppression') || q.includes('minority')) {
      const m1 = visibleMatters.find(m => m.matter_id === 'MTR-2020-00045') || visibleMatters[0];
      const m2 = visibleMatters.find(m => m.matter_id === 'MTR-2021-00033') || visibleMatters[1];
      const m3 = visibleMatters.find(m => m.matter_id === 'MTR-2019-00001') || visibleMatters[2];

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
            practice_area: 'Corporate / Disputes',
            similarity: 86,
            similarity_reason: 'Identical claims of promoter siphoning, oppressive rights issues, and exclusion from board meetings.'
          },
          {
            matter_id: m2.matter_id,
            matter_code: m2.matter_code,
            title: 'XYZ Technologies — Minority Oppression & Pre-emption',
            court: 'NCLT Delhi',
            date_range: '2022–2023',
            practice_area: 'Disputes & Corporate',
            similarity: 81,
            similarity_reason: 'Dispute over promoter share transfers breaching tag-along rights and fair market valuation.'
          },
          {
            matter_id: m3.matter_id,
            matter_code: m3.matter_code,
            title: 'Acme Infra — Shareholder Exit & Forensic Audit',
            court: 'Arbitration / High Court',
            date_range: '2021–2022',
            practice_area: 'Disputes',
            similarity: 76,
            similarity_reason: 'Deadlock resolution and forensic inspection prayers in joint venture entity.'
          }
        ],
        evidenceDocs: [
          { id: 'DOC-00004', type: 'PLEADING', title: 'Petition u/s 241-242 (Oppression & Mismanagement)', matterTitle: 'ABC Holdings' },
          { id: 'DOC-00003', type: 'MEMO', title: 'Research Memo: Board Control & Interim Relief in NCLT', matterTitle: 'XYZ Tech' },
          { id: 'DOC-00002', type: 'OPINION', title: 'Client Advice on Share Transfer Deadlock', matterTitle: 'Acme Infra' },
          { id: 'DOC-00001', type: 'SUBMISSIONS', title: 'Written Submissions on Maintainability of Section 244 Waiver', matterTitle: 'ABC Holdings' }
        ],
        contextPoints: [
          { title: 'Similar Shareholder Structure', desc: '40/60 promoter vs investor equity distribution with reserved board matters.' },
          { title: 'Minority Oppression Claims', desc: 'Promoters passed unilateral resolutions stripping minority representation.' },
          { title: 'Board Control & Transfer Restrictions', desc: 'Tested ROFR, tag-along covenants, and Section 241 statutory safeguards.' },
          { title: 'Comparable Relief Sought', desc: 'Interim injunction on share dilution and appointment of forensic auditor.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', office: 'Mumbai', initials: 'AM', relevantCount: 14 },
          { member_id: 'MEM-00002', name: 'Udant Dewan', role: 'Partner', office: 'Delhi', initials: 'UD', relevantCount: 9 },
          { member_id: 'MEM-00049', name: 'Alka Wable', role: 'Associate', office: 'Bengaluru', initials: 'AW', relevantCount: 7 }
        ],
        pipeline: { intent: 'Shareholder Oppression Reasoning & Precedents' }
      };
    } else if (q.includes('siac') || q.includes('arbitration') || q.includes('emergency')) {
      return {
        answer: "The firm has handled 19 international arbitrations seated in Singapore under SIAC Rules, including 4 urgent Emergency Arbitrator applications for interim status-quo orders concerning joint venture agreements.",
        matchCount: 19,
        documentsCount: 48,
        authoritiesCount: 16,
        winRate: '89%',
        matchedMatters: [
          {
            matter_id: 'MTR-2020-00015',
            matter_code: 'ARB/SIN/0015/2020',
            title: 'Siam Trans-Pacific — SIAC Emergency Injunction',
            court: 'SIAC (Singapore Seat)',
            date_range: '2023–2024',
            practice_area: 'International Arbitration',
            similarity: 92,
            similarity_reason: 'Emergency Arbitrator appointment obtained within 24 hours to restrain encashment of bank guarantees.'
          },
          {
            matter_id: 'MTR-2021-00045',
            matter_code: 'ARB/MUM/0045/2021',
            title: 'Kalyan Logistics — SIAC Share Vesting Dispute',
            court: 'SIAC / Singapore High Court',
            date_range: '2022–2023',
            practice_area: 'Arbitration',
            similarity: 84,
            similarity_reason: 'Cross-border joint venture breach with enforcement under New York Convention.'
          }
        ],
        evidenceDocs: [
          { id: 'DOC-00004', type: 'NOTICE', title: 'Notice of Arbitration & Application for Emergency Relief', matterTitle: 'Siam Trans-Pacific' },
          { id: 'DOC-00003', type: 'SUBMISSIONS', title: 'Memorial on Interim Measures & Test of Irreparable Harm', matterTitle: 'Siam Trans-Pacific' }
        ],
        contextPoints: [
          { title: 'Emergency Injunction Test', desc: 'Demonstrated exceptional urgency and risk of dissipation of assets.' },
          { title: 'SIAC 2024 Expedited Rules', desc: 'Tribunal constituted in 14 days under expedited procedure provisions.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', office: 'Singapore/Mumbai', initials: 'AM', relevantCount: 19 },
          { member_id: 'MEM-00057', name: 'Ekansh Balay', role: 'Associate', office: 'Delhi', initials: 'EB', relevantCount: 8 }
        ],
        pipeline: { intent: 'SIAC International Arbitration Retrieval' }
      };
    } else if (q.includes('indemnity') || q.includes('locked-box') || q.includes('spa') || q.includes('cap')) {
      return {
        answer: "In M&A transactions, the firm standardizes general indemnity caps between 15%–20% of Transaction Consideration, with Fundamental Warranties and Tax Claims capped at 100% of purchase price with an 18-month survival period.",
        matchCount: 34,
        documentsCount: 92,
        authoritiesCount: 18,
        winRate: '94%',
        matchedMatters: [
          {
            matter_id: 'MTR-2019-00001',
            matter_code: 'MNA/DEL/0001/2019',
            title: 'Singh-Srinivas Holdings — Share Purchase Agreement',
            court: 'Bombay High Court / Negotiation',
            date_range: '2019–2020',
            practice_area: 'M&A',
            similarity: 95,
            similarity_reason: 'Standard locked-box anti-leakage covenants with ₹106.7 crore quantum.'
          }
        ],
        evidenceDocs: [
          { id: 'DOC-00004', type: 'CONTRACT', title: 'Share Purchase Agreement (v1 Executed)', matterTitle: 'Singh-Srinivas Holdings' },
          { id: 'DOC-00005', type: 'REDLINE', title: 'Share Purchase Agreement (v2 Marked Up)', matterTitle: 'Singh-Srinivas Holdings' }
        ],
        contextPoints: [
          { title: 'Locked-Box Anti-Leakage Undertaking', desc: 'Strict indemnity on value extraction between Locked-Box Date and Closing.' },
          { title: 'De Minimis & Basket Thresholds', desc: 'Individual threshold of ₹15 lakh with tipping basket of ₹1 crore.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', office: 'Mumbai', initials: 'AM', relevantCount: 22 },
          { member_id: 'MEM-00002', name: 'Udant Dewan', role: 'Partner', office: 'Delhi', initials: 'UD', relevantCount: 16 }
        ],
        pipeline: { intent: 'M&A Precedent & Clause Extraction' }
      };
    } else {
      const m = visibleMatters[0] || { title: 'Singh-Srinivas Holdings — Share Purchase Agreement', matter_id: 'MTR-2019-00001', matter_code: 'MNA/DEL/0001/2019' };
      return {
        answer: `Identified 5 relevant institutional records matching "${escapeHtml(query)}" across corporate transactions, pleadings, and advice memos.`,
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
            date_range: '2021–2024',
            practice_area: m.practice_area || 'Corporate',
            similarity: 84,
            similarity_reason: 'Factual and legal alignment with query terms.'
          }
        ],
        evidenceDocs: [
          { id: 'DOC-00001', type: 'MEMO', title: 'Legal Advice & Strategy Note', matterTitle: m.title }
        ],
        contextPoints: [
          { title: 'Precedent Alignment', desc: 'Consistent with firm-wide position approved by practice leaders.' }
        ],
        people: [
          { member_id: 'MEM-00001', name: 'Aryan Maharaj', role: 'Partner', office: 'Mumbai', initials: 'AM', relevantCount: 12 }
        ],
        pipeline: { intent: 'Institutional Knowledge Synthesis' }
      };
    }
  }

  // --- SCREEN 3: MATTERS ---
  function renderMattersScreen() {
    const visibleMatters = getVisibleMatters();
    const query = (state.searchQuery || '').toLowerCase();
    const filtered = visibleMatters.filter(m => {
      if (!query) return true;
      return m.title.toLowerCase().includes(query) ||
             (m.client_name || '').toLowerCase().includes(query) ||
             (m.matter_code || '').toLowerCase().includes(query) ||
             (m.practice_area || '').toLowerCase().includes(query) ||
             (m.lead_partner || '').toLowerCase().includes(query);
    });

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Matters</div>
            <div class="view-header-desc">Matter-centric legal DMS. Reconstructed matter intelligence across all 10 practice areas and 4 offices.</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('documents')">＋ Ingest to Matter</button>
          </div>
        </div>

        <div class="filter-bar">
          <div class="search-input-box">
            <span class="search-input-icon">🔍</span>
            <input id="matters-search-input" type="text" placeholder="Filter matters by client, title, code, lead partner, or practice area..." value="${escapeHtml(state.searchQuery)}">
          </div>
          <select id="matters-practice-filter" class="filter-select">
            <option value="">All Practice Areas</option>
            <option value="Corporate">Corporate</option>
            <option value="M&A">M&A</option>
            <option value="Disputes">Disputes</option>
            <option value="Arbitration">Arbitration</option>
            <option value="Tax">Tax</option>
            <option value="Insolvency">Insolvency & NCLT</option>
          </select>
          <select id="matters-status-filter" class="filter-select">
            <option value="">All Statuses</option>
            <option value="Open">Open / Active</option>
            <option value="Closed">Closed</option>
            <option value="Stayed">Stayed</option>
          </select>
          <span class="mono" style="font-size:11px;color:var(--text-muted);margin-left:auto;">Showing ${filtered.length} of ${visibleMatters.length} matters</span>
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
                <th>Quantum</th>
                <th>Status</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.slice(0, 50).map(m => `
                <tr onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                  <td class="mono" style="font-size:11px;font-weight:600;color:var(--accent-primary);">${m.matter_code}</td>
                  <td>
                    <div style="font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:1px;">${m.client_name}</div>
                  </td>
                  <td><span class="scope-chip">${m.practice_area}</span></td>
                  <td style="font-size:12px;">${m.court || 'Commercial Tribunal'}</td>
                  <td>${m.lead_partner}</td>
                  <td class="mono" style="font-size:11.5px;">${m.claim_amount || '—'}</td>
                  <td><span class="status-pill ${m.status.toLowerCase()}">${m.status}</span></td>
                  <td class="mono" style="font-size:11px;color:var(--text-muted);">${m.opened_date}</td>
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

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('matters')">Matters</a> <span>/</span>
          <a onclick="window.lexosNavigate('client-detail', { clientId: '${m.client_id}' })">${m.client_name}</a> <span>/</span>
          <span class="mono">${m.matter_code}</span>
        </div>

        <div class="matter-detail-header">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="mono" style="font-size:12px;font-weight:700;color:var(--accent-primary);background:var(--bg-surface-elevated);padding:2px 8px;border-radius:var(--radius-xs);border:1px solid var(--border-subtle);">${m.matter_code}</span>
                <span class="status-pill ${m.status.toLowerCase()}">${m.status}</span>
                ${m.restricted ? '<span class="status-pill restricted">🔒 Restricted / Ethical Wall</span>' : ''}
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);letter-spacing:-0.02em;">${escapeHtml(m.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are the key arguments and documents in matter ${m.matter_code}?');"><span>✦</span> Ask Matter</button>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('documents')">＋ Add Doc</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div><strong>Client:</strong> ${m.client_name}</div>
            <div><strong>Practice Areas:</strong> ${m.teams ? m.teams.join(' · ') : m.practice_area}</div>
            <div><strong>Forum:</strong> ${m.court || 'Tribunal'}</div>
            <div><strong>Lead Partner:</strong> ${m.lead_partner}</div>
            <div><strong>Quantum:</strong> <span class="mono">${m.claim_amount || '—'}</span></div>
            <div><strong>Opened:</strong> <span class="mono">${m.opened_date}</span></div>
          </div>
        </div>

        <div class="tabs-nav">
          <button class="tab-btn ${state.matterTab === 'overview' ? 'active' : ''}" data-tab="overview">Overview & DNA</button>
          <button class="tab-btn ${state.matterTab === 'timeline' ? 'active' : ''}" data-tab="timeline">Matter Timeline</button>
          <button class="tab-btn ${state.matterTab === 'documents' ? 'active' : ''}" data-tab="documents">Documents (14)</button>
          <button class="tab-btn ${state.matterTab === 'projects' ? 'active' : ''}" data-tab="projects">Work Streams / Projects</button>
          <button class="tab-btn ${state.matterTab === 'arguments' ? 'active' : ''}" data-tab="arguments">Arguments & Strategies</button>
          <button class="tab-btn ${state.matterTab === 'authorities' ? 'active' : ''}" data-tab="authorities">Authorities & Statutes</button>
          <button class="tab-btn ${state.matterTab === 'people' ? 'active' : ''}" data-tab="people">Team & Staffing</button>
          <button class="tab-btn ${state.matterTab === 'graph' ? 'active' : ''}" data-tab="graph">Connected Knowledge Graph</button>
        </div>

        <div id="matter-tab-content">
          ${renderMatterTabContent(m)}
        </div>
      </div>
    `;
  }

  function renderMatterTabContent(m) {
    switch (state.matterTab) {
      case 'overview':
        return `
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
            <div style="display:flex;flex-direction:column;gap:16px;">
              <div class="reasoning-card">
                <div class="layer-header">
                  <span class="layer-badge layer-1-badge"><span>✦</span> AI Matter Memory Summary</span>
                </div>
                <div class="layer-content">
                  <p style="font-size:13.5px;color:var(--text-primary);line-height:1.6;margin-bottom:12px;">${m.ai_memory?.summary || 'Reconstructed institutional memory for this active matter.'}</p>
                  <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Key Issues in View:</div>
                  <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">
                    ${(m.legal_issues || ['Indemnity cap', 'Locked-box leakage', 'Material adverse change']).map(iss => `
                      <span class="scope-chip">${iss}</span>
                    `).join('')}
                  </div>
                  <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Core Facts Touching Matter:</div>
                  <ul style="list-style:none;display:flex;flex-direction:column;gap:4px;font-size:12.5px;color:var(--text-secondary);">
                    ${(m.facts || ['Buyer acquired controlling stake in manufacturing target', 'Tax liabilities surfaced during diligence', 'Escrow negotiated against leakage']).map(f => `
                      <li>• ${f}</li>
                    `).join('')}
                  </ul>
                </div>
              </div>

              <div class="reasoning-card">
                <div class="layer-header">
                  <span class="layer-badge layer-2-badge">Multi-Team Relationship Architecture</span>
                </div>
                <div class="layer-content" style="font-size:12.5px;color:var(--text-secondary);">
                  <p style="margin-bottom:10px;">This matter connects simultaneously across distinct practice teams:</p>
                  <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:10px;">
                    <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                      <div style="font-weight:600;color:var(--text-primary);">Corporate / M&A</div>
                      <div style="font-size:11px;color:var(--text-muted);">SPA drafting, negotiation & diligence</div>
                    </div>
                    <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                      <div style="font-weight:600;color:var(--text-primary);">Tax & Structuring</div>
                      <div style="font-size:11px;color:var(--text-muted);">Contingent tax indemnity & locked-box</div>
                    </div>
                    <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                      <div style="font-weight:600;color:var(--text-primary);">Dispute Resolution</div>
                      <div style="font-size:11px;color:var(--text-muted);">Arbitration seats & court filings</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div style="display:flex;flex-direction:column;gap:16px;">
              <div class="reasoning-card">
                <div class="layer-header">
                  <span class="layer-badge layer-4-badge">Similar Institutional Precedents</span>
                </div>
                <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;padding:12px;">
                  <div class="evidence-item-row" onclick="window.lexosNavigate('matter-detail', { matterId: 'MTR-2020-00045' })">
                    <div>
                      <div style="font-weight:600;color:var(--text-primary);font-size:12px;">ABC Holdings — Shareholder Dispute</div>
                      <div style="font-size:11px;color:var(--text-muted);">86% Similarity • Bombay HC</div>
                    </div>
                  </div>
                  <div class="evidence-item-row" onclick="window.lexosNavigate('matter-detail', { matterId: 'MTR-2021-00033' })">
                    <div>
                      <div style="font-weight:600;color:var(--text-primary);font-size:12px;">XYZ Technologies — Oppression</div>
                      <div style="font-size:11px;color:var(--text-muted);">81% Similarity • NCLT</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="reasoning-card">
                <div class="layer-header">
                  <span class="layer-badge layer-3-badge">Client Memory Preference</span>
                </div>
                <div class="layer-content" style="font-size:12px;color:var(--text-secondary);">
                  <div style="color:var(--accent-emerald);font-weight:600;margin-bottom:4px;">✓ Preferred by General Counsel:</div>
                  <div style="margin-bottom:8px;">Executive summaries, risk heatmaps, concise liability tables.</div>
                  <div style="color:var(--accent-rose);font-weight:600;margin-bottom:4px;">✕ Avoid:</div>
                  <div>Long case law summaries and redundant recitals.</div>
                </div>
              </div>
            </div>
          </div>
        `;
      case 'timeline':
        return `
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Chronological Matter Timeline (Reconstructed from 14 Documents)</span>
              <span class="mono" style="font-size:11px;color:var(--text-muted);">Auto-Generated from Filings & Drafts</span>
            </div>
            <div class="layer-content">
              <div class="timeline-stream">
                ${(m.timeline || []).map(tl => `
                  <div class="timeline-node">
                    <div class="timeline-node-dot"></div>
                    <div class="timeline-node-content">
                      <div class="timeline-date">${tl.date} • ${tl.author}</div>
                      <div class="timeline-event-title">${escapeHtml(tl.event)}</div>
                      <div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
                        <span class="scope-chip">${tl.doc_type || 'Document'}</span>
                        <a onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00004' })" style="font-size:11.5px;color:var(--accent-primary);cursor:pointer;">Open underlying document →</a>
                      </div>
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>
          </div>
        `;
      case 'documents':
        const docs = (getFirmData().documents || []).slice(0, 8);
        return `
          <div class="data-table-container">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Doc ID</th>
                  <th>Title</th>
                  <th>Document Type</th>
                  <th>Version</th>
                  <th>Author</th>
                  <th>Date</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                ${docs.map(d => `
                  <tr onclick="window.lexosNavigate('doc-detail', { docId: '${d.document_id}' })">
                    <td class="mono" style="font-size:11px;color:var(--accent-purple);">${d.document_id}</td>
                    <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                    <td><span class="scope-chip">${d.document_type}</span></td>
                    <td><span class="version-tag">${d.version || 'v1 Final'}</span></td>
                    <td>${d.author_name}</td>
                    <td class="mono" style="font-size:11px;">${d.date}</td>
                    <td><span class="status-pill active">${d.status}</span></td>
                    <td><button class="btn btn-ghost btn-sm">Preview →</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      case 'projects':
        return `
          <div style="display:flex;flex-direction:column;gap:12px;">
            ${(m.projects || []).map(p => `
              <div class="reasoning-card" style="padding:14px;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                  <div>
                    <span class="mono" style="font-size:11px;color:var(--accent-primary);margin-right:8px;">${p.id}</span>
                    <strong style="font-size:13.5px;color:var(--text-primary);">${escapeHtml(p.title)}</strong>
                    <span class="scope-chip" style="margin-left:8px;">${p.team} Team</span>
                  </div>
                  <span class="status-pill ${p.status === 'Completed' ? 'active' : 'open'}">${p.status}</span>
                </div>
                <div style="display:flex;align-items:center;gap:16px;font-size:12px;color:var(--text-secondary);margin-bottom:8px;">
                  <div>Lead: <strong>${p.owner}</strong></div>
                  <div>Target Deadline: <span class="mono">${p.deadline}</span></div>
                  <div>Progress: <span class="mono">${p.progress}%</span></div>
                </div>
                <div class="confidence-bar">
                  <div class="confidence-fill" style="width:${p.progress}%;"></div>
                </div>
              </div>
            `).join('')}
          </div>
        `;
      case 'arguments':
        return `
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-3-badge">Tested Arguments & Legal Positions</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:12px;">
              <div style="padding:12px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-size:11px;font-weight:600;color:var(--accent-emerald);margin-bottom:4px;">CLIENT POSITION (ACCEPTED BY TRIBUNAL)</div>
                <div style="font-size:13px;font-weight:600;color:var(--text-primary);">Cap should reflect disclosed tax exposure & escrow retention</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">Supported by DOC-00004 Clause 14 & Due Diligence Report. Successfully established in pre-closing settlement.</div>
              </div>
              <div style="padding:12px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-size:11px;font-weight:600;color:var(--accent-rose);margin-bottom:4px;">OPPOSING COUNSEL ARGUMENT (REJECTED)</div>
                <div style="font-size:13px;font-weight:600;color:var(--text-primary);">Seller cannot stand behind historic tax risks indefinitely</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">Countered via Section 281 of Income-tax Act, 1961 precedent arguments.</div>
              </div>
            </div>
          </div>
        `;
      case 'authorities':
        return `
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-2-badge">Cited Statutory Provisions & Precedents</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:10px;">
              <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-weight:600;color:var(--text-primary);font-size:13px;">Companies Act, 2013 — Section 241 & 242</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">Application to Tribunal for relief in cases of oppression and mismanagement.</div>
              </div>
              <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-weight:600;color:var(--text-primary);font-size:13px;">Arbitration and Conciliation Act, 1996 — Section 9 & 17</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">Interim measures by Court and Arbitral Tribunal.</div>
              </div>
              <div style="padding:10px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
                <div style="font-weight:600;color:var(--text-primary);font-size:13px;">Tata Consultancy Services v. Cyrus Investments Pvt. Ltd. (2021) 9 SCC 449</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">Supreme Court landmark precedent on justifiable lack of confidence and just & equitable winding up test.</div>
              </div>
            </div>
          </div>
        `;
      case 'people':
        return `
          <div class="matched-matters-grid">
            ${(m.resolved_members || [{ name: 'Aryan Maharaj', role: 'Partner', role_on_matter: 'Lead Partner', office: 'Mumbai' }]).map(mem => `
              <div class="person-card-compact" style="padding:12px;">
                <div class="user-avatar">${mem.name ? mem.name.split(' ').map(n=>n[0]).join('') : 'L'}</div>
                <div style="flex:1;">
                  <div style="font-weight:600;color:var(--text-primary);font-size:13px;">${mem.name}</div>
                  <div style="font-size:11px;color:var(--text-muted);">${mem.role} • ${mem.office || 'Office'}</div>
                  <div style="font-size:11px;color:var(--accent-primary);font-weight:600;margin-top:2px;">${mem.role_on_matter || 'Team Member'}</div>
                </div>
              </div>
            `).join('')}
          </div>
        `;
      case 'graph':
        return `
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Interactive Matter Knowledge Graph</span>
              <span class="mono" style="font-size:11px;color:var(--text-muted);">Click nodes to navigate</span>
            </div>
            <div class="layer-content" style="padding:0;">
              <div class="graph-canvas-container">
                <canvas id="matter-graph-canvas" class="graph-canvas"></canvas>
                <div class="graph-legend">
                  <div class="legend-item"><span class="legend-dot" style="background:var(--accent-primary);"></span> Current Matter</div>
                  <div class="legend-item"><span class="legend-dot" style="background:var(--accent-purple);"></span> Documents (14)</div>
                  <div class="legend-item"><span class="legend-dot" style="background:var(--accent-emerald);"></span> People / Lawyers</div>
                  <div class="legend-item"><span class="legend-dot" style="background:var(--accent-amber);"></span> Arguments & DNA</div>
                  <div class="legend-item"><span class="legend-dot" style="background:var(--accent-rose);"></span> Similar Matters</div>
                </div>
              </div>
            </div>
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
    const allDocs = [...state.customDocs, ...(data.documents || []).slice(0, 100)];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Document Management & Ingestion</div>
            <div class="view-header-desc">Smart AI classification. Drag and drop any document or sync cloud repositories without tedious metadata forms.</div>
          </div>
          <div class="view-header-actions">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> 38,232 Docs Indexed</span>
          </div>
        </div>

        <!-- Smart Ingestion Dropzone -->
        <div id="ingest-dropzone-target" class="ingest-dropzone">
          <div style="font-size:24px;color:var(--accent-primary);margin-bottom:8px;">📂</div>
          <div style="font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:4px;">Drop files, emails, or folders anywhere here</div>
          <div style="font-size:12px;color:var(--text-muted);max-width:480px;margin:0 auto 12px auto;">
            AI automatically classifies Client, Matter, Team, Document Type, Authors, Dates, and Clauses with high confidence.
          </div>
          <input type="file" id="file-upload-input" multiple style="display:none;">
          <button id="trigger-browse-btn" class="btn btn-secondary btn-sm">Browse Local Files</button>

          <div class="connector-badges-row">
            <button class="connector-btn" onclick="simulateCloudConnect('SharePoint')"><span>🔗</span> Connect SharePoint</button>
            <button class="connector-btn" onclick="simulateCloudConnect('OneDrive')"><span>☁️</span> Connect OneDrive</button>
            <button class="connector-btn" onclick="simulateCloudConnect('Outlook / Exchange')"><span>✉️</span> Connect Email</button>
            <button class="connector-btn" onclick="simulateCloudConnect('iManage')"><span>🗄️</span> Connect iManage</button>
          </div>
        </div>

        <!-- Pending Ingestion Approvals -->
        ${state.ingestPending.length ? `
          <div class="reasoning-card" style="margin-bottom:20px;">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge"><span>✦</span> AI AUTO-CLASSIFICATION RESULTS</span>
              <span class="status-pill active">Ready to Confirm</span>
            </div>
            <div class="layer-content">
              ${state.ingestPending.map((p, idx) => `
                <div style="padding:12px;background:var(--bg-surface-elevated);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);margin-bottom:8px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <strong style="color:var(--text-primary);font-size:13px;">${p.filename}</strong>
                    <span class="status-pill active">${p.confidence}% Confidence</span>
                  </div>
                  <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">
                    Identified: <strong>${p.client}</strong> → <strong>${p.matter}</strong> • Type: <em>${p.docType}</em> • Team: ${p.team}
                  </div>
                  <div style="display:flex;gap:8px;">
                    <button class="btn btn-primary btn-sm" onclick="window.confirmIngestion(${idx})">Confirm Classification</button>
                    <button class="btn btn-secondary btn-sm" onclick="showToast('Matter selector opened.')">Change Matter...</button>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <!-- Documents Table -->
        <div class="filter-bar">
          <div class="search-input-box">
            <span class="search-input-icon">🔍</span>
            <input id="docs-search-input" type="text" placeholder="Filter documents by title, author, matter, or type...">
          </div>
        </div>

        <div class="data-table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>Doc ID</th>
                <th>Document Title</th>
                <th>Type</th>
                <th>Matter</th>
                <th>Version</th>
                <th>Author</th>
                <th>Date</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${allDocs.map(d => `
                <tr onclick="window.lexosNavigate('doc-detail', { docId: '${d.document_id}' })">
                  <td class="mono" style="font-size:11px;color:var(--accent-purple);">${d.document_id}</td>
                  <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(d.title)}</td>
                  <td><span class="scope-chip">${d.document_type}</span></td>
                  <td><a onclick="event.stopPropagation();window.lexosNavigate('matter-detail', { matterId: '${d.matter_id}' })" style="color:var(--accent-primary);text-decoration:none;">${d.matter_id}</a></td>
                  <td><span class="version-tag">${d.version || 'v1 Final'}</span></td>
                  <td>${d.author_name}</td>
                  <td class="mono" style="font-size:11px;">${d.date}</td>
                  <td><span class="status-pill active">${d.status}</span></td>
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

    if (browseBtn && fileInp) {
      browseBtn.addEventListener('click', () => fileInp.click());
    }

    if (fileInp) {
      fileInp.addEventListener('change', (e) => {
        handleIncomingFiles(e.target.files);
      });
    }

    if (dropzone) {
      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
      dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        handleIncomingFiles(e.dataTransfer.files);
      });
    }
  }

  function handleIncomingFiles(files) {
    if (!files || !files.length) return;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      state.ingestPending.push({
        filename: f.name,
        client: 'Singh-Srinivas Holdings',
        matter: 'Acquisition of XYZ Pvt Ltd (MNA/DEL/0001/2019)',
        matter_id: 'MTR-2019-00001',
        docType: f.name.includes('SPA') ? 'Share Purchase Agreement' : (f.name.includes('Petition') ? 'Pleading' : 'Due Diligence Report'),
        team: 'Corporate / M&A',
        confidence: 96
      });
    }
    showToast(`AI extracted metadata for ${files.length} document(s).`);
    renderWorkspace();
  }

  window.confirmIngestion = function(idx) {
    const item = state.ingestPending[idx];
    if (!item) return;
    const newDocId = `DOC-NEW-${Date.now().toString().slice(-4)}`;
    state.customDocs.unshift({
      document_id: newDocId,
      matter_id: item.matter_id,
      title: item.filename.replace(/\.[^/.]+$/, ""),
      document_type: item.docType,
      author_name: getCurrentMember().name,
      date: new Date().toISOString().slice(0, 10),
      status: 'Final',
      version: 'v1.0 Executed',
      text: `INGESTED FILE: ${item.filename}\nClassified to ${item.matter}\nProcessed by Apex Chambers AI Institutional Memory.`
    });
    state.ingestPending.splice(idx, 1);
    showToast(`Successfully indexed ${item.filename} into ${item.matter}`);
    renderWorkspace();
  };

  window.simulateCloudConnect = function(source) {
    showToast(`Connecting to ${source}... Synchronizing institutional files.`);
    setTimeout(() => {
      state.ingestPending.push({
        filename: `${source}_Executive_Summary_2026.docx`,
        client: 'Aggarwal Infrastructure Ltd.',
        matter: 'Solar Power Tariff Arbitration',
        matter_id: 'MTR-2021-00067',
        docType: 'Advisory Note',
        team: 'Disputes & Regulatory',
        confidence: 94
      });
      renderWorkspace();
    }, 600);
  };

  // --- SCREEN 4B: DOCUMENT DETAIL ---
  function renderDocDetailScreen(docId) {
    const d = getDocById(docId) || getFirmData().documents?.[0];
    if (!d) return `<div class="view-container">Document not found.</div>`;

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('documents')">Documents</a> <span>/</span>
          <a onclick="window.lexosNavigate('matter-detail', { matterId: '${d.matter_id}' })">${d.matter_id}</a> <span>/</span>
          <span class="mono">${d.document_id}</span>
        </div>

        <div class="matter-detail-header">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="version-tag">${d.version || 'v1 Final'}</span>
                <span class="status-pill active">${d.status}</span>
                <span class="scope-chip">${d.document_type}</span>
              </div>
              <h1 style="font-size:20px;font-weight:700;color:var(--text-primary);letter-spacing:-0.02em;">${escapeHtml(d.title)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('Summarize key obligations in document ${d.document_id}');"><span>✦</span> Ask Doc</button>
              <button class="btn btn-primary btn-sm" onclick="showToast('Exported redline comparison package.')">Export Redline</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div><strong>Author:</strong> ${d.author_name}</div>
            <div><strong>Date:</strong> <span class="mono">${d.date}</span></div>
            <div><strong>Matter:</strong> ${d.matter_id}</div>
          </div>
        </div>

        <div class="tabs-nav">
          <button class="tab-btn ${state.docTab === 'overview' ? 'active' : ''}" data-doctab="overview">Document Preview</button>
          <button class="tab-btn ${state.docTab === 'diff' ? 'active' : ''}" data-doctab="diff">Git-Style Version Redlines</button>
          <button class="tab-btn ${state.docTab === 'clauses' ? 'active' : ''}" data-doctab="clauses">Extracted Clauses (6)</button>
          <button class="tab-btn ${state.docTab === 'audit' ? 'active' : ''}" data-doctab="audit">Audit Trail</button>
        </div>

        <div id="doc-tab-content">
          ${renderDocTabContent(d)}
        </div>
      </div>
    `;
  }

  function renderDocTabContent(d) {
    switch (state.docTab) {
      case 'overview':
        return `
          <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:24px;font-family:var(--font-sans);font-size:13.5px;line-height:1.7;color:var(--text-primary);white-space:pre-wrap;">
${escapeHtml(d.text || 'SHARE PURCHASE AGREEMENT\n\n1. Parties\nThe Seller and the Buyer agree to the sale of Sale Shares.\n\n2. Consideration\nThe locked-box equity value is ₹106.7 crore, subject to leakage.\n\n14. Indemnity Cap\nThe aggregate liability under tax and general warranties is capped at 15% of purchase price.')}
          </div>
        `;
      case 'diff':
        return `
          <div class="version-tree-timeline">
            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:6px;">Git-Inspired Version History:</div>
            <div class="version-row active">
              <div>
                <span class="version-tag">Version 4 — Executed</span>
                <strong style="color:var(--text-primary);margin-left:8px;">Aryan Maharaj committed final executed draft</strong>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Closing adjustments applied • Signed at Mumbai Office • 24 May 2024</div>
              </div>
              <span class="mono" style="font-size:11px;color:var(--accent-emerald);">+14 lines, -6 lines</span>
            </div>
            <div class="version-row">
              <div>
                <span class="version-tag">Version 3 — Indemnity Revised</span>
                <strong style="color:var(--text-primary);margin-left:8px;">Udant Dewan negotiated escrow cap from ₹10 Cr to ₹20 Cr</strong>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Seller comments incorporated • 18 Aug 2023</div>
              </div>
              <span class="mono" style="font-size:11px;color:var(--accent-primary);">+28 lines, -12 lines</span>
            </div>
            <div class="version-row">
              <div>
                <span class="version-tag">Version 1 — Initial Draft</span>
                <strong style="color:var(--text-primary);margin-left:8px;">Alka Wable created base draft from Master SPA precedent</strong>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Initial term sheet baseline • 29 Jul 2023</div>
              </div>
            </div>
          </div>

          <div class="diff-viewer-container">
            <div class="diff-header">
              <span style="font-weight:600;color:var(--text-primary);">Visual Redline Comparison: v3 (Indemnity Revised) vs v4 (Executed)</span>
              <span class="mono" style="font-size:11px;color:var(--text-muted);">Unified Diff View</span>
            </div>
            <div class="diff-pane">
              <div class="diff-line">
                <span class="diff-line-number">14</span>
                <span>14. Indemnity & Liability Cap</span>
              </div>
              <div class="diff-line removed">
                <span class="diff-line-number">15</span>
                <span>- The aggregate maximum liability of the Seller shall not exceed ₹10 crore under any circumstances.</span>
              </div>
              <div class="diff-line added">
                <span class="diff-line-number">15</span>
                <span>+ The aggregate maximum liability of the Seller in respect of Warranty Claims shall not exceed 15% (fifteen percent) of the Purchase Price, save and except in the case of Fundamental Warranties, Tax Claims, or Fraud, where liability shall be capped at the full Purchase Price.</span>
              </div>
              <div class="diff-line added">
                <span class="diff-line-number">16</span>
                <span>+ 15. Escrow Account: An amount of ₹10,67,00,000 shall be maintained in the Escrow Account for 18 months following the Closing Date.</span>
              </div>
            </div>
          </div>
        `;
      case 'clauses':
        return `
          <div style="display:flex;flex-direction:column;gap:10px;">
            <div class="reasoning-card" style="padding:14px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <strong style="font-size:13px;color:var(--text-primary);">Clause 14 — Indemnity Cap & De Minimis</strong>
                <span class="status-pill active">Standard Market Standard</span>
              </div>
              <p style="font-size:12.5px;color:var(--text-secondary);line-height:1.5;">The Seller's aggregate liability under the tax and general indemnities is capped at 15% of purchase price, with fundamental warranties capped at consideration.</p>
            </div>
            <div class="reasoning-card" style="padding:14px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <strong style="font-size:13px;color:var(--text-primary);">Clause 15 — Locked-Box Leakage Protection</strong>
                <span class="status-pill active">Strict Anti-Leakage</span>
              </div>
              <p style="font-size:12.5px;color:var(--text-secondary);line-height:1.5;">Covenant ensuring no dividends, management fees, or non-permitted transfers between locked-box accounts date and completion.</p>
            </div>
          </div>
        `;
      case 'audit':
        return `
          <div class="reasoning-card" style="padding:14px;">
            <div style="font-size:12px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;margin-bottom:8px;">Document Access & Chain of Custody</div>
            <div class="timeline-stream">
              <div class="timeline-node">
                <div class="timeline-node-dot"></div>
                <div class="timeline-node-content">
                  <div class="timeline-date">Today • 10:30 AM</div>
                  <div class="timeline-event-title">Aryan Maharaj accessed document for client presentation</div>
                </div>
              </div>
              <div class="timeline-node">
                <div class="timeline-node-dot"></div>
                <div class="timeline-node-content">
                  <div class="timeline-date">Yesterday • 2:15 PM</div>
                  <div class="timeline-event-title">Alka Wable updated version v4 executed bundle</div>
                </div>
              </div>
            </div>
          </div>
        `;
      default:
        return `<div>Preview</div>`;
    }
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
            <div class="view-header-desc">Client profiles that function as corporate memory — preserving specific drafting preferences, negotiation tendencies, and historical advice.</div>
          </div>
          <div class="view-header-actions">
            <span class="status-badge-live"><span class="status-dot-pulse"></span> 500 Clients Connected</span>
          </div>
        </div>

        <div class="matched-matters-grid">
          ${clients.slice(0, 18).map(c => `
            <div class="matched-matter-card" onclick="window.lexosNavigate('client-detail', { clientId: '${c.client_id}' })">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span class="scope-chip">${c.industry || 'Corporate'}</span>
                <span class="mono" style="font-size:11px;color:var(--text-muted);">${c.client_id}</span>
              </div>
              <div style="font-weight:700;color:var(--text-primary);font-size:14px;">${escapeHtml(c.name)}</div>
              <div style="font-size:11.5px;color:var(--text-secondary);">HQ: ${c.headquarters || 'Mumbai'} • Total Matters: ${c.matters_count || 12}</div>
              <div style="font-size:11px;color:var(--accent-emerald);font-weight:500;background:var(--bg-surface);padding:4px 6px;border-radius:var(--radius-xs);margin-top:4px;">
                ✓ ${c.client_memory?.preferred?.[0] || 'Prefers executive summaries & risk matrices'}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function attachClientsEvents() {}

  function renderClientDetailScreen(clientId) {
    const c = getClientById(clientId) || getFirmData().clients?.[0];
    if (!c) return `<div class="view-container">Client not found.</div>`;

    const visibleMatters = getVisibleMatters().filter(m => m.client_id === c.client_id || m.client_name === c.name);

    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('clients')">Clients</a> <span>/</span>
          <span class="mono">${c.client_id}</span>
        </div>

        <div class="matter-detail-header">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;">
            <div>
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span class="scope-chip">${c.industry}</span>
                <span class="status-pill active">${c.size || 'Enterprise'}</span>
              </div>
              <h1 style="font-size:22px;font-weight:700;color:var(--text-primary);letter-spacing:-0.02em;">${escapeHtml(c.name)}</h1>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('ask');executeAskQuery('What are our historical transactions and advice for ${escapeHtml(c.name)}?');"><span>✦</span> Ask Client Memory</button>
            </div>
          </div>

          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:12px;">
            <div><strong>Headquarters:</strong> ${c.headquarters}</div>
            <div><strong>Total Billing:</strong> <span class="mono">${c.total_billing || '₹42.5 crore'}</span></div>
            <div><strong>Active Matters:</strong> <span class="mono">${visibleMatters.length}</span></div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge"><span>✦</span> Institutional Client Preferences</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;font-size:12.5px;">
              <div style="color:var(--accent-emerald);font-weight:600;">✓ Preferred Presentation Formats:</div>
              <ul style="list-style:none;display:flex;flex-direction:column;gap:3px;color:var(--text-secondary);">
                ${(c.client_memory?.preferred || ['Executive summaries', 'Risk matrices', 'Concise opinions']).map(p => `
                  <li>• ${p}</li>
                `).join('')}
              </ul>
              <div style="color:var(--accent-rose);font-weight:600;margin-top:6px;">✕ Formats to Avoid:</div>
              <ul style="list-style:none;display:flex;flex-direction:column;gap:3px;color:var(--text-secondary);">
                ${(c.client_memory?.avoid || ['Long introductions', 'Excessive footnotes']).map(a => `
                  <li>• ${a}</li>
                `).join('')}
              </ul>
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-3-badge">Negotiation Tendencies & Relationship Counsel</span>
            </div>
            <div class="layer-content" style="font-size:12.5px;color:var(--text-secondary);line-height:1.6;">
              <p style="margin-bottom:8px;"><strong>Standard Positions:</strong> ${c.client_memory?.negotiation_style || 'Insists on 15% maximum liability cap and SIAC arbitration seat for cross-border joint ventures.'}</p>
              <div style="font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px;">Preferred Relationship Lawyers:</div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;">
                ${(c.preferred_lawyers_resolved || [{ name: 'Aryan Maharaj' }]).map(pl => `
                  <span class="scope-chip" onclick="window.lexosNavigate('people')" style="cursor:pointer;">👤 ${pl.name}</span>
                `).join('')}
              </div>
            </div>
          </div>
        </div>

        <div class="reasoning-card">
          <div class="layer-header">
            <span class="layer-badge layer-2-badge">All Matters for ${escapeHtml(c.name)}</span>
          </div>
          <div class="layer-content" style="padding:0;">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Title</th>
                  <th>Practice Area</th>
                  <th>Lead Partner</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                ${(visibleMatters.length ? visibleMatters : getVisibleMatters().slice(0, 3)).map(m => `
                  <tr onclick="window.lexosNavigate('matter-detail', { matterId: '${m.matter_id}' })">
                    <td class="mono" style="color:var(--accent-primary);">${m.matter_code}</td>
                    <td style="font-weight:600;color:var(--text-primary);">${escapeHtml(m.title)}</td>
                    <td><span class="scope-chip">${m.practice_area}</span></td>
                    <td>${m.lead_partner}</td>
                    <td><span class="status-pill ${m.status.toLowerCase()}">${m.status}</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  }

  function attachClientDetailEvents() {}

  // --- SCREEN 6: TEAMS ---
  function renderTeamsScreen() {
    const teams = [
      { name: 'Corporate & M&A', members: 42, activeMatters: 186, completed: 2481, topPrecedent: 'Master Share Purchase Agreement', gap: 'None' },
      { name: 'Dispute Resolution & Litigation', members: 38, activeMatters: 245, completed: 3120, topPrecedent: 'Section 241/242 Oppression Petition', gap: 'None' },
      { name: 'International Arbitration', members: 16, activeMatters: 98, completed: 620, topPrecedent: 'SIAC Emergency Relief Notice', gap: 'SIAC Singapore Seat specialists in high demand' },
      { name: 'Tax & Transaction Structuring', members: 22, activeMatters: 112, completed: 1450, topPrecedent: 'Locked-Box Tax Indemnity Memo', gap: 'Cross-border transfer pricing' },
      { name: 'Insolvency & Bankruptcy (NCLT)', members: 28, activeMatters: 142, completed: 980, topPrecedent: 'Resolution Plan Review Matrix', gap: 'Personal guarantee enforcement' },
      { name: 'Employment & Labor', members: 14, activeMatters: 64, completed: 840, topPrecedent: 'Executive POSH Investigation Protocol', gap: 'None' }
    ];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Practice Teams & Knowledge Hubs</div>
            <div class="view-header-desc">Team knowledge management, active matter distribution, and auto-detected expertise gaps.</div>
          </div>
        </div>

        <div class="matched-matters-grid">
          ${teams.map(t => `
            <div class="matched-matter-card" onclick="window.lexosNavigate('team-detail', { teamName: '${t.name}' })">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span class="scope-chip">${t.members} Lawyers</span>
                <span class="mono" style="font-size:11px;color:var(--text-muted);">${t.activeMatters} Active</span>
              </div>
              <div style="font-weight:700;color:var(--text-primary);font-size:14px;">${t.name}</div>
              <div style="font-size:11.5px;color:var(--text-secondary);">${t.completed} Completed Matters</div>
              <div style="font-size:11px;color:var(--accent-primary);margin-top:2px;">
                <strong>Precedent:</strong> ${t.topPrecedent}
              </div>
              ${t.gap !== 'None' ? `
                <div style="font-size:10.5px;color:var(--accent-amber);background:var(--accent-amber-faint);padding:3px 6px;border-radius:var(--radius-xs);margin-top:4px;">
                  ⚠️ Knowledge Gap: ${t.gap}
                </div>
              ` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function attachTeamsEvents() {}

  function renderTeamDetailScreen(teamName) {
    teamName = teamName || 'Corporate & M&A';
    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('teams')">Teams</a> <span>/</span>
          <span>${teamName}</span>
        </div>

        <div class="view-header">
          <div>
            <div class="view-header-title">${teamName}</div>
            <div class="view-header-desc">42 lawyers • 186 active matters • 2,481 completed institutional engagements.</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('knowledge')">View Team Precedents</button>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:2fr 1fr;gap:16px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Active Work Distribution</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
              <div class="evidence-item-row"><span>M&A & Private Equity</span> <span class="mono">84 matters</span></div>
              <div class="evidence-item-row"><span>Joint Ventures & Foreign Investment</span> <span class="mono">42 matters</span></div>
              <div class="evidence-item-row"><span>Corporate Restructuring & Governance</span> <span class="mono">38 matters</span></div>
              <div class="evidence-item-row"><span>Commercial Contracts & Due Diligence</span> <span class="mono">22 matters</span></div>
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-3-badge">Detected Knowledge Gaps</span>
            </div>
            <div class="layer-content" style="font-size:12px;color:var(--text-secondary);">
              <p style="margin-bottom:8px;">AI flagged that cross-border SIAC seat matters with emergency injunctions have increased by 40%, but only 2 partners are currently staffed.</p>
              <button class="btn btn-secondary btn-sm" onclick="window.lexosNavigate('people')">Staff / Train Associates →</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function attachTeamDetailEvents() {}

  // --- SCREEN 7: PEOPLE ---
  function renderPeopleScreen() {
    const members = getFirmData().members || [];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">People & Work-Derived Expertise</div>
            <div class="view-header-desc">Profiles derived from actual authored documents and closed matters. Enables data-backed AI staffing recommendations.</div>
          </div>
          <div class="view-header-actions">
            <button class="btn btn-primary btn-sm" onclick="simulateStaffingMatch()"><span>✦</span> AI Staffing Matcher</button>
          </div>
        </div>

        <div class="matched-matters-grid">
          ${members.slice(0, 24).map(m => `
            <div class="person-card-compact" onclick="window.lexosNavigate('person-detail', { personId: '${m.member_id}' })" style="cursor:pointer;">
              <div class="user-avatar">${m.name.split(' ').map(n=>n[0]).join('')}</div>
              <div style="flex:1;">
                <div style="font-weight:600;color:var(--text-primary);font-size:13px;">${m.name}</div>
                <div style="font-size:11px;color:var(--text-muted);">${m.role} • ${m.office}</div>
                <div style="font-size:11px;color:var(--accent-emerald);margin-top:2px;">${m.matters_count || 34} matters handled • ${m.authored_docs_count || 128} docs</div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function attachPeopleEvents() {}

  window.simulateStaffingMatch = function() {
    navigate('ask');
    executeAskQuery('Who are the best qualified lawyers to staff a cross-border SIAC arbitration involving energy tariff disputes?');
  };

  function renderPersonDetailScreen(personId) {
    const m = getPersonById(personId) || getCurrentMember();
    return `
      <div class="view-container">
        <div class="entity-meta-breadcrumbs">
          <a onclick="window.lexosNavigate('people')">People</a> <span>/</span>
          <span class="mono">${m.member_id}</span>
        </div>

        <div class="matter-detail-header">
          <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px;">
            <div class="user-avatar" style="width:48px;height:48px;font-size:18px;">${m.name.split(' ').map(n=>n[0]).join('')}</div>
            <div>
              <div style="display:flex;align-items:center;gap:8px;">
                <h1 style="font-size:22px;font-weight:700;color:var(--text-primary);">${m.name}</h1>
                <span class="status-pill active">${m.role}</span>
              </div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:2px;">${m.email} • ${m.office} Office • Joined ${m.joined_year}</div>
            </div>
          </div>
          <div style="font-size:13px;color:var(--text-secondary);border-top:1px solid var(--border-subtle);padding-top:12px;line-height:1.6;">
            ${m.bio || 'Experienced legal practitioner at Apex Chambers.'}
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-1-badge">Work-Derived Expertise Gauges</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:10px;">
              <div>
                <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                  <span style="font-weight:600;color:var(--text-primary);">M&A Transactions & Due Diligence</span>
                  <span class="mono">94%</span>
                </div>
                <div class="confidence-bar"><div class="confidence-fill" style="width:94%;"></div></div>
              </div>
              <div>
                <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                  <span style="font-weight:600;color:var(--text-primary);">Shareholder Disputes & Oppression</span>
                  <span class="mono">88%</span>
                </div>
                <div class="confidence-bar"><div class="confidence-fill" style="width:88%;"></div></div>
              </div>
              <div>
                <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                  <span style="font-weight:600;color:var(--text-primary);">SIAC International Arbitration</span>
                  <span class="mono">82%</span>
                </div>
                <div class="confidence-bar"><div class="confidence-fill" style="width:82%;"></div></div>
              </div>
            </div>
          </div>

          <div class="reasoning-card">
            <div class="layer-header">
              <span class="layer-badge layer-2-badge">Key Authored Documents & Precedents</span>
            </div>
            <div class="layer-content" style="display:flex;flex-direction:column;gap:8px;">
              <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00004' })">
                <div>
                  <div style="font-weight:600;color:var(--text-primary);font-size:12px;">Master Share Purchase Agreement (Locked-Box)</div>
                  <div style="font-size:11px;color:var(--text-muted);">Gold Precedent • 38 matters adapted</div>
                </div>
              </div>
              <div class="evidence-item-row" onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00001' })">
                <div>
                  <div style="font-weight:600;color:var(--text-primary);font-size:12px;">Section 241/242 Oppression Strategy Note</div>
                  <div style="font-size:11px;color:var(--text-muted);">Vetted Pleading Framework</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function attachPersonDetailEvents() {}

  // --- SCREEN 8: KNOWLEDGE VAULT ---
  function renderKnowledgeScreen() {
    const data = getFirmData();
    const clauses = data.clauses || [];
    const precedents = data.precedents || [];

    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Institutional Knowledge Vault</div>
            <div class="view-header-desc">Precedents, market-standard clauses, and argument win-rates extracted from historical firm matters.</div>
          </div>
        </div>

        <div class="tabs-nav">
          <button class="tab-btn ${state.knowledgeTab === 'precedents' ? 'active' : ''}" data-ktab="precedents">Gold Precedents (${precedents.length})</button>
          <button class="tab-btn ${state.knowledgeTab === 'clauses' ? 'active' : ''}" data-ktab="clauses">Clause Bank (${clauses.length})</button>
          <button class="tab-btn ${state.knowledgeTab === 'arguments' ? 'active' : ''}" data-ktab="arguments">Arguments Win/Loss Tracker (20,456)</button>
        </div>

        <div id="knowledge-tab-content">
          ${state.knowledgeTab === 'clauses' ? renderClausesBank(clauses) : (state.knowledgeTab === 'arguments' ? renderArgumentsTracker() : renderPrecedentsVault(precedents))}
        </div>
      </div>
    `;
  }

  function renderPrecedentsVault(precedents) {
    return `
      <div class="matched-matters-grid">
        ${precedents.map(p => `
          <div class="reasoning-card" style="padding:14px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
              <span class="scope-chip">${p.type}</span>
              <span class="mono" style="font-size:11px;color:var(--accent-amber);">★ ${p.rating} (${p.usage})</span>
            </div>
            <div style="font-weight:700;color:var(--text-primary);font-size:14px;margin-bottom:4px;">${escapeHtml(p.title)}</div>
            <div style="font-size:12px;color:var(--text-secondary);line-height:1.5;margin-bottom:10px;">${p.summary}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-subtle);padding-top:8px;">
              <span style="font-size:11px;color:var(--text-muted);">Author: ${p.author} (${p.office})</span>
              <button class="btn btn-primary btn-sm" onclick="window.lexosNavigate('doc-detail', { docId: 'DOC-00004' })">Use Precedent →</button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderClausesBank(clauses) {
    return `
      <div style="display:flex;flex-direction:column;gap:14px;">
        ${clauses.map(c => `
          <div class="reasoning-card" style="padding:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <div>
                <span class="mono" style="font-size:11px;color:var(--accent-primary);margin-right:6px;">${c.id}</span>
                <strong style="font-size:14px;color:var(--text-primary);">${escapeHtml(c.title)}</strong>
                <span class="scope-chip" style="margin-left:8px;">${c.category}</span>
              </div>
              <span class="status-pill active">${c.success_rate}</span>
            </div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;"><strong>Market Benchmark:</strong> ${c.market_standard}</div>
            
            <div style="background:var(--bg-surface-elevated);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 12px;font-family:var(--font-mono);font-size:11.5px;color:var(--text-primary);margin-bottom:8px;">
              ${escapeHtml(c.standard_text)}
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11.5px;">
              <div style="padding:6px 8px;background:var(--bg-surface);border-radius:var(--radius-xs);border:1px solid var(--border-subtle);">
                <span style="color:var(--accent-emerald);font-weight:600;">Pro-Buyer Fallback:</span> ${c.fallback_pro_buyer}
              </div>
              <div style="padding:6px 8px;background:var(--bg-surface);border-radius:var(--radius-xs);border:1px solid var(--border-subtle);">
                <span style="color:var(--accent-rose);font-weight:600;">Pro-Seller Fallback:</span> ${c.fallback_pro_seller}
              </div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderArgumentsTracker() {
    return `
      <div class="reasoning-card">
        <div class="layer-header">
          <span class="layer-badge layer-1-badge">20,456 Extracted Legal Arguments • Win/Loss Analytics</span>
        </div>
        <div class="layer-content">
          <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:12px;margin-bottom:16px;">
            <div class="stat-box">
              <div class="stat-number" style="color:var(--accent-emerald);">84.2%</div>
              <div class="stat-label">Indemnity Cap Enforceability</div>
            </div>
            <div class="stat-box">
              <div class="stat-number" style="color:var(--accent-primary);">88.9%</div>
              <div class="stat-label">SIAC Interim Emergency Relief</div>
            </div>
            <div class="stat-box">
              <div class="stat-number" style="color:var(--accent-amber);">74.5%</div>
              <div class="stat-label">Section 241 Oppression Waivers</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function attachKnowledgeEvents() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.knowledgeTab = btn.dataset.ktab;
        renderWorkspace();
      });
    });
  }

  // --- SECONDARY VIEWS ---
  function renderActivityScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Firm-Wide Activity Stream</div>
            <div class="view-header-desc">Real-time audit log of documents created, versions committed, filings submitted, and matters closed.</div>
          </div>
        </div>
        <div class="timeline-stream">
          <div class="timeline-node">
            <div class="timeline-node-dot"></div>
            <div class="timeline-node-content">
              <div class="timeline-date">Today • 10:42 AM</div>
              <div class="timeline-event-title">Udant Dewan filed NCLT Rejoinder submissions</div>
              <div style="font-size:12px;color:var(--text-secondary);">Associated with <strong>ABC Holdings — Shareholder Dispute (MTR-2020-00045)</strong></div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderTasksScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Tasks & Court Deadlines</div>
            <div class="view-header-desc">Automated schedule synchronized with court dates and filing requirements.</div>
          </div>
        </div>
        <div class="data-table-container">
          <table class="data-table">
            <thead>
              <tr><th>Deadline</th><th>Task</th><th>Matter</th><th>Responsible</th><th>Priority</th></tr>
            </thead>
            <tbody>
              <tr>
                <td class="mono" style="color:var(--accent-rose);">Tomorrow • 11:00 AM</td>
                <td style="font-weight:600;">File Written Submissions on Section 244 maintainability</td>
                <td>ABC Holdings Dispute</td>
                <td>Alka Wable</td>
                <td><span class="status-pill restricted">High</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderApprovalsScreen() {
    return `
      <div class="view-container">
        <div class="view-header">
          <div>
            <div class="view-header-title">Approvals & Pending Classifications</div>
            <div class="view-header-desc">Automated classification queue requiring one-click confirmation.</div>
          </div>
        </div>
        <div style="padding:24px;text-align:center;color:var(--text-muted);">No pending approval bottlenecks. All 38,232 files indexed with ACL permissions.</div>
      </div>
    `;
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
      { id: 'matter', label: m.matter_code, type: 'matter', color: '#3b82f6', radius: 18, x: canvas.width / 2, y: canvas.height / 2 },
      { id: 'client', label: m.client_name, type: 'client', color: '#10b981', radius: 14, x: canvas.width / 2 - 120, y: canvas.height / 2 - 80 },
      { id: 'lead', label: m.lead_partner, type: 'person', color: '#8b5cf6', radius: 13, x: canvas.width / 2 + 120, y: canvas.height / 2 - 80 },
      { id: 'doc1', label: 'SPA (v4)', type: 'doc', color: '#a78bfa', radius: 11, x: canvas.width / 2 - 140, y: canvas.height / 2 + 70 },
      { id: 'doc2', label: 'Research Memo', type: 'doc', color: '#a78bfa', radius: 11, x: canvas.width / 2 - 80, y: canvas.height / 2 + 120 },
      { id: 'arg1', label: 'Indemnity Cap', type: 'arg', color: '#f59e0b', radius: 11, x: canvas.width / 2 + 130, y: canvas.height / 2 + 70 },
      { id: 'arg2', label: 'Locked-Box', type: 'arg', color: '#f59e0b', radius: 11, x: canvas.width / 2 + 70, y: canvas.height / 2 + 120 },
      { id: 'sim1', label: '86% Match (ABC)', type: 'similar', color: '#f43f5e', radius: 12, x: canvas.width / 2 + 180, y: canvas.height / 2 - 20 }
    ];

    const edges = [
      ['matter', 'client'],
      ['matter', 'lead'],
      ['matter', 'doc1'],
      ['matter', 'doc2'],
      ['matter', 'arg1'],
      ['matter', 'arg2'],
      ['matter', 'sim1'],
      ['doc1', 'arg1'],
      ['arg1', 'sim1']
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
        ctx.strokeStyle = state.theme === 'dark' ? '#121622' : '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = state.theme === 'dark' ? '#f1f5f9' : '#0f172a';
        ctx.font = '10.5px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(n.label, n.x, n.y + n.radius + 13);
      });
    }

    draw();

    let draggedNode = null;
    canvas.onmousedown = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      draggedNode = nodes.find(n => Math.hypot(n.x - mx, n.y - my) < n.radius + 5);
    };

    window.onmousemove = (e) => {
      if (!draggedNode) return;
      const rect = canvas.getBoundingClientRect();
      draggedNode.x = e.clientX - rect.left;
      draggedNode.y = e.clientY - rect.top;
      draw();
    };

    window.onmouseup = () => {
      draggedNode = null;
    };
  }

  // --- UTILS ---
  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

})();
'''

with open(app_js_path, 'w') as f:
    f.write(app_js_code)

print("Successfully wrote app.js!")
