#!/usr/bin/env bash
# Post-build smoke test for ngshare-notebook. Run as:
#   ngshare-notebook/ci/smoke.sh IMAGE_REF
set -euo pipefail

IMAGE="${1:?usage: smoke.sh IMAGE_REF}"

# ngshare authenticates through jupyterhub's client library, pinned for
# every image in JUPYTERHUB_PINS.env.
. "$(dirname "$0")/../../JUPYTERHUB_PINS.env"
hub_version=$(docker run --rm --entrypoint python3 "$IMAGE" -c \
  'import importlib.metadata as m; print(m.version("jupyterhub"))')
if [ "$hub_version" != "$JUPYTERHUB_VERSION" ]; then
  echo "FAIL: jupyterhub $hub_version, expected $JUPYTERHUB_VERSION (JUPYTERHUB_PINS.env)" >&2
  exit 1
fi

# No curl in the python:3.12-slim-bookworm base - everything here uses the
# stdlib instead. Script piped to `python3 -` via stdin rather than -c, to
# stay out of nested-quoting hell.
docker run --rm -i --entrypoint python3 "$IMAGE" - <<'PYEOF'
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


def fail(msg):
    print('FAIL: ' + msg, file=sys.stderr)
    sys.exit(1)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Stand in for the hub: ngshare's user_for_token() does a GET to
# $JUPYTERHUB_API_URL/user with the caller's token and trusts whatever 200
# JSON comes back - good enough to exercise real auth without a real hub.
# Also answers the OAuth token exchange (POST .../oauth2/token) so the
# oauth_callback path - and the cookie it sets - can be exercised too.
class FakeHubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'name': 'smoketest', 'admin': False}).encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'access_token': 'smoke-test-oauth-token'}).encode())

    def log_message(self, *args):
        pass


fake_hub = HTTPServer(('127.0.0.1', 8000), FakeHubHandler)
Thread(target=fake_hub.serve_forever, daemon=True).start()

env = dict(os.environ)
env.update(
    JUPYTERHUB_API_URL='http://127.0.0.1:8000/hub/api',
    JUPYTERHUB_API_TOKEN='smoke-test-api-token',
    JUPYTERHUB_CLIENT_ID='smoke-test-client',
    JUPYTERHUB_SERVICE_PREFIX='/services/ngshare/',
    JUPYTERHUB_SERVICE_URL='http://0.0.0.0:12121/services/ngshare/',
    # Small on purpose, just for this run, so the body-size-cap assertion
    # below doesn't need to push megabytes through the socket.
    NGSHARE_MAX_BODY_BYTES='1024',
)

# --admins smoketest: matches the fake hub's returned username, so the
# POST below exercises a full admin-gated handler end to end, not just
# the auth layer.
#
# stdout/stderr are captured (not inherited) so the access-log assertion
# below can inspect ngshare's own output in isolation from this script's
# prints.
proc = subprocess.Popen(
    [
        'python3', '/ngshare/run.py',
        '--database', 'sqlite:////tmp/ngshare-smoke.db',
        '--storage', '/tmp/ngshare-smoke-storage/',
        '--admins', 'smoketest',
    ],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

try:
    healthz_url = 'http://127.0.0.1:12121/services/ngshare/healthz'
    for _ in range(60):
        try:
            with urllib.request.urlopen(healthz_url, timeout=1) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError):
            pass
        if proc.poll() is not None:
            fail('ngshare exited early with code %r' % proc.returncode)
        time.sleep(0.5)
    else:
        fail('ngshare never became healthy')

    # 1) The regression this whole file originally guarded: xsrf_cookies=True
    # with no token exemption meant check_xsrf_cookie() rejected every
    # non-GET request authenticated only by an Authorization header -
    # Tornado's generic 403 HTML page, before any ngshare code ran. A real
    # ngshare JSON response (success or error) proves the request reached
    # ngshare's own routing instead.
    req = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/course/smoke-test-course',
        method='POST',
        headers={
            'Authorization': 'token smoke-test-user-token',
            # Client-supplied, so neither may become the logged peer
            # address - asserted on the access-log line (check 8) below.
            'X-Real-Ip': '203.0.113.66',
            'X-Forwarded-For': '198.51.100.7',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            body = r.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read()

    print('Header-token POST status: %d' % status)
    print(body.decode(errors='replace'))

    if status == 403 and b'<html' in body.lower():
        fail(
            "got Tornado's generic XSRF 403 HTML page - the "
            'Authorization-header exemption is broken'
        )

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        fail("response body is not valid JSON - request never reached ngshare's own handler")

    if 'success' not in parsed:
        fail('response JSON has no "success" key: %r' % (parsed,))

    print('OK: header-token POST reached ngshare')

    # 2) A 403 here is NOT proof XSRF is enforced on its own: MyRequestHandler's
    # @authenticated decorator refuses an unauthenticated POST with 403
    # regardless of whether xsrf_cookies is even on. What actually
    # distinguishes "refused for lacking a token" from "refused for lacking
    # _xsrf" is the log line Tornado itself writes - asserted on `out`
    # below, once the process output has been captured.
    req_noauth = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/course/smoke-test-course-noauth',
        method='POST',
    )
    try:
        with urllib.request.urlopen(req_noauth, timeout=5) as r:
            fail(
                'unauthenticated POST should have been rejected, got %d'
                % r.status
            )
    except urllib.error.HTTPError as e:
        if e.code != 403:
            fail('expected 403 for unauthenticated POST, got %d' % e.code)
        print('OK: unauthenticated POST correctly rejected (403)')

    # 2b) Only the "token <t>" scheme ngshare actually reads is exempt from
    # XSRF. The fake hub accepts any token, so if any Authorization header
    # still bypassed the check, this POST would succeed.
    req_basic = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/course/smoke-test-course-basic',
        method='POST',
        headers={'Authorization': 'Basic c21va2U6dGVzdA=='},
    )
    try:
        with urllib.request.urlopen(req_basic, timeout=5) as r:
            fail('non-token Authorization POST bypassed XSRF, got %d' % r.status)
    except urllib.error.HTTPError as e:
        if e.code != 403:
            fail('expected 403 for non-token Authorization POST, got %d' % e.code)
        print('OK: non-token Authorization POST still subject to XSRF (403)')

    # 3) Prove the body-size cap actually refuses an oversized request,
    # using the small NGSHARE_MAX_BODY_BYTES set above.
    oversized_body = b'x' * 2000
    req_big = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/course/smoke-test-course-big',
        data=oversized_body,
        method='POST',
        headers={'Authorization': 'token smoke-test-user-token'},
    )
    try:
        with urllib.request.urlopen(req_big, timeout=5) as r:
            fail('oversized POST should have been refused, got %d' % r.status)
    except urllib.error.HTTPError as e:
        print('OK: oversized POST refused (HTTP %d)' % e.code)
    except (urllib.error.URLError, ConnectionError) as e:
        print('OK: oversized POST refused (connection closed: %s)' % e)

    # 4) Prove the auth cookie actually carries HttpOnly, Secure,
    # SameSite=Lax and the service-prefix path - not just that *a* cookie
    # gets set. Needs the fake hub's token endpoint (added above) to
    # answer the OAuth code exchange oauth_callback makes.
    #
    # Two Set-Cookie headers for this name are expected now, not one: a
    # browser holding a cookie from before this path scoping existed
    # (default path '/') would otherwise keep BOTH that stale cookie and
    # the new path-scoped one, and Tornado's cookie parser can read back
    # the stale one - which can never validate - looping the OAuth dance
    # forever. Reproduced and fixed; checked explicitly below rather than
    # just inspecting whichever Set-Cookie header happens to come first.
    opener = urllib.request.build_opener(_NoRedirect())
    req_cookie = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/oauth_callback?code=smoke-test-code',
    )
    try:
        resp = opener.open(req_cookie, timeout=5)
        set_cookie_headers = resp.headers.get_all('Set-Cookie') or []
    except urllib.error.HTTPError as e:
        if e.code != 302:
            fail('oauth_callback: expected a 302 redirect, got %d' % e.code)
        set_cookie_headers = e.headers.get_all('Set-Cookie') or []

    print('Set-Cookie headers: %r' % set_cookie_headers)

    real_cookie = next(
        (h for h in set_cookie_headers
         if 'ngshare-oauth-token=' in h and not h.startswith('ngshare-oauth-token=;')),
        None,
    )
    if real_cookie is None:
        fail('oauth_callback did not set the ngshare-oauth-token cookie with a real value')
    for expected in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/services/ngshare/'):
        if expected not in real_cookie:
            fail('Set-Cookie is missing %r: %s' % (expected, real_cookie))
    print('OK: auth cookie carries HttpOnly, Secure, SameSite=Lax and the service-prefix path')

    legacy_clear = next(
        (h for h in set_cookie_headers
         if h.startswith('ngshare-oauth-token=;') and 'Path=/;' in h),
        None,
    )
    if legacy_clear is None:
        fail(
            'oauth_callback did not clear the legacy path=/ cookie - a browser '
            'holding one from before this fix would loop forever'
        )
    print('OK: legacy path=/ cookie is explicitly cleared alongside the new one')

    time.sleep(0.3)  # let any pending access-log write flush before we kill it
finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    fake_hub.shutdown()

print('--- ngshare process output ---')
print(out)

# 5) Prove the request-logging fix actually produces a log line, not just
# that fileConfig no longer disables the loggers. "smoketest" is the
# resolved username from MyRequestHandler.prepare(), proving this came
# from the already-resolved handler.user (not a second hub round-trip).
if 'smoketest' not in out or 'POST' not in out:
    fail('expected an access-log line for the authenticated POST, found none')

# 6) This is what actually proves assertions #2/#2b's 403s were XSRF rejections,
# not just @authenticated refusing a request with no token - tornado.general
# only writes this line when check_xsrf_cookie() itself raises.
if out.count("'_xsrf' argument missing from POST") < 2:
    fail('expected the tornado.general XSRF-rejection line, found none - '
         "the unauthenticated-POST 403 above may not be an XSRF rejection at all")
print('OK: unauthenticated POST was actually refused by XSRF, confirmed via the log line')

# 7) Same visibility fix, for the oversized-POST rejection from check #3 -
# proves tornado.general is now actually reaching stdout at INFO, not just
# that a raised level didn't error.
if 'Content-Length too long' not in out:
    fail('expected the tornado.general oversized-body rejection line, found none')
print('OK: oversized-POST rejection reason is now visible in the log')

# 8) The logged address is the TCP peer, not the client's X-Real-Ip, and
# X-Forwarded-For is logged only as a labelled field.
post_lines = [l for l in out.splitlines()
              if 'smoketest POST /services/ngshare/course/smoke-test-course ' in l]
if not post_lines:
    fail('no access-log line for the header-token POST')
if '127.0.0.1 smoketest POST' not in post_lines[0] or 'xff=198.51.100.7' not in post_lines[0]:
    fail('access log trusted a client-supplied address: %r' % post_lines[0])
print('OK: access log records the peer address, not client-supplied X-Real-Ip')

print('ALL CHECKS PASSED')
PYEOF
