"""Restart-safe archive-and-import migration; never replay external work."""
from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path

VERSION = 4


def atomic_json(path: Path, value) -> None:
    """Atomically replace state without widening existing filesystem permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.name + '.', suffix='.tmp', delete=False) as output:
        temp = Path(output.name)
        temp.chmod(mode)
        try:
            json.dump(value, output, indent=2)
        except BaseException:
            output.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _backup(root: Path) -> None:
    """Keep all prior archives and state; SQLite backup includes committed WAL pages."""
    if (root / 'legacy').is_symlink():
        raise ValueError('Migration archive directory must not be a symbolic link.')
    destination = root / 'legacy' / 'before-single-assistant-v4'
    if destination.is_symlink():
        raise ValueError('Migration backup directory must not be a symbolic link.')
    if (destination / 'complete').exists():
        return
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    for source in root.iterdir():
        if source.name == 'legacy':
            for item in source.iterdir():
                if item != destination:
                    target = destination / 'legacy' / item.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if item.is_symlink():
                        if target.is_symlink():
                            target.unlink()
                        shutil.copy2(item, target, follow_symlinks=False)
                    elif item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True, symlinks=True)
                    else:
                        shutil.copy2(item, target)
            continue
        if source.name.endswith(('-wal', '-shm', '.lock')):
            continue
        target = destination / source.name
        if target.is_symlink():
            target.unlink()
        if source.is_symlink():
            shutil.copy2(source, target, follow_symlinks=False)
        elif source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        elif source.suffix in {'.sqlite3', '.sqlite', '.db'}:
            with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
            target.chmod(stat.S_IMODE(source.stat().st_mode))
        else:
            shutil.copy2(source, target)
    (destination / 'complete').write_text('4', encoding='utf-8')


def migrate_roster(main: dict, presets: list[dict], guidance: dict) -> list[dict]:
    from questchain.config import get_agents_path, get_cron_jobs_path
    path = get_agents_path()
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'single_assistant_v4.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not isinstance(data, list):
        raise ValueError('Invalid agents.json; saved definitions were left unchanged.')
    if marker.exists():
        return data
    # Acquire the same data-directory lock as the runtime before changing state.
    from questchain.runtime.store import RunStore
    store = RunStore(root / 'tasks.sqlite3')
    try:
        _backup(root)
        modern = [a for a in data if a.get('kind') in {'main', 'subagent'}]
        retiring = [a for a in modern if a.get('kind') == 'subagent'
                    and a.get('built_in') and a.get('class_name') == 'Planner']
        legacy = [a for a in data if a not in modern] + retiring
        from questchain.config import get_active_agent_path
        if (not modern and (path.exists() or get_active_agent_path().exists())
                and not (root / 'agents_bootstrap_v3').exists()
                and not any(a['id'] == 'default' for a in data)):
            legacy.append(dict(id='default', name='QuestChain', built_in=True, model=None,
                               system_prompt=None, tools='all', class_name='Custom', revision=1))
        archive = root / 'legacy' / 'agents.json'
        prior = json.loads(archive.read_text(encoding='utf-8')) if archive.exists() else []
        by_id = {a['id']: a for a in prior}
        # Latest active definition wins; every prior archive copy remains in backup.
        by_id.update({a['id']: a for a in legacy})
        atomic_json(archive, list(by_id.values()))
        roster = [a for a in modern if a not in retiring]
        if not any(a.get('kind') == 'main' for a in roster):
            if any(a['id'] == main['id'] for a in data + prior):
                main['id'] = 'main-' + secrets.token_hex(6)
            roster.insert(0, main)
        from questchain.agents import MAIN_SYSTEM_PROMPT, PREVIOUS_MAIN_SYSTEM_PROMPT
        for definition in roster:
            if (definition.get('kind') == 'main'
                    and (definition.get('system_prompt') or '').strip() == PREVIOUS_MAIN_SYSTEM_PROMPT.strip()):
                definition.update(system_prompt=MAIN_SYSTEM_PROMPT, revision=definition.get('revision', 1) + 1)
        if not modern:
            for preset in presets:
                roster.append({**preset, 'id': secrets.token_hex(6), 'kind': 'subagent',
                               'built_in': True, 'definition_version': 3, 'revision': 1,
                               'when_to_call': guidance[preset['class_name']], 'when_not_to_call': '',
                               'routing_examples': [], 'routable': True})
        # Pause legacy schedules durably before changing identities. Import cannot resume them.
        jobs_path = get_cron_jobs_path()
        if jobs_path.exists():
            jobs = json.loads(jobs_path.read_text(encoding='utf-8'))
            if not isinstance(jobs, list):
                raise ValueError('Invalid cron jobs; migration stopped before changing the roster.')
            legacy_ids = {a['id'] for a in legacy}
            active_ids = {a['id'] for a in roster}
            for job in jobs:
                owner = job.get('agent_id') or 'default'
                if owner in legacy_ids or owner not in active_ids:
                    job.update(enabled=False, migration_pause='Review the assigned agent and explicitly resume this legacy job.')
            atomic_json(jobs_path, jobs)
        for run in store.runs():
            if run['status'] not in {'completed', 'partial', 'failed', 'cancelled', 'interrupted', 'waiting_input'}:
                run.update(status='interrupted', error='Migration interrupted this run. Review external effects before explicitly retrying.')
                store.put(run)
        atomic_json(path, roster)
        atomic_json(marker, {'version': VERSION})
        return roster
    finally:
        store.close()


def migrate_manual_roster(main: dict, presets: list[dict]) -> list[dict]:
    """Preserve identities, tools, history and schedules while disabling routing.

    Unlike v4 this does not archive/replace the user's roster or replay any jobs.
    Existing v4 archives remain available for explicit import.
    """
    from questchain.config import get_agents_path, get_active_agent_path
    path = get_agents_path()
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'manual_agents_v5.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not isinstance(data, list) or any(not isinstance(a, dict) or not a.get('id') for a in data):
        raise ValueError('Invalid agents.json; saved definitions were left unchanged.')
    if marker.exists():
        return data
    from questchain.runtime.store import RunStore
    store = RunStore(root / 'tasks.sqlite3')
    try:
        # Another startup may have completed migration while we waited for the lock.
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if not isinstance(data, list) or any(not isinstance(a, dict) or not a.get('id') for a in data):
            raise ValueError('Invalid agents.json; saved definitions were left unchanged.')
        if marker.exists():
            return data
        # Archive only the roster: no other state is modified by this migration.
        destination = root / 'legacy' / 'before-manual-agents-v5.json'
        if destination.is_symlink() or destination.parent.is_symlink():
            raise ValueError('Migration archive must not be a symbolic link.')
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_suffix('.tmp')
            if temp.is_symlink():
                raise ValueError('Migration archive temp must not be a symbolic link.')
            # Restrict permissions before placing any potentially private prompts here.
            temp.touch(mode=0o600, exist_ok=True)
            temp.chmod(0o600)
            temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            temp.replace(destination)
        if not data:
            active_path = get_active_agent_path()
            if path.exists() or (active_path.exists() and active_path.read_text(encoding='utf-8').strip() == 'default'):
                main = {**main, 'id': 'default'}
            data = [main] + [{**p, 'id': secrets.token_hex(6), 'kind': 'specialist',
                             'built_in': True, 'revision': 1} for p in presets]
        primary = next((a for a in data if a.get('kind') == 'main'), None)
        if primary is None:
            primary = next((a for a in data if a['id'] == 'default'), None)
        if primary is None:
            primary = {**main, 'id': 'default'}
            data.insert(0, primary)
        for agent in data:
            agent['kind'] = 'main' if agent is primary else 'specialist'
            agent['routable'] = False
            agent['definition_version'] = 5
            agent.setdefault('revision', 1)
            # Retain custom prompts verbatim; capabilities enforce no delegation.
        atomic_json(path, data)
        atomic_json(marker, {'version': 5})
        return data
    finally:
        store.close()
