ARG BASE_CONTAINER=quay.io/jupyter/tensorflow-notebook:hub-6.1.1@sha256:8bb7ab896f69f0fdd4a9e1feff27aa4dc614d0a9011b0d133050dcc6ef1b5066
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

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
    tzdata && \
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

# Shared root-level build inputs: install-common.sh plus the files it uses,
# including the ngshare nbgrader_config.py and the formgrader patches.
# Shared pip constraints apply at build time only (set inline, not an ENV).
COPY install-common.sh constraints.txt nbgrader_config.py patch_formgrader.py /tmp/common/
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt \
    /bin/bash -x /tmp/common/install-common.sh --with-nbgrader

# pip, under the shared constraints (build time only, set inline) so torch's
# closure can't move jupyterlab/jinja2/etc. outside what check_constraints.py
# validates.
# CPU-only PyTorch: cluster nodes have no GPU
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
    torch \
    torchvision \
    torchaudio

# torch is already satisfied by the CPU wheels above; listing it again here
# risks pip pulling the CUDA build from PyPI. No `jupyter` metapackage: all it
# pulls in except jupyter-console is already in the base.
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt pip install --no-cache-dir \
    opencv-python-headless \
    plotly \
    skorch \
    torch-inspect

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
