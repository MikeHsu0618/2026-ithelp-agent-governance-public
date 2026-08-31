"""Offline Cognito-shaped Human and M2M app-client contract for Day 12."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.oauth_flows import PKCE_VERIFIER

ClientKind = Literal["HUMAN_PUBLIC", "M2M_CONFIDENTIAL"]
STANDARD_USER_SCOPES = frozenset({"openid", "email", "phone", "profile"})


class CognitoContractError(ValueError):
    """Stable, non-sensitive Cognito contract failure."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


@dataclass(frozen=True, slots=True)
class _ClientRegistration:
    client_id: str
    kind: ClientKind
    redirect_uris: tuple[str, ...]
    allowed_scopes: frozenset[str]
    allowed_resources: frozenset[str]
    secret_salt: bytes | None = None
    secret_verifier: bytes | None = None


class OfflineCognitoUserPool:
    """A teaching reduction of Cognito app-client and access-token constraints."""

    def __init__(self, *, issuer: LocalIssuer) -> None:
        self.issuer = issuer
        self._clients: dict[str, _ClientRegistration] = {}

    def register_human_client(
        self,
        *,
        client_id: str,
        redirect_uris: tuple[str, ...],
        allowed_scopes: frozenset[str],
        allowed_resources: frozenset[str],
    ) -> None:
        if not redirect_uris or not allowed_resources:
            raise ValueError("Human app clients need redirect URIs and resources")
        self._register(
            _ClientRegistration(
                client_id=client_id,
                kind="HUMAN_PUBLIC",
                redirect_uris=redirect_uris,
                allowed_scopes=allowed_scopes,
                allowed_resources=allowed_resources,
            )
        )

    def register_m2m_client(
        self,
        *,
        client_id: str,
        client_secret: str,
        allowed_scopes: frozenset[str],
    ) -> None:
        if len(client_secret) < 24:
            raise ValueError("client_secret must contain at least 24 characters")
        if not allowed_scopes or any(scope in STANDARD_USER_SCOPES for scope in allowed_scopes):
            raise ValueError("M2M app clients may register custom resource-server scopes only")
        salt = secrets.token_bytes(16)
        self._register(
            _ClientRegistration(
                client_id=client_id,
                kind="M2M_CONFIDENTIAL",
                redirect_uris=(),
                allowed_scopes=allowed_scopes,
                allowed_resources=frozenset(),
                secret_salt=salt,
                secret_verifier=_secret_verifier(client_secret, salt),
            )
        )

    def issue_human_access_token(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        requested_scopes: tuple[str, ...],
        resource: str,
        subject: str,
        code_verifier: str,
        code_challenge: str,
        additional_claims: dict[str, Any],
        issued_at: datetime,
    ) -> IssuedToken:
        registration = self._client(client_id)
        if registration.kind != "HUMAN_PUBLIC":
            raise CognitoContractError(
                "UNAUTHORIZED_CLIENT",
                "authorization",
                "Human authorization requires a public client",
            )
        if redirect_uri not in registration.redirect_uris:
            raise CognitoContractError(
                "REDIRECT_URI_MISMATCH",
                "authorization",
                "callback URI does not match the registered value",
            )
        self._validate_scopes(registration, requested_scopes, stage="authorization")
        if resource not in registration.allowed_resources:
            raise CognitoContractError(
                "INVALID_RESOURCE", "authorization", "resource is not registered for this client"
            )
        if not _pkce_matches(code_verifier, code_challenge):
            raise CognitoContractError(
                "PKCE_VERIFICATION_FAILED", "token", "PKCE S256 verification failed"
            )
        return self.issuer.issue_access_token(
            subject=subject,
            audience=resource,
            client_id=client_id,
            scopes=requested_scopes,
            additional_claims=additional_claims,
            issued_at=issued_at,
            token_type_header=None,
        )

    def issue_m2m_access_token(
        self,
        *,
        client_id: str,
        client_secret: str,
        requested_scopes: tuple[str, ...],
        issued_at: datetime,
        resource: str | None = None,
    ) -> IssuedToken:
        if resource is not None:
            raise CognitoContractError(
                "RESOURCE_BINDING_UNSUPPORTED",
                "token",
                "Cognito client-credentials tokens do not support resource binding",
            )
        registration = self._client(client_id)
        if registration.kind != "M2M_CONFIDENTIAL":
            raise CognitoContractError(
                "UNAUTHORIZED_CLIENT",
                "client_authentication",
                "Client Credentials requires a confidential app client",
            )
        if registration.secret_salt is None or registration.secret_verifier is None:
            raise CognitoContractError(
                "INVALID_CLIENT", "client_authentication", "client is invalid"
            )
        supplied = _secret_verifier(client_secret, registration.secret_salt)
        if not hmac.compare_digest(supplied, registration.secret_verifier):
            raise CognitoContractError(
                "INVALID_CLIENT", "client_authentication", "client authentication failed"
            )
        self._validate_scopes(registration, requested_scopes, stage="token")
        return self.issuer.issue_access_token(
            subject=None,
            audience=None,
            client_id=client_id,
            scopes=requested_scopes,
            additional_claims={},
            issued_at=issued_at,
            token_type_header=None,
        )

    def safe_registration_snapshot(self) -> list[dict[str, Any]]:
        """Return app-client metadata without secret material or verifiers."""

        return [
            {
                "client_id": client.client_id,
                "kind": client.kind,
                "grant": (
                    "authorization_code" if client.kind == "HUMAN_PUBLIC" else "client_credentials"
                ),
                "redirect_uris": list(client.redirect_uris),
                "allowed_scopes": sorted(client.allowed_scopes),
                "allowed_resources": sorted(client.allowed_resources),
                "secret_stored": (
                    "none-public-client"
                    if client.kind == "HUMAN_PUBLIC"
                    else "scrypt-verifier-only"
                ),
            }
            for client in sorted(self._clients.values(), key=lambda item: item.client_id)
        ]

    def _register(self, registration: _ClientRegistration) -> None:
        if not registration.client_id or registration.client_id in self._clients:
            raise ValueError("client_id must be unique and non-empty")
        if not registration.allowed_scopes:
            raise ValueError("at least one allowed scope is required")
        self._clients[registration.client_id] = registration

    def _client(self, client_id: str) -> _ClientRegistration:
        try:
            return self._clients[client_id]
        except KeyError as error:
            raise CognitoContractError(
                "CLIENT_NOT_REGISTERED", "registration", "app client is not registered"
            ) from error

    @staticmethod
    def _validate_scopes(
        registration: _ClientRegistration,
        requested_scopes: tuple[str, ...],
        *,
        stage: str,
    ) -> None:
        if not requested_scopes or not set(requested_scopes).issubset(registration.allowed_scopes):
            raise CognitoContractError(
                "INVALID_SCOPE", stage, "requested scope is not enabled for this app client"
            )


def _secret_verifier(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _pkce_matches(verifier: str, challenge: str) -> bool:
    if PKCE_VERIFIER.fullmatch(verifier) is None:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
