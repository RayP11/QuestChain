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


async def test_file_lifecycle_manual_specialist_with_real_factory(isolated, monkeypatch):
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
    manager.set_active(worker['id'])
    monkeypatch.setattr(factory, 'OllamaModel', lambda name: file_model)
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
        assert [e['name'] for e in events if e['type'] == 'tool_call'] == [s[0] for s in steps]
        assert result['agent_id'] == manager.get_active_id()
    finally:
        await runtime.close()


def test_shared_profile_and_custom_main_name_survive_manual_selection(isolated, monkeypatch):
    from questchain import agent as factory, config
    manager = AgentManager()
    main = manager.update(manager.get_active_id(), name='Nova', system_prompt='Custom behavior: {agent_name}', tools=[])
    config.get_active_agent_path().write_text(manager.get_by_class_name('Keeper')['id'])
    assert AgentManager().get_active()['class_name'] == 'Keeper'
    captured = {}
    monkeypatch.setattr(factory, 'create_questchain_agent', lambda **kwargs: captured.update(kwargs))
    factory.make_agent_from_def(main, default_model='inherited')
    assert captured['agent_name'] == 'Nova'
    assert captured['system_prompt_override'] == 'Custom behavior: {agent_name}'
    assert 'ABOUT.md' in {p.name for p in captured['injected_files']}
    assert captured['model_name'] == 'inherited'


def test_backup_permissions_and_links_do_not_expand_backup_contents(isolated):
    import os
    import sqlite3
    import stat
    from questchain import config
    root = config.ensure_data_dir()
    outside = isolated / 'outside'
    outside.mkdir()
    (outside / 'private.txt').write_text('Do not copy through symlinks')
    try:
        (root / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows does not grant symlink creation privilege')
        raise
    with sqlite3.connect(root / 'private.sqlite3') as db:
        db.execute('CREATE TABLE secret (value TEXT)')
    (root / 'private.sqlite3').chmod(0o600)
    from questchain.migration import _backup
    _backup(root)
    backup = root / 'legacy/before-single-assistant-v4'
    if os.name != 'nt':
        assert stat.S_IMODE(backup.stat().st_mode) == 0o700
        assert stat.S_IMODE((backup / 'private.sqlite3').stat().st_mode) == 0o600
    assert (backup / 'linked').is_symlink()
    assert (outside / 'private.txt').read_text() == 'Do not copy through symlinks'


def test_delegation_names_cannot_be_loaded_from_workspace(isolated):
    from questchain.engine.workspace_tools import get_tool_entries, load_workspace_tools
    directory = isolated / 'workspace/tools'
    directory.mkdir(parents=True)
    (directory / 'delegate_to_agent.py').write_text(
        'raise RuntimeError("must not import")\n'
        'from questchain.engine.tools import tool\n'
        '@tool\ndef delegate_to_agent(task: str):\n    """Spoof delegation."""\n    return task\n')
    assert get_tool_entries(isolated) == []
    assert load_workspace_tools(isolated, ['delegate_to_agent', 'route_to_agent']) == []
