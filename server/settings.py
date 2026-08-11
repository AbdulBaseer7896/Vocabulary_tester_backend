import os
import warnings
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name):
    """Comma-separated environment variable → list of trimmed values."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# Render sets this for every service, so it doubles as "am I in production?".
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
ON_RENDER = bool(RENDER_HOST)

# Locally this falls back to a throwaway key. In production the deploy fails
# loudly rather than quietly shipping a public, well-known secret.
SECRET_KEY = os.environ.get("SECRET_KEY") or ("dev-only-key-change-me" if not ON_RENDER else "")
if ON_RENDER and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set as an environment variable in production.")

# Debug defaults off in production and on locally; DEBUG=true can override.
DEBUG = os.environ.get("DEBUG", "false" if ON_RENDER else "true").lower() == "true"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", *env_list("ALLOWED_HOSTS")]
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "vocab",
]

MIDDLEWARE = [
    "vocab.middleware.SimpleCorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves the admin's CSS itself, so no separate web server is needed.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "server.wsgi.application"

# Postgres when DATABASE_URL is set, otherwise the local SQLite file.
# Render's disk is wiped on every deploy, so SQLite there loses all data.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

if ON_RENDER and not os.environ.get("DATABASE_URL"):
    # Render's filesystem is rebuilt on every deploy and restart, so a SQLite
    # file there is not storage — it is a cache that empties without warning.
    warnings.warn(
        "No DATABASE_URL is set. This service is using SQLite on an ephemeral "
        "disk: every deploy and restart will erase all decks, runs, and marks. "
        "Attach a Postgres database and set DATABASE_URL.",
        RuntimeWarning,
        stacklevel=2,
    )

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Browser origins allowed to call the API: the Vite dev server, plus whatever
# FRONTEND_ORIGINS lists (the deployed frontend).
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    *env_list("FRONTEND_ORIGINS"),
]

CSRF_TRUSTED_ORIGINS = [origin for origin in CORS_ALLOWED_ORIGINS if origin.startswith("https://")]
if RENDER_HOST:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")

if ON_RENDER:
    # Render terminates TLS in front of the app, so trust its protocol header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
