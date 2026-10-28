ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:hub-6.1.1@sha256:987bbee395831e8a2b1ee4e989cb41122cc79099ca8052681dc2af5948d64f86
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

# libpango/libharfbuzz-subset: system libraries WeasyPrint (HTML/CSS -> PDF)
# needs. It replaces pdfkit, whose wkhtmltopdf is unmaintained and whose
# 1.0.0 release has an unfixed HIGH (CVE-2025-26240).
#
# /usr/bin/pebble ships in the ubuntu:26.04 OCI image but isn't dpkg-tracked,
# so purge can't remove it; docker-stacks uses tini + start.sh, not pebble,
# and its embedded Go stdlib is the source of several HIGH scan rows.
#
# ffmpeg comes with the base for matplotlib animation export. It's unused
# here, slow to get Ubuntu fixes and behind many of the image's scan
# findings. Reinstate if a course needs video export; GIF export via pillow
# still works.
RUN apt-get update && \
    apt-get upgrade -y --with-new-pkgs && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    tzdata \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 && \
    apt-get purge -y ffmpeg && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /usr/bin/pebble && \
    rm -rf /var/lib/pebble

USER ${NB_UID}

# Keep singleuser jupyterhub on the hub's series; the version is set once
# for every image in JUPYTERHUB_PINS.env (repo root). Written to
# conda-meta/pinned first so every later mamba install/update in this image
# (including install-common.sh) keeps it there.
COPY JUPYTERHUB_PINS.env /tmp/jupyterhub-pins.env
RUN . /tmp/jupyterhub-pins.env && \
    : "${JUPYTERHUB_VERSION:?missing in JUPYTERHUB_PINS.env}" && \
    echo "jupyterhub-singleuser ${JUPYTERHUB_VERSION}" >> "${CONDA_DIR}/conda-meta/pinned" && \
    mamba install --yes "jupyterhub-singleuser=${JUPYTERHUB_VERSION}" && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

# Shared root-level build inputs: install-common.sh plus the files it uses.
# Shared pip constraints apply at build time only: each pip-running RUN below
# sets PIP_CONSTRAINT inline. Deliberately not an ENV, so student pods can
# install any package version (a server restart returns them to the pins).
COPY install-common.sh constraints.txt nbgrader_config.py patch_formgrader.py /tmp/common/
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt \
    /bin/bash -x /tmp/common/install-common.sh --with-nbgrader

# conda
USER root
RUN mkdir -p /home/jovyan/.cache/conda/pkgs/cache/shards && \
    chown -R ${NB_UID}:users /home/jovyan/.cache
USER ${NB_UID}
RUN mamba install -y -c conda-forge \
    gdal \
    geos \
    proj \
    geopandas && \
    mamba clean -afy

# Node gets its own layer so a version bump doesn't invalidate the geo-libs
# solve above it.
RUN mamba install -y -c conda-forge nodejs=22 && \
    mamba clean -afy

# Install AI CLI tools. Versions are sourced from RUNTIME_PINS.env (repo root,
# shared with r-notebook), baked in at /etc/runtime-pins.env so a running
# container can be checked against its own pins. The :? guards fail the build
# if a pin is missing, instead of npm silently installing latest. npm itself
# is updated first (NPM_VERSION) so the CLIs install with the pinned npm.
COPY RUNTIME_PINS.env /etc/runtime-pins.env
RUN . /etc/runtime-pins.env && \
    : "${NPM_VERSION:?missing in RUNTIME_PINS.env}" \
      "${CLAUDE_CODE_VERSION:?missing in RUNTIME_PINS.env}" \
      "${GEMINI_CLI_VERSION:?missing in RUNTIME_PINS.env}" \
      "${CODEX_ACP_VERSION:?missing in RUNTIME_PINS.env}" && \
    npm install -g "npm@${NPM_VERSION}" && \
    npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@google/gemini-cli@${GEMINI_CLI_VERSION}" \
        "@zed-industries/codex-acp@${CODEX_ACP_VERSION}"

# pip - single resolution against the shared + image requirements, governed
# by the shared constraints (build-time only, set inline)
COPY requirements.txt /tmp/requirements-common.txt
COPY scipy-notebook/requirements.txt /tmp/requirements-image.txt
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt pip install --no-cache-dir \
        -r /tmp/requirements-common.txt -r /tmp/requirements-image.txt

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
