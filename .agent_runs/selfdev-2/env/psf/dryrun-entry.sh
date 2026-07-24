#!/bin/sh
# Start the local httpbin server, wait for it, then exec the verifier argv.
python /opt/httpbin_server.py &
i=0
while [ $i -lt 50 ]; do
  if python -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit(0 if s.connect_ex(('127.0.0.1',8080))==0 else 1)"; then
    break
  fi
  i=$((i+1))
  sleep 0.2
done
exec "$@"
