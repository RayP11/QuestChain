"""Manual specialist selection: no implicit routing or permission expansion."""
import asyncio
import copy
import json

import pytest

from questchain.agents import AgentManager, tool_access_allowed
from questchain.engine.tools import ToolRegistry
from questchain.runtime import TaskRequest, TaskRuntime


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    from questchain import config
    from questchain.engine import context
    root = tmp_path / 'data'
    monkeypatch.setattr(config, 'QUESTCHAIN_DATA_DIR', root)
    monkeypatch.setattr(context, 'QUESTCHAIN_DATA_DIR', root)
    return root


def test_manual_selection_persists_and_unknown_id_does_not_change_it(isolated):
    manager = AgentManager()
    specialist = manager.get_by_class_name('Keeper')
    manager.set_active(specialist['id'])
    assert AgentManager().get_active()['id'] == specialist['id']
    with pytest.raises(ValueError, match='not found'):
        manager.set_active('missing')
    assert AgentManager().get_active_id() == specialist['id']
    manager.set_active(next(a['id'] for a in manager.all_agents() if a['kind'] == 'main'))
    assert AgentManager().get_active()['kind'] == 'main'


def test_routing_metadata_cannot_enable_delegation(isolated):
    manager = AgentManager()
    specialist = manager.add('Reviewer', None, 'Review carefully.', [],
                             when_to_call='Review anything', routable=True)
    assert not specialist['routable']
    assert manager.catalog() == []
    updated = manager.update(specialist['id'], routable=True)
    assert not updated['routable']
    for name in ('delegate_to_agent', 'route_to_agent'):
        assert not tool_access_allowed({'tools': 'all'}, name)


def test_manual_migration_preserves_user_state_and_is_idempotent(isolated):
    isolated.mkdir(parents=True)
    agents = [
        {'id': 'default', 'name': 'My QuestChain', 'tools': ['read_file'],
         'class_name': 'Custom', 'system_prompt': 'My custom instructions', 'revision': 7},
        {'id': 'keeper-42', 'name': 'Notes', 'tools': ['read_file', 'write_file'],
         'class_name': 'Keeper', 'system_prompt': 'Keep this exact custom prompt', 'routable': True},
    ]
    (isolated / 'agents.json').write_text(json.dumps(agents), encoding='utf-8')
    (isolated / 'active_agent').write_text('keeper-42', encoding='utf-8')
    jobs = '[{"id":"job-1","agent_id":"keeper-42","enabled":false}]'
    (isolated / 'cron_jobs.json').write_text(jobs, encoding='utf-8')
    history = isolated / 'history'
    history.mkdir()
    (history / 'saved.json').write_text('{"messages":["remember me"]}', encoding='utf-8')
    manager = AgentManager()
    assert manager.get_active_id() == 'keeper-42'
    assert {a['id'] for a in manager.all_agents()} == {'default', 'keeper-42'}
    for original in agents:
        migrated = manager.get(original['id'])
        for key in ('name', 'tools', 'system_prompt'):
            assert migrated[key] == original[key]
        assert migrated['routable'] is False
    assert (isolated / 'cron_jobs.json').read_text(encoding='utf-8') == jobs
    assert (history / 'saved.json').read_text(encoding='utf-8') == '{"messages":["remember me"]}'
    archive = isolated / 'legacy' / 'before-manual-agents-v5.json'
    assert json.loads(archive.read_text(encoding='utf-8')) == agents
    assert AgentManager().all_agents() == manager.all_agents()
    assert json.loads(archive.read_text(encoding='utf-8')) == agents


class RecordingRunner:
    def __init__(self, definition, calls, invoke=None):
        self.definition, self.calls, self.invoke = definition, calls, invoke
        self.tools = ToolRegistry()

    async def run(self, prompt, thread_id, on_tool_call, **kwargs):
        self.calls.append((self.definition['id'], prompt, copy.deepcopy({k: v for k, v in kwargs.items() if k != 'tool_budget'}), self.tools.names()))
        if self.invoke:
            await self.invoke(on_tool_call)
        yield self.definition['name'] + ' directly answered'


@pytest.mark.parametrize('source', ['cli', 'web', 'telegram', 'cron'])
async def test_selected_specialist_executes_once_without_parent_synthesis(isolated, source):
    manager = AgentManager()
    specialist = manager.add('Reviewer', None, 'Review.', [])
    calls = []
    runtime = TaskRuntime(manager, default_model='unused',
                          agent_factory=lambda d: RecordingRunner(d, calls), event_sink=lambda _: None)
    try:
        rid = runtime.submit(TaskRequest('Review this', specialist['id'], 'conversation', source))
        result = await asyncio.wait_for(runtime.wait(rid), 3)
        assert result['status'] == 'completed'
        assert result['agent_id'] == specialist['id']
        assert result['result'] == 'Reviewer directly answered'
        assert len(calls) == len(runtime.store.runs()) == 1
        assert 'delegate_to_agent' not in calls[0][3]
        assert 'route_to_agent' not in calls[0][3]
        assert not result.get('parent_run_id')
    finally:
        await runtime.close()


async def test_manual_switch_keeps_model_history_scoped_to_selected_agent(isolated):
    manager = AgentManager()
    first = manager.add('First', None, '', [])
    second = manager.add('Second', None, '', [])
    calls = []
    runtime = TaskRuntime(manager, default_model='unused',
                          agent_factory=lambda d: RecordingRunner(d, calls), event_sink=lambda _: None)
    try:
        for agent, text in ((first, 'first secret'), (second, 'second secret'), (first, 'first followup')):
            await runtime.wait(runtime.submit(TaskRequest(text, agent['id'], 'same-thread')))
        assert calls[1][2]['initial_messages'] == []
        assert [m['content'] for m in calls[2][2]['initial_messages'] if m['role'] == 'user'] == ['first secret']
        assert all(call[2]['shared_history'] is None for call in calls)
    finally:
        await runtime.close()


@pytest.mark.parametrize('tool', ['delegate_to_agent', 'route_to_agent'])
async def test_injected_delegation_attempt_is_rejected_even_with_all_tools(isolated, tool):
    manager = AgentManager()
    agent = manager.get_active()
    calls = []
    async def invoke(callback):
        await callback(tool, {'agent_id': 'other', 'task': 'do work'})
    runtime = TaskRuntime(manager, default_model='unused',
                          agent_factory=lambda d: RecordingRunner(d, calls, invoke), event_sink=lambda _: None)
    try:
        result = await runtime.wait(runtime.submit(TaskRequest('Try routing', agent['id'], 'c')))
        assert result['status'] == 'failed'
        assert 'delegation is disabled' in result['error']
        assert len(runtime.store.runs()) == 1
    finally:
        await runtime.close()


async def test_live_tool_revocation_is_enforced_for_selected_specialist(isolated):
    manager = AgentManager()
    agent = manager.add('Restricted', None, '', ['read_file'])
    # A runner without a tool registry lets us isolate the live callback guard.
    class Runner:
        async def run(self, prompt, on_tool_call, **kwargs):
            manager.update(agent['id'], tools=[])
            await on_tool_call('read_file', {'path': '/workspace/note.txt'})
            yield 'must not reach here'
    runtime = TaskRuntime(manager, default_model='unused', agent_factory=lambda _: Runner(), event_sink=lambda _: None)
    try:
        result = await runtime.wait(runtime.submit(TaskRequest('Read', agent['id'], 'c')))
        assert result['status'] == 'failed'
        assert 'no longer enabled' in result['error']
    finally:
        await runtime.close()


def test_manual_migration_restart_keeps_ids_and_original_archive(isolated, monkeypatch):
    from questchain import migration
    isolated.mkdir(parents=True)
    original = [{'id': 'specialist', 'name': 'Saved', 'class_name': 'Custom',
                 'tools': [], 'system_prompt': 'Exact prompt'}]
    (isolated / 'agents.json').write_text(json.dumps(original), encoding='utf-8')
    atomic = migration.atomic_json
    def fail_marker(path, value):
        if path.name == 'manual_agents_v5.json':
            raise OSError('Simulated crash before marker')
        atomic(path, value)
    monkeypatch.setattr(migration, 'atomic_json', fail_marker)
    with pytest.raises(OSError, match='Simulated crash'):
        AgentManager()
    first = json.loads((isolated / 'agents.json').read_text(encoding='utf-8'))
    monkeypatch.setattr(migration, 'atomic_json', atomic)
    assert AgentManager().all_agents() == first
    assert json.loads((isolated / 'legacy/before-manual-agents-v5.json').read_text(encoding='utf-8')) == original


async def test_direct_scheduled_occurrence_is_deduplicated(isolated):
    manager = AgentManager()
    owner = manager.add('Scheduled owner', None, '', [])
    calls = []
    runtime = TaskRuntime(manager, default_model='unused',
                          agent_factory=lambda d: RecordingRunner(d, calls), event_sink=lambda _: None)
    try:
        request = TaskRequest('Once', owner['id'], 'scheduled', 'cron', occurrence_key='same-occurrence')
        first = runtime.submit(request)
        assert runtime.submit(request) == first
        await runtime.wait(first)
        assert runtime.submit(request) == first
        assert len(calls) == len(runtime.store.runs()) == 1
    finally:
        await runtime.close()


async def test_cancel_direct_specialist_and_explicit_retry(isolated):
    manager = AgentManager()
    owner = manager.add('Slow', None, '', [])
    manager.set_active(owner['id'])
    started, cleaned = asyncio.Event(), asyncio.Event()
    runs = []
    class Runner:
        async def run(self, *args, **kwargs):
            runs.append(True)
            if len(runs) == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            yield 'Retry completed'
    runtime = TaskRuntime(manager, default_model='unused', agent_factory=lambda _: Runner(), event_sink=lambda _: None)
    try:
        first = runtime.submit(TaskRequest('Work', owner['id'], 'chat'))
        await asyncio.wait_for(started.wait(), 2)
        runtime.cancel(first)
        assert (await runtime.wait(first))['status'] == 'cancelled'
        assert cleaned.is_set() and not runtime.lock.locked()
        manager.set_active(next(a['id'] for a in manager.all_agents() if a['kind'] == 'main'))
        retried = await runtime.wait(runtime.retry(first))
        assert retried['status'] == 'completed'
        assert retried['agent_id'] == owner['id']
        assert retried['result'] == 'Retry completed'
    finally:
        await runtime.close()


async def test_retry_deleted_original_owner_does_not_fall_back_to_main(isolated):
    manager = AgentManager()
    owner = manager.add('Temporary', None, '', [])
    calls = []
    runtime = TaskRuntime(manager, default_model='unused',
                          agent_factory=lambda d: RecordingRunner(d, calls), event_sink=lambda _: None)
    try:
        first = runtime.submit(TaskRequest('Work', owner['id'], 'chat'))
        await runtime.wait(first)
        manager.remove(owner['id'])
        with pytest.raises(ValueError, match='no longer exists'):
            runtime.retry(first)
        assert len(calls) == len(runtime.store.runs()) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize('completed_by_other_startup', [False, True])
def test_migration_rechecks_roster_and_marker_after_lock(isolated, monkeypatch, completed_by_other_startup):
    from questchain.runtime import store
    isolated.mkdir(parents=True)
    path = isolated / 'agents.json'
    path.write_text('[]', encoding='utf-8')
    newer = [{'id': 'other-startup', 'kind': 'main', 'name': 'Latest', 'class_name': 'Custom',
              'tools': [], 'system_prompt': 'Latest prompt', 'revision': 9}]
    closed = []
    class ConcurrentStartup:
        def __init__(self, _path):
            # Simulate another process finishing after the initial unlocked read.
            path.write_text(json.dumps(newer), encoding='utf-8')
            if completed_by_other_startup:
                (isolated / 'manual_agents_v5.json').write_text('{"version":5}', encoding='utf-8')
        def close(self):
            closed.append(True)
    monkeypatch.setattr(store, 'RunStore', ConcurrentStartup)
    manager = AgentManager()
    assert [a['id'] for a in manager.all_agents()] == ['other-startup']
    assert manager.get('other-startup')['revision'] == 9
    assert closed == [True]
    archive = isolated / 'legacy/before-manual-agents-v5.json'
    if completed_by_other_startup:
        assert manager.all_agents() == newer
        assert not archive.exists()
    else:
        assert json.loads(archive.read_text(encoding='utf-8')) == newer


def test_migration_preserves_private_roster_and_archive_modes(isolated):
    import os
    import stat
    if os.name == 'nt':
        pytest.skip('POSIX permission bits are not enforced by Windows chmod')
    isolated.mkdir(parents=True)
    path = isolated / 'agents.json'
    path.write_text('[{"id":"default","name":"Private","class_name":"Custom","tools":[],"system_prompt":"Private prompt"}]', encoding='utf-8')
    path.chmod(0o600)
    AgentManager()
    archive = isolated / 'legacy/before-manual-agents-v5.json'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
