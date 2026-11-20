import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def deployment(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(root / "scripts" / "deploy.sh", scripts / "deploy.sh")
    for name in ("data", "reports", "backups", "bin"):
        (tmp_path / name).mkdir()
    trace = tmp_path / "commands.jsonl"
    fake_docker = tmp_path / "bin" / "docker"
    fake_docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['DEPLOY_TRACE'], 'a') as log:\n"
        "    log.write(json.dumps(args) + '\\n')\n"
        "if args[0] == 'compose' and 'ps' in args:\n"
        "    print('test-container')\n"
        "elif args[0] == 'inspect':\n"
        "    if '.Config.Image' in args[2]:\n"
        "        print('example/old@sha256:' + '1' * 64)\n"
        "    elif 'RestartCount' in args[2]:\n"
        "        print('true:0')\n"
        "    else:\n"
        "        print('true')\n"
        "elif 'scripts.backup_db' in args and os.environ.get('FAIL_BACKUP'):\n"
        "    sys.exit(1)\n"
    )
    fake_docker.chmod(0o755)
    fake_sleep = tmp_path / "bin" / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n")
    fake_sleep.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", DEPLOY_TRACE=str(trace))
    return tmp_path, env, trace


def run_deploy(root, env, image=None):
    return subprocess.run(
        ["bash", str(root / "scripts" / "deploy.sh"), image or "example/bot@sha256:" + "2" * 64],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_deployment_backs_up_before_replacing_bot(deployment):
    root, env, trace = deployment
    result = run_deploy(root, env)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in trace.read_text().splitlines()]
    pull = next(i for i, command in enumerate(commands) if "pull" in command)
    stop = next(i for i, command in enumerate(commands) if "stop" in command)
    backup = next(i for i, command in enumerate(commands) if "scripts.backup_db" in command)
    start = next(i for i, command in enumerate(commands) if "up" in command)
    assert pull < stop < backup < start
    assert "2" * 64 in (root / ".env.release").read_text()
    assert "1" * 64 in (root / ".previous-image").read_text()


def test_backup_failure_does_not_replace_bot(deployment):
    root, env, trace = deployment
    env["FAIL_BACKUP"] = "1"
    result = run_deploy(root, env)
    assert result.returncode != 0
    commands = [json.loads(line) for line in trace.read_text().splitlines()]
    assert not any("up" in command for command in commands)
    assert any("start" in command for command in commands)
    assert (root / ".env.release").read_text() == ""


def test_deployment_rejects_mutable_image_tag(deployment):
    root, env, trace = deployment
    result = run_deploy(root, env, image="example/bot:latest")
    assert result.returncode == 2
    assert not trace.exists()
