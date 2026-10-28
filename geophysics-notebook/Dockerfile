ARG BASE_CONTAINER=quay.io/jupyter/scipy-notebook:hub-6.1.1@sha256:987bbee395831e8a2b1ee4e989cb41122cc79099ca8052681dc2af5948d64f86
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

# Same base as scipy-notebook, so the shared root constraints apply as-is.
# Build time only: each pip-running RUN below sets PIP_CONSTRAINT inline.
COPY install-common.sh constraints.txt nbgrader_config.py patch_formgrader.py /tmp/common/
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt \
    /bin/bash -x /tmp/common/install-common.sh --with-nbgrader

# Geophysics stack (SimPEG), the EOSC 350 course environment. Pinned so a
# base refresh mid-term doesn't move it; bump deliberately. mkl + pydiso
# give pymatsolver the Pardiso solver; both are x86_64 only, so this image
# doesn't build on Apple silicon. Newest releases with Python 3.13 builds:
# discretize 0.13 and pydiso 0.3 exist only for 3.12/3.14, and pydiso 0.2.0
# needs mkl 2025.x. Move them up when the base moves to Python 3.14.
USER root
RUN mkdir -p /home/jovyan/.cache/conda/pkgs/cache/shards && \
    chown -R ${NB_UID}:users /home/jovyan/.cache
USER ${NB_UID}
RUN mamba install -y -c conda-forge \
    simpeg=0.25.2 \
    discretize=0.12.0 \
    empymod=2.6.1 \
    pymatsolver=0.5.1 \
    pydiso=0.2.0 \
    mkl=2025.3 \
    cvxopt=1.3.3 \
    deepdish=0.3.7 && \
    mamba clean -afy

# deepdish 0.3.7 is the last release and still uses aliases numpy removed
# (np.ComplexWarning, np.unicode_, np.string_, np.object);
# rename them in place. The grep fails the build if a new deepdish release
# changes these lines, so the patch is revisited instead of silently skipped.
RUN dd="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/deepdish" && \
    grep -q 'np.ComplexWarning' "$dd/core.py" && \
    grep -q 'np.unicode_' "$dd/io/hdf5io.py" && \
    sed -i 's/np\.ComplexWarning/np.exceptions.ComplexWarning/' "$dd/core.py" && \
    sed -i 's/np\.unicode_/np.str_/g; s/np\.string_/np.bytes_/g; s/np\.object\b/object/g' "$dd/io/hdf5io.py" && \
    python -c 'import deepdish'

# pip - the shared requirements, governed by the shared constraints
COPY requirements.txt /tmp/requirements-common.txt
RUN PIP_CONSTRAINT=/tmp/common/constraints.txt pip install --no-cache-dir \
        -r /tmp/requirements-common.txt

# geosci-labs isn't released on conda-forge; pinned to the commit the course
# image used (newest main, after the v0.3.1 release). --no-deps: its dependencies all come from the conda layer above.
RUN pip install --no-cache-dir --no-deps \
        "git+https://github.com/geoscixyz/geosci-labs@d572702deae966da8109fa67c0a9a2741b43c757"

# Fix ownership in case root touched files
USER root
RUN chown -R jovyan:users /home/jovyan

USER jovyan
ENV HOME=/home/jovyan
WORKDIR $HOME
