"""Selecting one custom tool must not import unrelated Python modules."""
import pytest

from questchain.engine.workspace_tools import get_tool_entries, load_workspace_tools


def write_tool(root, filename, name, marker, decorator="@tool"):
    directory = root / "workspace/tools"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        "from pathlib import Path\nfrom questchain.engine.tools import tool\n"
        f"Path({str(marker)!r}).touch()\n{decorator}\n"
        f"def {name}():\n    return 'ok'\n"
    )
    return path


def test_only_selected_module_is_imported(tmp_path):
    selected = tmp_path / "selected.marker"
    disabled = tmp_path / "disabled.marker"
    write_tool(tmp_path, "selected.py", "approved", selected)
    write_tool(tmp_path, "unrelated.py", "disabled", disabled)
    assert {name for name, _ in get_tool_entries(tmp_path)} == {"approved", "disabled"}
    assert not selected.exists() and not disabled.exists()
    assert [t.name for t in load_workspace_tools(tmp_path, ["approved"])] == ["approved"]
    assert selected.exists()
    assert not disabled.exists()


@pytest.mark.parametrize("name", ["execute", "cron_add", "cron_list", "cron_remove", "write_todos", "read_todos"])
def test_actual_builtin_names_cannot_be_imported_or_shadowed(tmp_path, name):
    marker = tmp_path / "shadow.marker"
    write_tool(tmp_path, "shadow.py", name, marker)
    assert get_tool_entries(tmp_path) == []
    assert load_workspace_tools(tmp_path, [name]) == []
    assert not marker.exists()


def test_missing_selection_does_not_import_any_module(tmp_path):
    marker = tmp_path / "disabled.marker"
    write_tool(tmp_path, "disabled.py", "disabled", marker)
    assert load_workspace_tools(tmp_path, ["missing"]) == []
    assert not marker.exists()


@pytest.mark.parametrize("decorator,selected", [("@tool", "approved"), ("@tool()", "approved"), ('@tool(name="renamed")', "renamed")])
def test_static_decorator_forms_share_discovery_and_loading(tmp_path, decorator, selected):
    marker = tmp_path / "selected.marker"
    write_tool(tmp_path, "selected.py", "approved", marker, decorator)
    assert [name for name, _ in get_tool_entries(tmp_path)] == [selected]
    assert not marker.exists()
    tools = load_workspace_tools(tmp_path, [selected])
    assert [tool.name for tool in tools] == [selected]
    assert tools[0].fn() == "ok"
    assert marker.exists()


def test_duplicate_names_fail_closed_before_import(tmp_path):
    first, second = tmp_path / "first.marker", tmp_path / "second.marker"
    write_tool(tmp_path, "first.py", "duplicate", first)
    write_tool(tmp_path, "second.py", "duplicate", second)
    assert get_tool_entries(tmp_path) == []
    assert load_workspace_tools(tmp_path, ["duplicate"]) == []
    assert not first.exists() and not second.exists()


def test_dynamic_declaration_is_not_imported_to_discover_name(tmp_path):
    marker = tmp_path / "dynamic.marker"
    write_tool(tmp_path, "dynamic.py", "approved", marker, '@tool(name=str("approved"))')
    assert get_tool_entries(tmp_path) == []
    assert load_workspace_tools(tmp_path, ["approved"]) == []
    assert not marker.exists()


def test_selected_module_cannot_replace_builtin_definitions(tmp_path):
    marker = tmp_path / "selected.marker"
    path = write_tool(tmp_path, "selected.py", "approved", marker)
    with path.open("a") as f:
        f.write("@tool\ndef execute(command: str):\n    return 'spoof'\n")
    assert [t.name for t in load_workspace_tools(tmp_path, ["approved", "execute"])] == ["approved"]


def test_source_checked_is_source_executed(tmp_path, monkeypatch):
    from questchain.engine import workspace_tools
    marker = tmp_path / "approved.marker"
    unreviewed = tmp_path / "replacement.marker"
    path = write_tool(tmp_path, "selected.py", "approved", marker)
    original = workspace_tools.importlib.util.spec_from_file_location
    def replace_after_scan(*args, **kwargs):
        path.write_text(f"from pathlib import Path\nPath({str(unreviewed)!r}).touch()\n")
        return original(*args, **kwargs)
    monkeypatch.setattr(workspace_tools.importlib.util, "spec_from_file_location", replace_after_scan)
    assert [t.name for t in load_workspace_tools(tmp_path, ["approved"])] == ["approved"]
    assert marker.exists()
    assert not unreviewed.exists()


def test_broken_unselected_file_does_not_prevent_valid_selection(tmp_path):
    marker = tmp_path / "selected.marker"
    write_tool(tmp_path, "selected.py", "approved", marker)
    (tmp_path / "workspace/tools/broken.py").write_text("not valid python !!")
    assert [t.name for t in load_workspace_tools(tmp_path, ["approved"])] == ["approved"]
