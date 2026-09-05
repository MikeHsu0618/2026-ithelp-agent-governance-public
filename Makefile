LAB01 := $(CURDIR)/labs/01-unsafe-agent
LAB02 := $(CURDIR)/labs/02-identity-boundary
LAB03 := $(CURDIR)/labs/03-gateway-runtime
AGENTGATEWAY_IMAGE := cr.agentgateway.dev/agentgateway@sha256:bf2f339ef326d32def2aaeb44b1b4549801293c19b89e764a4228667d97d9896

.PHONY: lab-01-up lab-01-test lab-01-check lab-01-fixture lab-01-live lab-01-replay lab-01-down \
	lab-02-up lab-02-test lab-02-check lab-02-demo lab-02-delegation lab-02-passthrough lab-02-oauth \
	lab-02-cognito lab-02-cognito-config-check lab-02-down \
	lab-03-check lab-03-fixture lab-03-live \
	lab-03-runtime-up lab-03-runtime-check lab-03-runtime-config-check \
	lab-03-runtime-run lab-03-runtime-traffic lab-03-runtime-down

lab-01-up:
	uv sync --directory "$(LAB01)" --all-groups

lab-01-test:
	uv run --directory "$(LAB01)" pytest -q

lab-01-check: lab-01-test
	uv run --directory "$(LAB01)" ruff check .
	uv run --directory "$(LAB01)" ruff format --check .

lab-01-fixture:
	uv run --directory "$(LAB01)" unsafe-agent run --scenario normal --model fixture --policy open
	uv run --directory "$(LAB01)" unsafe-agent run --scenario attack --model fixture --policy open
	uv run --directory "$(LAB01)" unsafe-agent run --scenario attack --model fixture --policy allowlist

lab-01-live:
	uv run --directory "$(LAB01)" --env-file "$(LAB01)/.env" unsafe-agent run --scenario attack --model live --policy open

lab-03-check: lab-01-check

lab-03-fixture:
	uv run --directory "$(LAB01)" unsafe-agent run --scenario attack --model fixture --policy open --input-guard keyword
	uv run --directory "$(LAB01)" unsafe-agent run --scenario attack-obfuscated --model fixture --policy open --input-guard keyword
	uv run --directory "$(LAB01)" unsafe-agent run --scenario attack-obfuscated --model fixture --policy allowlist --input-guard keyword

lab-03-live:
	uv run --directory "$(LAB01)" --env-file "$(LAB01)/.env" unsafe-agent run --scenario attack-obfuscated --model live --policy open --input-guard keyword
	uv run --directory "$(LAB01)" --env-file "$(LAB01)/.env" unsafe-agent run --scenario attack-obfuscated --model live --policy allowlist --input-guard keyword

lab-01-replay:
	@test -n "$(TRACE_ID)" || (printf '%s\n' 'usage: make lab-01-replay TRACE_ID=<32-hex-trace-id>' >&2; exit 2)
	uv run --directory "$(LAB01)" unsafe-agent replay --trace-id "$(TRACE_ID)"

lab-01-down:
	uv run --directory "$(LAB01)" unsafe-agent clean --lab-root .

lab-02-up:
	uv sync --directory "$(LAB02)" --all-groups

lab-02-test:
	uv run --directory "$(LAB02)" pytest -q

lab-02-check: lab-02-test
	uv run --directory "$(LAB02)" ruff check .
	uv run --directory "$(LAB02)" ruff format --check .

lab-02-demo:
	uv run --directory "$(LAB02)" identity-boundary run

lab-02-delegation:
	uv run --directory "$(LAB02)" identity-boundary delegation --artifact-root "$(LAB02)/artifacts"

lab-02-passthrough:
	uv run --directory "$(LAB02)" identity-boundary passthrough --artifact-root "$(LAB02)/artifacts"

lab-02-oauth:
	uv run --directory "$(LAB02)" identity-boundary oauth --artifact-root "$(LAB02)/artifacts"

lab-02-cognito:
	uv run --directory "$(LAB02)" identity-boundary cognito --artifact-root "$(LAB02)/artifacts"

lab-02-cognito-config-check:
	terraform -chdir="$(LAB02)/configs/cognito-terraform" fmt -check
	terraform -chdir="$(LAB02)/configs/cognito-terraform" init -backend=false
	terraform -chdir="$(LAB02)/configs/cognito-terraform" validate
	docker run --rm \
		-v "$(LAB02)/configs:/config:ro" \
		cr.agentgateway.dev/agentgateway@sha256:efd79355b89094a8225a9db465d9a01dc656b377f0bab458761b935a13231d29 \
		--file /config/agentgateway-cognito.yaml \
		--validate-only

lab-02-down:
	uv run --directory "$(LAB02)" identity-boundary clean --lab-root "$(LAB02)"

lab-03-runtime-up:
	uv sync --directory "$(LAB03)" --all-groups

lab-03-runtime-check:
	uv run --directory "$(LAB03)" pytest -q
	uv run --directory "$(LAB03)" ruff check .
	uv run --directory "$(LAB03)" ruff format --check .
	$(MAKE) lab-03-runtime-config-check

lab-03-runtime-config-check:
	docker run --rm \
		-v "$(LAB03)/configs:/config:ro" \
		$(AGENTGATEWAY_IMAGE) \
		--file /config/agentgateway.example.yaml \
		--validate-only

lab-03-runtime-run:
	uv run --directory "$(LAB03)" gateway-runtime run --artifact-root "$(LAB03)/artifacts"

lab-03-runtime-traffic:
	uv run --directory "$(LAB03)" gateway-runtime traffic --artifact-root "$(LAB03)/artifacts"

lab-03-runtime-down:
	uv run --directory "$(LAB03)" gateway-runtime clean --lab-root "$(LAB03)"
