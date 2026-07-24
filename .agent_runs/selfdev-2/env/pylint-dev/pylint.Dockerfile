FROM python:3.9-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/pylint-dev/pylint.git /repo \
 && git -C /repo checkout e90702074e
RUN cd /repo && pip install --no-cache-dir -e .[testutils]
# Minimal test-requirement pins (requirements_test_min.txt family); the
# astroid pin is the shared middle ground across the three candidate bases.
RUN pip install --no-cache-dir \
    astroid==2.12.13 "py~=1.11.0" "pytest~=7.2" "typing-extensions~=4.4"
