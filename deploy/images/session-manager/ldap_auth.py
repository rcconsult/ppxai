"""LDAP/Active Directory authentication with in-memory caching.

Adapted from sophia-trino-service/ldap_auth.py for the session manager.
Supports stub mode (accept any username, no password) and ldap mode
(validate against Active Directory).
"""

import hashlib
import logging
import os
import time

import ldap3

log = logging.getLogger("ldap-auth")


class LDAPAuthenticator:
    """Authenticate users against Active Directory via LDAP simple bind."""

    def __init__(self) -> None:
        self._url = os.environ["LDAP_URL"]
        self._use_ssl = self._url.startswith("ldaps://")
        self._base_dn = os.environ["LDAP_BASE_DN"]
        self._bind_dn = os.environ["LDAP_BIND_DN"]
        self._bind_password = os.environ["LDAP_BIND_PASSWORD"]
        self._user_filter = os.getenv("LDAP_USER_FILTER", "(objectClass=person)")
        self._username_attr = os.getenv("LDAP_USERNAME_ATTR", "sAMAccountName")
        self._cache_ttl = int(os.getenv("LDAP_CACHE_TTL", "300"))

        # Cache: {username: (password_sha256, expiry_timestamp)}
        self._cache: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def _check_cache(self, username: str, password: str) -> bool | None:
        """Return True/False from cache, or None on miss/expired."""
        entry = self._cache.get(username)
        if entry is None:
            return None
        pw_hash, expiry = entry
        if time.monotonic() > expiry:
            del self._cache[username]
            return None
        return pw_hash == self._hash_password(password)

    def _update_cache(self, username: str, password: str) -> None:
        self._cache[username] = (
            self._hash_password(password),
            time.monotonic() + self._cache_ttl,
        )

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate a user against AD. Returns True on success."""
        cached = self._check_cache(username, password)
        if cached is not None:
            return cached

        try:
            # Step 1: bind as service account
            server = ldap3.Server(self._url, use_ssl=self._use_ssl, get_info=ldap3.NONE)
            svc_conn = ldap3.Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                authentication=ldap3.SIMPLE,
                raise_exceptions=True,
            )
            svc_conn.bind()

            # Step 2: search for user
            search_filter = (
                f"(&({self._username_attr}={ldap3.utils.conv.escape_filter_chars(username)})"
                f"{self._user_filter})"
            )
            svc_conn.search(
                search_base=self._base_dn,
                search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=[],
            )

            if not svc_conn.entries:
                svc_conn.unbind()
                log.warning(f"User {username!r} not found in AD")
                return False

            user_dn = str(svc_conn.entries[0].entry_dn)
            svc_conn.unbind()

            # Step 3: rebind as the user to verify password
            user_conn = ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                authentication=ldap3.SIMPLE,
                raise_exceptions=True,
            )
            user_conn.bind()
            user_conn.unbind()

            log.info(f"User {username!r} authenticated OK")
            self._update_cache(username, password)
            return True

        except ldap3.core.exceptions.LDAPBindError:
            log.warning(f"User {username!r} bind failed (bad password)")
            return False
        except ldap3.core.exceptions.LDAPException as exc:
            log.error(f"LDAP error authenticating {username!r}: {exc}")
            return False

    def ping(self) -> bool:
        """Test service account bind for health checks."""
        try:
            server = ldap3.Server(self._url, use_ssl=self._use_ssl, get_info=ldap3.NONE)
            conn = ldap3.Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                authentication=ldap3.SIMPLE,
                raise_exceptions=True,
            )
            conn.bind()
            conn.unbind()
            return True
        except Exception:
            return False
