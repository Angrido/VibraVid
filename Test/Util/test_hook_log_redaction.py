# 12.11.26

import logging

from VibraVid.utils import hooks, os_manager


def test_building_a_hook_command_does_not_log_the_process_environment(monkeypatch, caplog):
    monkeypatch.setenv("VIBRAVID_PASSWORD", "env-password-must-not-be-logged")
    monkeypatch.setattr(os_manager, "system", "linux")
    hook = {"type": "bash", "command": "true", "env": {"API_TOKEN": "hook-token-must-not-be-logged"}}

    with caplog.at_level(logging.DEBUG, logger=hooks.logger.name):
        command, kwargs = hooks._build_command_for_hook(hook, "post_download", {"title": "x"})

    assert kwargs["env"]["VIBRAVID_PASSWORD"] == "env-password-must-not-be-logged"
    assert kwargs["env"]["API_TOKEN"] == "hook-token-must-not-be-logged"
    assert "must-not-be-logged" not in caplog.text
    assert "true" in caplog.text
