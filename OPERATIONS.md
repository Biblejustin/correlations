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
the fixture test target does not. NOAA climate indices run as their own fetch stage before analysis. The regional
analysis also produces the climate-control, seasonal influenza and purchasing-power
extension report; a failed extension stops publication. `make catalogs
SOURCES="climate_indices"` retries only that source. Source names and historical earthquake query
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

The subsequent climate/seasonal/affordability publication is recorded in
[`results/extensions_validation_summary.json`](results/extensions_validation_summary.json):
230 central tests plus five feeder tests, all 56 live stages and 112 readable
artifacts passed. All twelve repositories were clean and matched their published
main branches. Five original statistical result tables and four frozen wheat
files stayed byte-identical. The new source and generated-publication commits
both passed GitHub CI.

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

The daily refresh runs on the VPS through `correlations-refresh.timer` at 06:30
America/Chicago. The systemd calendar follows daylight saving time and catches
up after downtime. The legacy `signs-update.timer` and local Codex refresh are
disabled after migration verification; the unrelated podcast `daily-refresh.timer`
retains its own schedule.

The deployment keeps twelve clean `main` checkouts in a dedicated workspace,
an isolated Python 3.13 environment, the exact Node version pinned by the
astronomy feeder, and GitHub credentials belonging only to Biblejustin. The
scheduled wrapper checks every fetch/push destination, permits only explicit
fast-forward updates, and stops on local edits, divergence, changed approved
runtime/frozen inputs, or concurrent execution. It invokes the existing
`make PY=/absolute/path/to/verified/python publish` entry point. Source and
analytical failures retain diagnostic files; publication still uses the runner's
existing validation gates. No scheduled job resets, stashes, force-pushes, or
silently upgrades dependencies.

Deployment code and systemd templates live in [`ops/vps/`](ops/vps/). Runtime
configuration, credentials, logs, and comparison state stay outside Git. A
reviewed deployed copy of the wrapper runs independently of the checkout it
updates. Changes to approved deployment or runtime files require explicit review
and redeployment. Unit status and the persisted JSON status distinguish completed
publication from a later verification or monthly-source-review problem.

Only substantive observation changes, newly usable periods, revised findings,
changed eligibility, or failures require review. Receipt timestamps, cache or
plot changes, ordinary small earthquakes/flares, and normal new daily Kinneret
observations remain quiet. The comparison is a descriptive review queue, not a
new anomaly detector. Monthly official CRU-CY, UCDP annual country-year and V-Dem
Core release checks can flag new versions; they never adopt or splice products.
Frozen wheat inputs and the minimum ten compatible future annual pairs remain
protected. Missing observations are never replaced with zeros or reclassified
as complete.

The service writes alerts to VPS logs and structured status. An outbound alert
channel must be configured separately with an authorized destination; no local
Codex process or model API is required for scheduled refreshes.

## Trade and economic source monitoring

The runner now fetches `trade_shipping` and `economic_sources` before analysis. Retry with `make catalogs SOURCES="trade_shipping economic_sources"`. `monitor_trade.py` is a separate analysis and writes `results/monitoring/trade/`; any failed source or analysis prevents publication. Shipping archives retain paginated raw responses, count/edit-marker checks and immutable snapshots. Economic archives retain raw World Bank metadata/data and FAOSTAT ZIP/catalog responses, hashes and immutable normalized snapshots. Missing observations do not become zeros.

`python refresh_trade_sources.py --offline` verifies and replays the active shipping archive without advancing its cutoff. `python refresh_economic_sources.py --offline` uses cached source responses and retains their retrieval evidence. Neither mode reconstructs information available before the source was released. `python -m monitoring.recovery_audit --offline` reproduces the separate dated WFP/IPC investigation; large historical archive discovery is not part of daily refresh.

## Pinned eclipse replay

The `astronomy` fetch stage runs the feeder's `monitor_eclipses.py --offline` with the shared Python executable and Node 26.8.1 on `PATH`. No additional Python packages are needed for eclipse calculations. Install the exact Node version recorded in the feeder's `.nvmrc`; a mismatch fails before output promotion. `make catalogs SOURCES="astronomy"` replays only this stage.

Routine replay verifies pinned NASA source/code bytes and recomputes dated outputs under `data/eclipses/`. It does not alter `sources/`, `vendor/`, the frozen plan or the selected historical CSV. In the feeder, `python monitor_eclipses.py --check-sources` stages live candidates for explicit review and never promotes them automatically. The central sync allowlist copies nine declared artifacts and rejects incomplete or mismatched export bundles, including source/code changes since calculation. Original NASA raw objects remain in the feeder archive.

The subsequent trade/celestial publication is recorded in [trade_celestial_validation_summary.json](results/trade_celestial_validation_summary.json): 264 central tests with 101 subtests, 15 eclipse feeder tests, all 60 live stages including 34 analysis stages, and 160 readable artifacts (73 CSV, 46 JSON, 34 PNG, seven Markdown). All twelve repositories were clean on main and matched their actual Biblejustin publication destinations after the live run. Original comparison-table hashes, frozen wheat inputs and the selected historical eclipse CSV remained unchanged. [Central PR 7](https://github.com/Biblejustin/correlations/pull/7) and [astronomy PR 1](https://github.com/Biblejustin/astronomical-signs/pull/1) retain the reviewed source changes. Earlier verification records remain dated evidence.
