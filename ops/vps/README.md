# VPS daily refresh

`correlations-refresh.timer` runs the existing validated publication pipeline at
06:30 America/Chicago. Python, Node, GitHub authentication, source fetches,
analysis, publication, release checks, logs and comparison state all live on the
VPS. No desktop app or model API is involved.

## Deployment layout

The supplied units use these paths. Review and adjust them together when moving
to a different server or service account.

| Path | Purpose |
|---|---|
| `/home/ubuntu/correlations-workspace` | Twelve sibling repositories and `verification-venv` |
| `/home/ubuntu/correlations-runtime` | Isolated Python 3.13 and Node 26.8.1 installations |
| `/home/ubuntu/correlations-service/bin` | Reviewed copies of the deployment Python files |
| `/home/ubuntu/correlations-service/config.json` | Approved paths and integrity hashes; mode 0600 |
| `/home/ubuntu/correlations-service/github` | Isolated `gh` configuration for Biblejustin; private directory |
| `/home/ubuntu/correlations-service/state` | Run logs, semantic snapshots, status and monthly release evidence |

Install the direct pins from the central `requirements-dev.txt` in a clean
Python 3.13 venv. Install the exact Node version in the astronomy feeder's
`.nvmrc`, verify its official archive checksum, and keep its binary on the service
PATH. Do not change the system Python or Node used by unrelated applications.

Clone only the twelve Biblejustin repositories listed in `scheduled_refresh.py`,
on clean `main` branches. Preserve existing checkouts and local edits. Existing
SQLite catalogs can be transferred with SQLite's backup API, then checked by
SHA-256 and `PRAGMA quick_check`; do not copy a database while a writer can leave
an inconsistent file. Ordinary runs refresh those catalogs through the existing
fetchers.

Authenticate `gh` as Biblejustin in the isolated configuration directory, without
putting a token in a command argument, repository, unit file or log. Verify the
identity and every fetch/push URL before enabling publication.

## Approve and start

Copy the reviewed Python files from this directory into the service's `bin`
directory. The deployed wrapper must remain outside the workspace it updates.
Create a new approval configuration; the generator refuses to overwrite one:

```sh
/home/ubuntu/correlations-workspace/verification-venv/bin/python \
  /home/ubuntu/correlations-service/bin/config_generator.py \
  --workspace /home/ubuntu/correlations-workspace \
  --deployed /home/ubuntu/correlations-service/bin \
  --destination /home/ubuntu/correlations-service/config.json \
  --python /home/ubuntu/correlations-workspace/verification-venv/bin/python \
  --node /home/ubuntu/correlations-runtime/node-v26.8.1-linux-x64/bin/node \
  --state-dir /home/ubuntu/correlations-service/state \
  --gh-config-dir /home/ubuntu/correlations-service/github
```

For the initial September 2026 migration, copy the dated
`release_review_seed_2026-09.json` into `state/release_reviews/2026-09.json` and
preserve the original audit referenced by its hash. That consumes September's
already completed official release check. Never relabel an old audit as a new
month or use a seed to hide a failed check.

Install the reviewed service and timer in `/etc/systemd/system`, run
`systemd-analyze verify`, and reload systemd. Run the same configured wrapper
with `--check` for an account, checkout, remote, runtime and integrity preflight.
Then start `correlations-refresh.service` manually and verify its complete
publication and status before enabling `correlations-refresh.timer`.

Retire the old `signs-update.timer` and pause the local Codex refresh after the
new service succeeds. The unrelated podcast `daily-refresh.timer` retains its
own schedule. Enable the new timer for boot startup and confirm its next trigger
with `systemctl list-timers correlations-refresh.timer`.

## Status and failures

Inspect `state/status.json`, the current run directory under `state/runs/`, and:

```sh
systemctl status correlations-refresh.timer correlations-refresh.service
journalctl -u correlations-refresh.service --since today
```

The oneshot service is normally inactive between successful runs; the timer
stays active. A zero exit status, successful current run receipt, clean
repositories and verified remote heads establish a completed publication.
Status records distinguish a fetch/analysis/push failure from a problem found
after publication. A process termination retains an interrupted-run receipt.
The preflight command keeps its own receipt and does not clear production
failure history.

`notification_needed` identifies a new review event; retained state also records
continuing problems. This deployment has no outbound notification client. Logs
and JSON status remain on the VPS until an authorized destination is configured.
The comparison is descriptive, not a new statistical anomaly test: normal small
quakes/flares, receipt times, plot rendering and routine daily lake additions do
not warrant alerts. Clock-only rolling flu views are excluded; normalized WHO
observations still participate. Lake review flags a crossing of the published
lower-red reference (-213 m), or a change exceeding 0.25 m per elapsed day. The
latter is an explicit operational review threshold, not a statistical or prophetic
claim. Both rules appear in the approved semantic policy. Changed measurements, usable periods, eligibility and
adjusted findings can require review.

A failed run preserves files. Inspect and resolve the cause before retrying;
dirty repositories intentionally block publication. Never reset, stash or
force-push to make an unattended run appear healthy. Dependency, frozen-input,
product-plan or deployment-code changes require explicit review and a new
approved deployment configuration. Keep the previous configuration and evidence
when replacing it.

Monthly checks inspect only the configured official CRU-CY, UCDP annual
country-year and V-Dem Core products. A newer version becomes a review candidate.
Failed or ambiguous checks remain explicit; no product is silently adopted and
no failed monthly attempt is retried every day.
