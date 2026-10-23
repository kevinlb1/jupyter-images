"""
Hardening launcher for the vendored ngshare package - wraps it without
patching its source, so it fails loudly (AttributeError) rather than
silently no-op'ing if upstream ever renames/removes what this patches.

What this adds, and why:
  - Request logging: ngshare's own startup code calls
    logging.config.fileConfig (from dbutil.upgrade(), inside main(), before
    MyApplication is ever constructed), which defaults to
    disable_existing_loggers=True and silently disables every logger that
    already existed - Tornado's access/application/general loggers
    included. Patched here, before any ngshare code runs, so none of them
    get disabled in the first place.
  - XSRF cookie protection + SameSite/HttpOnly/Secure on the auth cookie:
    none of which ngshare turns on itself, leaving it without standard
    protection against cross-site request forgery. Header-token requests
    (the only kind nbgrader/the hub ever send) are exempted the same way
    JupyterHub's own HubAuth does: a browser never attaches an
    Authorization header to a cross-site form POST, so CSRF only applies
    to the cookie session.
  - Request body-size cap (default 25MiB, override via
    NGSHARE_MAX_BODY_BYTES): ngshare accepts requests of unlimited size by
    default, so a single very large upload can exhaust memory/disk. Must
    stay below the pod's memory limit (see README) - a request under this
    cap can still hold several decoded copies of its payload in memory.
"""

import logging
import logging.config
import os
import sys

import ngshare.ngshare as ngs
from tornado.httpserver import HTTPServer as _RealHTTPServer

def _env_int_bytes(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            '{} must be a plain integer number of bytes (e.g. 26214400), '
            'not a Kubernetes-style quantity like "25Mi": {!r}'.format(name, raw)
        )


MAX_BODY_BYTES = _env_int_bytes('NGSHARE_MAX_BODY_BYTES', 25 * 1024 * 1024)

_access_log = logging.getLogger('ngshare.access')
# tornado.general is where Tornado itself logs the *reason* a request was
# refused - '_xsrf' argument missing from POST, Content-Length too long -
# at INFO. The root logger alembic.ini configures sits at WARNING, so
# these never reach stdout even though disable_existing_loggers is fixed
# above; raised explicitly here, with its own handler, same as
# ngshare.access below.
_general_log = logging.getLogger('tornado.general')

# dbutil.upgrade() -> alembic -> alembic/env.py calls
# logging.config.fileConfig(config.config_file_name) with no explicit
# disable_existing_loggers argument, so it defaults to True and disables
# every logger that already existed, not just the ones alembic.ini
# configures. Patched here, before main() ever calls dbutil.upgrade(), so
# nothing gets disabled in the first place - fixing the cause instead of
# re-enabling one logger after the fact.
_orig_file_config = logging.config.fileConfig


def _file_config(*args, **kwargs):
    kwargs['disable_existing_loggers'] = False
    return _orig_file_config(*args, **kwargs)


logging.config.fileConfig = _file_config


def _log_function(handler):
    # The chart's liveness/readiness probes hit /healthz every 10s - about
    # 17,000 identical lines/day/pod that would dwarf real traffic. A
    # failing healthz is still worth a line; only successful ones are
    # skipped.
    if isinstance(handler, ngs.HealthCheckHandler) and handler.get_status() < 400:
        return
    # handler.user was already resolved in MyRequestHandler.prepare(); a
    # second handler.get_current_user() here would be an uncached
    # requests.get to the hub on every single request.
    user = getattr(handler, 'user', None)
    username = user.id if user else '-'
    # remote_ip is the TCP peer (the hub's proxy), not the browser: the
    # server no longer runs with xheaders=True, which let any client set
    # remote_ip through its own X-Real-Ip header. The proxy-appended
    # X-Forwarded-For is logged as-is instead, labelled and capped, so it
    # reads as the client-supplied chain it is, not as a verified address.
    xff = handler.request.headers.get('X-Forwarded-For', '-')[:200]
    _access_log.info(
        '%s %s %s %s %d %.2fms xff=%s',
        handler.request.remote_ip,
        username,
        handler.request.method,
        # request.path, not request.uri: the latter includes the query
        # string, which for the OAuth callback carries the auth `code`.
        handler.request.path,
        handler.get_status(),
        handler.request.request_time() * 1000,
        xff,
    )


_orig_app_init = ngs.MyApplication.__init__


def _patched_app_init(self, prefix, db_url, storage_path, debug=False, admin=(), autoreload=False):
    _orig_app_init(self, prefix, db_url, storage_path, debug=debug, admin=admin, autoreload=autoreload)

    if not _access_log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _access_log.addHandler(handler)
        _access_log.setLevel(logging.INFO)
        _access_log.propagate = False

    if not _general_log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _general_log.addHandler(handler)
        _general_log.setLevel(logging.INFO)
        _general_log.propagate = False

    self.settings['log_function'] = _log_function
    self.settings['xsrf_cookies'] = True
    # The prefix ngshare actually routes under (--prefix, else
    # $JUPYTERHUB_SERVICE_PREFIX, else '/api/'), so the auth cookie's path
    # can't drift from the routes it has to reach.
    self.settings['ngshare_cookie_path'] = prefix


# Tornado runs check_xsrf_cookie() before prepare() for any non-GET
# request when xsrf_cookies is on. MyRequestHandler never calls
# HubAuth._get_user (it overrides get_current_user with its own
# requests.get), so _token_authenticated never gets set and every
# token-authenticated write (nbgrader submit/release, roster sync, ...)
# gets a 403 before any ngshare code runs. Mirror HubAuth's own exemption:
# a browser can't attach Authorization to a cross-site form POST, so CSRF
# only applies to the cookie-authenticated path.
#
# Only the "token <t>" scheme is exempt - the one MyRequestHandler's
# get_current_token() actually reads (header[6:]) and the one nbgrader,
# the hub and the roster sync send. Any other Authorization value (Basic,
# Bearer, ...) is never used for auth here, so it gets no exemption.
_orig_check_xsrf_cookie = ngs.MyRequestHandler.check_xsrf_cookie


def _check_xsrf_cookie(self):
    if self.request.headers.get('Authorization', '').startswith('token '):
        return
    return _orig_check_xsrf_cookie(self)


ngs.MyRequestHandler.check_xsrf_cookie = _check_xsrf_cookie


# When check_xsrf_cookie rejects a request, prepare() never ran, so
# self.db was never set - on_finish() still runs and the original
# `self.db.close()` raises AttributeError.
def _on_finish(self):
    db = getattr(self, 'db', None)
    if db is not None:
        db.close()


ngs.MyRequestHandler.on_finish = _on_finish


# ngshare's own set_secure_cookie('ngshare-oauth-token', token) call sets
# no cookie attributes at all - settings['cookie_options'] (the previous
# approach here) is read by neither Tornado nor ngshare, so it was a
# no-op. Wrap the one call site that actually sets this cookie instead.
#
# Once XSRF applies to the cookie-authenticated path, home.html's forms
# will 403 (they don't embed xsrf_form_html()) - the web page becomes
# read-only, which is the intended effect; see README.
#
# path defaults to ngshare's routing prefix, not Tornado's own default of '/':
# without it the browser sends this cookie to every path on the host,
# including other users' servers under /user/<name>/, and since the
# cookie is signed (not encrypted) a server owner logging request headers
# could decode the hub OAuth token inside it and replay it against
# ngshare with the instructor's rights. JupyterHub scopes its own service
# cookie to the service prefix for the same reason.
_orig_set_secure_cookie = ngs.JupyterHubLoginHandler.set_secure_cookie


def _set_secure_cookie(self, name, value, *args, **kwargs):
    if name == 'ngshare-oauth-token':
        kwargs.setdefault('httponly', True)
        kwargs.setdefault('secure', True)
        kwargs.setdefault('samesite', 'Lax')
        kwargs.setdefault('path', self.settings['ngshare_cookie_path'])
        # Migration hazard: before this path scoping existed, every cookie
        # of this name was issued at Tornado's default path '/'. A browser
        # holding one of those from before this change deployed now gets
        # BOTH cookies (same name, different path = different cookie
        # identity, so the new one does not replace the old one) - and
        # Tornado's cookie parser can end up reading back the stale one,
        # which can never validate (signed by a since-replaced
        # cookie_secret), making get_current_user() permanently fail and
        # looping the OAuth dance forever. Reproduced locally: planting a
        # stale path='/' cookie alongside this one is enough to trigger
        # the exact "Detected unused OAuth state cookies" loop seen in
        # stg.
        #
        # self.clear_cookie(name, path='/') does NOT work here: it and
        # set_secure_cookie both write through the same SimpleCookie dict
        # keyed only by name, so whichever call happens second silently
        # replaces the first - only one Set-Cookie line for this name
        # survives, not two. Added as a raw header instead, bypassing
        # that dict, so both the clearing cookie (old path) and the real
        # one (new path) ride out as independent Set-Cookie lines. A
        # one-time, self-healing fix - once every browser has visited
        # after this deploys, the stale cookie is gone and this is a
        # harmless no-op clear of a cookie that no longer exists.
        self.add_header(
            'Set-Cookie',
            '{}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT'.format(name),
        )
    return _orig_set_secure_cookie(self, name, value, *args, **kwargs)


ngs.JupyterHubLoginHandler.set_secure_cookie = _set_secure_cookie


def _hardened_http_server(app, *args, **kwargs):
    kwargs.setdefault('max_body_size', MAX_BODY_BYTES)
    kwargs.setdefault('max_buffer_size', MAX_BODY_BYTES)
    return _RealHTTPServer(app, *args, **kwargs)


ngs.MyApplication.__init__ = _patched_app_init
ngs.HTTPServer = _hardened_http_server


if __name__ == '__main__':
    ngs.main(sys.argv[1:])
