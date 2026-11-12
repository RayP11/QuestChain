const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../questchain/static/app.js'), 'utf8');
const openStart = source.indexOf('function openAgentForm(agent) {');
const openEnd = source.indexOf('// Opens the agent edit form', openStart);
const saveStart = source.indexOf("document.getElementById('af-save').addEventListener");
const saveEnd = source.indexOf('\n});', saveStart) + '\n});'.length;
assert.ok(openStart >= 0 && openEnd > openStart && saveStart >= 0 && saveEnd > saveStart);

function form() {
  const nodes = new Map();
  const sent = [];
  const State = {connected: true};
  const document = {getElementById(id) {
    if (!nodes.has(id)) {
      let value = '';
      nodes.set(id, {
        get value() { return value; },
        set value(v) { value = String(v).replace(/\r\n?/g, '\n'); },
        focus() {}, classList: {add() {}},
        addEventListener(event, callback) { this[event] = callback; },
      });
    }
    return nodes.get(id);
  }};
  const context = vm.createContext({State, document,
    renderToolPicker() {}, getSelectedTools: () => ['read_file'],
    applyRolePreset() { document.getElementById('af-prompt').value = 'Role preset'; },
    send(payload) { sent.push(payload); },
  });
  vm.runInContext(source.slice(openStart, openEnd) + '\n' + source.slice(saveStart, saveEnd), context);
  return {open: context.openAgentForm, nodes, sent, save: () => nodes.get('af-save').click()};
}

for (const prompt of [null, '', '   \t', '  Keep this prompt.  ', 'First\r\nSecond\rThird\n']) {
  test(`unchanged prompt preserved exactly: ${JSON.stringify(prompt)}`, () => {
    const f = form();
    f.open({id: 'writer', name: 'Writer', system_prompt: prompt, tools: []});
    f.nodes.get('af-name').value = 'Renamed';
    f.save();
    assert.equal(f.sent.length, 1);
    assert.equal(f.sent[0].system_prompt, prompt);
    assert.equal(f.sent[0].type, 'update_agent');
  });
}

test('intentional clearing and whitespace edits are not blocked or trimmed', () => {
  for (const replacement of ['', '  New prompt  ', ' \t ']) {
    const f = form();
    f.open({id: 'writer', name: 'Writer', system_prompt: 'Original', tools: []});
    f.nodes.get('af-prompt').value = replacement;
    f.save();
    assert.equal(f.sent.length, 1);
    assert.equal(f.sent[0].system_prompt, replacement);
  }
});

test('new agent can explicitly use an empty prompt', () => {
  const f = form();
  f.open(null);
  f.nodes.get('af-name').value = 'New agent';
  f.nodes.get('af-prompt').value = '';
  f.save();
  assert.equal(f.sent[0].system_prompt, '');
  assert.equal(f.sent[0].type, 'create_agent');
});
