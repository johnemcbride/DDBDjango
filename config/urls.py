from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from demo_app import views as demo_views
from demo_app.cognito_mock_views import (
    CognitoMockAuthorizeView,
    cognito_mock_token,
    cognito_mock_userinfo,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("demo_app.urls")),
    path("explorer/", demo_views.ExplorerView.as_view(), name="explorer"),
    # django-allauth: handles /accounts/login/, /accounts/logout/,
    # /accounts/amazon-cognito/login/, /accounts/amazon-cognito/login/callback/
    path("accounts/", include("allauth.urls")),
    # ── Local Cognito OAuth2 mock (dev only) ───────────────────────────────
    # allauth's amazon_cognito adapter redirects to COGNITO_DOMAIN/oauth2/...
    # In local dev we set COGNITO_DOMAIN=http://localhost:8000/cognito-mock
    # so these views handle the full OAuth2 code flow without LocalStack Pro.
    path("cognito-mock/oauth2/authorize", CognitoMockAuthorizeView.as_view(), name="cognito_mock_authorize"),
    path("cognito-mock/oauth2/token",     cognito_mock_token,                  name="cognito_mock_token"),
    path("cognito-mock/oauth2/userInfo",  cognito_mock_userinfo,               name="cognito_mock_userinfo"),
    path("", include("demo_app.frontend_urls")),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path("__debug__/", include(debug_toolbar.urls)),
    ]
