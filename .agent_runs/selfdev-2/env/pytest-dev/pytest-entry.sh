#!/bin/sh
# The workspace checkout (src layout) lacks the setuptools-scm-generated
# _pytest/_version.py; copy the one generated during the image build into
# the mounted workspace, then exec the verifier argv. git clean -fdx in the
# harness wipes it between phases, so this runs at every container start.
SRC=/repo/src/_pytest/_version.py
DSTDIR=/work/src/_pytest
if [ -d "$DSTDIR" ] && [ -f "$SRC" ]; then
  cp "$SRC" "$DSTDIR/_version.py"
fi
exec "$@"
