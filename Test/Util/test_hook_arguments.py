# 21.11.26

import os
import subprocess
import sys

import pytest

from VibraVid.utils import hooks, os_manager


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe parsing is a Windows thing")
def test_bat_hook_gets_each_value_as_one_literal_argument(tmp_path):
    """A list run through `cmd /c` is quoted for whitespace only: `&` in a title ran a second command, and a script under a path with spaces did not start."""
    folder = tmp_path / "my hooks"
    folder.mkdir()
    script = folder / "post.bat"
    script.write_text('@echo off\r\n>"%~dp0out.txt" echo %1 %2 %3\r\n', encoding="ascii")
    hook = {"type": "bat", "path": str(script), "args": ["{download_title}", "{download_error}", "plain"]}

    command, kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": "Tom&Jerry 100%"})
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, **kwargs)

    assert result.returncode == 0, result.stderr
    assert (folder / "out.txt").read_text().strip() == '"Tom&Jerry 100%" "" "plain"'


def test_python_hook_keeps_empty_values_in_their_position(monkeypatch):
    """Dropping an empty value shifted the next one: on success the download path arrived in the error slot."""
    monkeypatch.setattr(os_manager, "system", "linux")
    hook = {"type": "python", "path": "/hooks/post.py", "args": ["{download_title}", "{download_error}", "{download_path}"]}

    command, _kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": "Film", "path": "/video/Film.mkv"})

    assert command[2:] == ["Film", "", os.path.abspath("/video/Film.mkv")]


def test_inline_bash_template_values_lose_shell_metacharacters(monkeypatch):
    """A title substituted into an inline command was shell code: `x'; touch /tmp/pwned; echo '` ran `touch`."""
    monkeypatch.setattr(os_manager, "system", "linux")
    hook = {"type": "bash", "command": "echo 'Download finished: {download_title}'", "allow_inline_template": True}
    title = "x'; touch /tmp/pwned; echo `id` $(id) \"a\" \\ & | < > \n end"

    command, kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": title})

    assert command == ["/bin/bash", "-lc", "echo 'Download finished: x touch /tmp/pwned echo id id a       end'"]
    assert kwargs["env"]["SC_DOWNLOAD_TITLE"] == title


def test_inline_bash_template_keeps_an_apostrophe_title_inside_the_quotes(monkeypatch):
    monkeypatch.setattr(os_manager, "system", "linux")
    hook = {"type": "shell", "command": "echo 'Download finished: {download_title}'", "allow_inline_template": True}

    command, _kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": "L'amica geniale"})

    assert command[2] == "echo 'Download finished: Lamica geniale'"


def test_inline_cmd_template_values_lose_cmd_metacharacters(monkeypatch):
    monkeypatch.setattr(os_manager, "system", "windows")
    hook = {"type": "cmd", "command": 'echo "{download_title}"', "allow_inline_template": True}
    title = 'Tom&Jerry" | del x ^ 100% <a> !v!\r\nend'

    command, kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": title})

    assert command == ["cmd", "/c", 'echo "TomJerry  del x  100 a vend"']
    assert kwargs["env"]["SC_DOWNLOAD_TITLE"] == title


def test_inline_command_without_template_is_left_alone(monkeypatch):
    monkeypatch.setattr(os_manager, "system", "linux")
    hook = {"type": "bash", "command": "echo '{download_title}' $SC_DOWNLOAD_TITLE"}

    command, _kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": "a;b"})

    assert command[2] == "echo '{download_title}' $SC_DOWNLOAD_TITLE"
