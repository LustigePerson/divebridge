"""Minimal client for the private MySSI app API.

Ported from agrippa1994/divessi-log-importer (MIT) and gerardpuig/divessi-export (MIT).
There is no official API: this talks to the same backend as the MySSI Android app and may
break without notice.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)
# httpx logs full URLs at INFO level; the SSI API carries password and token in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BASE_URL = "https://api.divessi.com"
RPC_ENDPOINT = "/app/a21.php"
DEFAULT_PARAMS = {
    "ssiapp": "0815_ADR",
    "lang": "en",
    "version": "ADR_4.1.268-ssi",
    "context": "s",
}
SITES_CACHE_URL = f"{BASE_URL}/app/APP_CACHE_SITES.zip"


class APIError(Exception):
    def __init__(self, message: str, payload: Any = None):
        super().__init__(message)
        self.payload = payload


class SsiClient:
    def __init__(self, email: str | None = None, password: str | None = None,
                 data_dir: Path | None = None, token: str | None = None, timeout: float = 60.0):
        self.email = email
        self.password = password
        self.data_dir = data_dir
        self._token = token
        self._http = httpx.Client(base_url=BASE_URL, params=DEFAULT_PARAMS, timeout=timeout)
        if self._token is None and data_dir is not None:
            self._token = self._load_cached_token()

    # -- token handling ------------------------------------------------------
    @property
    def token_file(self) -> Path | None:
        return self.data_dir / "ssi_token.json" if self.data_dir else None

    def _load_cached_token(self) -> str | None:
        f = self.token_file
        if f and f.exists():
            try:
                d = json.loads(f.read_text())
                if d.get("email") == self.email:
                    return d.get("token")
            except (OSError, ValueError):
                pass
        return None

    def _store_token(self, token: str) -> None:
        f = self.token_file
        if f:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"email": self.email, "token": token}))

    def forget_token(self) -> None:
        self._token = None
        f = self.token_file
        if f and f.exists():
            f.unlink()

    @property
    def has_token(self) -> bool:
        return self._token is not None

    # -- low level -----------------------------------------------------------
    def _get(self, what: str, **params: str) -> Any:
        r = self._http.get(RPC_ENDPOINT, params={"what": what, **params})
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise APIError(f"{what}: non-JSON response: {r.text[:200]}") from e
        if isinstance(data, dict) and data.get("authenticated") is False:
            raise APIError(data.get("error_message") or data.get("authenticated_message") or f"{what}: not authenticated", data)
        return data

    def _post(self, what: str, body: dict[str, Any], **params: str) -> Any:
        encoded = {"json_data": json.dumps(body, separators=(",", ":"))}
        r = self._http.post(RPC_ENDPOINT, params={"what": what, **params}, data=encoded)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if isinstance(data, dict) and data.get("authenticated") is False:
            raise APIError(data.get("error_message") or f"{what}: not authenticated", data)
        return data

    # -- public --------------------------------------------------------------
    def authenticate(self) -> str:
        if not self.email or not self.password:
            raise APIError("SSI e-mail/password not configured")
        data = self._get("authenticate", l=self.email, p=self.password)
        if not data.get("authenticated") or not data.get("token"):
            raise APIError(data.get("error_message") or "login failed", data)
        self._token = data["token"]
        self._store_token(self._token)
        log.info("SSI login ok for %s (mid=%s)", data.get("authenticated_email"), data.get("mid"))
        return self._token

    def _with_token(self, fn):
        if self._token is None:
            self.authenticate()
        try:
            return fn(self._token)
        except APIError:
            # token expired? retry once with fresh login
            if self.email and self.password:
                self.authenticate()
                return fn(self._token)
            raise

    def get_divelog(self) -> dict[str, Any]:
        return self._with_token(lambda t: self._get("get_divelog", token=t))

    def get_user_data(self) -> dict[str, Any]:
        return self._with_token(lambda t: self._get("get_user_data", token=t))

    def get_divelog_vars(self) -> dict[str, Any]:
        """Variable definitions (weather, water type, entry, ... id -> name)."""
        return self._with_token(lambda t: self._get("get_divelog_vars", token=t))

    def save_divelog(self, payload: dict[str, Any]) -> Any:
        return self._with_token(lambda t: self._post("save_divelog", payload, token=t))

    def download_sites_zip(self) -> bytes:
        r = self._http.get(SITES_CACHE_URL)
        r.raise_for_status()
        return r.content

    def close(self) -> None:
        self._http.close()
