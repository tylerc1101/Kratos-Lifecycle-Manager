"""Runtime settings for the KLM Semaphore reconciler."""

import os
from dataclasses import dataclass

DEFAULT_SEMAPHORE_URL = "https://127.0.0.1:3000"
DEFAULT_BUNDLE_DIR = "/opt/openspace/bundles"
DEFAULT_ENVIRONMENT_DIR = "/opt/openspace/environments"
DEFAULT_ENVIRONMENT_SELECTION_FILE = "/opt/openspace/state/klm/environment.yml"
DEFAULT_STATE_FILE = "/opt/openspace/state/klm/ownership.json"
DEFAULT_TOKEN_FILE = "/opt/openspace/secrets/semaphore_api_token"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PROJECT_NAME = "KLM"


class SettingsError(Exception):
    pass


@dataclass
class Settings:
    base_url: str
    bundle_dir: str
    environment_dir: str
    environment_selection_file: str
    state_file: str
    project_name: str
    timeout_seconds: int
    dry_run: bool
    verify_tls: object
    api_token: str
    username: str
    password: str


def load_settings():
    base_url = os.environ.get("SEMAPHORE_URL", DEFAULT_SEMAPHORE_URL).rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise SettingsError("SEMAPHORE_URL must start with http:// or https://")

    bundle_dir = os.environ.get("KLM_BUNDLE_DIR", DEFAULT_BUNDLE_DIR)
    if not os.path.isdir(bundle_dir):
        raise SettingsError("Bundle directory does not exist: %s" % bundle_dir)

    environment_dir = os.environ.get("KLM_ENVIRONMENT_DIR", DEFAULT_ENVIRONMENT_DIR)
    if not os.path.isdir(environment_dir):
        raise SettingsError("Environment directory does not exist: %s" % environment_dir)

    project_name = os.environ.get("KLM_PROJECT_NAME", DEFAULT_PROJECT_NAME).strip()
    if not project_name:
        raise SettingsError("KLM_PROJECT_NAME must not be empty")

    token_file = os.environ.get("SEMAPHORE_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    api_token = os.environ.get("SEMAPHORE_API_TOKEN", "").strip()
    if os.path.isfile(token_file):
        with open(token_file, "r", encoding="utf-8") as handle:
            api_token = handle.read().strip()

    username = os.environ.get("SEMAPHORE_ADMIN", "admin")
    password = os.environ.get("SEMAPHORE_ADMIN_PASSWORD", "")

    if not api_token and not password:
        raise SettingsError(
            "No Semaphore API token or admin password is available. "
            "Set SEMAPHORE_API_TOKEN or SEMAPHORE_ADMIN_PASSWORD."
        )

    return Settings(
        base_url=base_url,
        bundle_dir=bundle_dir,
        environment_dir=environment_dir,
        environment_selection_file=os.environ.get(
            "KLM_ENVIRONMENT_SELECTION_FILE",
            DEFAULT_ENVIRONMENT_SELECTION_FILE,
        ),
        state_file=os.environ.get("KLM_STATE_FILE", DEFAULT_STATE_FILE),
        project_name=project_name,
        timeout_seconds=_int_env("SEMAPHORE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
        dry_run=_is_true(os.environ.get("KLM_DRY_RUN", "false")),
        verify_tls=_tls_setting(base_url),
        api_token=api_token,
        username=username,
        password=password,
    )


def _tls_setting(base_url):
    ca_bundle = os.environ.get("SEMAPHORE_CA_BUNDLE", "").strip()
    if ca_bundle:
        if not os.path.isfile(ca_bundle):
            raise SettingsError("SEMAPHORE_CA_BUNDLE does not exist: %s" % ca_bundle)
        return ca_bundle

    explicit = os.environ.get("SEMAPHORE_VERIFY_TLS", "").strip()
    if explicit:
        return _is_true(explicit)

    # KLM talks only to its own local Semaphore instance by default.
    # The self-signed certificate is persistent, but older installations may
    # have been created before the certificate contained loopback SANs.
    return not (
        base_url.startswith("https://127.0.0.1")
        or base_url.startswith("https://localhost")
    )


def _int_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise SettingsError("%s must be an integer" % name) from error
    if value <= 0:
        raise SettingsError("%s must be greater than zero" % name)
    return value


def _is_true(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")
