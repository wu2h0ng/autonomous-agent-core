# Batch-B dry-run verifier image for django/django (ADR-0056 decision 2).
#
# The container runs `python -m pytest <node-id>...` with the task checkout
# bind-mounted at /work (rw); the site-packages django copy installed here is
# shadowed by /work at runtime (sys.path[0] == cwd). Deps therefore only need
# to satisfy the runtime checkout, which spans django 3.2a..4.0a.
FROM python:3.9-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Repo clone at the FIRST candidate's environment_setup_commit (django 3.2a),
# pip-installed to materialize the project's declared runtime deps.
RUN git clone --filter=blob:none https://github.com/django/django.git /repo \
    && git -C /repo checkout -q 65dfb06a1ab56c238cc80f5e1c31f61210c4577d \
    && pip install --no-cache-dir /repo \
    && rm -rf /repo/.git

# Pinned verifier + dep set (pip install /repo above pulls latest-compatible;
# force exact pins afterwards so the environment is reproducible).
RUN pip install --no-cache-dir \
    asgiref==3.7.2 \
    sqlparse==0.4.4 \
    pytz==2024.1 \
    pytest==7.4.4 \
    pytest-django==4.5.2

# Django test-suite bootstrap, image-side because `git clean -fdx` in the
# executor's restore step wipes any untracked conftest.py from /work.
# Replicates tests/runtests.py setup(): test_sqlite settings +
# ALWAYS_INSTALLED_APPS + the test packages named by the pytest argv
# (runtests.get_apps_to_install), then django.setup(). pytest-django (which
# reads DJANGO_SETTINGS_MODULE) handles test-database creation for
# django.test.TestCase classes. Inert unless a django checkout is at /work.
RUN printf '%s\n' \
    'import os' \
    'import sys' \
    '' \
    'if os.path.isdir("/work/tests") and os.path.isfile("/work/django/__init__.py"):' \
    '    for _p in ("/work", "/work/tests"):' \
    '        if _p not in sys.path:' \
    '            sys.path.insert(0, _p)' \
    '    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_sqlite")' \
    '    os.environ["RUNNING_DJANGOS_TEST_SUITE"] = "true"' \
    '    from django.conf import settings' \
    '    settings.INSTALLED_APPS = [' \
    '        "django.contrib.contenttypes",' \
    '        "django.contrib.auth",' \
    '        "django.contrib.sites",' \
    '        "django.contrib.sessions",' \
    '        "django.contrib.messages",' \
    '        "django.contrib.admin.apps.SimpleAdminConfig",' \
    '        "django.contrib.staticfiles",' \
    '    ]' \
    '    for _arg in sys.argv[1:]:' \
    '        if _arg.startswith("tests/") and "::" in _arg:' \
    '            _pkg = _arg.split("/")[1]' \
    '            if _pkg.isidentifier() and _pkg not in settings.INSTALLED_APPS:' \
    '                settings.INSTALLED_APPS.append(_pkg)' \
    '    settings.ROOT_URLCONF = "urls"' \
    '    settings.STATIC_URL = "/static/"' \
    '    settings.STATIC_ROOT = "/tmp/static"' \
    '    settings.TEMPLATES = [{' \
    '        "BACKEND": "django.template.backends.django.DjangoTemplates",' \
    '        "DIRS": ["/work/tests/templates"],' \
    '        "APP_DIRS": True,' \
    '        "OPTIONS": {' \
    '            "context_processors": [' \
    '                "django.template.context_processors.debug",' \
    '                "django.template.context_processors.request",' \
    '                "django.contrib.auth.context_processors.auth",' \
    '                "django.contrib.messages.context_processors.messages",' \
    '            ],' \
    '        },' \
    '    }]' \
    '    settings.LANGUAGE_CODE = "en"' \
    '    settings.SITE_ID = 1' \
    '    settings.MIDDLEWARE = [' \
    '        "django.contrib.sessions.middleware.SessionMiddleware",' \
    '        "django.middleware.common.CommonMiddleware",' \
    '        "django.middleware.csrf.CsrfViewMiddleware",' \
    '        "django.contrib.auth.middleware.AuthenticationMiddleware",' \
    '        "django.contrib.messages.middleware.MessageMiddleware",' \
    '    ]' \
    '    settings.MIGRATION_MODULES = {' \
    '        "auth": None,' \
    '        "contenttypes": None,' \
    '        "sessions": None,' \
    '    }' \
    '    settings.SILENCED_SYSTEM_CHECKS = ["fields.W342", "fields.W903"]' \
    '    import django' \
    '    django.setup()' \
    > /usr/local/lib/python3.9/site-packages/sitecustomize.py

ENV DJANGO_SETTINGS_MODULE=test_sqlite
