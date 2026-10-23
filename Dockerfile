# The plugin's image. It runs beside a sidecar in the deployment's cluster, and
# reaches nothing but that sidecar and the ECB's public Data Portal.
#
# Built on the base image for the SDK this plugin pins: Python and
# open-meridian, the same version as pyproject.toml's, already installed. So
# the image's own layer is this plugin, and an upload sends only that. Move
# the two together when moving to a new SDK.
#
# BASE is for building against a base made locally rather than a released one.
# The release by its tag and its digest, the image exactly; move both together.
ARG BASE=ghcr.io/open-meridian/plugin-python:0.32.1@sha256:92f58ed38f475a50a6ca4f28c90e70b30d5f9c4528541d1720045ca09a70db9f
FROM ${BASE}
WORKDIR /plugin
# Installed from a mount rather than copied, so the image holds the installed
# package and no source beside it.
RUN --mount=type=bind,target=/tmp/src,rw pip install --no-cache-dir /tmp/src
# The vendor's documentation (contract v25): the declaration names docs/,
# relative to where the plugin runs, /plugin, and `meridian-declaration`
# reads it there when `meridian plugin upload` prints the declaration.
COPY docs/ docs/
USER 65532
CMD ["ecb"]
