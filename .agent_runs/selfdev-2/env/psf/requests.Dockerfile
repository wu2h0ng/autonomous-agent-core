FROM python:3.9-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/psf/requests.git /repo \
 && git -C /repo checkout 4bceb312f1
RUN pip install --no-cache-dir pytest==7.4.4
RUN pip install --no-cache-dir \
    flask==2.2.5 werkzeug==2.2.3 markupsafe==2.1.3 itsdangerous==2.1.2 \
    jinja2==3.1.3 click==8.1.7 httpbin==0.10.2
COPY httpbin_server.py /opt/httpbin_server.py
COPY dryrun-entry.sh /usr/local/bin/dryrun-entry.sh
RUN chmod +x /usr/local/bin/dryrun-entry.sh
ENV HTTPBIN_URL=http://127.0.0.1:8080/
ENTRYPOINT ["/usr/local/bin/dryrun-entry.sh"]
