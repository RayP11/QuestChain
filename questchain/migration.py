"""Restart-safe archive-and-import migration; never replay external work."""
from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
from pathlib import Path

VERSION = 4


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)


def _backup(root: Path) -> None:
    """Keep all prior archives and state; SQLite backup includes committed WAL pages."""
    destination = root / 'legacy' / 'before-single-assistant-v4'
    if (destination / 'complete').exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for source in root.iterdir():
        if source.name == 'legacy':
            for item in source.iterdir():
                if item != destination:
                    target = destination / 'legacy' / item.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if item.is_dir():
                        shutil.copytree(item, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, target)
            continue
        if source.name.endswith(('-wal', '-shm', '.lock')):
            continue
        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.suffix in {'.sqlite3', '.sqlite', '.db'}:
            with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
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
