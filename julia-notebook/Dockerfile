ARG BASE_CONTAINER=quay.io/jupyter/julia-notebook:hub-6.1.1@sha256:a881516f6103e3d10d0a6f8d4e5528a7d9fbd5b8e0b3ef8b89c798e0b2f00dde
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

# Shared root-level build inputs: install-common.sh plus the files it uses.
# Shared pip constraints apply at build time only (set inline, not an ENV).
COPY install-common.sh constraints.txt nbgrader_config.py patch_formgrader.py /tmp/common/
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt \
    /bin/bash -x /tmp/common/install-common.sh --with-nbgrader

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
