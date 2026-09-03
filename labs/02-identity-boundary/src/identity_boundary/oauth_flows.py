"""Offline OAuth flow primitives for the Day 11 comparison lab."""

import base64
import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from identity_boundary.issuer import IssuedToken, LocalIssuer
from identity_boundary.validator import TokenPolicy, TokenRejected, TokenValidator

PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOKEN_EXCHANGE_GRANT = "token_exchange"
CLIENT_CREDENTIALS_GRANT = "client_credentials"
AUTHORIZATION_CODE_GRANT = "authorization_code"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class OAuthFlowError(ValueError):
    """A stable, non-sensitive OAuth flow failure for the offline lab."""

    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        *,
        reason_code: str = "NOT_APPLICABLE",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    """One in-memory authorization code returned to a public client."""

    authorization_code: str


@dataclass(frozen=True, slots=True)
class _SecretVerifier:
    salt: bytes
    digest: bytes

    @classmethod
    def create(cls, credential: str) -> "_SecretVerifier":
        _validate_client_credential(credential)
        salt = secrets.token_bytes(16)
        return cls(salt=salt, digest=_derive_client_credential(credential, salt))

    def matches(self, credential: str) -> bool:
        try:
            candidate = _derive_client_credential(credential, self.salt)
        except (TypeError, ValueError):
            return False
        return secrets.compare_digest(candidate, self.digest)


@dataclass(frozen=True, slots=True)
class _ClientRegistration:
    client_id: str
    client_type: str
    redirect_uris: tuple[str, ...]
    allowed_grants: frozenset[str]
    allowed_scopes: frozenset[str]
    allowed_resources: frozenset[str]
    credential_verifier: _SecretVerifier | None


@dataclass(slots=True)
class _AuthorizationCodeRecord:
    client_id: str
    redirect_uri: str
    subject: str
    resource: str
    scopes: frozenset[str]
    code_challenge: str
    expires_at: datetime
    consumed: bool = False


class OfflineAuthorizationServer:
    """A small in-memory authorization server used only for deterministic policy cases."""

    def __init__(
        self,
        *,
        issuer: LocalIssuer,
        subject_token_policy: TokenPolicy,
        actor_token_policy: TokenPolicy,
    ) -> None:
        self.issuer = issuer
        self._subject_token_validator = TokenValidator(
            jwks=issuer.jwks(), policy=subject_token_policy
        )
        self._actor_token_validator = TokenValidator(jwks=issuer.jwks(), policy=actor_token_policy)
        self._registrations: dict[str, _ClientRegistration] = {}
        self._authorization_codes: dict[str, _AuthorizationCodeRecord] = {}

    def register_public_client(
        self,
        *,
        client_id: str,
        redirect_uris: tuple[str, ...],
        allowed_scopes: frozenset[str],
        allowed_resources: frozenset[str],
    ) -> None:
        """Register a public client that can use Authorization Code + PKCE."""

        if not redirect_uris:
            raise ValueError("a public client requires at least one redirect URI")
        self._register(
            _ClientRegistration(
                client_id=client_id,
                client_type="public",
                redirect_uris=redirect_uris,
                allowed_grants=frozenset({AUTHORIZATION_CODE_GRANT}),
                allowed_scopes=allowed_scopes,
                allowed_resources=allowed_resources,
                credential_verifier=None,
            )
        )

    def register_confidential_client(
        self,
        *,
        client_id: str,
        client_secret: str,
        allowed_grants: frozenset[str],
        allowed_scopes: frozenset[str],
        allowed_resources: frozenset[str],
    ) -> None:
        """Register a confidential client without retaining its raw credential."""

        supported = frozenset({CLIENT_CREDENTIALS_GRANT, TOKEN_EXCHANGE_GRANT})
        if not allowed_grants or not allowed_grants.issubset(supported):
            raise ValueError("confidential client grant is not supported by this lab")
        self._register(
            _ClientRegistration(
                client_id=client_id,
                client_type="confidential",
                redirect_uris=(),
                allowed_grants=allowed_grants,
                allowed_scopes=allowed_scopes,
                allowed_resources=allowed_resources,
                credential_verifier=_SecretVerifier.create(client_secret),
            )
        )

    def authorize_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: frozenset[str],
        resource: str,
        subject: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> AuthorizationGrant:
        """Authorize one Human request and bind an opaque code to its PKCE challenge."""

        registration = self._registration(client_id)
        if AUTHORIZATION_CODE_GRANT not in registration.allowed_grants:
            raise OAuthFlowError(
                "UNAUTHORIZED_CLIENT",
                "authorization_request",
                "client cannot use the authorization code grant",
            )
        if redirect_uri not in registration.redirect_uris:
            raise OAuthFlowError(
                "REDIRECT_URI_MISMATCH",
                "authorization_request",
                "redirect URI does not exactly match the registered value",
            )
        self._validate_scope_and_resource(
            registration,
            scopes=scopes,
            resource=resource,
            stage="authorization_request",
        )
        if code_challenge_method != "S256" or not _is_pkce_challenge(code_challenge):
            raise OAuthFlowError(
                "PKCE_REQUIRED",
                "authorization_request",
                "a valid S256 code challenge is required",
            )
        if not subject:
            raise OAuthFlowError(
                "ACCESS_DENIED", "authorization_request", "resource owner is missing"
            )

        authorization_code = secrets.token_urlsafe(32)
        self._authorization_codes[_credential_digest(authorization_code)] = (
            _AuthorizationCodeRecord(
                client_id=client_id,
                redirect_uri=redirect_uri,
                subject=subject,
                resource=resource,
                scopes=scopes,
                code_challenge=code_challenge,
                expires_at=datetime.now(UTC) + timedelta(minutes=2),
            )
        )
        return AuthorizationGrant(authorization_code=authorization_code)

    def redeem_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        authorization_code: str,
        code_verifier: str,
    ) -> IssuedToken:
        """Redeem a one-time code only when client, callback, and PKCE proof all match."""

        self._registration(client_id)
        record = self._authorization_codes.get(_credential_digest(authorization_code))
        if record is None or record.consumed or record.expires_at <= datetime.now(UTC):
            raise OAuthFlowError("INVALID_GRANT", "token_request", "authorization code is invalid")
        if record.client_id != client_id or record.redirect_uri != redirect_uri:
            raise OAuthFlowError(
                "INVALID_GRANT", "token_request", "authorization code binding does not match"
            )
        if not PKCE_VERIFIER.fullmatch(code_verifier):
            raise OAuthFlowError("INVALID_GRANT", "token_request", "PKCE verifier is invalid")
        expected_challenge = _pkce_challenge(code_verifier)
        if not secrets.compare_digest(expected_challenge, record.code_challenge):
            raise OAuthFlowError("INVALID_GRANT", "token_request", "PKCE proof does not match")

        record.consumed = True
        return self.issuer.issue_access_token(
            subject=record.subject,
            audience=record.resource,
            client_id=record.client_id,
            scopes=tuple(sorted(record.scopes)),
            additional_claims={},
            lifetime=timedelta(minutes=5),
        )

    def client_credentials(
        self,
        *,
        client_id: str,
        client_secret: str,
        scopes: frozenset[str],
        resource: str,
    ) -> IssuedToken:
        """Issue an app-only token after authenticating a confidential client."""

        registration = self._authenticate_confidential_client(
            client_id, client_secret, grant=CLIENT_CREDENTIALS_GRANT
        )
        self._validate_scope_and_resource(
            registration, scopes=scopes, resource=resource, stage="token_request"
        )
        return self.issuer.issue_access_token(
            subject=f"client/{client_id}",
            audience=resource,
            client_id=client_id,
            scopes=tuple(sorted(scopes)),
            additional_claims={},
            lifetime=timedelta(minutes=5),
        )

    def token_exchange(
        self,
        *,
        client_id: str,
        client_secret: str,
        subject_token: str,
        subject_token_type: str,
        actor_token: str,
        actor_token_type: str,
        scopes: frozenset[str],
        resource: str,
    ) -> IssuedToken:
        """Issue a delegated token after validating subject, actor, and their binding."""

        registration = self._authenticate_confidential_client(
            client_id, client_secret, grant=TOKEN_EXCHANGE_GRANT
        )
        if subject_token_type != ACCESS_TOKEN_TYPE:
            raise OAuthFlowError(
                "SUBJECT_TOKEN_TYPE_UNSUPPORTED",
                "token_request",
                "subject token type is not supported",
            )
        if actor_token_type != ACCESS_TOKEN_TYPE:
            raise OAuthFlowError(
                "ACTOR_TOKEN_TYPE_UNSUPPORTED",
                "token_request",
                "actor token type is not supported",
            )
        if resource not in registration.allowed_resources:
            raise OAuthFlowError(
                "INVALID_TARGET", "token_request", "requested resource is not allowed"
            )
        self._validate_scopes(registration, scopes, stage="token_request")
        try:
            subject_claims = self._subject_token_validator.validate(subject_token)
        except TokenRejected as error:
            raise OAuthFlowError(
                "SUBJECT_TOKEN_INVALID",
                "subject_token",
                "subject token could not be accepted",
                reason_code=error.code,
            ) from error

        try:
            actor_claims = self._actor_token_validator.validate(actor_token)
        except TokenRejected as error:
            raise OAuthFlowError(
                "ACTOR_TOKEN_INVALID",
                "actor_token",
                "actor token could not be accepted",
                reason_code=error.code,
            ) from error

        expected_actor = f"client/{client_id}"
        actor_subject = actor_claims.get("sub")
        if actor_subject != expected_actor:
            raise OAuthFlowError(
                "ACTOR_CLIENT_MISMATCH",
                "delegation_policy",
                "actor token does not represent the authenticated client",
            )

        may_act = subject_claims.get("may_act")
        if not isinstance(may_act, Mapping) or may_act.get("sub") != actor_subject:
            raise OAuthFlowError(
                "ACTOR_NOT_AUTHORIZED",
                "delegation_policy",
                "subject token does not authorize this actor",
            )

        return self.issuer.issue_access_token(
            subject=str(subject_claims["sub"]),
            audience=resource,
            client_id=client_id,
            scopes=tuple(sorted(scopes)),
            additional_claims={"act": {"sub": str(actor_subject)}},
            lifetime=timedelta(minutes=1),
        )

    def safe_registration_snapshot(self) -> list[dict[str, object]]:
        """Return publishable registration metadata without verifiers or raw credentials."""

        return [
            {
                "client_id": registration.client_id,
                "client_type": registration.client_type,
                "redirect_uris": list(registration.redirect_uris),
                "allowed_grants": sorted(registration.allowed_grants),
                "allowed_scopes": sorted(registration.allowed_scopes),
                "allowed_resources": sorted(registration.allowed_resources),
                "client_authentication": (
                    "none" if registration.client_type == "public" else "configured"
                ),
            }
            for registration in sorted(
                self._registrations.values(), key=lambda item: item.client_id
            )
        ]

    def _register(self, registration: _ClientRegistration) -> None:
        if not registration.client_id:
            raise ValueError("client_id must not be empty")
        if registration.client_id in self._registrations:
            raise ValueError("client_id is already registered")
        if not registration.allowed_scopes or not registration.allowed_resources:
            raise ValueError("client registration requires scopes and resources")
        self._registrations[registration.client_id] = registration

    def _registration(self, client_id: str) -> _ClientRegistration:
        try:
            return self._registrations[client_id]
        except KeyError as error:
            raise OAuthFlowError(
                "CLIENT_NOT_REGISTERED", "registration", "client is not registered"
            ) from error

    def _authenticate_confidential_client(
        self, client_id: str, client_credential: str, *, grant: str
    ) -> _ClientRegistration:
        registration = self._registration(client_id)
        if registration.client_type != "confidential" or grant not in registration.allowed_grants:
            raise OAuthFlowError(
                "UNAUTHORIZED_CLIENT", "client_authentication", "client cannot use this grant"
            )
        verifier = registration.credential_verifier
        if verifier is None or not verifier.matches(client_credential):
            raise OAuthFlowError(
                "INVALID_CLIENT", "client_authentication", "client authentication failed"
            )
        return registration

    def _validate_scope_and_resource(
        self,
        registration: _ClientRegistration,
        *,
        scopes: frozenset[str],
        resource: str,
        stage: str,
    ) -> None:
        self._validate_scopes(registration, scopes, stage=stage)
        if resource not in registration.allowed_resources:
            raise OAuthFlowError("INVALID_TARGET", stage, "requested resource is not allowed")

    @staticmethod
    def _validate_scopes(
        registration: _ClientRegistration, scopes: frozenset[str], *, stage: str
    ) -> None:
        if not scopes or not scopes.issubset(registration.allowed_scopes):
            raise OAuthFlowError("INVALID_SCOPE", stage, "requested scope is not allowed")


def create_pkce_pair() -> tuple[str, str]:
    """Return an RFC 7636-compatible verifier and its S256 challenge."""

    verifier = secrets.token_urlsafe(32)
    return verifier, _pkce_challenge(verifier)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _is_pkce_challenge(challenge: str) -> bool:
    return isinstance(challenge, str) and PKCE_CHALLENGE.fullmatch(challenge) is not None


def _credential_digest(credential: str) -> str:
    if not isinstance(credential, str) or not credential:
        return "invalid"
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def _validate_client_credential(credential: str) -> None:
    if not isinstance(credential, str) or len(credential) < 32:
        raise ValueError("confidential client credential must contain at least 32 characters")


def _derive_client_credential(credential: str, salt: bytes) -> bytes:
    _validate_client_credential(credential)
    return hashlib.scrypt(credential.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
