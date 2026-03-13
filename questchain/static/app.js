// ── State ─────────────────────────────────────────────────────
const State = {
  ws: null,
  connected: false,
  streaming: false,
  streamEl: null,        // current streaming bubble DOM element
  typingEl: null,        // typing indicator
  agents: [],
  activeAgentId: '',
  viewingAgentId: '',    // agent currently shown in stats view (may differ from active)
  quests: [],
  selectedQuestName: null,
  page: 'chat',
  settings: null,
  editingAgentId: null,
  pendingEditId: null,   // agent to open in edit form once settings load
};

// ── WebSocket ─────────────────────────────────────────────────
const _WS_TOKEN = document.querySelector('meta[name="ws-token"]')?.content || '';

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const tokenParam = _WS_TOKEN ? `?token=${encodeURIComponent(_WS_TOKEN)}` : '';
  const ws = new WebSocket(`${proto}://${location.host}/ws${tokenParam}`);
  State.ws = ws;

  ws.onopen = () => {
    State.connected = true;
    document.getElementById('conn-dot').className = 'connection-dot connected';
    ws.send(JSON.stringify({ type: 'get_agents' }));
    ws.send(JSON.stringify({ type: 'get_stats' }));
    ws.send(JSON.stringify({ type: 'get_quests' }));
  };

  ws.onclose = () => {
    State.connected = false;
    document.getElementById('conn-dot').className = 'connection-dot error';
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    handleEvent(msg);
  };
}

function send(obj) {
  if (State.ws && State.connected) State.ws.send(JSON.stringify(obj));
}

// ── Event router ──────────────────────────────────────────────
function handleEvent(msg) {
  switch (msg.type) {
    case 'user_message':  onUserMessage(msg); break;
    case 'token':         onToken(msg); break;
    case 'tool_call':     onToolCall(msg); break;
    case 'assistant_done':onDone(msg); break;
    case 'agents':        onAgents(msg); break;
    case 'stats':         onStats(msg); break;
    case 'quests':        onQuests(msg); break;
    case 'settings':      onSettings(msg); break;
  }
}

// ── Chat events ───────────────────────────────────────────────
function onUserMessage(msg) {
  removeTyping();
  appendMessage('user', msg.content, msg.source !== 'web' ? msg.source : null);
}

function onToken(msg) {
  removeTyping();
  if (!State.streaming || !State.streamEl) {
    State.streaming = true;
    const wrap = appendMessage('assistant', '', null, true);
    State.streamEl = wrap.querySelector('.msg-bubble');
  }
  State.streamEl.textContent += msg.content;
  State.streamEl.classList.add('stream-cursor');
  scrollToBottom();
}

function onToolCall(msg) {
  removeTyping();
  const el = document.createElement('div');
  el.className = 'tool-pill';
  el.innerHTML = `<span class="dot"></span>${escHtml(msg.name)}`;
  document.getElementById('messages').appendChild(el);
  scrollToBottom();
}

function onDone(msg) {
  if (State.streamEl) {
    State.streamEl.classList.remove('stream-cursor');
  }
  State.streaming = false;
  State.streamEl = null;
  removeTyping();
  document.getElementById('send-btn').disabled = false;
  // Stop all tool pill dots from pulsing
  document.querySelectorAll('.tool-pill .dot').forEach(d => d.style.animation = 'none');
  // refresh stats after response
  send({ type: 'get_stats' });
}

function onAgents(msg) {
  State.agents = msg.agents || [];
  State.activeAgentId = msg.active_id || '';
  // Always update viewing to match active when agents list refreshes
  State.viewingAgentId = State.activeAgentId;
  renderRoster();
  updateChatHeader();
  // Render stats panel directly from enriched agents data — no extra roundtrip
  renderStatsFromAgents();
}

function onStats(msg) {
  // Stats events arrive after turns (EventBus push) or explicit get_stats.
  // Update the stored enriched data in State.agents so renderStats stays consistent.
  const statsAgentId = msg.metrics?.agent_id || '';
  const agent = State.agents.find(a => a.id === statsAgentId);
  if (agent) {
    agent.progression = msg.progression || agent.progression;
    agent.metrics = msg.metrics || agent.metrics;
    agent.level = msg.progression?.level || agent.level;
  }
  // Update chat header and portrait for active agent
  if (!statsAgentId || statsAgentId === State.activeAgentId) {
    document.getElementById('chat-agent-name').textContent = msg.metrics?.agent_name || 'QuestChain';
    document.getElementById('chat-agent-level').textContent = `Lv. ${msg.progression?.level || 1}`;
    document.getElementById('chat-model').textContent = msg.metrics?.model_name || '';
    updateChatPortrait(agent || null);
  }
  // Render stats panel if this is for the agent being viewed
  if (!statsAgentId || statsAgentId === State.viewingAgentId) {
    renderStats(msg);
  }
}

function onQuests(msg) {
  State.quests = msg.quests || [];
  renderQuestList();
}

function onSettings(msg) {
  State.settings = msg;
  if (State.page === 'settings') renderSettings();
  // Handle a deferred edit triggered from the agent roster
  if (State.pendingEditId) {
    const id = State.pendingEditId;
    State.pendingEditId = null;
    const agent = (State.settings?.agents || []).find(a => a.id === id)
               || State.agents.find(a => a.id === id);
    if (agent) openAgentForm(agent);
  }
}

// ── Settings rendering ────────────────────────────────────────
function renderSettings() {
  const s = State.settings;
  if (!s) return;

  // Session
  document.getElementById('settings-thread-id').textContent = s.thread_id || '—';

  // Model
  document.getElementById('settings-model-current').textContent = s.model_name || '—';
  const modelList = document.getElementById('settings-model-list');
  if (s.available_models && s.available_models.length) {
    modelList.innerHTML = s.available_models.map(m =>
      `<span class="model-chip${m === s.model_name ? ' active' : ''}">${escHtml(m)}</span>`
    ).join('');
  } else {
    modelList.innerHTML = '<span class="model-chip text-muted-hint">None found</span>';
  }

  // Agents table
  const tbody = document.getElementById('settings-agent-tbody');
  tbody.innerHTML = (s.agents || []).map(a => `
    <tr>
      <td class="agent-tbl-name">${escHtml(a.name)}</td>
      <td class="agent-tbl-class">${escHtml(a.class_name)}</td>
      <td class="agent-tbl-model">${escHtml(a.model || '—')}</td>
      <td><div class="agent-tbl-actions">
        <button class="btn-icon" data-edit-id="${escAttr(a.id)}">Edit</button>
        ${a.id !== 'default' ? `<button class="btn-icon danger" data-delete-id="${escAttr(a.id)}">Delete</button>` : ''}
      </div></td>
    </tr>
  `).join('');
  tbody.querySelectorAll('[data-edit-id]').forEach(btn => {
    btn.addEventListener('click', () => openAgentFormById(btn.dataset.editId));
  });
  tbody.querySelectorAll('[data-delete-id]').forEach(btn => {
    btn.addEventListener('click', () => deleteAgent(btn.dataset.deleteId));
  });

  // Populate class <select> once
  const sel = document.getElementById('af-class');
  if (sel && !sel.options.length && s.agent_classes) {
    s.agent_classes.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = `${c.icon} ${c.name}`;
      sel.appendChild(opt);
    });
  }

  // Cron jobs
  const cronBody = document.getElementById('settings-cron-body');
  if (s.cron_jobs && s.cron_jobs.length) {
    cronBody.innerHTML = s.cron_jobs.map(j => `
      <div class="cron-row">
        <span class="cron-name">${escHtml(j.name || j.id)}</span>
        <span class="cron-expr">${escHtml(j.cron_expression || '')}</span>
        <span class="cron-status ${j.enabled !== false ? 'on' : 'off'}">${j.enabled !== false ? 'ON' : 'OFF'}</span>
        <button class="btn-icon danger" data-cron-id="${escAttr(j.id)}">Remove</button>
      </div>
    `).join('');
    cronBody.querySelectorAll('[data-cron-id]').forEach(btn => {
      btn.addEventListener('click', () => deleteCronJob(btn.dataset.cronId));
    });
  } else {
    cronBody.innerHTML = '<span class="cron-empty">No cron jobs configured.</span>';
  }

  // Integrations
  const intg = s.integrations || {};
  const intRows = [
    { id: 'intg-tavily',   key: 'tavily',      ok: 'Configured', fail: 'Not configured' },
    { id: 'intg-claude',   key: 'claude_code', ok: 'Found',       fail: 'Not found' },
    { id: 'intg-telegram', key: 'telegram',    ok: 'Configured', fail: 'Not configured' },
  ];
  intRows.forEach(r => {
    const el = document.getElementById(r.id);
    if (!el) return;
    const ok = intg[r.key];
    el.className = `integration-badge ${ok ? 'ok' : 'missing'}`;
    el.textContent = ok ? r.ok : r.fail;
  });
}

function renderToolPicker(selectedTools) {
  const picker = document.getElementById('af-tool-picker');
  const tools = State.settings?.selectable_tools || [];
  picker.innerHTML = '';
  // selectedTools: "all" or array of names — "all" means nothing explicitly checked
  const selected = Array.isArray(selectedTools) ? new Set(selectedTools) : new Set();
  tools.forEach(t => {
    const chip = document.createElement('div');
    chip.className = 'tool-chip' + (selected.has(t.name) ? ' selected' : '');
    chip.dataset.name = t.name;
    chip.title = t.description;
    chip.innerHTML = escHtml(t.name) + (t.workspace ? ' <span class="ws-badge">[WS]</span>' : '');
    chip.addEventListener('click', () => chip.classList.toggle('selected'));
    picker.appendChild(chip);
  });
}

function getSelectedTools() {
  const chips = document.querySelectorAll('#af-tool-picker .tool-chip.selected');
  if (chips.length === 0) return 'all';
  return Array.from(chips).map(c => c.dataset.name);
}

function openAgentForm(agent) {
  State.editingAgentId = agent ? agent.id : null;
  document.getElementById('af-name').value = agent ? agent.name : '';
  document.getElementById('af-model').value = agent ? (agent.model || '') : '';
  document.getElementById('af-prompt').value = agent ? (agent.system_prompt || '') : '';
  if (agent) document.getElementById('af-class').value = agent.class_name;
  renderToolPicker(agent ? (agent.tools || 'all') : 'all');
  document.getElementById('agent-form').classList.add('open');
  document.getElementById('af-name').focus();
}

// Opens the agent edit form by ID, navigating to settings first if needed.
// Used by roster edit buttons (may be called from the agent page).
function editAgent(id) {
  if (State.page !== 'settings') switchPage('settings');
  openAgentFormById(id);
}

// Opens the agent edit form by ID. Assumes settings data is available or defers.
// Used by the settings page agent table (already on the right page).
function openAgentFormById(id) {
  const agent = (State.settings?.agents || []).find(a => a.id === id)
             || State.agents.find(a => a.id === id);
  if (!agent) {
    State.pendingEditId = id;
    send({ type: 'get_settings' });
    return;
  }
  openAgentForm(agent);
}

function deleteAgent(id) {
  if (!confirm('Delete this agent? This cannot be undone.')) return;
  send({ type: 'delete_agent', agent_id: id });
}

function deleteCronJob(id) {
  if (!confirm('Remove this cron job?')) return;
  send({ type: 'delete_cron', cron_id: id });
}

// ── Chat rendering ────────────────────────────────────────────
function appendMessage(role, text, sourceLabel, streaming) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? '👤' : '⚔';

  const inner = document.createElement('div');

  if (sourceLabel) {
    const lbl = document.createElement('div');
    lbl.className = 'msg-source-label';
    lbl.textContent = sourceLabel === 'telegram' ? '📱 Telegram' : sourceLabel;
    inner.appendChild(lbl);
  }

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.textContent = text;
  inner.appendChild(bubble);

  wrap.appendChild(avatar);
  wrap.appendChild(inner);
  document.getElementById('messages').appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function showTyping() {
  if (State.typingEl) return;
  const el = document.createElement('div');
  el.className = 'typing-indicator';
  el.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  State.typingEl = el;
  document.getElementById('messages').appendChild(el);
  scrollToBottom();
}

function removeTyping() {
  if (State.typingEl) {
    State.typingEl.remove();
    State.typingEl = null;
  }
}

function scrollToBottom() {
  const el = document.getElementById('messages');
  el.scrollTop = el.scrollHeight;
}

function updateChatHeader() {
  const active = State.agents.find(a => a.id === State.activeAgentId);
  if (!active) return;
  document.getElementById('chat-agent-name').textContent = active.name || 'QuestChain';
  document.getElementById('chat-agent-level').textContent = `Lv. ${active.progression?.level || active.level || 1}`;
  document.getElementById('chat-model').textContent = active.metrics?.model_name || active.model || '';
  updateChatPortrait(active);
}

function updateChatPortrait(agent) {
  if (!agent) agent = State.agents.find(a => a.id === State.activeAgentId);
  if (!agent) return;
  const prog = agent.progression || {};
  const level = prog.level || agent.level || 1;
  const className = agent.class_name || 'Custom';
  const icon = CLASS_ICONS[className] || '🌀';

  document.getElementById('chat-portrait-class-icon').textContent = icon;
  document.getElementById('chat-portrait-class-name').textContent = className;
  document.getElementById('chat-portrait-name').textContent = agent.name || 'QuestChain';
  document.getElementById('chat-portrait-level').textContent = `Level ${level}`;

  // XP bar
  const xpThis = prog.xp_this_level || 0;
  const xpLeft = prog.xp_next_level || 100;
  const xpTotal = xpThis + xpLeft;
  const pct = xpTotal > 0 ? Math.min(100, Math.round(xpThis / xpTotal * 100)) : 0;
  document.getElementById('chat-portrait-xp-bar-fill').style.width = pct + '%';
  document.getElementById('chat-portrait-xp-val').textContent = `${xpThis} / ${xpTotal}`;

  // Image
  const img = document.getElementById('chat-portrait-img');
  img.style.opacity = '0';
  img.src = `/agent-image?agent_id=${encodeURIComponent(agent.id || '')}`;
  img.onload = () => { img.style.opacity = '1'; };
  img.onerror = () => { img.style.opacity = '0.2'; };
}

// ── Agent stats rendering ─────────────────────────────────────
const CLASS_ICONS = { Custom:'🌀', Sage:'📚', Explorer:'🔭', Architect:'⚒️', Oracle:'🔮', Scheduler:'⏱️' };
// Use the bundled character image (served relative to the page)
const AGENT_IMAGE_SRC = 'data:image/png;base64,'; // placeholder; real image injected below

function updateAgentImage(agentId) {
  const img = document.getElementById('agent-image');
  img.style.display = '';
  img.src = `/agent-image?agent_id=${encodeURIComponent(agentId || '')}`;
  img.onerror = function() { this.style.display = 'none'; };
}

// Render the stats panel from the enriched agent data already in State.agents
function renderStatsFromAgents() {
  const id = State.viewingAgentId || State.activeAgentId;
  const agent = State.agents.find(a => a.id === id);
  if (!agent) return;
  renderStats({ progression: agent.progression || {}, metrics: agent.metrics || {} });
}

function renderStats(msg) {
  const prog = msg.progression || {};
  const metrics = msg.metrics || {};

  // Update header level
  const level = prog.level || 1;
  const className = prog.class_name || 'Custom';

  updateAgentImage(metrics.agent_id || '');

  document.getElementById('agent-name-display').textContent = metrics.agent_name || 'QuestChain';
  document.getElementById('agent-level-display').textContent = `Level ${level}`;
  document.getElementById('agent-class-icon').textContent = CLASS_ICONS[className] || '🌀';
  document.getElementById('agent-class-name').textContent = className;

  const xpThis = prog.xp_this_level || 0;
  const xpLeft = prog.xp_next_level || 100;
  const xpTotal = xpThis + xpLeft;
  const pct = xpTotal > 0 ? Math.min(100, Math.round(xpThis / xpTotal * 100)) : 100;
  document.getElementById('xp-bar').style.width = pct + '%';
  document.getElementById('xp-label-val').textContent = `${xpThis} / ${xpTotal} XP`;

  document.getElementById('stat-prompts').textContent = fmt(metrics.prompt_count);
  document.getElementById('stat-tokens').textContent = fmtLarge(metrics.tokens_used);
  document.getElementById('stat-chain').textContent = fmt(metrics.highest_chain);
  document.getElementById('stat-errors').textContent = fmt(metrics.total_errors);
  document.getElementById('stat-tools').textContent = fmt(metrics.num_tools);

  // Achievements
  const achs = prog.achievements || [];
  const achWrap = document.getElementById('achievements-list');
  if (achs.length === 0) {
    achWrap.innerHTML = '<span class="no-achievements">No achievements yet — start a quest!</span>';
  } else {
    achWrap.innerHTML = achs.map(a =>
      `<span class="achievement-badge">${escHtml(a)}</span>`
    ).join('');
  }
}

function renderRoster() {
  const list = document.getElementById('roster-list');
  if (!State.agents.length) {
    list.innerHTML = '<div class="agents-empty">No agents</div>';
    return;
  }
  list.innerHTML = State.agents.map(a => {
    const isViewing = a.id === State.viewingAgentId;
    const isActive = a.id === State.activeAgentId;
    const icon = CLASS_ICONS[a.class_name] || '🌀';
    const delBtn = a.id !== 'default'
      ? `<button class="roster-item-action danger" data-action="delete" data-id="${escAttr(a.id)}" title="Delete agent">✕</button>`
      : '';
    return `
      <div class="roster-item ${isViewing ? 'active' : ''}" data-id="${escAttr(a.id)}">
        <span class="roster-item-icon">${icon}</span>
        <div class="roster-item-info">
          <div class="roster-item-name">${escHtml(a.name || 'Agent')}</div>
          <div class="roster-item-level">Lv. ${escHtml(String(a.level ?? '?'))} · ${escHtml(a.class_name || 'Custom')}</div>
        </div>
        ${isActive ? '<div class="roster-item-active-dot" title="Active in CLI"></div>' : ''}
        <div class="roster-item-actions">
          <button class="roster-item-action" data-action="edit" data-id="${escAttr(a.id)}" title="Edit agent">✏</button>
          ${delBtn}
        </div>
      </div>`;
  }).join('');

  list.querySelectorAll('.roster-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.closest('[data-action]')) return;
      const id = el.dataset.id;
      State.viewingAgentId = id;
      State.activeAgentId = id;
      send({ type: 'switch_agent', agent_id: id });
      renderRoster();
      renderStatsFromAgents();
      updateChatHeader();
    });
  });

  list.querySelectorAll('[data-action="edit"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      editAgent(btn.dataset.id);
    });
  });

  list.querySelectorAll('[data-action="delete"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      const agent = State.agents.find(a => a.id === id);
      const name = agent ? agent.name : id;
      if (confirm(`Delete agent "${name}"? This cannot be undone.`)) {
        send({ type: 'delete_agent', agent_id: id });
      }
    });
  });
}

// ── Quest rendering ───────────────────────────────────────────
function renderQuestList() {
  const list = document.getElementById('quest-list');
  if (!State.quests.length) {
    list.innerHTML = '<div class="quest-empty">No quests yet.<br>Create one to get started.</div>';
    return;
  }
  list.innerHTML = State.quests.map(q => `
    <div class="quest-item ${q.name === State.selectedQuestName ? 'active' : ''}" data-name="${escAttr(q.name)}">
      <span class="quest-item-icon">⚔</span>
      <span class="quest-item-title">${escHtml(q.title || q.name)}</span>
      <button class="quest-item-del" data-name="${escAttr(q.name)}" title="Delete">✕</button>
    </div>`).join('');

  list.querySelectorAll('.quest-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.closest('.quest-item-del')) return;
      selectQuest(el.dataset.name);
    });
  });
  list.querySelectorAll('.quest-item-del').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const name = btn.dataset.name;
      if (confirm(`Delete quest "${name}"?`)) {
        send({ type: 'delete_quest', name });
        if (State.selectedQuestName === name) clearEditor();
      }
    });
  });
}

function selectQuest(name) {
  State.selectedQuestName = name;
  const q = State.quests.find(x => x.name === name);
  if (q) {
    document.getElementById('quest-name-input').value = q.name.replace(/\.md$/, '');
    document.getElementById('quest-content-input').value = q.content;
  }
  renderQuestList();
}

function clearEditor() {
  State.selectedQuestName = null;
  document.getElementById('quest-name-input').value = '';
  document.getElementById('quest-content-input').value = '';
  renderQuestList();
}

// ── Navigation ────────────────────────────────────────────────
function switchPage(page) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.nav-btn[data-page="${page}"]`);
  if (btn) btn.classList.add('active');
  document.getElementById(`page-${page}`).classList.add('active');
  State.page = page;
  if (page === 'agent') {
    renderStatsFromAgents();
    send({ type: 'get_agents' });
  }
  if (page === 'quests') send({ type: 'get_quests' });
  if (page === 'settings') {
    send({ type: 'get_settings' });
    renderSettings();
  }
}

document.querySelectorAll('.nav-btn[data-page]').forEach(btn => {
  btn.addEventListener('click', () => switchPage(btn.dataset.page));
});

// ── Chat input ────────────────────────────────────────────────
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    doSend();
  }
});

sendBtn.addEventListener('click', doSend);

function doSend() {
  const text = chatInput.value.trim();
  if (!text || !State.connected || State.streaming) return;

  // Don't append locally — the server echoes it back as a user_message event
  showTyping();
  send({ type: 'chat', message: text });
  chatInput.value = '';
  chatInput.style.height = 'auto';
  sendBtn.disabled = true;
}

// ── Quest buttons ─────────────────────────────────────────────
document.getElementById('btn-new-quest').addEventListener('click', () => {
  State.selectedQuestName = null;
  document.getElementById('quest-name-input').value = '';
  document.getElementById('quest-content-input').value = '';
  document.getElementById('quest-name-input').focus();
  renderQuestList();
});

document.getElementById('btn-save-quest').addEventListener('click', () => {
  const name = document.getElementById('quest-name-input').value.trim();
  const content = document.getElementById('quest-content-input').value;
  if (!name) { document.getElementById('quest-name-input').focus(); return; }

  if (State.selectedQuestName) {
    send({ type: 'update_quest', name: State.selectedQuestName, content });
  } else {
    send({ type: 'create_quest', name, content });
    State.selectedQuestName = name.endsWith('.md') ? name : name + '.md';
  }
});

// ── New Chat button ───────────────────────────────────────────
document.getElementById('btn-new-chat').addEventListener('click', () => {
  send({ type: 'new_thread' });
  document.getElementById('messages').innerHTML = '';
});

// ── Settings buttons ──────────────────────────────────────────
document.getElementById('btn-new-agent').addEventListener('click', () => {
  openAgentForm(null);
});

document.getElementById('af-cancel').addEventListener('click', () => {
  document.getElementById('agent-form').classList.remove('open');
  State.editingAgentId = null;
});

document.getElementById('af-save').addEventListener('click', () => {
  const name = document.getElementById('af-name').value.trim();
  if (!name) { document.getElementById('af-name').focus(); return; }
  const payload = {
    name,
    tools: getSelectedTools(),
    class_name: document.getElementById('af-class').value,
    model: document.getElementById('af-model').value.trim() || null,
    system_prompt: document.getElementById('af-prompt').value.trim() || null,
  };
  if (State.editingAgentId) {
    send({ type: 'update_agent', agent_id: State.editingAgentId, ...payload });
  } else {
    send({ type: 'create_agent', ...payload });
  }
  document.getElementById('agent-form').classList.remove('open');
  State.editingAgentId = null;
});

// ── Helpers ───────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) { return escHtml(s); }
function fmt(n) { return (n || 0).toLocaleString(); }
function fmtLarge(n) {
  n = n || 0;
  if (n >= 1_000_000) return (n/1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n/1_000).toFixed(1) + 'K';
  return n.toString();
}

// ── Portrait panel click ──────────────────────────────────────
document.getElementById('chat-portrait-panel').addEventListener('click', () => {
  switchPage('agent');
});

// ── Boot ──────────────────────────────────────────────────────
connect();
