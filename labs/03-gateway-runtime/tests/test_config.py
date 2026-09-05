from gateway_runtime.config import build_agentgateway_config, redacted_config
from gateway_runtime.credentials import EphemeralCredentials


def test_one_gateway_routes_api_keys_and_jwt_to_the_same_backend() -> None:
    material = EphemeralCredentials.create()
    config = build_agentgateway_config(
        material,
        provider_host="host.docker.internal:40123",
        jwks_path="/config/jwks.json",
    )

    assert list(config["gateways"]) == ["lab"]
    assert config["gateways"]["lab"]["port"] == 3000
    assert len(config["routes"]) == 2
    assert {route["name"] for route in config["routes"]} == {"api-key", "jwt"}
    assert {route["backends"][0]["host"] for route in config["routes"]} == {
        "host.docker.internal:40123"
    }

    api_route = next(route for route in config["routes"] if route["name"] == "api-key")
    configured_keys = api_route["policies"]["apiKey"]["keys"]
    assert [item["key"] for item in configured_keys] == [
        material.human_virtual_key,
        material.workload_consumer_key,
    ]
    assert material.retired_workload_key not in str(config)


def test_redacted_config_keeps_structure_without_any_runtime_secret() -> None:
    material = EphemeralCredentials.create()
    config = build_agentgateway_config(
        material,
        provider_host="host.docker.internal:40123",
        jwks_path="/config/jwks.json",
    )

    safe = redacted_config(config)
    serialized = str(safe)

    assert safe["routes"][0]["policies"]["apiKey"]["keys"][0]["key"] == "<redacted>"
    for secret in material.raw_secrets():
        assert secret not in serialized
