"""
cognito_mock_views.py
=====================
A minimal local OAuth2 / OpenID-Connect server that speaks the same protocol
as Amazon Cognito's hosted-UI endpoints:

  GET  /cognito-mock/oauth2/authorize      – shows a login form
  POST /cognito-mock/oauth2/authorize      – validates credentials, redirects
  POST /cognito-mock/oauth2/token          – exchanges auth-code for tokens
  GET  /cognito-mock/oauth2/userInfo       – returns user-info JSON

Purpose
-------
Local development only.  Satisfies django-allauth's amazon_cognito OAuth2
adapter so you get full SSO-style login without LocalStack Pro or a real AWS
account.  Set COGNITO_DOMAIN=http://localhost:8000/cognito-mock in the
environment (or in settings.SOCIALACCOUNT_PROVIDERS) and it "just works".

When deploying to a real environment, replace COGNITO_DOMAIN with your actual
Cognito User Pool domain and the mock views are never called.

Security
--------
• Uses cryptographically random auth codes (uuid4) stored in Django's cache.
• Issues opaque bearer tokens (uuid4) stored in the same cache.
• Works fine with Django's LocMemCache (default in dev) or Redis/Memcached.
• NEVER use this in production – it skips real Cognito validation entirely.
"""

import json
import uuid
from urllib.parse import urlencode, urlparse, urlunparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

User = get_user_model()

# Cache TTL for auth codes / tokens (10 minutes is plenty)
_TTL = 600
_CODE_PREFIX  = "cognito_mock_code:"
_TOKEN_PREFIX = "cognito_mock_token:"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_code(user_pk: str, redirect_uri: str, state: str) -> str:
    code = str(uuid.uuid4())
    cache.set(_CODE_PREFIX + code, {"user_pk": user_pk, "redirect_uri": redirect_uri, "state": state}, _TTL)
    return code


def _make_token(user_pk: str) -> dict:
    access = str(uuid.uuid4())
    id_tok = str(uuid.uuid4())
    cache.set(_TOKEN_PREFIX + access, {"user_pk": user_pk, "kind": "access"}, _TTL)
    cache.set(_TOKEN_PREFIX + id_tok,  {"user_pk": user_pk, "kind": "id"},     _TTL)
    return {
        "access_token": access,
        "id_token": id_tok,
        "token_type": "Bearer",
        "expires_in": _TTL,
    }


def _user_info(user) -> dict:
    return {
        "sub": str(user.pk),
        "email": user.email,
        "email_verified": True,
        "given_name": user.first_name or "",
        "family_name": user.last_name or "",
        "preferred_username": user.username,
    }


# ─── Login / Authorize ────────────────────────────────────────────────────────

_LOGIN_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Local Cognito Mock — Sign In</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <style>body{{background:#f6f7fb}}
  .card{{border-radius:14px;border:none;box-shadow:0 4px 24px rgba(0,0,0,.08)}}</style>
</head>
<body class="d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card p-4" style="width:360px">
  <div class="text-center mb-3">
    <span style="font-size:2rem">☁️</span>
    <h5 class="fw-bold mt-1">Local Cognito Mock</h5>
    <p class="text-muted small mb-0">Development only – no real auth</p>
  </div>
  {error}
  <form method="POST">
    <input type="hidden" name="client_id"     value="{client_id}"/>
    <input type="hidden" name="redirect_uri"  value="{redirect_uri}"/>
    <input type="hidden" name="response_type" value="code"/>
    <input type="hidden" name="state"         value="{state}"/>
    <input type="hidden" name="scope"         value="{scope}"/>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Email</label>
      <input type="email" name="email" class="form-control" required
             value="{email}" placeholder="demo@ddblog.local"/>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold small">Password</label>
      <input type="password" name="password" class="form-control" required
             placeholder="Demo1234!"/>
    </div>
    <p class="text-muted" style="font-size:.75rem">
      Create an account via <strong>/accounts/signup/</strong> first if needed.<br/>
      Default demo user: <code>demo@ddblog.local</code> / <code>Demo1234!</code>
    </p>
    <button type="submit" class="btn btn-primary w-100">Sign in with Cognito Mock</button>
  </form>
</div>
</body>
</html>"""


class CognitoMockAuthorizeView(View):
    """GET → show login form. POST → validate, redirect with code."""

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        context = {
            "client_id":     request.GET.get("client_id", ""),
            "redirect_uri":  request.GET.get("redirect_uri", "/"),
            "state":         request.GET.get("state", ""),
            "scope":         request.GET.get("scope", "openid email profile"),
            "email":         "",
            "error":         "",
        }
        return HttpResponse(_LOGIN_HTML.format(**context))

    def post(self, request):
        email        = request.POST.get("email", "").strip().lower()
        password     = request.POST.get("password", "")
        redirect_uri = request.POST.get("redirect_uri", "/")
        state        = request.POST.get("state", "")
        client_id    = request.POST.get("client_id", "")
        scope        = request.POST.get("scope", "openid email profile")

        def _bad(msg):
            context = {
                "client_id": client_id, "redirect_uri": redirect_uri,
                "state": state, "scope": scope, "email": email,
                "error": f'<div class="alert alert-danger small">{msg}</div>',
            }
            return HttpResponse(_LOGIN_HTML.format(**context), status=400)

        if not email or not password:
            return _bad("Email and password are required.")

        # Try to find a matching user (Django auth.User ot custom user)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return _bad("No account found with that email.")
        except Exception:
            return _bad("User lookup failed.")

        if not user.check_password(password):
            return _bad("Incorrect password.")

        if not user.is_active:
            return _bad("Account is inactive.")

        code = _make_code(str(user.pk), redirect_uri, state)

        # Redirect back to the allauth callback URL with ?code=...&state=...
        parsed = list(urlparse(redirect_uri))
        query = urlencode({"code": code, "state": state})
        parsed[4] = query
        return redirect(urlunparse(parsed))


# ─── Token exchange ───────────────────────────────────────────────────────────

@csrf_exempt
def cognito_mock_token(request):
    """POST with grant_type=authorization_code → returns token JSON."""
    if request.method != "POST":
        return HttpResponse(status=405)

    code         = request.POST.get("code", "")
    grant_type   = request.POST.get("grant_type", "")
    redirect_uri = request.POST.get("redirect_uri", "")

    # Also handle JSON body (some clients send application/json)
    if not code and request.content_type == "application/json":
        try:
            body = json.loads(request.body)
            code = body.get("code", "")
            grant_type = body.get("grant_type", grant_type)
        except Exception:
            pass

    if grant_type not in ("authorization_code", "refresh_token"):
        return JsonResponse({"error": "unsupported_grant_type"}, status=400)

    if grant_type == "authorization_code":
        cached = cache.get(_CODE_PREFIX + code)
        if not cached:
            return JsonResponse({"error": "invalid_grant", "error_description": "Code expired or invalid"}, status=400)
        cache.delete(_CODE_PREFIX + code)  # single-use
        tokens = _make_token(cached["user_pk"])
        return JsonResponse(tokens)

    # refresh_token — not fully implemented; just return an error
    return JsonResponse({"error": "invalid_grant"}, status=400)


# ─── UserInfo endpoint ────────────────────────────────────────────────────────

@csrf_exempt
def cognito_mock_userinfo(request):
    """GET with Authorization: Bearer <token> → returns user-info JSON."""
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("Bearer "):
        return JsonResponse({"error": "invalid_token"}, status=401)

    token = auth[7:]
    cached = cache.get(_TOKEN_PREFIX + token)
    if not cached:
        return JsonResponse({"error": "invalid_token", "error_description": "Token expired"}, status=401)

    try:
        user = User.objects.get(pk=cached["user_pk"])
    except User.DoesNotExist:
        return JsonResponse({"error": "invalid_token"}, status=401)

    return JsonResponse(_user_info(user))
