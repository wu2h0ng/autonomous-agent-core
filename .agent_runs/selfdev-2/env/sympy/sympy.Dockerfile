FROM python:3.9-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/sympy/sympy.git /repo \
 && git -C /repo checkout 50b81f9f6b
RUN cd /repo && pip install --no-cache-dir -e .
RUN pip install --no-cache-dir mpmath==1.3.0 pytest==6.2.5
