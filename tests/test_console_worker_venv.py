"""Worker dispatch must preserve virtualenv imports; no strategy is executed."""
import json
import subprocess
import venv
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from lab import research_console
from lab.database import init_database
from tests.test_development_console_http import _serve_console


@pytest.mark.parametrize("stage", ["development", "holdout"])
def test_controller_dispatch_preserves_virtualenv_python(tmp_path, monkeypatch, stage):
    env = tmp_path / "worker-venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(env)
    python = env / "bin/python"
    site = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip()
    (Path(site) / "worker_only_dependency.py").write_text("VALUE = 98\n")
    database = tmp_path / "lab.sqlite"
    init_database(database)

    class DispatchVerified(Exception):
        pass

    def verify_worker(_db, _prepared, _capability, worker_python):
        # Exercise the interpreter actually supplied by each controller call site.
        result = subprocess.check_output(
            [str(worker_python), "-c",
             "import json,sys,worker_only_dependency as dep; "
             "print(json.dumps([sys.prefix,dep.VALUE]))"],
            env=research_console._minimal_environment(), text=True,
        )
        assert json.loads(result) == [str(env), 98]
        raise DispatchVerified

    with _serve_console(database, tmp_path) as server:
        controller = server.research_console_controller
        monkeypatch.setattr(research_console.sys, "executable", str(python))
        monkeypatch.setattr(research_console, stage + "_worker_argv", verify_worker)
        setattr(controller, "_" + stage + "_capability", SimpleNamespace(status="READY"))
        if stage == "development":
            monkeypatch.setattr(
                research_console, "prepare_development_run",
                lambda *args, **kwargs: SimpleNamespace(research_run_id=kwargs["research_run_id"]),
            )
            with pytest.raises(DispatchVerified):
                controller.create_research_run("candidate-test-only")
        else:
            run_id = str(uuid4())
            controller._campaign_directory(run_id, must_exist=False).mkdir()
            monkeypatch.setattr(
                research_console, "prepare_holdout_continuation",
                lambda *args, **kwargs: SimpleNamespace(research_run_id=run_id),
            )
            with pytest.raises(DispatchVerified):
                controller.authorize_holdout(run_id)


@pytest.mark.parametrize("kind", ["missing", "directory", "not-executable"])
def test_worker_python_rejects_invalid_target(tmp_path, monkeypatch, kind):
    target = tmp_path / "python"
    if kind == "directory":
        target.mkdir()
    elif kind == "not-executable":
        target.write_text("not executable\n")
        target.chmod(0o600)
    monkeypatch.setattr(research_console.sys, "executable", str(target))
    with pytest.raises(OSError):
        research_console._worker_python()
