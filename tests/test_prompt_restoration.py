"""Historical defaults and runtime compatibility without changing user data."""
import pytest
from questchain.prompts import *

@pytest.mark.parametrize('role,key', [('Keeper','KEEPER_SYSTEM_PROMPT'),('Explorer','EXPLORER_SYSTEM_PROMPT'),('Builder','BUILDER_SYSTEM_PROMPT'),('Planner','PLANNER_SYSTEM_PROMPT'),('Scheduler','SENTINEL_SYSTEM_PROMPT'),('Custom','MAIN_SYSTEM_PROMPT'),('Router','ROUTER_SYSTEM_PROMPT')])
def test_all_known_stock_versions_restore(role,key):
    for old in LEGACY_STOCK_PROMPTS[key]:
        actual=resolve_prompt(old,role,['cron_list','cron_add','cron_remove'])
        assert 'delegate_to_agent' not in actual
        assert 'Route requests' not in actual
        assert 'write_todos' not in actual
        if role=='Scheduler':
            assert 'cron_list, cron_add, and cron_remove' in actual
            assert 'never assume UTC' in actual
            assert 'quests' not in actual

@pytest.mark.parametrize('custom', ['', ' ', '\r\n', '{"instruction": "keep exactly"}', 'My own prompt', SENTINEL_SYSTEM_PROMPT+' ', SENTINEL_SYSTEM_PROMPT.replace('\n','\r\n')])
def test_custom_text_is_not_replaced(custom):
    assert resolve_prompt(custom,'Scheduler',[]) == custom


def test_historical_tool_hints_only_when_enabled():
    assert 'write_todos' in resolve_prompt(KEEPER_SYSTEM_PROMPT,'Keeper',['write_todos'])
    assert 'claude_code' in resolve_prompt(BUILDER_SYSTEM_PROMPT,'Builder',['claude_code'])
    assert 'claude_code' not in resolve_prompt(BUILDER_SYSTEM_PROMPT,'Builder',[])
    assert resolve_prompt(None,'Scheduler',[]) != resolve_prompt(SENTINEL_SYSTEM_PROMPT,'Scheduler',[])


def test_factory_preserves_custom_braces_and_manual_boundary(monkeypatch,tmp_path):
    from questchain import agent as factory
    monkeypatch.setattr(factory,'ensure_memory_dir',lambda:None)
    agent=factory.create_questchain_agent(system_prompt_override='JSON {"a": 1} {agent_name}',agent_name='Ray',tools_filter=[])
    assert agent._base_system_prompt.startswith('JSON {"a": 1} Ray')
    assert 'other QuestChain agents' in agent._base_system_prompt
    assert agent.tools.names()==[]


def test_clock_includes_offset():
    from questchain.engine.agent import Agent
    from questchain.engine.tools import ToolRegistry
    agent=Agent(model=None,tools=ToolRegistry(),system_prompt='Test')
    assert '(UTC' in agent._build_system_prompt()


def test_disabled_scheduling_tools_do_not_get_action_instructions():
    prompt=resolve_prompt(SENTINEL_SYSTEM_PROMPT,'Scheduler',[])
    assert 'Scheduling tools are unavailable' in prompt
    assert 'call cron_add' not in prompt
