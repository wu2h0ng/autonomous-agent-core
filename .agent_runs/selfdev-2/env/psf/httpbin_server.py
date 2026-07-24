"""Local httpbin server for offline SWE-bench requests verification.

The 2013-era requests test suite reads HTTPBIN_URL (baked into the image as
http://127.0.0.1:8080/) and makes real HTTP calls; under --network none the
only reachable endpoint is loopback, so the container entrypoint starts this
server before exec'ing the verifier argv.
"""

from httpbin import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, threaded=True)
