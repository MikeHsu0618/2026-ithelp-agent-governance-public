"""Build the single-gateway configuration used for every comparison path."""

import copy
from typing import Any

from gateway_runtime.credentials import EphemeralCredentials


def build_agentgateway_config(
    material: EphemeralCredentials,
    *,
    provider_host: str,
    jwks_path: str,
) -> dict[str, Any]:
    """Return a routing-based config with API-key and JWT policies on separate routes."""

    backend = {
        "host": provider_host,
        "policies": {
            "backendAuth": {
                "key": {
                    "value": material.provider_key,
                    "location": {"header": {"name": "authorization", "prefix": "Bearer "}},
                }
            }
        },
    }
    match_path = {"path": {"exact": "/v1/chat/completions"}}
    return {
        "gateways": {"lab": {"port": 3000, "protocol": "HTTP"}},
        "routes": [
            {
                "name": "api-key",
                "gateways": ["lab"],
                "matches": [
                    {
                        **match_path,
                        "headers": [{"name": "x-demo-credential", "value": {"exact": "api-key"}}],
                    }
                ],
                "policies": {
                    "apiKey": {
                        "mode": "strict",
                        "keys": [
                            {
                                "key": material.human_virtual_key,
                                "metadata": {
                                    "kind": "HUMAN_VIRTUAL_KEY",
                                    "human": "user/sre-oncaller",
                                    "workload": "NOT_APPLICABLE",
                                    "consumer": "key/human-sre-oncaller",
                                },
                            },
                            {
                                "key": material.workload_consumer_key,
                                "metadata": {
                                    "kind": "WORKLOAD_CONSUMER_KEY",
                                    "human": "NOT_APPLICABLE",
                                    "workload": "workload/runtime-a",
                                    "consumer": "key/runtime-a",
                                },
                            },
                        ],
                    },
                    "transformations": {
                        "request": {
                            "set": {
                                "x-audit-kind": "apiKey.kind",
                                "x-audit-human": "apiKey.human",
                                "x-audit-workload": "apiKey.workload",
                                "x-audit-consumer": "apiKey.consumer",
                            }
                        }
                    },
                },
                "backends": [copy.deepcopy(backend)],
            },
            {
                "name": "jwt",
                "gateways": ["lab"],
                "matches": [
                    {
                        **match_path,
                        "headers": [{"name": "x-demo-credential", "value": {"exact": "jwt"}}],
                    }
                ],
                "policies": {
                    "jwtAuth": {
                        "mode": "strict",
                        "issuer": material.issuer,
                        "audiences": [material.audience],
                        "jwks": {"file": jwks_path},
                    },
                    "authorization": {
                        "rules": [
                            {"allow": ('jwt.token_use == "access" && jwt.scope == "llm.invoke"')}
                        ]
                    },
                    "transformations": {
                        "request": {
                            "set": {
                                "x-audit-kind": '"JWT_PRINCIPAL"',
                                "x-audit-human": "jwt.sub",
                                "x-audit-workload": '"NOT_APPLICABLE"',
                                "x-audit-consumer": "jwt.client_id",
                            }
                        }
                    },
                },
                "backends": [copy.deepcopy(backend)],
            },
        ],
    }


def redacted_config(config: dict[str, Any]) -> dict[str, Any]:
    """Keep policy structure suitable for evidence while removing every raw key."""

    safe = copy.deepcopy(config)
    for route in safe["routes"]:
        api_key = route.get("policies", {}).get("apiKey")
        if api_key:
            for item in api_key["keys"]:
                item["key"] = "<redacted>"
        for backend in route["backends"]:
            backend_auth = backend.get("policies", {}).get("backendAuth")
            if backend_auth:
                backend_auth["key"]["value"] = "<redacted>"
    return safe
