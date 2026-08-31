"""Strict JWT validation and authorization-input checks for Lab 02."""

import json
import re
from dataclasses import dataclass
from typing import Any

import jwt
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuedAtError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)

ALLOWED_ALGORITHM = "RS256"
ACCESS_TOKEN_TYPE = "at+jwt"
SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
BASE_REGISTERED_CLAIMS = ("iss", "exp", "iat", "client_id", "token_use", "scope")


@dataclass(frozen=True, slots=True)
class TokenPolicy:
    """The resource and policy context a token must be valid for."""

    issuer: str
    audience: str | None
    client_id: str
    required_scopes: frozenset[str]
    required_claims: frozenset[str]
    require_subject: bool = True
    require_type_header: bool = True
    forbid_audience: bool = False

    def __post_init__(self) -> None:
        if not self.issuer.startswith("https://"):
            raise ValueError("issuer must use https")
        if self.audience == "" or not self.client_id:
            raise ValueError("audience, when configured, and client_id must not be empty")
        if not self.required_scopes:
            raise ValueError("at least one required scope is needed")
        if self.forbid_audience and self.audience is not None:
            raise ValueError("audience cannot be configured when it is forbidden")


class TokenRejected(ValueError):
    """A stable, non-sensitive reason for rejecting a token."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


class TokenValidator:
    """Validate one resource-bound access token against an offline JWKS."""

    def __init__(
        self,
        *,
        jwks: dict[str, Any],
        policy: TokenPolicy,
        max_token_bytes: int = 16_384,
    ) -> None:
        if max_token_bytes < 256:
            raise ValueError("max_token_bytes is too small for an RSA JWT")
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise ValueError("JWKS must contain a keys array")
        self._keys = tuple(key for key in keys if isinstance(key, dict))
        self.policy = policy
        self.max_token_bytes = max_token_bytes

    def validate(self, token: str) -> dict[str, Any]:
        """Return verified claims or raise a stable ``TokenRejected`` error."""

        self._validate_input(token)
        header = self._read_and_validate_header(token)
        public_key = self._select_public_key(header["kid"])

        try:
            required_claims = list(BASE_REGISTERED_CLAIMS)
            if self.policy.audience is not None:
                required_claims.append("aud")
            if self.policy.require_subject:
                required_claims.append("sub")
            claims = jwt.decode(
                token,
                public_key,
                algorithms=[ALLOWED_ALGORITHM],
                audience=self.policy.audience,
                issuer=self.policy.issuer,
                options={
                    "require": required_claims,
                    "verify_aud": self.policy.audience is not None,
                },
            )
        except ExpiredSignatureError as error:
            raise TokenRejected("TOKEN_EXPIRED", "claims", "token has expired") from error
        except InvalidIssuerError as error:
            raise TokenRejected(
                "ISSUER_MISMATCH", "claims", "issuer does not match the trusted issuer"
            ) from error
        except InvalidAudienceError as error:
            raise TokenRejected(
                "AUDIENCE_MISMATCH", "claims", "audience does not match this resource"
            ) from error
        except MissingRequiredClaimError as error:
            raise TokenRejected(
                "REGISTERED_CLAIM_MISSING", "claims", "a required registered claim is absent"
            ) from error
        except (InvalidIssuedAtError, ImmatureSignatureError) as error:
            raise TokenRejected(
                "TIME_CLAIM_INVALID", "claims", "token time claim is invalid"
            ) from error
        except InvalidSignatureError as error:
            raise TokenRejected(
                "SIGNATURE_INVALID", "signature", "signature verification failed"
            ) from error
        except (DecodeError, InvalidTokenError, TypeError, ValueError) as error:
            raise TokenRejected(
                "TOKEN_INVALID", "signature", "token could not be verified"
            ) from error

        self._validate_policy_claims(claims)
        return dict(claims)

    def _validate_input(self, token: str) -> None:
        if not isinstance(token, str) or not token:
            raise TokenRejected("TOKEN_INVALID", "input", "token must be a non-empty string")
        if len(token.encode("utf-8")) > self.max_token_bytes:
            raise TokenRejected("TOKEN_TOO_LARGE", "input", "token exceeds the input limit")

    def _read_and_validate_header(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except (DecodeError, InvalidTokenError, TypeError, ValueError) as error:
            raise TokenRejected("INVALID_HEADER", "header", "JWT header is malformed") from error

        if header.get("alg") != ALLOWED_ALGORITHM:
            raise TokenRejected("ALGORITHM_NOT_ALLOWED", "header", "JWT algorithm is not allowed")
        token_type = header.get("typ")
        if self.policy.require_type_header and token_type != ACCESS_TOKEN_TYPE:
            raise TokenRejected("TOKEN_TYPE_INVALID", "header", "JWT type is not an access token")
        if not self.policy.require_type_header and token_type not in (
            None,
            "JWT",
            ACCESS_TOKEN_TYPE,
        ):
            raise TokenRejected("TOKEN_TYPE_INVALID", "header", "JWT type is not an access token")
        key_id = header.get("kid")
        if not isinstance(key_id, str) or SAFE_KEY_ID.fullmatch(key_id) is None:
            raise TokenRejected("INVALID_HEADER", "header", "JWT key identifier is invalid")
        return header

    def _select_public_key(self, key_id: str) -> Any:
        matches = [key for key in self._keys if key.get("kid") == key_id]
        if len(matches) != 1:
            raise TokenRejected("KEY_NOT_FOUND", "key", "no unique trusted signing key was found")

        jwk = matches[0]
        if jwk.get("kty") != "RSA" or jwk.get("use") != "sig" or jwk.get("alg") != "RS256":
            raise TokenRejected("KEY_INVALID", "key", "the trusted signing key metadata is invalid")
        try:
            public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
        except (KeyError, TypeError, ValueError) as error:
            raise TokenRejected(
                "KEY_INVALID", "key", "the trusted signing key is invalid"
            ) from error
        if public_key.key_size < 2048:
            raise TokenRejected("KEY_INVALID", "key", "the trusted RSA signing key is too small")
        return public_key

    def _validate_policy_claims(self, claims: dict[str, Any]) -> None:
        if self.policy.forbid_audience and "aud" in claims:
            raise TokenRejected(
                "AUDIENCE_UNEXPECTED",
                "policy",
                "this token profile must not synthesize a resource audience",
            )
        if claims.get("token_use") != "access":
            raise TokenRejected("TOKEN_USE_INVALID", "policy", "an access token is required")
        if claims.get("client_id") != self.policy.client_id:
            raise TokenRejected(
                "CLIENT_MISMATCH", "policy", "token was not issued to the expected client"
            )

        raw_scope = claims.get("scope")
        if not isinstance(raw_scope, str):
            raise TokenRejected("SCOPE_INVALID", "policy", "scope must be a space-delimited string")
        granted_scopes = frozenset(raw_scope.split())
        if not self.policy.required_scopes.issubset(granted_scopes):
            raise TokenRejected("SCOPE_MISSING", "policy", "required OAuth scope is missing")

        for claim_name in sorted(self.policy.required_claims):
            if claim_name not in claims or claims[claim_name] in (None, ""):
                raise TokenRejected("CLAIM_MISSING", "policy", "a policy input claim is missing")
