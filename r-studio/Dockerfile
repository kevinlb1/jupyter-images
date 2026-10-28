# Soci 428 — RStudio Server image for JupyterHub (Z2JH)
# Base: rocker/tidyverse pins R version + tidyverse + RStudio Server.
# Pinned by digest; .github/workflows/base-image-updates.yml proposes newer
# 4.x.y tags and refreshed digests.
ARG BASE_CONTAINER=rocker/tidyverse:4.6.1@sha256:fd34ce1475d4379d7ac715b11decf08854d8f3b205d8fc4e6c48041408e00fc1
FROM $BASE_CONTAINER

# ---- System dependencies for JupyterHub integration ----
# We need Python + pip to install jupyterhub-singleuser and jupyter-rsession-proxy,
# which is the bridge that lets JupyterHub spawn and proxy to RStudio Server.
RUN apt-get update && apt-get upgrade -y --with-new-pkgs && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---- JupyterHub plumbing ----
# jupyterhub-singleuser is what Z2JH's KubeSpawner actually launches.
# jupyter-rsession-proxy is the extension that proxies RStudio through it.
# jupyterhub's version is set once for every image in JUPYTERHUB_PINS.env
# (repo root); the direct deps are pinned in r-studio/requirements.txt and
# their full closure in r-studio/constraints.txt (ci/regen-constraints.sh
# r-studio), so rebuilds are reproducible.
# Using --break-system-packages because Ubuntu marks the system Python as
# externally managed (PEP 668); acceptable here since the container is
# single-purpose.
COPY JUPYTERHUB_PINS.env /tmp/jupyterhub-pins.env
COPY r-studio/requirements.txt /tmp/requirements.txt
COPY r-studio/constraints.txt /tmp/constraints.txt
RUN . /tmp/jupyterhub-pins.env && \
    : "${JUPYTERHUB_VERSION:?missing in JUPYTERHUB_PINS.env}" && \
    PIP_CONSTRAINT=/tmp/constraints.txt pip3 install --break-system-packages --no-cache-dir \
        -r /tmp/requirements.txt "jupyterhub==${JUPYTERHUB_VERSION}"

# ---- Enable GitHub Copilot in RStudio Server ----
# This is the admin-side toggle. Each student still authenticates their own
# GitHub Education account from inside RStudio (Tools > Global Options > Copilot).
RUN echo "copilot-enabled=1" >> /etc/rstudio/rsession.conf

# ---- Course-specific R packages ----
# Binary installs from a dated Posit Package Manager snapshot, so a rebuild
# gets the same package versions; bump CRAN_SNAPSHOT (any date Posit has a
# snapshot for) to move them. The Ubuntu codename comes from the base image,
# so the binaries always match its system libraries.
# install.packages() only warns on failure; the check after it fails the
# build if any package didn't install.
# Add/remove packages as the syllabus evolves; rebuilding the image is cheap.
ARG CRAN_SNAPSHOT=2026-10-23
RUN . /etc/os-release && \
    CRAN_REPO="https://p3m.dev/cran/__linux__/${VERSION_CODENAME}/${CRAN_SNAPSHOT}" \
    R -q -e "pkgs <- c( \
        'haven', \
        'survey', \
        'srvyr', \
        'broom', \
        'modelsummary', \
        'marginaleffects', \
        'performance', \
        'see', \
        'car', \
        'lmtest', \
        'sandwich', \
        'estimatr', \
        'fixest', \
        'ggeffects', \
        'gtsummary', \
        'janitor', \
        'skimr', \
        'corrr' \
    ); \
    install.packages(pkgs, repos = Sys.getenv('CRAN_REPO')); \
    missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; \
    if (length(missing)) stop('failed to install: ', paste(missing, collapse = ', '))"

# ---- Shared course datasets (optional pattern) ----
# Bake common datasets into the image so every student has them at /srv/data.
# Alternatively, mount a read-only PVC at /srv/data via Z2JH — more flexible.
RUN mkdir -p /srv/data
# COPY datasets/ /srv/data/
RUN chmod -R a+r /srv/data

# ---- Home directory symlink for Z2JH compatibility ----
# Z2JH mounts the persistent home volume at /home/jovyan (hub-wide default).
# Rocker/RStudio expects the user's home at /home/rstudio.
# We create /home/jovyan as the real directory and symlink /home/rstudio to it,
# so RStudio's reads/writes land in the persistent volume at runtime.
RUN mkdir -p /home/jovyan \
    && chown rstudio:rstudio /home/jovyan \
    && rm -rf /home/rstudio \
    && ln -s /home/jovyan /home/rstudio

# ---- Fix RStudio Server state-directory ownership for non-root launch ----
# rocker/tidyverse creates these owned by the 'rstudio-server' system account,
# for its normal root-launched/s6-supervised startup path. jupyter-rsession-proxy
# instead launches rserver directly as the singleuser process (uid 1000, user
# 'rstudio'), which needs write access to its own state DB and session key.
RUN chown -R rstudio:rstudio /var/lib/rstudio-server /var/run/rstudio-server

# ---- Persistent user package library ----
# Rocker installs packages to /usr/local, which is NOT persisted across sessions.
# This creates a user-writable library inside the persistent home volume so
# student-installed packages survive logout. The Renviron file points R there.
RUN mkdir -p /home/rstudio/R/library \
    && chown -R rstudio:rstudio /home/jovyan \
    && echo "R_LIBS_USER=/home/rstudio/R/library" >> /usr/local/lib/R/etc/Renviron.site

# ---- Default working directory ----
WORKDIR /home/rstudio

# ---- Switch to non-root user for runtime ----
# Rocker creates the 'rstudio' user (UID 1000) in the base image.
# jupyter-server refuses to run as root, and Z2JH expects UID 1000 by default,
# so we explicitly switch before the container's CMD runs.
USER rstudio

# Z2JH's KubeSpawner will call `jupyterhub-singleuser` as the container command;
# no CMD/ENTRYPOINT override needed here. RStudio is launched on demand via
# jupyter-rsession-proxy when the user hits /rstudio.
