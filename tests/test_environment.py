"""Tool detection helpers (no real ffmpeg/Deno needed)."""

import os
import subprocess

from clipper_app import environment
from clipper_app.environment import (
    deno_version,
    find_tool,
    list_separator,
    prepend_to_path,
    winget_command_for_button,
)


def test_prepend_to_path_adds_folder_once(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(["/workspace/volumes/v_8aac/a", "/workspace/volumes/v_8aac/b"]),
    )
    prepend_to_path(str(tmp_path))
    prepend_to_path(str(tmp_path))
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path)
    assert parts.count(str(tmp_path)) == 1
    prepend_to_path(None)
    assert os.environ["PATH"].split(os.pathsep) == parts


def test_find_tool_uses_path(monkeypatch, tmp_path):
    name = "clipper-fake-tool"
    exe = tmp_path / (f"{name}.exe" if os.name == "nt" else name)
    exe.write_bytes(b"")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    found = find_tool(name)
    # On Windows the extension comes back in PATHEXT case (".EXE").
    assert found is not None
    assert os.path.normcase(found) == os.path.normcase(str(exe))


def test_find_tool_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(environment, "_extra_search_dirs", lambda: [str(tmp_path)])
    assert find_tool("clipper-tool-that-does-not-exist") is None


def test_deno_version_is_parsed(monkeypatch):
    def fake_run(*args, **kwargs):
        stdout = "deno 2.5.4 (stable, release, x86_64-pc-windows-msvc)\nv8 14.0\n"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    assert deno_version("deno.exe") == "2.5.4"


def test_deno_version_when_deno_is_broken(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("not a valid Win32 application")

    monkeypatch.setattr(environment.subprocess, "run", broken)
    assert deno_version("deno.exe") is None


def test_list_separator():
    assert list_separator() in (",", ";")


def test_winget_button_accepts_agreements():
    command = winget_command_for_button("winget install Gyan.FFmpeg")
    assert command.startswith("winget install Gyan.FFmpeg")
    assert "--accept-package-agreements" in command
