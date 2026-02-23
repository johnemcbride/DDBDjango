"""
management command: setup_cognito
==================================
Wires up django-allauth's Amazon Cognito provider.

Modes
-----
1. **Real Cognito / LocalStack Pro**
   Detects `COGNITO_IDP_ENDPOINT` env var (or falls back to DYNAMO_ENDPOINT_URL
   for the cognito-idp calls).  Creates a User Pool, App Client, domain, and
   seeds a demo user, then creates the Django SocialApp.

2. **Local dev mock (default)**
   If the cognito-idp API is not available (e.g. LocalStack Community), falls
   back to the built-in Django Cognito mock at /cognito-mock/.
   Creates fake-but-valid SocialApp credentials so allauth can redirect to the
   local mock server.  No boto3 calls are required for the mock path.

Run once (idempotent):
    DYNAMO_ENDPOINT_URL=http://localhost:4566 python manage.py setup_cognito

To force real Cognito (LocalStack Pro / AWS):
    COGNITO_IDP_ENDPOINT=http://localhost:4566 python manage.py setup_cognito
"""

import os
import uuid

import boto3
from botocore.exceptions import ClientError
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

POOL_NAME      = "ddbdjango"
CLIENT_NAME    = "ddbdjango-client"
DOMAIN_PREFIX  = "ddbdjango"
DEMO_EMAIL     = "demo@ddblog.local"
DEMO_PASSWORD  = "Demo1234!"
CALLBACK_URL   = "http://localhost:8000/accounts/amazon-cognito/login/callback/"
LOGOUT_URL     = "http://localhost:8000/"
MOCK_DOMAIN    = "http://localhost:8000/cognito-mock"


class Command(BaseCommand):
    help = "Provision Cognito (or local mock) and wire up allauth for the demo site"

    # ── boto3 ─────────────────────────────────────────────────────────────────

    def _cognito_client(self):
        endpoint = os.environ.get(
            "COGNITO_IDP_ENDPOINT",
            os.environ.get("DYNAMO_ENDPOINT_URL", "http://localhost:4566"),
        )
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        return boto3.client(
            "cognito-idp",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _cognito_available(self, client) -> bool:
        """Check if the cognito-idp API is reachable."""
        try:
            client.list_user_pools(MaxResults=1)
            return True
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("InternalFailure", "NotImplementedError"):
                return False
            raise
        except Exception:
            return False

    # ── Cognito provisioning helpers ──────────────────────────────────────────

    def _get_or_create_pool(self, client):
        resp = client.list_user_pools(MaxResults=60)
        for pool in resp.get("UserPools", []):
            if pool["Name"] == POOL_NAME:
                self.stdout.write(f"  ✓ User Pool exists: {pool['Id']}")
                return pool["Id"], False
        resp = client.create_user_pool(
            PoolName=POOL_NAME,
            AutoVerifiedAttributes=["email"],
            UsernameAttributes=["email"],
            Policies={"PasswordPolicy": {"MinimumLength": 8, "RequireUppercase": True,
                       "RequireLowercase": True, "RequireNumbers": True, "RequireSymbols": False}},
        )
        pool_id = resp["UserPool"]["Id"]
        self.stdout.write(self.style.SUCCESS(f"  ✓ Created User Pool: {pool_id}"))
        return pool_id, True

    def _get_or_create_app_client(self, client, pool_id):
        resp = client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)
        for c in resp.get("UserPoolClients", []):
            if c["ClientName"] == CLIENT_NAME:
                detail = client.describe_user_pool_client(
                    UserPoolId=pool_id, ClientId=c["ClientId"]
                )["UserPoolClient"]
                self.stdout.write(f"  ✓ App Client exists: {c['ClientId']}")
                return c["ClientId"], detail.get("ClientSecret", ""), False
        resp = client.create_user_pool_client(
            UserPoolId=pool_id, ClientName=CLIENT_NAME, GenerateSecret=True,
            AllowedOAuthFlows=["code"], AllowedOAuthScopes=["openid", "email", "profile"],
            AllowedOAuthFlowsUserPoolClient=True,
            CallbackURLs=[CALLBACK_URL], LogoutURLs=[LOGOUT_URL],
            SupportedIdentityProviders=["COGNITO"],
            ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )
        uc = resp["UserPoolClient"]
        self.stdout.write(self.style.SUCCESS(f"  ✓ Created App Client: {uc['ClientId']}"))
        return uc["ClientId"], uc.get("ClientSecret", ""), True

    def _ensure_domain(self, client, pool_id):
        try:
            detail = client.describe_user_pool(UserPoolId=pool_id)["UserPool"]
            if detail.get("Domain"):
                self.stdout.write(f"  ✓ Domain already set: {detail['Domain']}")
                return
        except ClientError:
            pass
        try:
            client.create_user_pool_domain(Domain=DOMAIN_PREFIX, UserPoolId=pool_id)
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created domain: {DOMAIN_PREFIX}"))
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("InvalidParameterException", "AliasExistsException"):
                self.stdout.write(f"  ✓ Domain already registered ({code})")
            else:
                raise

    def _create_demo_user_cognito(self, client, pool_id):
        try:
            client.admin_create_user(
                UserPoolId=pool_id, Username=DEMO_EMAIL,
                TemporaryPassword=DEMO_PASSWORD, MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": DEMO_EMAIL},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
            client.admin_set_user_password(
                UserPoolId=pool_id, Username=DEMO_EMAIL, Password=DEMO_PASSWORD, Permanent=True
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ Cognito demo user: {DEMO_EMAIL}"))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UsernameExistsException":
                self.stdout.write(f"  ✓ Cognito demo user exists: {DEMO_EMAIL}")
            else:
                raise

    # ── Django helpers ────────────────────────────────────────────────────────

    def _configure_site(self):
        site, created = Site.objects.get_or_create(
            pk=1,
            defaults={"domain": "localhost:8000", "name": "DDBlog (local)"},
        )
        if not created and site.domain != "localhost:8000":
            site.domain = "localhost:8000"
            site.name = "DDBlog (local)"
            site.save()
        self.stdout.write(self.style.SUCCESS(f"  ✓ Site: {site.domain}"))

    def _configure_social_app(self, client_id: str, client_secret: str, domain: str):
        from allauth.socialaccount.models import SocialApp
        app, created = SocialApp.objects.get_or_create(
            provider="amazon_cognito",
            defaults={"name": "Amazon Cognito (LocalStack)", "client_id": client_id,
                      "secret": client_secret, "key": ""},
        )
        if not created:
            app.name = "Amazon Cognito (LocalStack)"
            app.client_id = client_id
            app.secret = client_secret
            app.save()
        site = Site.objects.get(pk=1)
        app.sites.add(site)
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"  ✓ {action} SocialApp (client_id={client_id})"))

    def _create_django_demo_user(self):
        """Create a local Django demo user + allauth SocialAccount for the mock path."""
        from django.contrib.auth import get_user_model
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount
        User = get_user_model()
        try:
            user, created = User.objects.get_or_create(
                email=DEMO_EMAIL,
                defaults={
                    "username": "demo",
                    "first_name": "Demo",
                    "last_name": "User",
                    "is_active": True,
                },
            )
            if created or not user.has_usable_password():
                user.set_password(DEMO_PASSWORD)
                user.save()
            action = "Created" if created else "Exists"
            self.stdout.write(self.style.SUCCESS(f"  ✓ {action} Django demo user: {DEMO_EMAIL}"))

            # Ensure allauth EmailAddress record exists (avoids signup prompt)
            EmailAddress.objects.get_or_create(
                user=user,
                email=DEMO_EMAIL,
                defaults={"primary": True, "verified": True},
            )

            # Pre-create SocialAccount linking demo user to amazon_cognito provider.
            # uid must match the 'sub' returned by cognito_mock_views (str(user.pk)).
            uid = str(user.pk)
            SocialAccount.objects.get_or_create(
                user=user,
                provider="amazon_cognito",
                defaults={
                    "uid": uid,
                    "extra_data": {
                        "sub": uid,
                        "email": DEMO_EMAIL,
                        "email_verified": True,
                        "given_name": "Demo",
                        "family_name": "User",
                        "preferred_username": "demo",
                    },
                },
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ SocialAccount wired (uid={uid})"))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  ⚠ Demo user: {exc}"))

    # ── main ──────────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO("\n=== Cognito / Mock Setup ===\n"))

        client = self._cognito_client()
        use_real = self._cognito_available(client)

        if use_real:
            self.stdout.write(self.style.SUCCESS("Mode: Real Cognito (LocalStack Pro / AWS)\n"))

            self.stdout.write("[ 1 ] User Pool")
            pool_id, _ = self._get_or_create_pool(client)

            self.stdout.write("[ 2 ] App Client")
            client_id, client_secret, _ = self._get_or_create_app_client(client, pool_id)

            self.stdout.write("[ 3 ] Domain")
            self._ensure_domain(client, pool_id)

            self.stdout.write("[ 4 ] Cognito demo user")
            self._create_demo_user_cognito(client, pool_id)

            cognito_domain = os.environ.get("COGNITO_DOMAIN", f"http://localhost:4566")
        else:
            self.stdout.write(self.style.WARNING(
                "cognito-idp not available (LocalStack Community).\n"
                "Falling back to the built-in Django Cognito mock at /cognito-mock/\n"
            ))
            # Use deterministic fake credentials for the mock
            client_id     = os.environ.get("COGNITO_CLIENT_ID",     "local-mock-client-id")
            client_secret = os.environ.get("COGNITO_CLIENT_SECRET",  str(uuid.uuid4()))
            cognito_domain = MOCK_DOMAIN

            self.stdout.write("[ 4 ] Django demo user (for mock login)")
            self._create_django_demo_user()

        self.stdout.write("[ 5 ] Django Site")
        self._configure_site()

        self.stdout.write("[ 6 ] allauth SocialApp")
        self._configure_social_app(client_id, client_secret, cognito_domain)

        self.stdout.write(self.style.SUCCESS(
            f"\n✅  Done!\n"
            f"\n   Cognito domain : {cognito_domain}"
            f"\n   Client ID      : {client_id}"
            f"\n   Callback URL   : {CALLBACK_URL}"
            f"\n   Demo user      : {DEMO_EMAIL}  /  {DEMO_PASSWORD}"
            f"\n\nVisit http://localhost:8000/ and click 'Sign in with Amazon Cognito'.\n"
        ))

