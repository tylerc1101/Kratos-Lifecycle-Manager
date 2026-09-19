"""Small Semaphore 2.19.12 REST API client using only the Python stdlib."""

import http.cookiejar
import json
import logging
import ssl
import urllib.error
import urllib.request

LOG = logging.getLogger(__name__)
DRY_RUN_ID = -1


class SemaphoreApiError(Exception):
    pass


class SemaphoreClient:
    def __init__(self, base_url, api_token="", username="", password="",
                 timeout_seconds=30, verify_tls=True, dry_run=False):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.dry_run = dry_run
        self.project_id = None
        self._lookup_cache = {}

        cookie_jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(cookie_jar)]
        if self.base_url.startswith("https://"):
            handlers.append(urllib.request.HTTPSHandler(context=self._ssl_context()))
        self.opener = urllib.request.build_opener(*handlers)

    def _ssl_context(self):
        if self.verify_tls is False:
            return ssl._create_unverified_context()
        context = ssl.create_default_context()
        if isinstance(self.verify_tls, str):
            context.load_verify_locations(cafile=self.verify_tls)
        return context

    def authenticate(self):
        if self.api_token:
            self.get_global("/api/user")
            return

        self.post_global(
            "/api/auth/login",
            {"auth": self.username, "password": self.password},
            honor_dry_run=False,
        )
        self.get_global("/api/user")

    def ping(self):
        return self.get_global("/api/ping")

    def set_project_id(self, project_id):
        self.project_id = project_id
        self.clear_lookup_cache()

    def _request(self, method, url, payload=None):
        data = None
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = "Bearer %s" % self.api_token
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                if not body:
                    return None
                text = body.decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
                if "json" in content_type:
                    try:
                        return json.loads(text)
                    except ValueError:
                        return text
                try:
                    return json.loads(text)
                except ValueError:
                    return text
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace").strip()
            if len(body) > 500:
                body = body[:500] + "..."
            raise SemaphoreApiError(
                "%s %s returned HTTP %d: %s"
                % (method, url, error.code, body or "(empty response body)")
            ) from error
        except urllib.error.URLError as error:
            raise SemaphoreApiError("%s %s failed: %s" % (method, url, error.reason)) from error

    def _global_url(self, path):
        return self.base_url + path

    def _project_url(self, path):
        if self.project_id is None:
            raise SemaphoreApiError("No Semaphore project has been selected")
        return "%s/api/project/%d%s" % (self.base_url, self.project_id, path)

    def get_global(self, path):
        return self._request("GET", self._global_url(path))

    def post_global(self, path, payload, honor_dry_run=True):
        if honor_dry_run and self.dry_run:
            LOG.info("[dry-run] POST %s", path)
            return {"id": DRY_RUN_ID}
        return self._request("POST", self._global_url(path), payload)

    def put_global(self, path, payload):
        if self.dry_run:
            LOG.info("[dry-run] PUT %s", path)
            return None
        return self._request("PUT", self._global_url(path), payload)

    def get(self, path):
        return self._request("GET", self._project_url(path))

    def post(self, path, payload):
        if self.dry_run:
            LOG.info("[dry-run] POST %s", path)
            return {"id": DRY_RUN_ID}
        return self._request("POST", self._project_url(path), payload)

    def put(self, path, payload):
        if self.dry_run:
            LOG.info("[dry-run] PUT %s", path)
            return None
        return self._request("PUT", self._project_url(path), payload)

    def delete(self, path):
        if self.dry_run:
            LOG.info("[dry-run] DELETE %s", path)
            return None
        return self._request("DELETE", self._project_url(path))

    # Project
    def list_projects(self):
        return self.get_global("/api/projects") or []

    def get_project(self, project_id):
        return self.get_global("/api/project/%d" % project_id)

    def create_project(self, payload):
        return self.post_global("/api/projects", payload)

    # Keys
    def list_keys(self):
        return self.get("/keys") or []

    def find_key(self, name):
        items = self._cached_list("/keys")
        matches = [item for item in items if item.get("name") == name]
        if len(matches) > 1:
            raise SemaphoreApiError(
                "More than one key store entry named '%s' exists" % name
            )
        if matches:
            return matches[0]
        available = ", ".join(
            sorted(str(item.get("name", "")) for item in items)
        ) or "(none)"
        raise SemaphoreApiError(
            "No key store entry named '%s' exists in project %d. Available: %s"
            % (name, self.project_id, available)
        )

    def find_key_id(self, name):
        return self.find_key(name)["id"]

    # Repositories
    def list_repositories(self):
        return self.get("/repositories") or []

    def create_repository(self, payload):
        return self.post("/repositories", payload)

    def update_repository(self, resource_id, payload):
        return self.put("/repositories/%d" % resource_id, payload)

    def delete_repository(self, resource_id):
        return self.delete("/repositories/%d" % resource_id)

    # Inventories
    def list_inventories(self):
        return self.get("/inventory") or []

    def create_inventory(self, payload):
        return self.post("/inventory", payload)

    def update_inventory(self, resource_id, payload):
        return self.put("/inventory/%d" % resource_id, payload)

    def delete_inventory(self, resource_id):
        return self.delete("/inventory/%d" % resource_id)

    # Views
    def list_views(self):
        return self.get("/views") or []

    def create_view(self, payload):
        return self.post("/views", payload)

    def update_view(self, resource_id, payload):
        return self.put("/views/%d" % resource_id, payload)

    def delete_view(self, resource_id):
        return self.delete("/views/%d" % resource_id)

    # Templates
    def list_templates(self):
        return self.get("/templates") or []

    def get_template(self, resource_id):
        return self.get("/templates/%d" % resource_id)

    def create_template(self, payload):
        return self.post("/templates", payload)

    def update_template(self, resource_id, payload):
        return self.put("/templates/%d" % resource_id, payload)

    def delete_template(self, resource_id):
        return self.delete("/templates/%d" % resource_id)

    # Workflows
    def list_workflows(self):
        return self.get("/workflows") or []

    def get_workflow(self, resource_id):
        return self.get("/workflows/%d" % resource_id)

    def create_workflow(self, payload):
        return self.post("/workflows", payload)

    def update_workflow(self, resource_id, payload):
        return self.put("/workflows/%d" % resource_id, payload)

    def delete_workflow(self, resource_id):
        return self.delete("/workflows/%d" % resource_id)

    # Optional pre-existing/operator-managed resources
    def find_environment_id(self, name):
        return self._find_id("/environment", "environment", name)

    def find_inventory_id(self, name):
        return self._find_id("/inventory", "inventory", name)

    def find_repository_id(self, name):
        return self._find_id("/repositories", "repository", name)

    def _find_id(self, path, label, name):
        items = self._cached_list(path)
        matches = [item for item in items if item.get("name") == name]
        if len(matches) > 1:
            raise SemaphoreApiError("More than one %s named '%s' exists" % (label, name))
        if matches:
            return matches[0]["id"]
        available = ", ".join(sorted(str(item.get("name", "")) for item in items)) or "(none)"
        raise SemaphoreApiError(
            "No %s named '%s' exists in project %d. Available: %s"
            % (label, name, self.project_id, available)
        )

    def _cached_list(self, path):
        if path not in self._lookup_cache:
            self._lookup_cache[path] = self.get(path) or []
        return self._lookup_cache[path]

    def clear_lookup_cache(self):
        self._lookup_cache = {}
