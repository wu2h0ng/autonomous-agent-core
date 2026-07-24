FROM python:3.9-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/pytest-dev/pytest.git /repo \
 && git -C /repo checkout c2f762460f
RUN cd /repo && pip install --no-cache-dir -e .
# Era-compatible pins covering both candidate families (pytest 5.1 / 6.0).
RUN pip install --no-cache-dir \
    pluggy==0.13.1 py==1.11.0 attrs==21.4.0 more-itertools==8.14.0 \
    packaging==21.3 wcwidth==0.2.5 atomicwrites==1.4.0 iniconfig==1.1.1 \
    toml==0.10.2 importlib-metadata==1.7.0 six==1.12.0
ENV PYTHONPATH=/work/src
COPY pytest-entry.sh /usr/local/bin/dryrun-entry.sh
RUN chmod +x /usr/local/bin/dryrun-entry.sh
ENTRYPOINT ["/usr/local/bin/dryrun-entry.sh"]
