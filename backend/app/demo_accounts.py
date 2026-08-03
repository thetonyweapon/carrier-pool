"""Ephemeral local accounts used only by the demo authentication flow."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from fastapi import Request

ADMIN_IDENTIFIER = "admin"
ADMIN_PASSWORD = "admin"
COMMON_PASSWORD_WORDS = frozenset(
    {"admin", "broker", "carrier", "demo", "freight", "letmein", "password", "qwerty", "secret"}
)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AccountValidationError(ValueError):
    pass


class AccountAuthenticationError(ValueError):
    pass


class AccountPermissionError(ValueError):
    pass


@dataclass(frozen=True)
class AccountSession:
    account_id: str
    identifier: str
    name: str
    broker_id: Optional[str]
    is_admin: bool


@dataclass(frozen=True)
class AccountProfile:
    account_id: str
    email: Optional[str]
    name: str
    broker_id: str
    is_admin: bool
    is_demo: bool
    profile_locked: bool


@dataclass
class _Account:
    account_id: str
    email: Optional[str]
    name: str
    broker_id: Optional[str]
    is_admin: bool
    salt: bytes
    password_digest: bytes


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if not EMAIL_PATTERN.fullmatch(value):
        raise AccountValidationError("a valid email address is required")
    return value


def validate_password(password: str) -> None:
    if not 6 <= len(password) <= 12:
        raise AccountValidationError("password must be 6-12 characters")
    if password.isalnum():
        raise AccountValidationError("password must include a non-alphanumeric character")
    lowered = password.casefold()
    if any(word in lowered for word in COMMON_PASSWORD_WORDS):
        raise AccountValidationError("password must not contain a common dictionary word")


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)


class DemoAccountRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accounts: dict[str, _Account] = {}
        self._email_index: dict[str, str] = {}
        self._accounts["account-admin"] = _Account(
            account_id="account-admin",
            email=None,
            name="Demo Sysadmin",
            broker_id=None,
            is_admin=True,
            salt=b"demo-admin-salt",
            password_digest=_password_digest(ADMIN_PASSWORD, b"demo-admin-salt"),
        )

    def authenticate(self, identifier: str, password: str, broker_id: str) -> AccountSession:
        with self._lock:
            if identifier.strip().casefold() == ADMIN_IDENTIFIER:
                account = self._accounts["account-admin"]
                if not hmac.compare_digest(password, ADMIN_PASSWORD):
                    raise AccountAuthenticationError("invalid credentials")
                return AccountSession(
                    account_id=account.account_id,
                    identifier=ADMIN_IDENTIFIER,
                    name=account.name,
                    broker_id=broker_id,
                    is_admin=True,
                )

            email = normalize_email(identifier)
            account_id = self._email_index.get(email)
            account = self._accounts.get(account_id or "")
            if account is None or account.broker_id != broker_id:
                raise AccountAuthenticationError("invalid credentials")
            if not hmac.compare_digest(
                account.password_digest, _password_digest(password, account.salt)
            ):
                raise AccountAuthenticationError("invalid credentials")
            return AccountSession(
                account_id=account.account_id,
                identifier=email,
                name=account.name,
                broker_id=account.broker_id,
                is_admin=False,
            )

    def create(self, broker_id: str, name: str, email: str, password: str) -> AccountSession:
        normalized_email = normalize_email(email)
        validate_password(password)
        normalized_name = name.strip()
        if not normalized_name:
            raise AccountValidationError("name is required")
        with self._lock:
            if normalized_email in self._email_index:
                raise AccountValidationError("email is already registered")
            account_id = f"account-{uuid4()}"
            salt = secrets.token_bytes(16)
            self._accounts[account_id] = _Account(
                account_id=account_id,
                email=normalized_email,
                name=normalized_name,
                broker_id=broker_id,
                is_admin=False,
                salt=salt,
                password_digest=_password_digest(password, salt),
            )
            self._email_index[normalized_email] = account_id
            return AccountSession(account_id, normalized_email, normalized_name, broker_id, False)

    def profile(self, session: AccountSession, is_demo: bool) -> AccountProfile:
        with self._lock:
            account = self._accounts.get(session.account_id)
        if account is None:
            raise AccountAuthenticationError("account is no longer available")
        return AccountProfile(
            account_id=account.account_id,
            email=account.email,
            name=account.name,
            broker_id=session.broker_id or "",
            is_admin=account.is_admin,
            is_demo=is_demo,
            profile_locked=account.is_admin or is_demo,
        )

    def update(
        self,
        session: AccountSession,
        is_demo: bool,
        name: Optional[str],
        email: Optional[str],
        password: Optional[str],
    ) -> AccountSession:
        if session.is_admin or is_demo:
            raise AccountPermissionError("this demo profile is locked")
        with self._lock:
            account = self._accounts.get(session.account_id)
            if account is None:
                raise AccountAuthenticationError("account is no longer available")
            next_name = account.name if name is None else name.strip()
            if not next_name:
                raise AccountValidationError("name is required")
            next_email = account.email if email is None else normalize_email(email)
            if next_email != account.email and next_email in self._email_index:
                raise AccountValidationError("email is already registered")
            if password is not None:
                validate_password(password)
                salt = secrets.token_bytes(16)
                digest = _password_digest(password, salt)
            else:
                salt, digest = account.salt, account.password_digest
            if next_email != account.email:
                self._email_index.pop(account.email or "", None)
                self._email_index[next_email] = account.account_id
            account.name, account.email, account.salt, account.password_digest = (
                next_name,
                next_email,
                salt,
                digest,
            )
            return AccountSession(
                account.account_id, next_email, next_name, account.broker_id, False
            )


def account_registry(request: Request) -> DemoAccountRegistry:
    return request.app.state.demo_accounts
