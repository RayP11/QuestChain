"""Single-assistant contracts through real runtime, engine, migration and adapters."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from questchain.agents import AgentManager, MAIN_SYSTEM_PROMPT, PREVIOUS_MAIN_SYSTEM_PROMPT
from questchain.engine.agent import Agent
from questchain.engine.model import Chunk
from questchain.engine.tools import ToolRegistry
from questchain.runtime import TaskRequest, TaskRuntime


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    from questchain import config
    from questchain.engine import context
    monkeypatch.setattr(config, 'QUESTCHAIN_DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(context, 'QUESTCHAIN_DATA_DIR', tmp_path / 'data')
    return tmp_path


class Model:
    num_ctx = 32768

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    async def chat_stream(self, messages, tools=None):
        self.calls.append(copy.deepcopy(messages))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, list):
            yield Chunk(done=True, tool_calls=step)
        else:
            yield Chunk(text=step, done=True)


def delegate(worker, task='Inspect the notes'):
    return [{'name': 'delegate_to_agent', 'args': {'agent_id': worker['id'], 'task': task}}]


def test_fresh_roster_and_custom_planner(isolated):
    manager = AgentManager()
    assert manager.get_active()['name'] == 'QuestChain'
    assert 'track dependencies and priorities' in manager.get_active()['system_prompt']
    assert {a['name'] for a in manager.all_agents() if a['kind'] == 'subagent'} == {'Researcher', 'Workspace', 'Builder', 'Scheduler'}
    assert set(manager.get_by_class_name('Keeper')['tools']) == {'read_file', 'write_file', 'edit_file', 'delete_file', 'ls', 'glob', 'grep'}
    assert not manager.get_by_class_name('Planner')
    worker = manager.add('My planner', None, None, [], class_name='Planner', when_to_call='Advise on plans', routable=True)
    assert worker['id'] in {a['id'] for a in manager.catalog()}
    assert AgentManager().get(worker['id']) == worker
    with pytest.raises(ValueError, match='cannot be deleted'):
        manager.remove(manager.get_active_id())


@pytest.mark.parametrize('source', ['cli', 'web', 'telegram'])
async def test_direct_worker_chat_and_selection_rejected(isolated, source):
    manager = AgentManager()
    worker = manager.get_by_class_name('Keeper')
    runtime = TaskRuntime(manager, default_model='fake')
    try:
        with pytest.raises(ValueError, match='direct chat'):
            runtime.submit(TaskRequest('Hello', worker['id'], source + '-one', source))
        with pytest.raises(ValueError, match='direct chat'):
            manager.set_active(worker['id'])
        assert runtime.store.runs() == []
    finally:
        await runtime.close()


@pytest.mark.parametrize('failure', [False, True])
async def test_private_delegation_outcome_and_parent_synthesis_one_slot(isolated, failure):
    manager = AgentManager()
    worker = manager.add('Reviewer', None, '', [], when_to_call='Review notes', routable=True)
    main = Model([delegate(worker), 'Main final answer'])
    child = Model([RuntimeError('Worker failed') if failure else 'PRIVATE worker findings'])
    events = []
    lock = asyncio.Lock()
    runtime = TaskRuntime(manager, default_model='fake', busy_lock=lock, event_sink=events.append,
        agent_factory=lambda d: Agent(main if d['kind'] == 'main' else child, ToolRegistry(), d['system_prompt'], d['name']))
    try:
        rid = runtime.submit(TaskRequest('Review', manager.get_active_id(), 'web-private', 'web'))
        result = await asyncio.wait_for(runtime.wait(rid), 2)
        assert result['agent_id'] == manager.get_active_id()
        assert result['result'] == 'Main final answer'
        assert result['status'] == 'completed'
        tool = next(m for m in main.calls[-1] if m['role'] == 'tool')
        outcome = json.loads(tool['content'])
        assert outcome['status'] == ('failed' if failure else 'completed')
        assert len(runtime.store.runs()) == 2
        assert len(runtime.snapshot('web-private')['runs']) == 1
        assert all(e['agent_id'] == manager.get_active_id() for e in runtime.events('web-private'))
        assert 'PRIVATE worker findings' not in json.dumps(events)
        assert len(child.calls) == 1
        assert 'delegate_to_agent' not in str(child.calls[0][0])
    finally:
        await runtime.close()


async def test_cancel_during_child_then_explicit_retry(isolated):
    manager = AgentManager()
    worker = manager.add('Slow', None, '', [], when_to_call='Work', routable=True)
    main = Model([delegate(worker)])
    entered = asyncio.Event()

    class Slow:
        async def run(self, *args, **kwargs):
            yield 'PRIVATE partial'
            entered.set()
            await asyncio.Event().wait()

    runtime = TaskRuntime(manager, default_model='fake', event_sink=lambda e: None,
        agent_factory=lambda d: Agent(main, ToolRegistry(), '', d['name']) if d['kind'] == 'main' else Slow())
    try:
        rid = runtime.submit(TaskRequest('Work', manager.get_active_id(), 'cli-cancel'))
        await asyncio.wait_for(entered.wait(), 2)
        runtime.cancel(rid)
        assert (await asyncio.wait_for(runtime.wait(rid), 2))['status'] == 'cancelled'
        assert {r['status'] for r in runtime.store.runs()} == {'cancelled'}
        main.steps = ['Reviewed prior effects; finished']
        retry = await runtime.wait(runtime.retry(rid))
        assert retry['status'] == 'completed'
        assert retry['task_id'] == runtime.store.get(rid)['task_id']
        assert len([r for r in runtime.store.runs() if r.get('private')]) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize('custom', [False, True])
def test_modern_planner_retirement_and_exact_prompt_upgrade(isolated, custom):
    from questchain import config
    root = config.ensure_data_dir()
    original = [dict(id='main-old', kind='main', name='Nova', model=None, tools=[],
                     system_prompt=PREVIOUS_MAIN_SYSTEM_PROMPT + ('\nMy custom guidance' if custom else ''),
                     revision=5, class_name='Custom', definition_version=3),
                dict(id='builtin-planner', kind='subagent', built_in=True, name='Edited planner',
                     tools=['read_file'], system_prompt='My customized built-in', class_name='Planner', revision=3),
                dict(id='custom-planner', kind='subagent', built_in=False, name='User planner',
                     tools=[], system_prompt='Keep exactly', class_name='Planner', revision=7)]
    config.get_agents_path().write_text(json.dumps(original))
    manager = AgentManager()
    assert manager.get('custom-planner') == original[2]
    assert manager.get('builtin-planner') is None
    assert next(a for a in manager.legacy_agents() if a['id'] == 'builtin-planner') == original[1]
    assert manager.get_active()['system_prompt'] == (original[0]['system_prompt'] if custom else MAIN_SYSTEM_PROMPT)
    assert manager.get_active()['revision'] == (5 if custom else 6)
    backup = root / 'legacy/before-single-assistant-v4/agents.json'
    assert json.loads(backup.read_text()) == original
    assert AgentManager().all_agents() == manager.all_agents()


@pytest.mark.parametrize('role,prompt', [('Planner', '  Exact custom prompt  '), ('Router', ''), ('Router', None)])
def test_legacy_import_preserves_definition_and_paused_schedule(isolated, role, prompt):
    from questchain import config
    root = config.ensure_data_dir()
    original = dict(id='old', name='Old name', class_name=role, model='custom-model', tools=[],
                    system_prompt=prompt, revision=7, definition_version=2)
    config.get_agents_path().write_text(json.dumps([original]))
    archive = root / 'legacy'
    archive.mkdir()
    (archive / 'agents.json').write_text(json.dumps([{**original, 'name': 'Older archive'}]))
    jobs = [dict(id='job-id', agent_id='old', enabled=True, prompt='External action', cron_expression='0 9 * * *', last_run_id='occurrence-id')]
    config.get_cron_jobs_path().write_text(json.dumps(jobs))
    manager = AgentManager()
    assert manager.legacy_agents()[0] == original
    imported = manager.migrate_legacy('old')
    for key in ('id', 'name', 'model', 'tools', 'system_prompt'):
        assert imported[key] == original[key]
    assert imported['kind'] == 'subagent' and not imported['routable'] and not imported['built_in']
    assert AgentManager().get('old') == imported
    saved = json.loads(config.get_cron_jobs_path().read_text())[0]
    assert saved['id'] == 'job-id' and saved['last_run_id'] == 'occurrence-id' and not saved['enabled']
    assert json.loads((archive / 'before-single-assistant-v4/legacy/agents.json').read_text())[0]['name'] == 'Older archive'
    manager.update('old', when_to_call='Review', routable=True)
    assert 'old' in {a['id'] for a in manager.catalog()}


@pytest.mark.parametrize('delegated', [False, True])
async def test_file_lifecycle_direct_and_delegated_with_real_factory(isolated, monkeypatch, delegated):
    from questchain import agent as factory
    from questchain.engine.builtins import filesystem
    manager = AgentManager()
    worker = manager.get_by_class_name('Keeper')
    path = '/workspace/knowledge/note.md'
    steps = [
        ('write_file', {'path': path, 'content': 'Status: draft'}),
        ('read_file', {'path': path}),
        ('edit_file', {'path': path, 'old_str': 'draft', 'new_str': 'ready'}),
        ('read_file', {'path': path}),
        ('delete_file', {'path': path}),
        ('ls', {'path': '/workspace/knowledge'}),
    ]
    file_model = Model([[{'name': name, 'args': args}] for name, args in steps] + ['Verified absence'])
    main = Model([delegate(worker, 'Create a draft note, update it to ready, then delete it and verify absence.'), 'Main verified the file lifecycle']) if delegated else file_model
    manager.update(manager.get_active_id(), tools=[] if delegated else worker['tools'])
    monkeypatch.setattr(factory, 'OllamaModel', lambda name: file_model if name == 'worker' else main)
    monkeypatch.setattr(factory, 'WORKSPACE_DIR', isolated)
    monkeypatch.setattr(factory, 'ensure_memory_dir', lambda: None)
    monkeypatch.setattr(filesystem, '_ROOT', isolated)
    manager.update(worker['id'], model='worker')
    events = []
    runtime = TaskRuntime(manager, default_model='main', event_sink=events.append)
    try:
        result = await asyncio.wait_for(runtime.wait(runtime.submit(TaskRequest('Do the file lifecycle', manager.get_active_id(), 'web-files', 'web'))), 3)
        assert result['status'] == 'completed', result['error']
        assert not (isolated / 'workspace/knowledge/note.md').exists()
        contents = [m['content'] for call in file_model.calls for m in call if m['role'] == 'tool']
        assert any('Status: draft' in c for c in contents)
        assert any('Status: ready' in c for c in contents)
        assert [e['name'] for e in events if e['type'] == 'tool_call'] == ([] if delegated else [s[0] for s in steps])
        assert result['agent_id'] == manager.get_active_id()
    finally:
        await runtime.close()


async def test_legacy_author_context_and_replies_stay_main(isolated):
    manager = AgentManager()
    model = Model(['Current main answer'])
    runtime = TaskRuntime(manager, default_model='fake', event_sink=lambda e: None,
        agent_factory=lambda d: Agent(model, ToolRegistry(), '', d['name']))
    old = dict(id='old-run', conversation_id='web-old', source='web', text='Old question', result='Old answer',
               agent_id='deleted-worker', agent_name='Historical author', task_id='old-task', message_id='old-message',
               status='completed', error='', created_at='2026-01-01', parent_run_id=None)
    runtime.store.put(old)
    try:
        result = await runtime.wait(runtime.submit(TaskRequest('Follow up', manager.get_active_id(), 'web-old', 'web', reply_to_run_id='old-run')))
        assert result['agent_id'] == manager.get_active_id()
        assert 'Historical author' in str(model.calls)
        assert runtime.snapshot('web-old')['runs'][0]['agent_name'] == 'Historical author'
    finally:
        await runtime.close()


async def test_worker_audio_is_discarded_and_recursion_rejected(isolated, monkeypatch):
    from questchain import agent as factory
    manager = AgentManager()
    worker = manager.add('Voice worker', None, '', [], when_to_call='Review', routable=True)
    main = Model([delegate(worker), 'Main answer'])
    public_audio = AsyncMock()

    def make(definition, audio_router=None, **kwargs):
        if definition['kind'] == 'main':
            return Agent(main, ToolRegistry(), '', definition['name'])
        class Voice:
            async def run(self, *args, on_tool_call, **kwargs):
                await audio_router(b'PRIVATE AUDIO')
                with pytest.raises(PermissionError):
                    await on_tool_call('delegate_to_agent', {})
                yield 'Private result'
        return Voice()
    monkeypatch.setattr(factory, 'make_agent_from_def', make)
    runtime = TaskRuntime(manager, default_model='fake', default_audio=public_audio, event_sink=lambda e: None)
    try:
        result = await runtime.wait(runtime.submit(TaskRequest('Review', manager.get_active_id(), 'web-audio', 'web')))
        assert result['status'] == 'completed'
        public_audio.assert_not_awaited()
    finally:
        await runtime.close()


def test_migration_restart_after_roster_write_keeps_ids_and_wal_backup(isolated, monkeypatch):
    import sqlite3
    from questchain import config, migration
    root = config.ensure_data_dir()
    config.get_agents_path().write_text(json.dumps([dict(id='legacy', name='Old', class_name='Custom', tools=[], system_prompt='Exact')]))
    db = sqlite3.connect(root / 'extra.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE important (value TEXT)')
    db.execute("INSERT INTO important VALUES ('committed WAL data')")
    db.commit()
    atomic = migration.atomic_json
    def fail_marker(path, value):
        if path.name == 'single_assistant_v4.json':
            raise OSError('Simulated crash before marker')
        atomic(path, value)
    monkeypatch.setattr(migration, 'atomic_json', fail_marker)
    with pytest.raises(OSError, match='Simulated crash'):
        AgentManager()
    first = json.loads(config.get_agents_path().read_text())
    monkeypatch.setattr(migration, 'atomic_json', atomic)
    assert AgentManager().all_agents() == first
    with sqlite3.connect(root / 'legacy/before-single-assistant-v4/extra.sqlite3') as backup:
        assert backup.execute('SELECT value FROM important').fetchone()[0] == 'committed WAL data'
    db.close()


async def test_stale_web_selection_and_forged_worker_request_route_main(isolated, monkeypatch):
    from questchain.gateway import server
    manager = AgentManager()
    worker = manager.get_by_class_name('Keeper')
    main = Model(['Main answer'])
    runtime = TaskRuntime(manager, default_model='fake', event_sink=lambda e: None,
        agent_factory=lambda d: Agent(main, ToolRegistry(), '', d['name']))
    ws = SimpleNamespace(send_json=AsyncMock())
    monkeypatch.setattr(server, '_runtime', runtime)
    monkeypatch.setattr(server, '_agent_manager', manager)
    monkeypatch.setattr(server, '_clients', {id(ws): {'conversation_id': 'web-forged', 'agent_id': worker['id']}})
    try:
        await server._handle_inbound(ws, {'type': 'switch_agent', 'agent_id': worker['id']})
        assert ws.send_json.call_args.args[0]['type'] == 'error'
        await server._handle_inbound(ws, {'type': 'chat', 'message': 'Hi', 'agent_id': worker['id']})
        result = await runtime.wait(ws.send_json.call_args.args[0]['run_id'])
        assert result['agent_id'] == manager.get_active_id()
    finally:
        await runtime.close()


def test_shared_profile_and_custom_main_name_with_stale_selection(isolated, monkeypatch):
    from questchain import agent as factory, config
    manager = AgentManager()
    main = manager.update(manager.get_active_id(), name='Nova', system_prompt='Custom behavior: {agent_name}', tools=[])
    config.get_active_agent_path().write_text(manager.get_by_class_name('Keeper')['id'])
    assert AgentManager().get_active() == main
    captured = {}
    monkeypatch.setattr(factory, 'create_questchain_agent', lambda **kwargs: captured.update(kwargs))
    factory.make_agent_from_def(main, default_model='inherited')
    assert captured['agent_name'] == 'Nova'
    assert captured['system_prompt_override'] == 'Custom behavior: {agent_name}'
    assert 'ABOUT.md' in {p.name for p in captured['injected_files']}
    assert captured['model_name'] == 'inherited'


async def test_import_does_not_resume_jobs_and_occurrence_is_deduplicated(isolated):
    from questchain import config
    from questchain.scheduler import CronScheduler
    config.ensure_data_dir()
    config.get_agents_path().write_text(json.dumps([dict(id='old-worker', name='Old worker', class_name='Custom', tools=[], system_prompt='Work')]))
    job = dict(id='stable-job', name='Old job', agent_id='old-worker', enabled=True,
               prompt='Review notes', cron_expression='0 9 * * *', timezone='UTC')
    config.get_cron_jobs_path().write_text(json.dumps([job]))
    manager = AgentManager()
    main = Model(['Main scheduled synthesis'])
    worker = Model(['PRIVATE scheduled work'])
    runtime = TaskRuntime(manager, default_model='fake', event_sink=lambda e: None,
        agent_factory=lambda d: Agent(main if d['kind'] == 'main' else worker, ToolRegistry(), '', d['name']))
    delivery = AsyncMock()
    scheduler = CronScheduler(None, delivery, agent_manager=manager, runtime=runtime)
    await scheduler.start()
    try:
        assert not scheduler.get_job('stable-job')['enabled']
        with pytest.raises(ValueError, match='Import'):
            scheduler.set_enabled('stable-job', True)
        manager.migrate_legacy('old-worker')
        assert not scheduler.get_job('stable-job')['enabled']
        assert scheduler._scheduler.get_job('cron:stable-job') is None
        scheduler.set_enabled('stable-job', True)
        assert scheduler.get_job('stable-job')['enabled']
        await scheduler._execute_job(scheduler.get_job('stable-job'), 'same-occurrence')
        await scheduler._execute_job(scheduler.get_job('stable-job'), 'same-occurrence')
        assert len(worker.calls) == 1
        assert len(main.calls) == 1
        assert delivery.await_count == 1
        saved = scheduler.get_job('stable-job')
        assert saved['last_result'] == 'Main scheduled synthesis'
        assert saved['last_agent_name'] == 'QuestChain'
        assert len(runtime.snapshot('cron-stable-job')['runs']) == 1
    finally:
        await scheduler.stop()
        await runtime.close()


async def test_main_plans_directly_and_can_delegate_multiple_bounded_tasks(isolated):
    manager = AgentManager()
    researcher = manager.get_by_class_name('Explorer')
    workspace = manager.get_by_class_name('Keeper')
    for d in (researcher, workspace):
        manager.update(d['id'], tools=[])
    main = Model(['My two-week launch plan', delegate(researcher, 'Research sources') + delegate(workspace, 'Inspect our notes'), 'Combined main answer'])
    models = {researcher['id']: Model(['Research findings']), workspace['id']: Model(['Notes findings'])}
    runtime = TaskRuntime(manager, default_model='fake', event_sink=lambda e: None,
        agent_factory=lambda d: Agent(main if d['kind'] == 'main' else models[d['id']], ToolRegistry(), '', d['name']))
    try:
        result = await runtime.wait(runtime.submit(TaskRequest('Plan a two-week launch without changing files.', manager.get_active_id(), 'cli-plan')))
        assert result['result'] == 'My two-week launch plan'
        assert len(runtime.store.runs()) == 1
        result = await runtime.wait(runtime.submit(TaskRequest('Research and inspect our notes', manager.get_active_id(), 'cli-plan')))
        assert result['result'] == 'Combined main answer'
        assert len([r for r in runtime.store.runs() if r.get('private')]) == 2
        assert all(len(m.calls) == 1 for m in models.values())
    finally:
        await runtime.close()
