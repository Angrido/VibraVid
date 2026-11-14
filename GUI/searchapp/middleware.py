# 01.11.26

import logging

from django.http import HttpResponseBadRequest, JsonResponse
from django.http.request import split_domain_port
from django.shortcuts import redirect
from django.utils.http import urlencode

from . import security

logger = logging.getLogger(__name__)


class LocalHostOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host, _ = split_domain_port(request.get_host())
        if security.foreign_host_blocked(host):
            logger.warning(
                "Refused request for host %r: without a login the GUI only answers on IP addresses and local names. "
                "Add it to ALLOWED_HOSTS or set VIBRAVID_USERNAME/VIBRAVID_PASSWORD.", host
            )
            return HttpResponseBadRequest("Host not allowed: add it to ALLOWED_HOSTS.")
        return self.get_response(request)


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not security.gui_auth_enabled():
            return self.get_response(request)

        path = request.path
        if path.startswith(security.EXEMPT_PREFIXES) or request.session.get(security.SESSION_KEY):
            return self.get_response(request)
        if path.startswith(security.BOT_TOKEN_PATHS) and security.bot_token_valid(request):
            return self.get_response(request)

        wants_json = path.startswith("/api/") or request.headers.get("X-Requested-With") == "XMLHttpRequest" \
            or "application/json" in request.headers.get("Accept", "")
        if wants_json:
            return JsonResponse({"success": False, "error": "Authentication required"}, status=401)
        query = urlencode({"next": request.get_full_path()}) if request.method == "GET" and path != "/" else ""
        return redirect(f"/login/?{query}" if query else "/login/")
