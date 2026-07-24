#!/bin/sh
# Copy compiled matplotlib extensions (+ generated _version.py) from the
# wheel install into the mounted workspace checkout, then exec the verifier
# argv. git clean -fdx in the harness wipes them between phases, so this
# must run at every container start.
SRC=/usr/local/lib/python3.9/site-packages/matplotlib
DST=/work/lib/matplotlib
if [ -d "$DST" ] && [ -d "$SRC" ]; then
  (cd "$SRC" && find . \( -name '*.so' -o -name '_version.py' \) -print) | while read -r f; do
    mkdir -p "$DST/$(dirname "$f")"
    cp "$SRC/$f" "$DST/$f"
  done
fi
exec "$@"
