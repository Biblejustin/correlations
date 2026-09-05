"""Operational regressions: environment drift and child failures must stop execution."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import verify_environment as env

BASE = Path(__file__).resolve().parents[1]


def test_requirements_include_relative_pins_and_reject_conflicts(tmp_path):
    (tmp_path / "base.txt").write_text("NumPy==2.5.0\n")
    dev = tmp_path / "dev.txt"
    dev.write_text("-r base.txt\npytest==9.1.1 # comment\n")
    assert env.read_pins(dev) == {"numpy": "2.5.0", "pytest": "9.1.1"}
    dev.write_text("-r base.txt\nnumpy==1.0\n")
    with pytest.raises(ValueError, match="Conflicting pins"):
        env.read_pins(dev)
    dev.write_text("-r dev.txt\n")
    with pytest.raises(ValueError, match="Recursive"):
        env.read_pins(dev)


def test_distribution_pin_cannot_hide_stale_imported_module(monkeypatch):
    monkeypatch.setattr(env.metadata, "version", lambda name: "1.9.0")
    monkeypatch.setattr(env.importlib, "import_module", lambda name: SimpleNamespace(__version__="1.8.0"))
    report = env.inspect_environment({"pywavelets": "1.9.0"}, python_version=(3, 13, 15), check_dependencies=False)
    assert not report["passed"]
    assert "disagrees" in report["problems"][0]
    assert report["packages"]["pywavelets"]["distribution"] == "1.9.0"
    assert report["packages"]["pywavelets"]["module"] == "1.8.0"


def test_missing_package_wrong_python_and_broken_dependencies_fail(monkeypatch):
    def missing(name):
        raise env.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(env.metadata, "version", missing)
    monkeypatch.setattr(env.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="dependency conflict", stderr=""))
    report = env.inspect_environment({"numpy": "2.5.0"}, python_version=(3, 12, 10))
    assert not report["passed"]
    assert len(report["problems"]) == 3
    assert report["dependency_check"]["returncode"] == 1


def test_verifier_exits_nonzero_and_preserves_failure_evidence(tmp_path, monkeypatch):
    pins = tmp_path / "pins.txt"
    pins.write_text("numpy==2.5.0\n")
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(env.metadata, "version", lambda name: "2.4.0")
    monkeypatch.setattr(env.importlib, "import_module", lambda name: SimpleNamespace(__version__="2.4.0"))
    monkeypatch.setattr(env.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="No broken requirements found.", stderr=""))
    assert env.main(["--requirements", str(pins), "--json", str(output)]) == 1
    report = json.loads(output.read_text())
    assert not report["passed"]
    assert report["packages"]["numpy"]["distribution"] == "2.4.0"


def make_fixture(tmp_path, *, verification_code=0, runner_code=23):
    """Run the real Make recipes with isolated Python programs; no source/network I/O."""
    shutil.copyfile(BASE / "Makefile", tmp_path / "Makefile")
    for name in ["verify_environment.py", "weekly_update.py", "run_suite.py"]:
        code = verification_code if name == "verify_environment.py" else runner_code
        (tmp_path / name).write_text(
            "import json, sys\n"
            "with open('calls.jsonl', 'a') as stream: stream.write(json.dumps(sys.argv) + '\\n')\n"
            f"print('fixture diagnostic: {name}', file=sys.stderr)\n"
            f"raise SystemExit({code})\n"
        )


@pytest.mark.parametrize("target,script,flags", [
    ("all", "weekly_update.py", ["--dry-run", "--workers", "2"]),
    ("refresh", "weekly_update.py", ["--dry-run", "--workers", "2"]),
    ("local", "weekly_update.py", ["--skip-fetch", "--dry-run", "--workers", "2"]),
    ("plots", "weekly_update.py", ["--skip-fetch", "--dry-run", "--workers", "2"]),
    ("catalogs", "weekly_update.py", ["--fetch-only", "--dry-run"]),
    ("correlations", "run_suite.py", ["--workers", "2"]),
    ("publish", "weekly_update.py", ["--publish", "--workers", "2"]),
])
def test_make_delegates_and_propagates_runner_failure(tmp_path, target, script, flags):
    make_fixture(tmp_path)
    result = subprocess.run(["make", f"PY={sys.executable}", target], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert f"fixture diagnostic: {script}" in result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert calls == [["verify_environment.py", "--requirements", "requirements-dev.txt"], [script, *flags]]


def test_make_stops_before_refresh_when_environment_invalid(tmp_path):
    make_fixture(tmp_path, verification_code=1, runner_code=0)
    result = subprocess.run(["make", f"PY={sys.executable}", "refresh"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 1
    assert calls[0][0] == "verify_environment.py"


def test_catalog_retry_preserves_shared_source_selector(tmp_path):
    make_fixture(tmp_path, runner_code=0)
    result = subprocess.run(["make", f"PY={sys.executable}", "SOURCES=ngdc monitoring", "catalogs"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert calls[-1] == ["weekly_update.py", "--fetch-only", "--dry-run", "--sources", "ngdc", "monitoring"]
