// Apex DMS Frontend — Single-Page Application
const API = ''; // Relative — uses Vite proxy in dev, Go backend in prod
let token = localStorage.getItem('apex_token');
let user = JSON.parse(localStorage.getItem('apex_user') || 'null');
let firmId = localStorage.getItem('apex_firm_id');
let currentPage = 'dashboard';

// --- API helpers ---
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  try {
    const res = await fetch(`${API}${path}`, { ...opts, headers });
    if (res.status === 401) { logout(); return null; }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      return err;
    }
    return res.json();
  } catch (e) {
    console.error('API error:', e);
    return { error: e.message };
  }
}
const get = (p) => api(p);
const post = (p, b) => api(p, { method: 'POST', body: JSON.stringify(b) });
const patch = (p, b) => api(p, { method: 'PATCH', body: JSON.stringify(b) });
const del = (p) => api(p, { method: 'DELETE' });

// --- Auth ---
async function login(email, password) {
  const data = await post('/auth/login', { email, password });
  if (data?.access_token) {
    token = data.access_token;
    user = data.user;
    firmId = data.membership.firm_id;
    localStorage.setItem('apex_token', token);
    localStorage.setItem('apex_user', JSON.stringify(user));
    localStorage.setItem('apex_firm_id', firmId);
    render();
  }
  return data;
}

async function register(email, password, name, firmName) {
  const data = await post('/auth/register', { email, password, display_name: name, firm_name: firmName });
  if (data?.access_token) {
    token = data.access_token;
    user = data.user;
    firmId = data.firm.firm_id;
    localStorage.setItem('apex_token', token);
    localStorage.setItem('apex_user', JSON.stringify(user));
    localStorage.setItem('apex_firm_id', firmId);
    render();
  }
  return data;
}

function logout() {
  token = null; user = null; firmId = null;
  localStorage.removeItem('apex_token');
  localStorage.removeItem('apex_user');
  localStorage.removeItem('apex_firm_id');
  render();
}

// --- Render ---
function render() {
  const app = document.getElementById('app');
  if (!token) { app.innerHTML = renderAuth(); bindAuth(); return; }
  app.innerHTML = renderLayout();
  bindNav();
  navigateTo(currentPage);
}

function renderAuth() {
  return `<div class="auth-page">
    <div class="auth-card fade-in" id="auth-card">
      <div style="text-align:center;margin-bottom:20px">
        <div style="width:40px;height:40px;background:var(--accent);border-radius:10px;display:inline-grid;place-items:center;font-weight:700;font-size:16px;color:#fff">A</div>
      </div>
      <div class="auth-title">Welcome back</div>
      <div class="auth-subtitle">Sign in to Apex Chambers DMS</div>
      <div id="auth-error" style="color:var(--red);font-size:12px;text-align:center;margin-bottom:12px;display:none"></div>
      <form id="login-form">
        <div class="form-group"><label>Email</label><input type="email" id="auth-email" value="shoaib@apexchambers.in" required></div>
        <div class="form-group"><label>Password</label><input type="password" id="auth-pass" value="SecurePass123!" required></div>
        <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:10px">Sign In</button>
      </form>
      <div class="auth-switch">No account? <a id="switch-register">Create one</a></div>
    </div>
  </div>`;
}

function renderLayout() {
  return `<div class="layout">
    <aside class="sidebar">
      <div class="sidebar-brand"><div class="logo">A</div><span>Apex DMS</span></div>
      <nav class="sidebar-nav">
        <div class="nav-section">Overview</div>
        <div class="nav-item active" data-page="dashboard"><span class="icon">◫</span>Dashboard</div>
        <div class="nav-section">Work</div>
        <div class="nav-item" data-page="matters"><span class="icon">◆</span>Matters</div>
        <div class="nav-item" data-page="documents"><span class="icon">◧</span>Documents</div>
        <div class="nav-item" data-page="clients"><span class="icon">◉</span>Clients</div>
        <div class="nav-section">AI</div>
        <div class="nav-item" data-page="chat"><span class="icon">◈</span>Assistant</div>
        <div class="nav-item" data-page="docsearch"><span class="icon">⚖</span>Doc Search</div>
        <div class="nav-section">System</div>
        <div class="nav-item" data-page="team"><span class="icon">◎</span>Team</div>
      </nav>
      <div class="sidebar-user">
        <div class="avatar">${user?.display_name?.[0] || 'U'}</div>
        <div class="user-info">
          <div class="user-name">${user?.display_name || 'User'}</div>
          <div class="user-role">owner</div>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="logout()" title="Sign out" style="font-size:14px">⏻</button>
      </div>
    </aside>
    <main class="main" id="main-content"></main>
  </div>`;
}

// --- Navigation ---
function bindNav() {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => navigateTo(el.dataset.page));
  });
}

async function navigateTo(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  const main = document.getElementById('main-content');
  if (!main) return;
  main.innerHTML = '<div style="padding:40px;color:var(--text-3)">Loading...</div>';

  switch(page) {
    case 'dashboard': await renderDashboard(main); break;
    case 'matters':   await renderMatters(main); break;
    case 'documents': await renderDocuments(main); break;
    case 'clients':   await renderClients(main); break;
    case 'chat':      await renderChat(main); break;
    case 'docsearch': await renderDocSearch(main); break;
    case 'team':      await renderTeam(main); break;
  }
}

// --- Dashboard ---
async function renderDashboard(el) {
  const [matters, docs, convs, clients] = await Promise.all([
    get('/matters/'), get('/documents/'), get('/conversations/'), get('/matters/clients')
  ]);
  const m = matters?.matters || [];
  const d = docs?.documents || [];
  const c = convs?.conversations || [];
  const cl = clients?.clients || [];

  el.innerHTML = `<div class="fade-in">
    <div class="page-header"><div><div class="page-title">Dashboard</div><div class="page-subtitle">Welcome back, ${user?.display_name}</div></div></div>
    <div class="stats-row">
      <div class="stat-card"><div class="stat-value">${m.length}</div><div class="stat-label">Active Matters</div></div>
      <div class="stat-card"><div class="stat-value">${d.length}</div><div class="stat-label">Documents</div></div>
      <div class="stat-card"><div class="stat-value">${c.length}</div><div class="stat-label">Conversations</div></div>
      <div class="stat-card"><div class="stat-value">${cl.length}</div><div class="stat-label">Clients</div></div>
    </div>
    <div class="page-header"><div><div class="page-title" style="font-size:16px">Recent Matters</div></div></div>
    ${m.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Code</th><th>Title</th><th>Client</th><th>Status</th><th>Updated</th></tr></thead>
      <tbody>${m.slice(0,5).map(ma => `<tr style="cursor:pointer" onclick="navigateTo('matters')">
        <td class="td-code">${ma.matter_code}</td>
        <td>${ma.title}</td>
        <td style="color:var(--text-2)">${ma.client_name || '—'}</td>
        <td><span class="badge badge-${ma.status}">${ma.status}</span></td>
        <td style="color:var(--text-3);font-size:12px">${timeAgo(ma.updated_at)}</td>
      </tr>`).join('')}</tbody>
    </table></div>` : '<div class="empty"><div class="empty-icon">◆</div><div class="empty-text">No matters yet</div></div>'}
    ${d.length ? `<div style="margin-top:24px"><div class="page-header"><div><div class="page-title" style="font-size:16px">Recent Documents</div></div></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Type</th><th>Matter</th><th>Size</th></tr></thead>
      <tbody>${d.slice(0,5).map(doc => `<tr>
        <td style="font-weight:500">${doc.title}</td>
        <td><span class="badge badge-draft">${doc.document_type || 'file'}</span></td>
        <td style="color:var(--text-2)">${doc.matter_title || '—'}</td>
        <td style="color:var(--text-3)">${formatSize(doc.current_size)}</td>
      </tr>`).join('')}</tbody>
    </table></div></div>` : ''}
  </div>`;
}

// --- Matters ---
async function renderMatters(el) {
  const data = await get('/matters/');
  const m = data?.matters || [];
  el.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div><div class="page-title">Matters</div><div class="page-subtitle">${m.length} matters</div></div>
      <button class="btn btn-primary" onclick="showCreateMatter()">+ New Matter</button>
    </div>
    ${m.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Code</th><th>Title</th><th>Client</th><th>Lead</th><th>Docs</th><th>Status</th><th></th></tr></thead>
      <tbody>${m.map(ma => `<tr>
        <td class="td-code">${ma.matter_code}</td>
        <td style="font-weight:500">${ma.title}</td>
        <td style="color:var(--text-2)">${ma.client_name || '—'}</td>
        <td style="color:var(--text-2)">${ma.lead_name || '—'}</td>
        <td>${ma.document_count}</td>
        <td><span class="badge badge-${ma.status}">${ma.status}</span></td>
        <td><button class="btn btn-ghost btn-sm" onclick="toggleStatus('${ma.matter_id}','${ma.status}')">⋯</button></td>
      </tr>`).join('')}</tbody>
    </table></div>` : '<div class="empty"><div class="empty-icon">◆</div><div class="empty-text">Create your first matter</div><button class="btn btn-primary" onclick="showCreateMatter()">+ New Matter</button></div>'}
  </div>`;
}

async function showCreateMatter() {
  const areas = await get('/matters/practice-areas');
  const clients = await get('/matters/clients');
  const pa = areas?.practice_areas || [];
  const cl = clients?.clients || [];
  showModal('New Matter', `
    <div class="form-group"><label>Title</label><input type="text" id="m-title" placeholder="e.g., MSEDCL Change in Law Petition"></div>
    <div class="form-group"><label>Description</label><textarea id="m-desc" placeholder="Brief description..."></textarea></div>
    <div class="form-group"><label>Client</label><select id="m-client"><option value="">— Select —</option>${cl.map(c=>`<option value="${c.client_id}">${c.name}</option>`).join('')}</select></div>
    <div class="form-group"><label>Practice Area</label><select id="m-area"><option value="">— Select —</option>${pa.map(a=>`<option value="${a.area_id}">${a.name}</option>`).join('')}</select></div>
  `, async () => {
    const body = { title: document.getElementById('m-title').value, description: document.getElementById('m-desc').value || undefined };
    const cid = document.getElementById('m-client').value;
    if (cid) body.client_id = cid;
    const aid = document.getElementById('m-area').value;
    if (aid) body.practice_area_id = aid;
    await post('/matters/', body);
    closeModal();
    navigateTo('matters');
  });
}

async function toggleStatus(id, current) {
  const next = current === 'active' ? 'closed' : 'active';
  await patch(`/matters/${id}/status`, { status: next });
  navigateTo('matters');
}

// --- Documents ---
async function renderDocuments(el) {
  const data = await get('/documents/');
  const d = data?.documents || [];
  el.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div><div class="page-title">Documents</div><div class="page-subtitle">${d.length} documents</div></div>
    </div>
    ${d.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Matter</th><th>Type</th><th>Size</th><th>Uploaded</th></tr></thead>
      <tbody>${d.map(doc => `<tr>
        <td style="font-weight:500">${doc.title}</td>
        <td style="color:var(--text-2)">${doc.matter_title || '—'}</td>
        <td><span class="badge badge-draft">${doc.document_type || 'file'}</span></td>
        <td style="color:var(--text-3)">${formatSize(doc.current_size)}</td>
        <td style="color:var(--text-3);font-size:12px">${timeAgo(doc.created_at)}</td>
      </tr>`).join('')}</tbody>
    </table></div>` : '<div class="empty"><div class="empty-icon">◧</div><div class="empty-text">No documents uploaded yet</div><div style="color:var(--text-3);font-size:12px">Upload documents through the API or matter context</div></div>'}
  </div>`;
}

// --- Clients ---
async function renderClients(el) {
  const data = await get('/matters/clients');
  const c = data?.clients || [];
  el.innerHTML = `<div class="fade-in">
    <div class="page-header">
      <div><div class="page-title">Clients</div><div class="page-subtitle">${c.length} clients</div></div>
      <button class="btn btn-primary" onclick="showCreateClient()">+ New Client</button>
    </div>
    ${c.length ? `<div class="card-grid">${c.map(cl => `<div class="card">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <div style="width:36px;height:36px;background:var(--accent);border-radius:8px;display:grid;place-items:center;font-weight:600;font-size:14px;color:#fff">${cl.name[0]}</div>
        <div><div style="font-weight:500;font-size:14px">${cl.name}</div><div style="font-size:11px;color:var(--text-3);text-transform:capitalize">${cl.client_type}</div></div>
      </div>
      ${cl.contact_email ? `<div style="font-size:12px;color:var(--text-2)">✉ ${cl.contact_email}</div>` : ''}
    </div>`).join('')}</div>` : '<div class="empty"><div class="empty-icon">◉</div><div class="empty-text">No clients yet</div></div>'}
  </div>`;
}

function showCreateClient() {
  showModal('New Client', `
    <div class="form-group"><label>Name</label><input type="text" id="c-name" placeholder="e.g., MSEDCL"></div>
    <div class="form-group"><label>Type</label><select id="c-type"><option value="organisation">Organisation</option><option value="individual">Individual</option></select></div>
    <div class="form-group"><label>Email</label><input type="email" id="c-email" placeholder="contact@example.com"></div>
  `, async () => {
    await post('/matters/clients', {
      name: document.getElementById('c-name').value,
      client_type: document.getElementById('c-type').value,
      contact_email: document.getElementById('c-email').value || undefined
    });
    closeModal();
    navigateTo('clients');
  });
}

// --- Chat ---
let activeConvId = null;
async function renderChat(el) {
  const data = await get('/conversations/');
  const convs = data?.conversations || [];
  el.innerHTML = `<div class="fade-in" style="display:grid;grid-template-columns:220px 1fr;gap:0;height:calc(100vh - 48px)">
    <div style="border-right:1px solid var(--border);padding:12px;overflow-y:auto">
      <button class="btn btn-primary btn-sm" style="width:100%;justify-content:center;margin-bottom:12px" onclick="newConversation()">+ New Chat</button>
      ${convs.map(c => `<div class="nav-item ${activeConvId===c.conversation_id?'active':''}" onclick="openConversation('${c.conversation_id}')" style="font-size:12px;padding:6px 10px">
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.title || 'Untitled'}</span>
        <span style="font-size:10px;color:var(--text-3)">${c.message_count}</span>
      </div>`).join('')}
      ${!convs.length ? '<div style="text-align:center;padding:20px;color:var(--text-3);font-size:12px">No conversations</div>' : ''}
    </div>
    <div id="chat-panel" style="display:flex;flex-direction:column;padding:16px">
      ${activeConvId ? '' : '<div class="empty" style="flex:1;display:grid;place-items:center"><div><div class="empty-icon">◈</div><div class="empty-text">Select or start a conversation</div></div></div>'}
    </div>
  </div>`;
  if (activeConvId) loadMessages(activeConvId);
}

async function newConversation() {
  const c = await post('/conversations/', { title: 'New Research' });
  if (c) { activeConvId = c.conversation_id; navigateTo('chat'); }
}

async function openConversation(id) {
  activeConvId = id;
  navigateTo('chat');
}

async function loadMessages(convId) {
  const data = await get(`/conversations/${convId}/messages`);
  const msgs = data?.messages || [];
  const panel = document.getElementById('chat-panel');
  if (!panel) return;
  panel.innerHTML = `
    <div class="chat-messages" id="chat-msgs">${msgs.map(m => `
      <div class="msg msg-${m.role}">
        ${formatMd(m.content)}
        <div class="msg-meta">${new Date(m.created_at).toLocaleTimeString()}</div>
      </div>
    `).join('')}</div>
    <div class="chat-input-row">
      <textarea id="chat-input" placeholder="Ask about your documents..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat()}"></textarea>
      <button class="btn btn-primary" onclick="sendChat()">Send</button>
    </div>
  `;
  const msgs_el = document.getElementById('chat-msgs');
  if (msgs_el) msgs_el.scrollTop = msgs_el.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  if (!input?.value.trim() || !activeConvId) return;
  const content = input.value.trim();
  input.value = '';
  // Optimistic: add user message
  const msgs_el = document.getElementById('chat-msgs');
  msgs_el.innerHTML += `<div class="msg msg-user fade-in">${escHtml(content)}</div>`;
  msgs_el.scrollTop = msgs_el.scrollHeight;
  // Show typing indicator
  msgs_el.innerHTML += `<div class="msg msg-assistant fade-in" id="typing-indicator"><span class="typing-dots">●●●</span> Thinking...</div>`;
  msgs_el.scrollTop = msgs_el.scrollHeight;
  // Send
  const data = await post(`/conversations/${activeConvId}/messages`, { content });
  // Remove typing indicator
  document.getElementById('typing-indicator')?.remove();
  if (data?.assistant_message) {
    msgs_el.innerHTML += `<div class="msg msg-assistant fade-in">${formatMd(data.assistant_message.content)}<div class="msg-meta">${new Date().toLocaleTimeString()}</div></div>`;
    msgs_el.scrollTop = msgs_el.scrollHeight;
  }
}

// --- Doc Search (integrated from port 8001) ---
let docSearchPdfDoc = null;
let docSearchCurrentPage = 1;
let docSearchTotalPages = 0;
let docSearchScale = 1.4;

async function renderDocSearch(el) {
  el.innerHTML = `<div class="fade-in ds-layout">
    <div class="ds-left">
      <div class="ds-query-panel">
        <div class="ds-title">⚖ Legal Doc Search</div>
        <textarea id="ds-query" rows="3" placeholder="Ask a question about the legal documents…"></textarea>
        <div class="ds-row">
          <button class="btn btn-primary" id="ds-ask-btn" onclick="doDocSearch()" style="flex:1;justify-content:center">Ask</button>
          <select id="ds-k-select" class="ds-select">
            <option value="5">Top 5</option>
            <option value="8" selected>Top 8</option>
            <option value="12">Top 12</option>
          </select>
        </div>
        <p class="ds-hint">Ctrl + Enter to submit</p>
      </div>
      <div id="ds-results" class="ds-results">
        <div class="ds-status">Enter a query and press Ask.</div>
      </div>
    </div>
    <div class="ds-right">
      <div id="ds-pdf-placeholder" class="ds-placeholder">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
        </svg>
        <p>Click a source citation to view the PDF</p>
      </div>
      <div id="ds-viewer-wrap" class="ds-viewer hidden">
        <div class="ds-toolbar">
          <span class="ds-doc-title" id="ds-doc-title"></span>
          <button onclick="dsChangePage(-1)" id="ds-btn-prev">◀</button>
          <span id="ds-page-info">— / —</span>
          <button onclick="dsChangePage(+1)" id="ds-btn-next">▶</button>
          <button onclick="dsZoomIn()">+</button>
          <button onclick="dsZoomOut()">−</button>
          <button onclick="dsCloseViewer()">✕</button>
        </div>
        <div id="ds-canvas-container" class="ds-canvas-container">
          <canvas id="ds-pdf-canvas"></canvas>
        </div>
      </div>
    </div>
  </div>`;

  // Bind keyboard shortcut
  document.getElementById('ds-query')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doDocSearch(); }
  });
}

async function doDocSearch() {
  const query = document.getElementById('ds-query')?.value.trim();
  if (!query) return;
  const k = parseInt(document.getElementById('ds-k-select')?.value || '8', 10);
  const btn = document.getElementById('ds-ask-btn');
  if (btn) btn.disabled = true;

  const results = document.getElementById('ds-results');
  results.innerHTML = '<div class="ds-status"><span class="ds-spinner"></span>Searching & asking LLM…</div>';

  try {
    const res = await fetch('/api/doc-search/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, k }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderDocSearchResults(data, query);
  } catch (e) {
    results.innerHTML = `<div class="ds-status" style="color:var(--red)">Error: ${e.message}</div>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderDocSearchResults(data, query) {
  const results = document.getElementById('ds-results');
  results.innerHTML = '';

  // Latency chips
  const lat = data.latency_ms || {};
  const latDiv = document.createElement('div');
  latDiv.className = 'ds-latency';
  latDiv.innerHTML = [
    dsChip(`Retrieve ${lat.retrieve_ms}ms`, lat.retrieve_ms < 500),
    dsChip(`LLM ${lat.llm_ms}ms`, lat.llm_ms < 3000),
    dsChip(`Total ${lat.total_ms}ms`, lat.total_ms < 4000),
  ].join('');
  if (data.provider) {
    const colors = {groq:'#10b981', nvidia:'#76b900', gemini:'#4285f4', extractive:'#f59e0b'};
    latDiv.innerHTML += `<span class="ds-chip" style="color:${colors[data.provider]||'var(--text-3)'};border-color:${colors[data.provider]||'var(--border)'}">${escHtml(data.provider)}</span>`;
  }
  results.appendChild(latDiv);

  // Answer
  const ansCard = document.createElement('div');
  ansCard.className = 'ds-answer-card';
  ansCard.innerHTML = `<div class="ds-card-label">Answer</div>`;
  if (data.abstained || !data.answer) {
    ansCard.innerHTML += `<p class="ds-abstained">The documents do not contain sufficient information to answer this question.</p>`;
  } else {
    ansCard.innerHTML += `<div class="ds-answer-text">${escHtml(data.answer)}</div>`;
  }
  results.appendChild(ansCard);

  // Citations
  if (data.citations?.length) {
    const citSec = document.createElement('div');
    citSec.className = 'ds-answer-card';
    citSec.innerHTML = `<div class="ds-card-label">Sources (${data.citations.length})</div>`;
    data.citations.forEach((c) => {
      const el = document.createElement('div');
      el.className = 'ds-citation-chip';
      el.innerHTML = `
        <div class="ds-cit-info">
          <div class="ds-cit-file">${escHtml(shortName(c.file))}</div>
          <div class="ds-cit-page">Page ${c.page}${c.snippet ? ' · ' + escHtml(c.snippet.slice(0,60)) + '…' : ''}</div>
        </div>
        <span class="ds-cit-arrow">↗</span>`;
      el.onclick = () => dsOpenPdf(c.file, c.page);
      citSec.appendChild(el);
    });
    results.appendChild(citSec);
  }

  // Hits
  if (data.hits?.length) {
    const hitsSec = document.createElement('div');
    hitsSec.className = 'ds-answer-card';
    const det = document.createElement('details');
    const sum = document.createElement('summary');
    sum.textContent = `${data.hits.length} retrieved chunks`;
    sum.style.cssText = 'cursor:pointer;color:var(--text-3);font-size:12px;padding:4px 0;list-style:none';
    det.appendChild(sum);
    data.hits.forEach(h => {
      const card = document.createElement('div');
      card.className = 'ds-hit-card';
      const badge = h.channel === 'vector' ? 'ds-channel-vector' : 'ds-channel-keyword';
      card.innerHTML = `
        <div class="ds-hit-meta">
          <span class="ds-hit-file">${escHtml(shortName(h.filename))}</span>
          <span class="ds-hit-page">p.${h.page_number}</span>
          <span class="ds-channel-badge ${badge}">${h.channel || 'hybrid'}</span>
        </div>
        <div class="ds-hit-text">${escHtml(h.text)}</div>`;
      card.onclick = () => dsOpenPdf(h.filename, h.page_number);
      det.appendChild(card);
    });
    hitsSec.appendChild(det);
    results.appendChild(hitsSec);
  }
}

function dsChip(label, fast) {
  return `<span class="ds-chip${fast?' ds-fast':''}">${escHtml(label)}</span>`;
}

// PDF Viewer functions
const PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
const PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
let pdfjsLib = null;

function loadPdfJs() {
  return new Promise((resolve, reject) => {
    if (pdfjsLib) return resolve(pdfjsLib);
    const s = document.createElement('script');
    s.src = PDFJS_CDN;
    s.onload = () => {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
      pdfjsLib = window.pdfjsLib;
      resolve(pdfjsLib);
    };
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

async function dsOpenPdf(filename, page) {
  document.getElementById('ds-pdf-placeholder')?.classList.add('hidden');
  document.getElementById('ds-viewer-wrap')?.classList.remove('hidden');
  document.getElementById('ds-doc-title').textContent = filename;

  try {
    await loadPdfJs();
    const url = '/api/doc-search/doc/serve/' + encodeURIComponent(filename);
    const loadingTask = pdfjsLib.getDocument(url);
    docSearchPdfDoc = await loadingTask.promise;
    docSearchTotalPages = docSearchPdfDoc.numPages;
    docSearchCurrentPage = Math.max(1, Math.min(page, docSearchTotalPages));
    await dsRenderPage(docSearchCurrentPage);
  } catch (e) {
    console.error('PDF load error', e);
    document.getElementById('ds-canvas-container').innerHTML = `<div style="padding:40px;color:var(--red);text-align:center">Could not load PDF: ${escHtml(filename)}<br><small style="color:var(--text-3)">Make sure the doc-search service has access to this file</small></div>`;
  }
}

async function dsRenderPage(pageNum) {
  if (!docSearchPdfDoc) return;
  const canvas = document.getElementById('ds-pdf-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  docSearchCurrentPage = pageNum;
  document.getElementById('ds-page-info').textContent = `${docSearchCurrentPage} / ${docSearchTotalPages}`;
  document.getElementById('ds-btn-prev').disabled = docSearchCurrentPage <= 1;
  document.getElementById('ds-btn-next').disabled = docSearchCurrentPage >= docSearchTotalPages;

  const page = await docSearchPdfDoc.getPage(pageNum);
  const viewport = page.getViewport({ scale: docSearchScale });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: ctx, viewport }).promise;
}

function dsChangePage(delta) {
  const next = docSearchCurrentPage + delta;
  if (next >= 1 && next <= docSearchTotalPages) dsRenderPage(next);
}
function dsZoomIn() { docSearchScale = Math.min(docSearchScale + 0.2, 3.0); dsRenderPage(docSearchCurrentPage); }
function dsZoomOut() { docSearchScale = Math.max(docSearchScale - 0.2, 0.6); dsRenderPage(docSearchCurrentPage); }
function dsCloseViewer() {
  document.getElementById('ds-viewer-wrap')?.classList.add('hidden');
  document.getElementById('ds-pdf-placeholder')?.classList.remove('hidden');
  docSearchPdfDoc = null;
}

// --- Team ---
async function renderTeam(el) {
  const data = await get('/firms/members');
  const m = data?.members || [];
  el.innerHTML = `<div class="fade-in">
    <div class="page-header"><div><div class="page-title">Team</div><div class="page-subtitle">${m.length} members</div></div></div>
    <div class="card-grid">${m.map(mem => `<div class="card" style="display:flex;align-items:center;gap:12px">
      <div style="width:40px;height:40px;background:var(--accent);border-radius:50%;display:grid;place-items:center;font-weight:600;font-size:15px;color:#fff">${mem.display_name?.[0] || '?'}</div>
      <div style="flex:1">
        <div style="font-weight:500">${mem.display_name}</div>
        <div style="font-size:12px;color:var(--text-3)">${mem.email}</div>
      </div>
      <span class="badge badge-active">${mem.role}</span>
    </div>`).join('')}</div>
  </div>`;
}

// --- Modal ---
function showModal(title, body, onSave) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'modal-overlay';
  overlay.innerHTML = `<div class="modal fade-in">
    <div class="modal-title">${title}</div>
    ${body}
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-save">Create</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
  document.getElementById('modal-save').addEventListener('click', onSave);
}

function closeModal() {
  document.getElementById('modal-overlay')?.remove();
}

// --- Auth bindings ---
function bindAuth() {
  document.getElementById('login-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = document.getElementById('auth-error');
    err.style.display = 'none';
    const data = await login(document.getElementById('auth-email').value, document.getElementById('auth-pass').value);
    if (data?.error) { err.textContent = data.error; err.style.display = 'block'; }
  });
  document.getElementById('switch-register')?.addEventListener('click', () => {
    const card = document.getElementById('auth-card');
    card.innerHTML = `
      <div style="text-align:center;margin-bottom:20px">
        <div style="width:40px;height:40px;background:var(--accent);border-radius:10px;display:inline-grid;place-items:center;font-weight:700;font-size:16px;color:#fff">A</div>
      </div>
      <div class="auth-title">Create account</div>
      <div class="auth-subtitle">Set up your firm on Apex DMS</div>
      <div id="auth-error" style="color:var(--red);font-size:12px;text-align:center;margin-bottom:12px;display:none"></div>
      <form id="register-form">
        <div class="form-group"><label>Your Name</label><input type="text" id="reg-name" required></div>
        <div class="form-group"><label>Email</label><input type="email" id="reg-email" required></div>
        <div class="form-group"><label>Password</label><input type="password" id="reg-pass" required></div>
        <div class="form-group"><label>Firm Name</label><input type="text" id="reg-firm" required></div>
        <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;padding:10px">Create Account</button>
      </form>
      <div class="auth-switch">Have an account? <a onclick="render()">Sign in</a></div>
    `;
    document.getElementById('register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const err = document.getElementById('auth-error');
      err.style.display = 'none';
      const data = await register(
        document.getElementById('reg-email').value,
        document.getElementById('reg-pass').value,
        document.getElementById('reg-name').value,
        document.getElementById('reg-firm').value
      );
      if (data?.error) { err.textContent = data.error; err.style.display = 'block'; }
    });
  });
}

// --- Utilities ---
function timeAgo(d) {
  const s = Math.floor((Date.now() - new Date(d)) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

function formatSize(bytes) {
  if (!bytes) return '—';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1048576).toFixed(1) + ' MB';
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function shortName(filename) {
  if (!filename) return '';
  const n = filename.replace(/\.pdf$/i, '');
  return n.length > 40 ? n.slice(0, 38) + '…' : n;
}

function formatMd(text) {
  if (!text) return '';
  return escHtml(text)
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

// Make functions globally accessible
window.navigateTo = navigateTo;
window.showCreateMatter = showCreateMatter;
window.showCreateClient = showCreateClient;
window.toggleStatus = toggleStatus;
window.newConversation = newConversation;
window.openConversation = openConversation;
window.sendChat = sendChat;
window.closeModal = closeModal;
window.logout = logout;
window.render = render;
window.doDocSearch = doDocSearch;
window.dsOpenPdf = dsOpenPdf;
window.dsChangePage = dsChangePage;
window.dsZoomIn = dsZoomIn;
window.dsZoomOut = dsZoomOut;
window.dsCloseViewer = dsCloseViewer;

// Boot
render();
