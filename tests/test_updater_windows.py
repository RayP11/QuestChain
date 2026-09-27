"""Update real Windows launchers using tiny offline wheels and isolated uv tools."""

import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("uv"), reason="Windows and uv required")
@pytest.mark.parametrize("console_launcher", [True, False])
def test_self_update_releases_running_tool_before_reinstallation(tmp_path, console_launcher):
    repo = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    env = dict(os.environ, UV_TOOL_DIR=str(tmp_path / "tools"), UV_TOOL_BIN_DIR=str(tmp_path / "bin"),
               UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", PYTHONIOENCODING="utf-8")
    env["PATH"] = str(Path(uv).parent) + os.pathsep + env["PATH"]
    destination = tmp_path / "questchain-0.0.2-py3-none-any.whl"

    def wheel(version, entry):
        info = f"questchain-{version}.dist-info"
        files = {
            "questchain/__init__.py": "",
            "questchain/__main__.py": entry,
            "questchain/config.py": "MODEL_PRESETS = {}\nOLLAMA_MODEL = 'test'\n",
            "questchain/updater.py": (repo / "questchain" / "updater.py").read_text(encoding="utf-8"),
            info + "/METADATA": f"Metadata-Version: 2.1\nName: questchain\nVersion: {version}\n",
            info + "/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            info + "/entry_points.txt": "[console_scripts]\nquestchain = questchain.__main__:main\n",
        }
        record = io.StringIO()
        writer = csv.writer(record)
        for path, content in files.items():
            writer.writerow([path, "", len(content.encode())])
        writer.writerow([info + "/RECORD", "", ""])
        files[info + "/RECORD"] = record.getvalue()
        path = tmp_path / f"questchain-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as output:
            for name, content in files.items():
                output.writestr(name, content.encode())
        return path

    wheel("0.0.2", "def main():\n    print('UPDATED_LAUNCHER_OK')\n")
    entry = (repo / "questchain" / "__main__.py").read_text(encoding="utf-8")
    entry = entry.replace('"git+https://github.com/RayP11/QuestChain@master"', repr(str(destination)))
    initial = wheel("0.0.1", entry)

    def run(command):
        result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    run([uv, "tool", "install", str(initial), "--python", sys.executable])
    launcher = tmp_path / "bin" / "questchain.exe"
    if console_launcher:
        update = [str(launcher), "--update"]
    else:
        update = [str(tmp_path / "tools" / "questchain" / "Scripts" / "python.exe"), "-m", "questchain", "--update"]
    # The helper inherits the pipes; communicate waits for it as well as the
    # exiting caller. Check its completion message, not just the caller's exit.
    assert "QuestChain updated." in run(update)
    assert "UPDATED_LAUNCHER_OK" in run([str(launcher)])
