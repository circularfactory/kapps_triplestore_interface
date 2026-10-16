"""How an adapter authenticates its requests: the auth providers.

A caller builds a provider and passes it to `connect()`. Only the adapter calls a provider's
methods, so they are private. A provider holds the secret, and never shows it in its `repr`.
"""

from __future__ import annotations

import threading
import time
from base64 import b64encode
from typing import TYPE_CHECKING, Optional, Protocol

from kapps_triplestore_interface import _environment

if TYPE_CHECKING:
    from kapps_triplestore_interface.graph_db import GraphDB

# A GDB token is renewed when it is this old. GraphDB's default validity of a token is 30 days,
# and the validity of a server's tokens is not part of the token. A server with a shorter
# validity, or one that restarted and so signs with a new key, answers 401, and the provider
# then logs in again once.
_RENEW_AFTER = 29 * 24 * 60 * 60


def _now() -> float:
    return time.monotonic()


class _TripleStoreAuth(Protocol):  # pylint: disable=too-few-public-methods
    """An auth provider, as the adapter uses it: the type that both providers satisfy.

    It is private for now. The public signatures name the two providers,
    `BasicAuth | GDBTokenAuth`, and a caller that needs a type names them too.

    The adapter asks the provider for the `Authorization` header of each request. A provider
    with a token logs in on first use, and again before its token expires. After a 401, the
    adapter asks it once to renew; a provider that renews returns a new header, and the adapter
    sends the request once more with it.
    """

    def _authorization(self, store: "GraphDB") -> Optional[str]:
        """The `Authorization` header of the next request. Logs in when it must."""

    def _renew(self, store: "GraphDB", refused: Optional[str]) -> Optional[str]:
        """A new header after a 401, or `None` if the provider has nothing to renew.

        `refused` is the header that the store answered with 401.
        """


class BasicAuth:
    """HTTP Basic authentication: the user name and the password in every request.

    It never logs in and has nothing to renew, so a 401 raises at once.

    Args:
        username (str): The user name.
        password (str): The password.
    """

    def __init__(self, username: str, password: str):
        self._username = username
        self._header = "Basic " + b64encode(f"{username}:{password}".encode()).decode()

    @classmethod
    def from_env(cls) -> BasicAuth:
        """The provider for the identity that the environment names.

        Reads `TRIPLESTORE_USERNAME` and `TRIPLESTORE_PASSWORD`. `GRAPHDB_USERNAME` and
        `GRAPHDB_PASSWORD` are their deprecated fallbacks: a value read from one of them emits
        a `DeprecationWarning`.

        Raises:
            ValueError: If a variable is missing. The message names it.
        """
        return cls(
            _environment.read("TRIPLESTORE_USERNAME"),
            _environment.read("TRIPLESTORE_PASSWORD"),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(username={self._username!r})"

    # The adapter calls these as it calls any provider's; Basic authentication needs neither
    # the store nor the refused header.
    # pylint: disable=unused-argument

    def _authorization(self, store: "GraphDB") -> Optional[str]:
        return self._header

    def _renew(self, store: "GraphDB", refused: Optional[str]) -> Optional[str]:
        return None

    # pylint: enable=unused-argument


class GDBTokenAuth:
    """GraphDB's GDB token: one login with the user name and the password, then the token.

    The provider logs in on first use. It logs in again when its token is 29 days old, before
    GraphDB's default validity of 30 days ends, and once after the store answers 401 to its
    token. One provider serves the stores of one server, from several threads.

    Args:
        username (str): The user name.
        password (str): The password.
    """

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        self._obtained_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> GDBTokenAuth:
        """The provider for the identity that the environment names.

        Reads `TRIPLESTORE_USERNAME` and `TRIPLESTORE_PASSWORD`. `GRAPHDB_USERNAME` and
        `GRAPHDB_PASSWORD` are their deprecated fallbacks: a value read from one of them emits
        a `DeprecationWarning`.

        Raises:
            ValueError: If a variable is missing. The message names it.
        """
        return cls(
            _environment.read("TRIPLESTORE_USERNAME"),
            _environment.read("TRIPLESTORE_PASSWORD"),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(username={self._username!r})"

    def _authorization(self, store: "GraphDB") -> Optional[str]:
        with self._lock:
            if self._token is None or _now() - self._obtained_at >= _RENEW_AFTER:
                self._log_in(store)
            return self._token

    def _renew(self, store: "GraphDB", refused: Optional[str]) -> Optional[str]:
        with self._lock:
            # Another thread may have renewed the token since the refused request left.
            if self._token is None or self._token == refused:
                self._log_in(store)
            return self._token

    def _log_in(self, store: "GraphDB") -> None:
        self._token = store._get_authentication_token(self._username, self._password)
        self._obtained_at = _now()
