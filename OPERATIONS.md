# Running and verifying the pipeline

Use Python 3.13 and run commands from this repository. Install the pinned runtime
and test dependencies once:

```sh
make bootstrap
make test
```

`bootstrap` creates `.venv`. Set `PYTHON=/path/to/python3.13` to choose the base
interpreter, or `VENV=/path/to/new/venv` to choose its location. For an existing
environment, use `make PY=/absolute/path/to/venv/bin/python test` (or another target).
Every operational target checks Python, exact direct dependency pins, imported
module versions and `pip check` before continuing. Missing or inconsistent
dependencies stop execution. `make bootstrap` can install changed pins into the
existing environment; a new venv gives the stronger check against stale packages.

| Target | Operation |
|---|---|
| `make` / `make refresh` | Fetch, validate, synchronize feeders and rebuild locally through `weekly_update.py --dry-run`. |
| `make local` / `make plots` | Synchronize and rebuild using local inputs through `weekly_update.py --skip-fetch --dry-run`. |
| `make catalogs` | Run fetch stages only, with regression checks; no analysis or publication. |
| `make catalogs SOURCES="ngdc monitoring"` | Retry selected fetch stages through the same runner and source queries. |
| `make correlations` | Run the central analysis suite through `run_suite.py`. |
| `make test` | Run fixture tests. No sibling repositories, source downloads or GitHub credentials needed. |
| `make verify-env` | Verify the configured environment without fetching or analyzing data. |
| `make publish` | Run the full validated pipeline and publish generated artifacts under the runner's account and ownership gates. |

Set `WORKERS=1` to serialize analysis jobs or use another positive worker count.
The pipeline requires its configured sibling repositories for operational runs;
the fixture test target does not. Source names and historical earthquake query
thresholds have one definition in `weekly_update.py`; Make does not duplicate
them. Ordinary refresh targets use `--dry-run` so publication remains explicit.

Failed commands retain their diagnostic output and make the target fail. The
runner stores stage logs in `logs/` and status in `results/analysis_run.json`,
`results/refresh_run.json`, or `results/fetch_run.json`. A successful fetch-only
run verifies source ingestion, not downstream analysis. If a full run reports
unavailable input or a failed stage, inspect that stage's log before retrying;
do not infer success from old figures already on disk. No Make recipe suppresses
errors or substitutes its own source-fetch command.

Publication records every initial branch and commit, then checks the whole
repository set before staging any output. Concurrent branch/commit changes or
unexpected staged/unstaged source edits stop publication. Each local head must
match its freshly queried publication branch, both initially and before commit;
unpublished local commits or concurrent upstream changes stop the run. The quake significant
catalog status sidecar is an explicit generated artifact, so a successful refresh
does not leave it dirty and block the next scheduled run.

## Dependency evidence

The clean verification environment created on September 5, 2026 used CPython
3.13.15 on macOS arm64. Installation from `requirements-dev.txt`, imported package
version checks, `pip check`, and `make test` all passed. That run passed 94 tests
and 13 subtests. `results/environment_verification.json` records the exact
interpreter, platform and direct dependency versions. `pipfreeze.lock` captures
all 24 installed runtime/test distributions from this clean environment.

That was the initial dependency verification. Subsequent source and operational
tests and the complete live pipeline are recorded in
`results/live_validation_summary.json`, including final test counts, source
periods, catalog audit counts and readable artifact hashes. The earlier
`results/validation_summary.json` remains the evidence from the first, limited
run; its limitations do not describe the later full live run.

The completed publication run is recorded in
[`results/publication_validation_summary.json`](results/publication_validation_summary.json):
155 central tests, five publisher-fixture tests, all 55 live stages, 84 readable
artifacts, and all twelve local `main` heads verified clean and equal to their
published branches. Frozen wheat inputs remain byte-identical. Earlier validation
summaries retain their original dates and describe earlier runs.

| Direct dependency | Verified distribution and imported version |
|---|---|
| pandas | 3.0.3 |
| numpy | 2.5.0 |
| scipy | 1.18.0 |
| matplotlib | 3.11.0 |
| requests | 2.34.2 |
| statsmodels | 0.14.6 |
| pytest (test/operational checks) | 9.1.1 |

The runtime and test requirements pin direct dependencies. The freeze file is an
observed transitive dependency snapshot, not a lock with package hashes or a
guarantee that other operating systems render identical figure bytes. To replay
that package set in a new Python 3.13 venv, install with `python -m pip install -r
pipfreeze.lock`, then run the verifier and tests. Input snapshots, fonts, compiled
libraries and operating system also affect reproducibility.

The earlier shared environment had PyWavelets distribution metadata reporting
1.9.0 while its imported `pywt` module reported 1.8.0. No project or operational
feeder source imported it; `wavelet.py` computes the transform directly. The unused
requirement was removed and the clean verification environment contains no
PyWavelets. Earlier environment/results records were preserved. The verifier
now rejects this kind of distribution/module mismatch for required packages.

To capture fresh environment evidence after an intentional dependency update:

```sh
.venv/bin/python verify_environment.py --requirements requirements-dev.txt --json results/environment_verification.json
.venv/bin/python -m pip freeze > pipfreeze.lock
make test
```

## Continuous integration

`.github/workflows/tests.yml` installs the same pins on Python 3.13, verifies the
environment, runs `make test` on Ubuntu and prints the installed package versions.
It runs for pushes to `main`, pull requests and manual dispatches in repositories
owned by `Biblejustin`. It does not run live data refreshes, read GitHub secrets,
persist checkout credentials, or publish artifacts. Fixture tests cover stale
module metadata, missing dependencies and Make's failure propagation as well as
the source and statistical integrity checks.

The workflow was published using an existing SSH key whose public key is
registered to Biblejustin; GitHub SSH authentication confirmed that account.
The separate OAuth token does not need broader workflow permissions for
ordinary generated-data publication. CI has read-only repository permissions
and cannot publish artifacts or change source catalogs.

## Scheduled operation

Use a separate local Codex scheduled task for a daily 06:30 America/Chicago
refresh. Its command is `make PY=/absolute/path/to/verified/python publish` from
the correlations repository. The workspace must contain all twelve sibling
repositories on clean `main` checkouts, with Biblejustin authentication and
remotes. Stop on changed ownership, local edits, divergence, missing dependencies
or failed stages; retain evidence instead of resetting files or publishing
partial results. Repositories can be fast-forwarded explicitly by the scheduled
caller after checking their state; the runner itself does not pull.

Alerts should cover failures, meaningful source revisions, newly usable
observation periods, material diagnostic changes and changed coverage or
validation eligibility. Routine ingestion timestamps, ordinary low-magnitude
quake additions and unchanged chart rendering should remain quiet. Compare
measurement dates as well as retrieval dates; a successful download does not
make an expired IPC assessment current. Keep biblical interpretation separate
from statistical evidence and never score an ineligible prospective model.

Local scheduled tasks require the computer awake and Codex running; see the
[official automation documentation](https://developers.openai.com/codex/app/automations).
The scheduler is configured through Codex, not installed by these Make targets.
