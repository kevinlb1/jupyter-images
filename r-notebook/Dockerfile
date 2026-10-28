ARG BASE_CONTAINER=quay.io/jupyter/r-notebook:hub-6.1.1@sha256:9a3cd29ccb1c4399d4cef51d4da7f0de319a2223a46b36520eab4b521e7ca044
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

# /usr/bin/pebble ships in the ubuntu:26.04 OCI image but isn't dpkg-tracked,
# so purge can't remove it; docker-stacks uses tini + start.sh, not pebble,
# and its embedded Go stdlib is the source of several HIGH scan rows.
RUN apt-get update && \
    apt-get upgrade -y --with-new-pkgs && \
    apt-get install -y --no-install-recommends \
    curl \
    wget \
    unzip \
    tzdata && \
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

# R packages via mamba (conda-forge)
RUN mamba install --yes -c conda-forge \
    r-stargazer \
    r-quanteda \
    r-quanteda.textmodels \
    r-quanteda.textplots \
    r-quanteda.textstats \
    r-caret \
    r-ggiraph \
    r-ggextra \
    r-isocodes \
    r-urltools \
    r-ggthemes \
    r-modelsummary \
    r-nsyllable \
    r-proxyc \
    r-tidytext \
    r-car \
    r-units \
    r-sf && \
    mamba clean --all -f -y

# R packages from CRAN (source)
RUN R -e "install.packages(c( \
    'ggiraphExtra', \
    'sandwich' \
), repos='https://cloud.r-project.org')" && \
    R -e "install.packages('https://cran.r-project.org/src/contrib/Archive/lisp/lisp_0.1.tar.gz', repos=NULL, type='source')" && \
    R -e "install.packages('https://cran.r-project.org/src/contrib/Archive/translate/translate_0.1.2.tar.gz', repos=NULL, type='source')"

# Shared root-level build inputs: install-common.sh plus the files it uses.
# Shared pip constraints apply at build time only: each pip-running RUN below
# sets PIP_CONSTRAINT inline. Deliberately not an ENV, so student pods can
# install any package version (a server restart returns them to the pins).
COPY install-common.sh constraints.txt nbgrader_config.py patch_formgrader.py /tmp/common/
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt \
    /bin/bash -x /tmp/common/install-common.sh --with-nbgrader

# Node gets its own layer, placed after the heavy R/CRAN/install-common
# layers (not folded into the mamba solve above), so a node bump doesn't
# force a re-download of the R conda stack or a CRAN recompile.
RUN mamba install -y -c conda-forge nodejs=22 && \
    mamba clean --all -f -y

# Install AI CLI tools. Versions are sourced from RUNTIME_PINS.env (repo root,
# shared with scipy-notebook), baked in at /etc/runtime-pins.env so a running
# container can be checked against its own pins. The :? guards fail the build
# if a pin is missing, instead of npm silently installing latest. npm itself
# is updated first (NPM_VERSION) so the CLIs install with the pinned npm.
# Placed below the heavy R/CRAN/install-common layers so a CLI version bump
# only costs this layer, not a recompile of everything above it.
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

# pip - single resolution against the shared requirements, governed by the
# shared constraints (build-time only, set inline)
COPY requirements.txt /tmp/requirements-common.txt
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt pip install --no-cache-dir \
        -r /tmp/requirements-common.txt

# Fix R locale issue
RUN echo "LC_ALL=en_US.UTF-8" >> /opt/conda/lib/R/etc/Renviron

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
