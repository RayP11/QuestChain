// ── Achievement metadata (icon + category, keyed by achievement id) ───────────
const ACHIEVEMENT_META = {
  first_strike:  { icon: '⚔️',  category: 'Progression' },
  awakening:     { icon: '🌅',  category: 'Progression' },
  seasoned:      { icon: '🗺️',  category: 'Progression' },
  veteran:       { icon: '🛡️',  category: 'Progression' },
  legend:        { icon: '🏆',  category: 'Progression' },
  century:       { icon: '💬',  category: 'Milestones'  },
  old_timer:     { icon: '⏳',  category: 'Milestones'  },
  iron_will:     { icon: '🔩',  category: 'Milestones'  },
  bibliophile:   { icon: '📚',  category: 'Tool Use'    },
  web_walker:    { icon: '🌐',  category: 'Tool Use'    },
  globe_trotter: { icon: '🗾',  category: 'Tool Use'    },
  blacksmith:    { icon: '🔨',  category: 'Tool Use'    },
  demolition:    { icon: '💥',  category: 'Tool Use'    },
  archivist:     { icon: '🗄️',  category: 'Tool Use'    },
  grand_planner: { icon: '📋',  category: 'Tool Use'    },
  polymath:      { icon: '🎓',  category: 'Behavioral'  },
  speed_demon:   { icon: '⚡',  category: 'Behavioral'  },
  centurion:     { icon: '💰',  category: 'Behavioral'  },
  busy_bee:      { icon: '🐝',  category: 'Behavioral'  },
  road_runner:   { icon: '🏃',  category: 'Behavioral'  },
};

// ── State ─────────────────────────────────────────────────────
const State = {
  ws: null,
  connected: false,
  streaming: false,
  messageEls: new Map(),
  runs: new Map(),
  routeEls: new Map(),
  conversationId: sessionStorage.getItem('questchain-conversation') || 'web-' + crypto.randomUUID(),
  lastSeq: 0,
  typingEl: null,        // typing indicator
  agents: [],
  activeAgentId: '',
  viewingAgentId: '',    // agent currently shown in stats view (may differ from active)
  jobs: [],
  selectedJobId: null,
  battleLog: [],       // array of {text, agentName, icon, time}, max 20
  agentStatus: {},     // agent_id → 'idle' | 'thinking' | 'tool:toolname'
  page: 'map',
  settings: null,
  editingAgentId: null,
  pendingEditId: null,   // agent to open in edit form once settings load
};

// ── WebSocket ─────────────────────────────────────────────────
const _WS_TOKEN = document.querySelector('meta[name="ws-token"]')?.content || '';

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const tokenParam = `?conversation=${encodeURIComponent(State.conversationId)}${_WS_TOKEN ? '&token=' + encodeURIComponent(_WS_TOKEN) : ''}`;
  const ws = new WebSocket(`${proto}://${location.host}/ws${tokenParam}`);
  State.ws = ws;

  ws.onopen = () => {
    State.connected = true;
    document.getElementById('conn-dot').className = 'connection-dot connected';
    document.getElementById('conn-dot').title = 'Connected';
    ws.send(JSON.stringify({ type: 'get_agents' }));
    ws.send(JSON.stringify({ type: 'get_stats' }));
    ws.send(JSON.stringify({ type: 'get_cron_jobs' }));
    if (State.selectedJobId) ws.send(JSON.stringify({type: 'get_cron_history', cron_id: State.selectedJobId}));
  };

  ws.onclose = () => {
    State.connected = false;
    document.getElementById('conn-dot').className = 'connection-dot error';
    document.getElementById('conn-dot').title = 'Disconnected';
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
  if (msg.conversation_id && msg.type !== 'conversation') {
    if (msg.conversation_id !== State.conversationId) return;
    if (msg.seq && msg.seq <= State.lastSeq) return;
    if (msg.seq) State.lastSeq = msg.seq;
  }
  switch (msg.type) {
    case 'conversation': onConversation(msg); break;
    case 'run_status': onRunStatus(msg); break;
    case 'routed': onRouted(msg); break;
    case 'agent_selected':
      State.activeAgentId = msg.agent_id;
      State.viewingAgentId = msg.agent_id;
      renderChatAgentList(); renderRoster(); updateChatHeader();
      break;
    case 'agent_saved':
      document.getElementById('agent-form').classList.remove('open');
      State.editingAgentId = null;
      break;
    case 'legacy_migrated':
      document.getElementById('legacy-agent-message').textContent = `${msg.name} migrated. Automatic routing is off until you enable it in Edit.`;
      break;
    case 'legacy_deleted':
      document.getElementById('legacy-agent-message').textContent = `${msg.name} deleted from the archive.`;
      break;
    case 'legacy_error': document.getElementById('legacy-agent-message').textContent = msg.error; break;
    case 'agent_error': document.getElementById('af-error').textContent = msg.error; break;
    case 'error':
      removeTyping();
      document.getElementById('run-status').textContent = msg.error;
      document.getElementById('send-btn').disabled = false;
      break;
    case 'resync_required': send({type: 'get_conversation'}); break;
    case 'user_message':  onUserMessage(msg); break;
    case 'token':         onToken(msg); break;
    case 'tool_call':     onToolCall(msg); break;
    case 'assistant_done':onDone(msg); break;
    case 'agents':        onAgents(msg); break;
    case 'stats':         onStats(msg); break;
    case 'cron_jobs': onJobs(msg); break;
    case 'cron_history': renderCronHistory(msg); break;
    case 'cron_error': document.getElementById('job-message').textContent = msg.message; break;
    case 'cron_saved':
      document.getElementById('job-message').textContent = msg.action === 'run_cron' ? 'Job queued.' : 'Changes saved.';
      if (msg.action === 'save_cron') { State.pendingJobId = msg.cron_id; send({ type: 'get_cron_jobs' }); }
      if (msg.action === 'delete_cron') clearJobEditor();
      break;
    case 'settings':      onSettings(msg); break;
  }
}

// ── Chat events ───────────────────────────────────────────────
const FINISHED = new Set(['completed', 'partial', 'failed', 'cancelled', 'interrupted', 'waiting_input']);

function messageFor(msg, role = 'assistant') {
  let wrap = State.messageEls.get(msg.message_id);
  if (!wrap) {
    wrap = appendMessage(role, '', role === 'user' ? 'You' : msg.agent_name);
    wrap.dataset.messageId = msg.message_id;
    State.messageEls.set(msg.message_id, wrap);
  }
  return wrap;
}

function onUserMessage(msg) {
  removeTyping();
  ChatMarkdown.set(messageFor(msg, 'user').querySelector('.msg-bubble'), msg.content);
}

function onToken(msg) {
  removeTyping();
  const bubble = messageFor(msg).querySelector('.msg-bubble');
  ChatMarkdown.append(bubble, msg.content);
  bubble.classList.add('stream-cursor');
  State.agentStatus[msg.agent_id] = 'thinking';
  if (State.page === 'map') updateBattleTileStatus(msg.agent_id);
  scrollToBottom();
}

function onToolCall(msg) {
  const el = document.createElement('div');
  el.className = 'tool-pill';
  el.textContent = `${msg.agent_name} · ${msg.name}`;
  document.getElementById('messages').appendChild(el);
  State.agentStatus[msg.agent_id] = 'tool:' + msg.name;
  pushBattleLog(msg.agent_id, `Used ${msg.name}`);
  if (State.page === 'map') updateBattleTileStatus(msg.agent_id);
  scrollToBottom();
}

function onDone(msg) {
  removeTyping();
  const wrap = messageFor(msg);
  const bubble = wrap.querySelector('.msg-bubble');
  ChatMarkdown.set(bubble, msg.content);
  bubble.classList.remove('stream-cursor');
  let outcome = wrap.querySelector('.run-outcome');
  if (!outcome) {
    outcome = document.createElement('div');
    outcome.className = 'run-outcome';
    wrap.lastElementChild.appendChild(outcome);
  }
  outcome.textContent = msg.error ? `${msg.status}: ${msg.error}` : msg.status === 'waiting_input' ? 'Waiting for your input' : '';
  onRunStatus(msg);
  send({ type: 'get_stats', agent_id: msg.agent_id });
  send({ type: 'get_agents' });
  pushBattleLog(msg.agent_id, msg.status === 'completed' ? 'Completed response' : msg.status);
  scrollToBottom();
}

function onRunStatus(msg) {
  State.runs.set(msg.run_id, {...State.runs.get(msg.run_id), ...msg});
  State.agentStatus[msg.agent_id] = FINISHED.has(msg.status) ? 'idle' : 'thinking';
  if (State.page === 'map') updateBattleTileStatus(msg.agent_id);
  renderRunStatus();
}

function renderRunStatus() {
  const bar = document.getElementById('run-status');
  bar.replaceChildren();
  const roots = [...State.runs.values()].filter(r => !r.parent_run_id);
  const active = roots.filter(r => !FINISHED.has(r.status));
  State.streaming = active.length > 0;
  for (const run of active) {
    const row = document.createElement('div');
    row.className = 'run-status-row';
    const text = document.createElement('span');
    text.textContent = `${run.destination_name || run.agent_name} · ${run.status}`;
    const cancel = document.createElement('button');
    cancel.className = 'btn-icon';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => send({type: 'cancel_run', run_id: run.run_id}));
    row.append(text, cancel);
    bar.appendChild(row);
  }
  const last = roots.at(-1);
  if (last && FINISHED.has(last.status) && last.status !== 'completed') {
    const row = document.createElement('div');
    row.className = 'run-status-row';
    const label = document.createElement('span');
    label.textContent = `${last.agent_name} · ${last.status.replaceAll('_', ' ')}`;
    const retry = document.createElement('button');
    retry.className = 'btn-icon';
    retry.textContent = 'Retry';
    retry.addEventListener('click', () => send({type: 'retry_run', run_id: last.run_id}));
    row.append(label, retry);
    bar.appendChild(row);
  }
  document.getElementById('send-btn').disabled = !State.connected;
}

function onRouted(msg) {
  onRunStatus(msg);
  if (State.routeEls.has(msg.run_id)) return;
  const el = document.createElement('div');
  el.className = 'routing-note';
  el.textContent = `${msg.agent_name} → ${msg.destination_name}`;
  State.routeEls.set(msg.run_id, el);
  document.getElementById('messages').appendChild(el);
}

function onConversation(msg) {
  State.conversationId = msg.conversation_id;
  sessionStorage.setItem('questchain-conversation', msg.conversation_id);
  State.lastSeq = msg.seq;
  State.messageEls.clear(); State.runs.clear(); State.routeEls.clear();
  removeTyping();
  document.getElementById('messages').replaceChildren();
  if (msg.selected_agent_id) State.activeAgentId = msg.selected_agent_id;
  for (const run of msg.runs || []) {
    const event = {...run, run_id: run.id, content: run.result};
    if (!run.parent_run_id) onUserMessage({...event, message_id: run.user_message_id, content: run.text});
    if (run.child_run_id) {
      const child = msg.runs.find(r => r.id === run.child_run_id);
      if (child) onRouted({...event, destination_name: child.agent_name});
    } else if (run.result || FINISHED.has(run.status)) {
      if (FINISHED.has(run.status)) {
        // Restore canonical messages without triggering redundant refresh requests.
        const wrap = messageFor(event);
        ChatMarkdown.set(wrap.querySelector('.msg-bubble'), run.result);
        if (run.error) {
          const outcome = document.createElement('div');
          outcome.className = 'run-outcome'; outcome.textContent = `${run.status}: ${run.error}`;
          wrap.lastElementChild.appendChild(outcome);
        }
      } else {
        onToken({...event, content: run.result});
      }
    }
    onRunStatus(event);
  }
  renderChatAgentList(); updateChatHeader(); renderRunStatus();
}

function onAgents(msg) {
  State.agents = msg.agents || [];
  if (!State.agents.some(a => a.id === State.activeAgentId)) State.activeAgentId = msg.active_id || '';
  // Always update viewing to match active when agents list refreshes
  State.viewingAgentId = State.activeAgentId;
  renderRoster();
  renderChatAgentList();
  updateChatHeader();
  // Render stats panel directly from enriched agents data — no extra roundtrip
  renderStatsFromAgents();
  // Refresh battle map if visible
  if (State.page === 'map') renderBattleMap();
  if (State.page === 'jobs') renderJobAgentSelect(document.getElementById('job-agent-select').value);
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

function onJobs(msg) {
  State.jobs = msg.jobs || [];
  if (State.pendingJobId) { selectJob(State.pendingJobId); State.pendingJobId = null; }
  if (State.settings) State.settings.cron_jobs = State.jobs;
  renderJobList();
  renderJobStatus();
  if (State.page === 'map') renderBattleMap();
  if (State.page === 'settings') renderSettings();
}

function onSettings(msg) {
  State.settings = msg;
  if (State.page === 'settings') renderSettings();
  if (State.page === 'map') renderBattleMap();
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
  document.getElementById('settings-thread-id').textContent = State.conversationId || '—';

  // Model
  document.getElementById('settings-model-current').textContent = s.model_name || '—';
  const modelList = document.getElementById('settings-model-list');
  if (s.available_models && s.available_models.length) {
    modelList.innerHTML = s.available_models.map(m =>
      `<span class="model-chip${m === s.model_name ? ' active' : ''}" data-model="${escAttr(m)}" title="Click to set as global model">${escHtml(m)}</span>`
    ).join('');
    modelList.querySelectorAll('.model-chip[data-model]').forEach(chip => {
      chip.style.cursor = 'pointer';
      chip.addEventListener('click', () => {
        const model = chip.dataset.model;
        if (model && model !== s.model_name) {
          if (confirm(`Set global model to "${model}" and clear per-agent overrides? Restart QuestChain to apply this change.`)) {
            send({ type: 'set_model', model, apply_all: true });
          }
        }
      });
    });
  } else {
    modelList.innerHTML = '<span class="model-chip text-muted-hint">None found</span>';
  }

  // Agents table
  const tbody = document.getElementById('settings-agent-tbody');
  tbody.innerHTML = (s.agents || []).map(a => `
    <tr>
      <td class="agent-tbl-name">${escHtml(a.name)}${a.availability_issues?.length ? `<small class="form-error">${escHtml(a.availability_issues.join("; "))}</small>` : ""}</td>
      <td class="agent-tbl-class">${escHtml(roleLabel(a.class_name))}</td>
      <td class="agent-tbl-model">${escHtml(a.model || '—')}</td>
      <td><div class="agent-tbl-actions">
        <button class="btn-icon" data-edit-id="${escAttr(a.id)}">Edit</button>
        <button class="btn-icon danger" data-delete-id="${escAttr(a.id)}">Delete</button>
      </div></td>
    </tr>
  `).join('');
  tbody.querySelectorAll('[data-edit-id]').forEach(btn => {
    btn.addEventListener('click', () => openAgentFormById(btn.dataset.editId));
  });
  tbody.querySelectorAll('[data-delete-id]').forEach(btn => {
    btn.addEventListener('click', () => deleteAgent(btn.dataset.deleteId));
  });

  const archived = s.legacy_agents || [];
  document.getElementById('legacy-agents-panel').hidden = archived.length === 0;
  const legacyList = document.getElementById('legacy-agent-list');
  legacyList.innerHTML = archived.map(a => `<div class="cron-row"><span class="cron-name">${escHtml(a.name)} · ${escHtml(a.class_name || 'Custom')} · ${escHtml(a.model || 'Default model')}<br><small>Tools: ${escHtml(a.tools === 'all' ? 'all available' : (a.tools || []).join(', ') || 'none')}</small></span><div class="agent-tbl-actions"><button class="btn-icon" data-migrate-id="${escAttr(a.id)}">Migrate ${escHtml(a.name)}</button><button class="btn-icon danger" data-delete-legacy-id="${escAttr(a.id)}" aria-label="Delete archived agent ${escAttr(a.name)}">Delete</button></div></div>`).join('');
  legacyList.querySelectorAll('[data-migrate-id]').forEach(button => button.addEventListener('click', () => send({type: 'migrate_legacy_agent', agent_id: button.dataset.migrateId})));
  legacyList.querySelectorAll('[data-delete-legacy-id]').forEach(button => button.addEventListener('click', () => {
    const agent = archived.find(a => a.id === button.dataset.deleteLegacyId);
    if (agent && confirm(`Delete archived agent "${agent.name}"? It will no longer be available to migrate.`)) {
      send({type: 'delete_legacy_agent', agent_id: agent.id});
    }
  }));

  // Populate class <select> once
  const sel = document.getElementById('af-class');
  if (sel && !sel.options.length && s.agent_classes) {
    s.agent_classes.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.name;
      opt.textContent = `${c.icon} ${roleLabel(c.name)}`;
      sel.appendChild(opt);
    });
  }

  // Cron jobs
  const cronBody = document.getElementById('settings-cron-body');
  if (s.cron_jobs && s.cron_jobs.length) {
    cronBody.innerHTML = s.cron_jobs.map(j => `
      <div class="cron-row">
        <span class="cron-name">${escHtml(j.name || j.id)}</span>
        <span class="cron-expr">${escHtml(cronToHuman(j.cron_expression))}</span>
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
    { id: 'intg-speak',    key: 'speak',       ok: 'Ready',       fail: 'Run /speak to set up' },
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
  document.getElementById('af-all-tools').checked = selectedTools === 'all';
  const selected = new Set(selectedTools === 'all' ? tools.filter(t => !t.workspace).map(t => t.name) : selectedTools || []);
  tools.forEach(t => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'tool-chip' + (selected.has(t.name) ? ' selected' : '');
    chip.dataset.name = t.name;
    chip.title = t.description;
    chip.innerHTML = escHtml(t.name) + (t.workspace ? ' <span class="ws-badge">[WS]</span>' : '');
    chip.setAttribute('aria-pressed', String(selected.has(t.name)));
    chip.addEventListener('click', () => {
      document.getElementById('af-all-tools').checked = false;
      chip.classList.toggle('selected');
      chip.setAttribute('aria-pressed', String(chip.classList.contains('selected')));
    });
    picker.appendChild(chip);
  });
}

function getSelectedTools() {
  const chips = document.querySelectorAll('#af-tool-picker .tool-chip.selected');
  if (document.getElementById('af-all-tools').checked) return 'all';
  return Array.from(chips).map(c => c.dataset.name);
}

function openAgentForm(agent) {
  State.editingAgentId = agent ? agent.id : null;
  document.getElementById('af-name').value = agent ? agent.name : '';
  document.getElementById('af-model').value = agent ? (agent.model || '') : '';
  document.getElementById('af-prompt').value = agent ? (agent.system_prompt || '') : '';
  document.getElementById('af-class').value = agent?.class_name || 'Custom';
  document.getElementById('af-guidance').value = agent?.when_to_call || '';
  document.getElementById('af-exclusions').value = agent?.when_not_to_call || '';
  document.getElementById('af-examples').value = (agent?.routing_examples || []).join('\n');
  document.getElementById('af-routable').checked = agent ? !!agent.routable : true;
  document.getElementById('af-error').textContent = '';
  renderToolPicker(agent ? (agent.tools || []) : []);
  if (!agent) applyRolePreset();
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
  inner.className = 'msg-content';

  if (sourceLabel) {
    const lbl = document.createElement('div');
    lbl.className = 'msg-source-label';
    lbl.textContent = sourceLabel === 'telegram' ? '📱 Telegram' : sourceLabel;
    inner.appendChild(lbl);
  }

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  ChatMarkdown.set(bubble, text);
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
  document.getElementById('chat-portrait-class-name').textContent = roleLabel(className);
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

function renderChatAgentList() {
  const list = document.getElementById('chat-agent-list');
  if (!list) return;
  list.innerHTML = State.agents.map(a => {
    const icon = CLASS_ICONS[a.class_name] || '🌀';
    const level = a.progression?.level || a.level || 1;
    const isActive = a.id === State.activeAgentId;
    return `
      <div class="chat-agent-item ${isActive ? 'active' : ''}" data-id="${escAttr(a.id)}">
        <span class="chat-agent-item-icon">${icon}</span>
        <div class="chat-agent-item-info">
          <div class="chat-agent-item-name">${escHtml(a.name || 'Agent')}</div>
          <div class="chat-agent-item-sub">Lv. ${level} · ${escHtml(roleLabel(a.class_name))}</div>
        </div>
      </div>`;
  }).join('');

  list.querySelectorAll('.chat-agent-item').forEach(el => {
    el.addEventListener('click', () => {
      const id = el.dataset.id;
      if (id === State.activeAgentId) return;
      State.activeAgentId = id;
      State.viewingAgentId = id;
      send({ type: 'switch_agent', agent_id: id });
      renderChatAgentList();
      renderRoster();
      updateChatHeader();
    });
  });
}

// ── Agent stats rendering ─────────────────────────────────────
const CLASS_ICONS = { Router:'🧭', Custom:'🌀', Keeper:'📚', Explorer:'🔭', Builder:'⚒️', Planner:'🔮', Scheduler:'⏱️' };
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
    achWrap.innerHTML = '<span class="no-achievements">No achievements yet — start a conversation!</span>';
  } else {
    // Group by category
    const grouped = {};
    achs.forEach(a => {
      const meta = ACHIEVEMENT_META[a.id] || { icon: '🏅', category: 'Other' };
      const cat = meta.category;
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push({ ...a, icon: meta.icon });
    });
    const catOrder = ['Progression', 'Milestones', 'Tool Use', 'Behavioral', 'Other'];
    let html = '';
    catOrder.forEach(cat => {
      if (!grouped[cat]) return;
      html += `<div class="ach-category-header">${escHtml(cat)}</div>`;
      html += '<div class="ach-category-group">';
      grouped[cat].forEach(a => {
        const date = a.earned_at ? a.earned_at.slice(0, 10) : '';
        html += `
          <div class="achievement-card">
            <span class="ach-icon">${a.icon}</span>
            <div class="ach-body">
              <span class="ach-name">${escHtml(a.name)}</span>
              <span class="ach-desc">${escHtml(a.description)}</span>
              ${date ? `<span class="ach-date">${escHtml(date)}</span>` : ''}
            </div>
          </div>`;
      });
      html += '</div>';
    });
    achWrap.innerHTML = html;
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
          <div class="roster-item-level">Lv. ${escHtml(String(a.level ?? '?'))} · ${escHtml(roleLabel(a.class_name))}</div>
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

// ── Cron job editor ───────────────────────────────────────────
function renderJobAgentSelect(id = '') {
  const sel = document.getElementById('job-agent-select');
  sel.innerHTML = '<option value="">Coordinator (Perseus)</option>' + State.agents.map(a => `<option value="${escAttr(a.id)}">${escHtml(a.name)}</option>`).join('');
  if (id && !State.agents.some(a => a.id === id)) {
    const missing = document.createElement('option');
    missing.value = id; missing.textContent = `Archived or missing agent (${id}) — migrate or reassign`;
    sel.appendChild(missing);
  }
  sel.value = id;
}
function renderJobList() {
  const list = document.getElementById('job-list');
  list.innerHTML = State.jobs.length ? State.jobs.map(j => `<button class="job-item ${j.id === State.selectedJobId ? 'active' : ''}" data-job-id="${escAttr(j.id)}"><span>⏰</span><span class="job-item-title">${escHtml(j.name)}<br><small>${escHtml(cronToHuman(j.cron_expression))} · ${j.running ? 'Running' : j.enabled ? 'Enabled' : 'Paused'}</small></span></button>`).join('') : '<div class="job-empty">No cron jobs yet. Create one to automate a task.</div>';
  list.querySelectorAll('[data-job-id]').forEach(el => el.addEventListener('click', () => selectJob(el.dataset.jobId)));
}
function selectJob(id) {
  const j = State.jobs.find(x => x.id === id);
  if (!j) return;
  State.selectedJobId = id;
  document.getElementById('job-history').textContent = 'Loading run history…';
  send({type: 'get_cron_history', cron_id: id});
  document.getElementById('job-name-input').value = j.name;
  loadJobSchedule(j.cron_expression);
  document.getElementById('job-timezone-input').value = j.timezone;
  document.getElementById('job-prompt-input').value = j.prompt;
  renderJobAgentSelect(j.agent_id || '');
  renderJobList(); renderJobStatus();
}
function clearJobEditor() {
  State.selectedJobId = null;
  document.getElementById('job-history').textContent = '';
  send({type: 'get_cron_history', cron_id: ''});
  document.getElementById('job-name-input').value = '';
  document.getElementById('job-prompt-input').value = '';
  loadJobSchedule('0 9 * * *');
  document.getElementById('job-timezone-input').value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  document.getElementById('job-message').textContent = '';
  renderJobAgentSelect(); renderJobList(); renderJobStatus();
}
function renderJobStatus() {
  const j = State.jobs.find(x => x.id === State.selectedJobId);
  for (const action of ['run','toggle','delete']) document.getElementById(`btn-${action}-job`).disabled = !j || (action === 'run' && j.running);
  document.getElementById('btn-toggle-job').textContent = j?.enabled === false ? 'Resume' : 'Pause';
  document.getElementById('job-status').textContent = j ? `ID: ${j.id} · ${j.running ? 'Running' : j.enabled ? 'Enabled' : 'Paused'} · Next: ${j.next_run || 'Not scheduled'} · Last: ${j.last_status || 'Never run'}${j.last_run ? ' at ' + j.last_run : ''}${j.agent_issue ? ' · ' + j.agent_issue : ''}` : '';
  document.getElementById('job-result').textContent = j?.last_result || '';
}

function renderCronHistory(msg) {
  if (msg.cron_id !== State.selectedJobId) return;
  const records = msg.runs || [];
  const roots = records.filter(r => !r.parent_run_id).reverse().slice(0, 20);
  document.getElementById('job-history').innerHTML = roots.length ? roots.map(root => {
    const child = records.find(r => r.parent_run_id === root.id);
    const run = child || root;
    const author = child ? `${root.agent_name} → ${child.agent_name}` : root.agent_name;
    const running = !FINISHED.has(root.status);
    return `<details ${running ? 'open' : ''}><summary>${escHtml(new Date(root.created_at).toLocaleString())} · ${escHtml(author)} · ${escHtml(root.status)}</summary><p>Delivery: ${escHtml(root.delivery_status || 'pending')} · Run: ${escHtml(root.id)}</p><pre class="job-run-output">${escHtml(run.result || (running ? 'Waiting for response…' : ''))}</pre>${run.error ? `<p class="form-error">${escHtml(run.error)}</p>` : ''}</details>`;
  }).join('') : '<p>No runs yet.</p>';
}

// ── Cron helpers ──────────────────────────────────────────────
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
function parseJobSchedule(expr) {
  const parts = (expr || '').trim().toLowerCase().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, day, month, weekday] = parts;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour) || +minute > 59 || +hour > 23 || month !== '*') return null;
  const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`;
  if (day === '*' && weekday === '*') return { repeat: 'daily', time };
  if (day === '*' && ['mon-fri', '0-4'].includes(weekday)) return { repeat: 'weekdays', time };
  const weekIndex = WEEKDAYS.indexOf(weekday);
  if (day === '*' && (weekIndex >= 0 || /^[0-6]$/.test(weekday))) return { repeat: 'weekly', time, weekday: WEEKDAYS[weekIndex >= 0 ? weekIndex : +weekday] };
  if (weekday === '*' && /^\d+$/.test(day) && +day >= 1 && +day <= 31) return { repeat: 'monthly', time, day: +day };
  return null;
}
function updateJobScheduleFields() {
  const repeat = document.getElementById('job-repeat-select').value;
  document.getElementById('job-weekday-wrap').hidden = repeat !== 'weekly';
  document.getElementById('job-monthday-wrap').hidden = repeat !== 'monthly';
  document.getElementById('job-time-input').disabled = repeat === 'existing';
  document.getElementById('job-schedule-hint').textContent = repeat === 'existing'
    ? 'This job uses a custom recurring schedule. It will stay unchanged unless you choose a new repeat option.'
    : repeat === 'monthly' ? 'Choose or type a time in the timezone above. Months without the selected day are skipped.'
    : 'Choose or type a time in the timezone above.';
}
function loadJobSchedule(expr) {
  State.existingSchedule = expr;
  const parsed = parseJobSchedule(expr);
  const select = document.getElementById('job-repeat-select');
  select.querySelector('[value="existing"]').hidden = !!parsed;
  select.value = parsed?.repeat || 'existing';
  document.getElementById('job-time-input').value = parsed?.time || '09:00';
  document.getElementById('job-weekday-select').value = parsed?.weekday || 'mon';
  document.getElementById('job-monthday-input').value = parsed?.day || 1;
  updateJobScheduleFields();
}
function readJobSchedule() {
  const repeat = document.getElementById('job-repeat-select').value;
  if (repeat === 'existing') return State.existingSchedule;
  const input = document.getElementById('job-time-input');
  if (!input.reportValidity() || !input.value) return null;
  const [hour, minute] = input.value.split(':').map(Number);
  let day = '*', weekday = '*';
  if (repeat === 'weekdays') weekday = 'mon-fri';
  if (repeat === 'weekly') weekday = document.getElementById('job-weekday-select').value;
  if (repeat === 'monthly') {
    const dayInput = document.getElementById('job-monthday-input');
    if (!dayInput.reportValidity()) return null;
    day = dayInput.value;
  }
  return `${minute} ${hour} ${day} * ${weekday}`;
}
document.getElementById('job-repeat-select').addEventListener('change', updateJobScheduleFields);
function cronToHuman(expr) {
  const parsed = parseJobSchedule(expr);
  if (!parsed) return 'Custom recurring schedule';
  const [hour, minute] = parsed.time.split(':').map(Number);
  const time = `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour >= 12 ? 'PM' : 'AM'}`;
  const repeat = parsed.repeat === 'daily' ? 'Every day' : parsed.repeat === 'weekdays' ? 'Weekdays' : parsed.repeat === 'weekly' ? `Every ${WEEKDAY_NAMES[WEEKDAYS.indexOf(parsed.weekday)]}` : `Monthly on day ${parsed.day}`;
  return `${repeat} at ${time}`;
}

// ── Battle Map ────────────────────────────────────────────────

function pushBattleLog(agentId, text) {
  const agent = State.agents.find(a => a.id === agentId);
  const name = agent ? agent.name : 'Agent';
  const icon = agent ? (CLASS_ICONS[agent.class_name] || '🌀') : '🌀';
  const now = new Date();
  const time = now.toTimeString().slice(0, 8);
  State.battleLog.push({ text, agentName: name, icon, time });
  if (State.battleLog.length > 20) State.battleLog.shift();
}

function renderBattleMap() {
  // Party count
  const countEl = document.getElementById('map-party-count');
  if (countEl) countEl.textContent = `Party: ${State.agents.length} agent${State.agents.length !== 1 ? 's' : ''}`;

  const objZone = document.getElementById('map-objectives');
  objZone.innerHTML = '<div class="map-section-label">Cron Jobs</div>' + State.jobs.map(j => `<button class="map-cron-tile" data-job-id="${escAttr(j.id)}"><span>⏰</span><span class="map-cron-body"><span class="map-cron-name">${escHtml(j.name)}</span><br><span class="map-cron-schedule">${escHtml(cronToHuman(j.cron_expression))} · ${escHtml(j.timezone)}</span></span><span class="map-cron-status ${j.enabled ? 'on' : 'off'}">${j.running ? 'Running' : j.enabled ? 'On' : 'Paused'}</span></button>`).join('') + (State.jobs.length ? '' : '<div class="map-empty">No scheduled jobs</div>') + '<button id="map-new-job" class="btn-new">+ New Job</button>';
  objZone.querySelectorAll('[data-job-id]').forEach(el => el.addEventListener('click', () => { switchPage('jobs'); selectJob(el.dataset.jobId); }));
  document.getElementById('map-new-job').addEventListener('click', () => { switchPage('jobs'); clearJobEditor(); });

  // Party zone
  const partyZone = document.getElementById('map-party');
  if (State.agents.length === 0) {
    partyZone.innerHTML = '<div class="map-empty">No agents yet — create one in Settings</div>';
  } else {
    partyZone.innerHTML = State.agents.map((a, i) => {
      const icon = CLASS_ICONS[a.class_name] || '🌀';
      const level = a.progression?.level || a.level || 1;
      const prog = a.progression || {};
      const xpThis = prog.xp_this_level || 0;
      const xpLeft = prog.xp_next_level || 100;
      const xpTotal = xpThis + xpLeft;
      const pct = xpTotal > 0 ? Math.min(100, Math.round(xpThis / xpTotal * 100)) : 0;
      const status = State.agentStatus[a.id] || 'idle';
      const statusClass = status === 'thinking' ? 'thinking' : (status.startsWith('tool:') ? 'working' : 'idle');
      const isActive = a.id === State.activeAgentId;
      return `
        <div class="map-agent-tile ${statusClass}${isActive ? ' active-turn' : ''}" data-id="${escAttr(a.id)}">
          <img class="map-agent-img" src="/agent-image?agent_id=${encodeURIComponent(a.id)}" alt="${escAttr(a.name)}" onerror="this.style.opacity='0.15'" />
          <div class="map-agent-body">
            <div class="map-agent-name">${icon} ${escHtml(a.name)}</div>
            <div class="map-agent-level">${escHtml(roleLabel(a.class_name))} · Lv.${level}</div>
            <div class="map-agent-xp-track"><div class="map-agent-xp-fill" style="width:${pct}%"></div></div>
            <div class="map-agent-connector">${isActive ? '──▶' : ''}</div>
          </div>
          <div class="map-status-dot"></div>
        </div>`;
    }).join('');
    partyZone.querySelectorAll('.map-agent-tile').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        if (id !== State.activeAgentId) {
          State.activeAgentId = id;
          State.viewingAgentId = id;
          send({ type: 'switch_agent', agent_id: id });
          renderChatAgentList();
          renderRoster();
          updateChatHeader();
        }
        switchPage('chat');
      });
    });
  }

}

function updateBattleTileStatus(agentId) {
  const tile = document.querySelector(`.map-agent-tile[data-id="${agentId}"]`);
  if (!tile) return;
  const status = State.agentStatus[agentId] || 'idle';
  tile.classList.remove('idle', 'thinking', 'working', 'active-turn');
  if (status === 'thinking') tile.classList.add('thinking');
  else if (status.startsWith('tool:')) tile.classList.add('working');
  else tile.classList.add('idle');
  if (agentId === State.activeAgentId) tile.classList.add('active-turn');
}

// ── Navigation ────────────────────────────────────────────────
function switchPage(page) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.nav-btn[data-page="${page}"]`);
  if (btn) btn.classList.add('active');
  document.getElementById(`page-${page}`).classList.add('active');
  State.page = page;
  if (page === 'map') {
    send({ type: 'get_agents' });
    send({ type: 'get_cron_jobs' });
    send({ type: 'get_settings' });
    renderBattleMap();
  }
  if (page === 'agent') {
    renderStatsFromAgents();
    send({ type: 'get_agents' });
  }
  if (page === 'jobs') { send({ type: 'get_cron_jobs' }); renderJobAgentSelect(State.jobs.find(j => j.id === State.selectedJobId)?.agent_id || ''); }
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
  if (!text || !State.connected) return;

  // Don't append locally — the server echoes it back as a user_message event
  showTyping();
  send({ type: 'chat', message: text, agent_id: State.activeAgentId, request_id: crypto.randomUUID() });
  chatInput.value = '';
  chatInput.style.height = 'auto';
  sendBtn.disabled = false;
}

// ── Cron job actions ──────────────────────────────────────────
document.getElementById('btn-new-job').addEventListener('click', clearJobEditor);
document.getElementById('btn-save-job').addEventListener('click', () => {
  if (!State.connected) { document.getElementById('job-message').textContent = 'Disconnected. Reconnect before saving.'; return; }
  const schedule = readJobSchedule();
  if (!schedule) return;
  send({ type: 'save_cron', cron_id: State.selectedJobId || '',
    name: document.getElementById('job-name-input').value,
    cron_expression: schedule,
    timezone: document.getElementById('job-timezone-input').value,
    prompt: document.getElementById('job-prompt-input').value,
    agent_id: document.getElementById('job-agent-select').value });
});
for (const action of ['run', 'toggle', 'delete']) {
  document.getElementById(`btn-${action}-job`).addEventListener('click', () => {
    if (action === 'delete' && !confirm('Delete this cron job? A running job will finish.')) return;
    send({ type: `${action}_cron`, cron_id: State.selectedJobId });
  });
}

// ── New Chat button ───────────────────────────────────────────
document.getElementById('btn-new-chat').addEventListener('click', () => {
  send({ type: 'new_thread' });
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
  const guidance = document.getElementById('af-guidance').value.trim();
  const routable = document.getElementById('af-routable').checked;
  const prompt = document.getElementById('af-prompt').value.trim();
  if (!prompt || (routable && !guidance)) {
    document.getElementById('af-error').textContent = !prompt ? 'Add a system prompt.' : 'Describe when to call this agent.';
    return;
  }
  if (!State.connected) { document.getElementById('af-error').textContent = 'Reconnect before saving.'; return; }
  const payload = {
    name,
    tools: getSelectedTools(),
    class_name: document.getElementById('af-class').value,
    model: document.getElementById('af-model').value.trim() || null,
    system_prompt: prompt,
    when_to_call: guidance, routable,
    when_not_to_call: document.getElementById('af-exclusions').value.trim(),
    routing_examples: document.getElementById('af-examples').value.split('\n').map(s => s.trim()).filter(Boolean),
  };
  if (State.editingAgentId) {
    send({ type: 'update_agent', agent_id: State.editingAgentId, ...payload });
  } else {
    send({ type: 'create_agent', ...payload });
  }
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

// ── Portrait header click (navigate to agent stats) ───────────
document.getElementById('chat-portrait-header').addEventListener('click', () => {
  switchPage('agent');
});

// ── Boot ──────────────────────────────────────────────────────
connect();

function roleLabel(role) {
  return State.settings?.role_labels?.[role] || ({Router:'Coordinator', Explorer:'Researcher', Keeper:'Workspace knowledge', Builder:'Builder', Planner:'Planning & advising'})[role] || role || 'Custom';
}
function applyRolePreset() {
  const role = document.getElementById('af-class').value;
  const preset = State.settings?.agent_presets?.[role];
  if (!preset) return;
  document.getElementById('af-prompt').value = preset.system_prompt;
  document.getElementById('af-guidance').value = preset.when_to_call;
  renderToolPicker(preset.tools);
}
document.getElementById('af-class').addEventListener('change', applyRolePreset);
