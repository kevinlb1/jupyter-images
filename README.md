# jupyter-images

Images for UBC's JupyterHub (Zero to JupyterHub). One folder with a
`Dockerfile` = one image, built from the repo root.

## Images

| Image | Base | Contents |
|---|---|---|
| `r-notebook` | `jupyter/r-notebook` | R text-analysis/modelling packages, AI CLIs + SDKs |
| `scipy-notebook` | `jupyter/scipy-notebook` | GDAL/GEOS/PROJ, geopandas, altair, vegafusion, WeasyPrint, pypdf, AI CLIs + SDKs |
| `julia-notebook` | `jupyter/julia-notebook` | Common install only |
| `geophysics-notebook` | `jupyter/scipy-notebook` (same pin as scipy) | SimPEG stack (simpeg, discretize, empymod, pymatsolver + mkl/pydiso, cvxopt, deepdish), geosci-labs; pinned in the Dockerfile |
| `tensorflow-notebook` | `jupyter/tensorflow-notebook` | CPU-only PyTorch, OpenCV, plotly, skorch |
| `ngshare-notebook` | `python:3.12-slim-bookworm` | ngshare (nbgrader exchange), own `requirements.txt`/`constraints.txt` |
| `r-studio` | `rocker/tidyverse` | RStudio via `jupyter-rsession-proxy`; R packages from a dated CRAN snapshot (`CRAN_SNAPSHOT`); own `requirements.txt`/`constraints.txt` |

- All five `*-notebook` images (not ngshare): nbgrader + ngshare exchange,
  formgrader patches, shared `constraints.txt`.
- `geophysics-notebook` (EOSC 350): base refreshes come from the watcher like
  scipy; the SimPEG packages and the geosci-labs commit are bumped by hand
  in its Dockerfile. deepdish is patched at build time for numpy 2.
  mkl/pydiso are x86_64 only: no Apple silicon builds.
- Not covered here: `ai100-notebook` (own maintainer), `codingworkspace-*`
  (own pipeline).

## Shared files

| File | Used by | Purpose |
|---|---|---|
| `JUPYTERHUB_PINS.env` | notebooks, r-studio, ngshare | JupyterHub version for user images |
| `install-common.sh` | notebooks, ai100 | Common pip install; `--with-nbgrader` adds nbgrader |
| `constraints.txt` | notebooks | Pip pins (generated) |
| `nbgrader_config.py`, `patch_formgrader.py` | notebooks | ngshare config, formgrader patches |
| `RUNTIME_PINS.env`, `requirements.txt` | r, scipy (+ geophysics: `requirements.txt` only) | AI CLI versions, AI SDKs |

## JupyterHub version

- `JUPYTERHUB_PINS.env` = **5.5.2** for every user image.
- Hub is JupyterHub 5.5.4 (chart 4.4.x); conda-forge stops at 5.5.2;
  same series = compatible.
- To change: edit the file, then `ci/regen-constraints.sh notebooks`,
  `ngshare`, `r-studio`.

## Builds

| Trigger | Builds | Publishes to ECR |
|---|---|---|
| Push to any branch | Changed images | Yes, short-SHA tag |
| Push to `main` / tag | Changed images | Yes, short-SHA + `latest` |
| PR to `main` | Changed images | No |
| Base image watcher | Images its update affects | No |

- "Changed" today: an image's folder changed, or **any** root file
  changed → every image.
- `ci/select_images.py` narrows this to images that `COPY` the changed
  file; not wired into `build.yml`/`build-pr.yml` yet (shared with
  CodingWorkspace).
- Each build runs `<image>/ci/smoke.sh`; notebook checks shared in
  `ci/smoke-notebook.sh`.

## Deploying (manual)

- `latest` is never deployed.
- Deploy = put the new **short-SHA** tag in the Z2JH Helm config
  (preview first, then production). Users get it after Stop → Start.
- Chart matching is manual:
  - The hub runs the chart's stock `k8s-hub` image (no custom hub image).
  - `JUPYTERHUB_PINS.env`: `K8S_HUB_IMAGE` = chart version,
    `JUPYTERHUB_VERSION` on the chart's JupyterHub series.
- The automation never deploys, upgrades the chart or edits Helm config.

## Base image watcher

`.github/workflows/base-image-updates.yml`, weekdays 14:17 UTC (or
Actions → **Base image updates** → **Run workflow**).

| Image | Follows |
|---|---|
| r, scipy, julia, tensorflow, geophysics | newest `hub-X.Y.Z`, same major |
| r-studio | newest `rocker/tidyverse` `X.Y.Z`, same major |
| ngshare | same `python:3.12-slim-bookworm` tag, new digest |

- New digest on the same tag also counts.
- New majors / Python minors: never applied, built or tested. Manual
  steps go in the update PR (if any) and an issue (see below).

On an update it:

1. Updates pins, regenerates the affected `constraints.txt`.
2. Builds and tests on the runner, **no push to ECR**:
   - constraints downgrade check (notebooks)
   - smoke test
   - real-hub test (`ci/hub-compat.sh`, notebooks + r-studio)
3. Opens/updates one PR: **Update base images**.

On failure: opens/updates issue **Base image updates failing**; closes on
the next passing run.

### Owners

- PR: owners are reviewers + assignees. Failure and major upgrade
  issues: owners assigned.
- Owners = `BASE_IMAGE_OWNERS` repo variable, else `OWNERS` default in the
  workflow.
- Change: set the variable (Settings → Secrets and variables → Actions →
  Variables), comma-separated usernames.
- Notifications: email and/or GitHub inbox, per personal settings.
- Owners need repo access; anyone who can't be added is skipped.

### When you get an update PR

- Nothing is published until you merge.
- Any build/test failed → don't merge; see failure report below.
- Check the constraint diff for big jumps (nbgrader, otter-grader,
  jupyterlab, pandas).
- Root `constraints.txt` changed → merge republishes every image; avoid
  before labs/exams.
- Merge → confirm **Validate and publish Docker images** passes on `main`
  → note new short-SHA tags → deploy manually.
- Don't commit to the update branch; fix things in a normal PR to `main`.

### When you get a failure report

- Nothing deployed; users unaffected.
- Open the run link → failed step → `FAIL`/`ERROR` lines.

| Failed step | Likely cause | Fix |
|---|---|---|
| Check registries / Push the update branch | Registry down or rate-limited | Wait or **Re-run failed jobs** |
| Regenerate constraints for the new bases | Requirement conflict | Run `ci/regen-constraints.sh` locally, fix in PR |
| Check constraints against the base | Pin would downgrade a base package | Regenerate; intended → `ALLOW_DOWNGRADE`/`ALLOW_MOVE` |
| Build image | Package gone from new base | Fix Dockerfile in PR |
| Build image (`patch_formgrader.py` failed) | nbgrader changed | Update the patch |
| Run smoke test | Image broken | See `FAIL:` line |
| Run against the deployed JupyterHub version | Image can't run on the hub | Check `JUPYTERHUB_PINS.env` |
| Create or update the PR | Actions can't create PRs | Settings → Actions → General → allow PR creation |

- Fix in a normal PR → next run (or **Run workflow**) retries.
- Can't fix soon → safe to leave, or disable the workflow.

### When you get a major upgrade notice

- Issue **Major base image upgrade available**, owners assigned; also in
  the update PR body when there is one.
- Nothing built, tested or published for the major; users unaffected.
- Lists per image: current tag, new tag, exact `ARG BASE_CONTAINER=` line
  (tag + digest), extra steps, release notes.
- Upgrade:
  1. Read the release notes.
  2. New branch from `main`; paste the `ARG BASE_CONTAINER=` line(s).
  3. Extra steps per image:
     - notebooks: all five together; `ci/regen-constraints.sh notebooks`
     - r-studio: `ci/regen-constraints.sh r-studio`; maybe bump
       `CRAN_SNAPSHOT`
     - ngshare: `ci/regen-constraints.sh ngshare`
  4. Build + smoke + hub-compat locally (see *Local commands*).
  5. PR to `main` → CI builds and tests.
  6. Merge → new short-SHA tags → deploy manually, stg first.
- Issue updates in place each run; closes itself once nothing is held back.
- Not ready to upgrade → leave it open.

### If nobody responds

- Nothing published or deployed; security fixes just wait.
- Same PR stays open and keeps updating.
- Failure issue gets a comment per failing run. No escalation.
- GitHub disables schedules after 60 days of repo inactivity → re-enable
  in Actions.

## Local commands

```bash
docker buildx build --load -f scipy-notebook/Dockerfile -t local/scipy-notebook:test .
scipy-notebook/ci/smoke.sh local/scipy-notebook:test
ci/hub-compat.sh scipy-notebook local/scipy-notebook:test
ci/regen-constraints.sh notebooks   # or ngshare, r-studio; --upgrade = newest everything
python3 ci/check_base_updates.py    # what the watcher would change
python3 ci/check_base_updates.py --major-report /tmp/major.md   # + manual steps for held-back majors
python3 ci/test_select_images.py && python3 ci/test_check_base_updates.py
```

- Apple silicon builds arm64; CI builds amd64. Some r-notebook R packages
  have no arm64 builds.
