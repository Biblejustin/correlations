"""Check Python, exact package pins, imported versions and dependency consistency."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

BASE = Path(__file__).resolve().parent
MODULE_NAMES = {"pywavelets": "pywt", "python-dateutil": "dateutil", "pillow": "PIL"}


def read_pins(path, seen=None):
    """Read this project's exact pins, including relative -r files; refuse ambiguity."""
    path = Path(path).resolve()
    seen = set() if seen is None else seen
    if path in seen:
        raise ValueError(f"Recursive requirements include: {path}")
    seen.add(path)
    pins = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            nested = read_pins(path.parent / line[3:].strip(), seen.copy())
        else:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
            if not match:
                raise ValueError(f"Expected an exact package pin in {path}: {line}")
            nested = {match[1]: match[2]}
        for name, version in nested.items():
            normalized = re.sub(r"[-_.]+", "-", name).lower()
            if normalized in pins and pins[normalized] != version:
                raise ValueError(f"Conflicting pins for {name}")
            pins[normalized] = version
    return pins


def inspect_environment(pins, *, python_version=None, check_dependencies=True):
    """Return evidence even on failure, including stale distribution/module metadata."""
    python_version = tuple(sys.version_info[:3] if python_version is None else python_version)
    problems = []
    if python_version[:2] != (3, 13):
        problems.append(f"Python 3.13 required; found {'.'.join(map(str, python_version))}")
    packages = {}
    for name, expected in sorted(pins.items()):
        record = {"expected": expected, "distribution": None, "module": None}
        packages[name] = record
        try:
            record["distribution"] = metadata.version(name)
            if record["distribution"] != expected:
                problems.append(f"{name}: expected {expected}, distribution {record['distribution']}")
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: distribution missing (expected {expected})")
            continue
        module_name = MODULE_NAMES.get(name, name.replace("-", "_"))
        try:
            module = importlib.import_module(module_name)
            record["module"] = str(module.__version__) if hasattr(module, "__version__") else None
            if record["module"] is not None and record["module"] != record["distribution"]:
                problems.append(f"{name}: imported module {record['module']} disagrees with distribution {record['distribution']}")
        except Exception as exc:
            problems.append(f"{name}: import failed: {type(exc).__name__}: {exc}")
    dependency_check = None
    if check_dependencies:
        result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False)
        dependency_check = {"returncode": result.returncode, "output": (result.stdout + result.stderr).strip()}
        if result.returncode:
            problems.append("pip check failed: " + dependency_check["output"])
    return {
        "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": not problems,
        "python": {"version": ".".join(map(str, python_version)), "executable": sys.executable,
                   "implementation": platform.python_implementation()},
        "platform": platform.platform(),
        "packages": packages,
        "dependency_check": dependency_check,
        "problems": problems,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=BASE / "requirements.txt")
    parser.add_argument("--json", type=Path, help="Write environment evidence, including failures")
    args = parser.parse_args(argv)
    try:
        report = inspect_environment(read_pins(args.requirements))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Environment verification failed: {exc}\n")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if report["passed"]:
        print(f"Environment verified: Python {report['python']['version']}; {len(report['packages'])} exact pins; pip check passed.")
    else:
        print("Environment verification failed:\n" + "\n".join("- " + item for item in report["problems"]), file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
