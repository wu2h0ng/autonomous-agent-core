FROM python:3.9-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/matplotlib/matplotlib.git /repo \
 && git -C /repo checkout de98877e3d
# The base commit is v3.5.0-1931-ga2a1b0a11b on master toward 3.6.0 (env
# commit de98877e3d is two days before the 3.6.0 release): use the manylinux
# wheel of the same series for the compiled extensions instead of a full
# source build. The entrypoint copies *.so + _version.py into the mounted
# workspace so pytest exercises the workspace checkout (base+gold code).
RUN pip install --no-cache-dir numpy==1.26.4 matplotlib==3.6.0 pytest==7.4.4 \
    pyparsing==2.4.7 setuptools==65.7.0
# The wheel's setuptools legacy-namespace .pth pre-seeds sys.modules
# ['mpl_toolkits'] pointing at site-packages, which would shadow the workspace
# checkout's mpl_toolkits and cross-link versions; remove it.
RUN rm -f /usr/local/lib/python3.9/site-packages/matplotlib-3.6.0-py3.9-nspkg.pth
COPY mpl-entry.sh /usr/local/bin/dryrun-entry.sh
RUN chmod +x /usr/local/bin/dryrun-entry.sh
ENV PYTHONPATH=/work/lib
ENTRYPOINT ["/usr/local/bin/dryrun-entry.sh"]
