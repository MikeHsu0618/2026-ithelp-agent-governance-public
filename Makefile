SHELL := /bin/bash
SELF_MAKEFILE := $(abspath $(firstword $(MAKEFILE_LIST)))

LAB01 := $(CURDIR)/labs/01-unsafe-agent
LAB02 := $(CURDIR)/labs/02-identity-boundary
LAB03 := $(CURDIR)/labs/03-gateway-runtime
AGENTGATEWAY_IMAGE := cr.agentgateway.dev/agentgateway@sha256:bf2f339ef326d32def2aaeb44b1b4549801293c19b89e764a4228667d97d9896
DAY16_CONFIG := $(LAB03)/configs/day-16
DAY16_MCP_FIXTURE := $(LAB03)/fixtures/day-16-mcp
DAY17_CONFIG := $(LAB03)/configs/day-17
DAY18_CONFIG := $(LAB03)/configs/day-18
DAY18_BYO_FIXTURE := $(LAB03)/fixtures/day-18-byo
DAY18_BYO_IMAGE := ithelp/day18-byo:2026.9.10
DAY18_KAGENT_VERSION := 0.10.1
KAGENT_VERSION ?= 0.10.0
DAY16_KIND_NAME := ithelp-day16
DAY16_CONTEXT := kind-ithelp-day16
DAY16_KUBECONFIG ?= $(LAB03)/.runtime/day-16/kubeconfig
DAY17_GATEWAY_HOST := http://agentgateway-proxy.agentgateway-system.svc.cluster.local
KIND_BIN ?= kind
KUBECTL_BIN ?= kubectl

.PHONY: lab-01-up lab-01-test lab-01-check lab-01-fixture lab-01-live lab-01-replay lab-01-down \
	lab-02-up lab-02-test lab-02-check lab-02-demo lab-02-delegation lab-02-passthrough lab-02-oauth \
	lab-02-cognito lab-02-cognito-config-check lab-02-down \
	lab-03-check lab-03-fixture lab-03-live \
	lab-03-runtime-up lab-03-runtime-check lab-03-runtime-config-check \
	lab-03-runtime-run lab-03-runtime-traffic lab-03-runtime-kagent-plan \
	lab-03-runtime-kagent-up lab-03-runtime-kagent-invoke lab-03-runtime-kagent-down \
	lab-03-runtime-a2a lab-03-runtime-a2a-up lab-03-runtime-a2a-reproduce lab-03-runtime-a2a-run \
	lab-03-runtime-byo lab-03-runtime-byo-up lab-03-runtime-byo-run \
	lab-03-runtime-down

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

lab-03-runtime-kagent-plan:
	uv run --directory "$(LAB03)" gateway-runtime kagent-boundary \
		--config-dir "$(DAY16_CONFIG)" \
		--artifact-root "$(LAB03)/artifacts"

lab-03-runtime-kagent-up:
	@command -v "$(KIND_BIN)" >/dev/null
	@command -v "$(KUBECTL_BIN)" >/dev/null
	@command -v helm >/dev/null
	@"$(KIND_BIN)" version | grep -q '^kind v0.30.0 '
	@"$(KUBECTL_BIN)" version --client -o json | grep -q '"gitVersion": "v1.34\.'
	@mkdir -p "$(dir $(DAY16_KUBECONFIG))"
	@if "$(KIND_BIN)" get clusters | grep -Fxq "$(DAY16_KIND_NAME)"; then \
		test -f "$(DAY16_KUBECONFIG)"; \
		test "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)" = "$(DAY16_CONTEXT)"; \
	else \
		existing_context="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context 2>/dev/null || true)"; \
		test -z "$$existing_context" -o "$$existing_context" = "$(DAY16_CONTEXT)"; \
		KUBECONFIG="$(DAY16_KUBECONFIG)" "$(KIND_BIN)" create cluster \
			--name "$(DAY16_KIND_NAME)" --kubeconfig "$(DAY16_KUBECONFIG)" --wait 90s; \
	fi
	@test "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)" = "$(DAY16_CONTEXT)"
	uv run --directory "$(LAB03)" gateway-runtime kagent-context-guard \
		--kubeconfig "$(DAY16_KUBECONFIG)" --context "$(DAY16_CONTEXT)"
	docker build -f "$(DAY16_MCP_FIXTURE)/Containerfile" \
		-t ithelp/day16-mcp:2026.8.31 "$(DAY16_MCP_FIXTURE)"
	"$(KIND_BIN)" load docker-image ithelp/day16-mcp:2026.8.31 --name "$(DAY16_KIND_NAME)"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" apply --server-side \
		-f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml
	helm upgrade --install agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds \
		--version v1.5.0 --namespace agentgateway-system --create-namespace \
		--kubeconfig "$(DAY16_KUBECONFIG)" --wait --timeout 3m
	helm upgrade --install agentgateway oci://cr.agentgateway.dev/charts/agentgateway \
		--version v1.5.0 --namespace agentgateway-system \
		--kubeconfig "$(DAY16_KUBECONFIG)" --wait --timeout 5m
	helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
		--version "$(KAGENT_VERSION)" --namespace kagent --create-namespace \
		--kubeconfig "$(DAY16_KUBECONFIG)" \
		--set kmcp.enabled=false --set substrate.enabled=false --wait --timeout 3m
	helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
		--version "$(KAGENT_VERSION)" --namespace kagent --kubeconfig "$(DAY16_KUBECONFIG)" \
		-f "$(DAY16_CONFIG)/kagent-values.yaml" --wait --timeout 6m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" apply -f "$(DAY16_CONFIG)/kagent-resources.yaml"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" apply -f "$(DAY16_CONFIG)/agentgateway-resources.yaml"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab rollout status \
		deployment/synthetic-llm --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab rollout status \
		deployment/mcp-everything --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n agentgateway-system rollout status \
		deployment/agentgateway-proxy --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab wait \
		--for=condition=Accepted modelconfig/day16-model --timeout=2m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab wait \
		--for=condition=Accepted remotemcpserver/day16-tools --timeout=2m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab wait \
		--for=condition=Ready agent/day16-agent --timeout=3m

lab-03-runtime-kagent-invoke:
	@test "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)" = "$(DAY16_CONTEXT)"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab exec deployment/synthetic-llm \
		-- python /app/client.py
	@count="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab \
		get remotemcpserver day16-tools -o jsonpath='{.status.discoveredTools[*].name}' | wc -w | tr -d ' ')"; \
		printf 'discovered-tools=%s\n' "$$count"; test "$$count" -eq 14
	@count="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n agentgateway-system \
		logs deployment/agentgateway-proxy | grep -c 'route=day16-lab/synthetic-llm' || true)"; \
		printf 'gateway-llm-requests=%s\n' "$$count"; test "$$count" -gt 0
	@count="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n agentgateway-system \
		logs deployment/agentgateway-proxy | grep -c 'route=day16-lab/mcp-everything' || true)"; \
		printf 'gateway-mcp-requests=%s\n' "$$count"; test "$$count" -gt 0

lab-03-runtime-a2a-up: lab-03-runtime-kagent-up
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" apply -f "$(DAY17_CONFIG)/a2a-route.yaml"
	@for backend in day17-kagent-http day17-kagent-a2a; do \
		"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab wait \
			--for=condition=Accepted "agentgatewaybackend/$$backend" --timeout=2m; \
	done
	@for route in day17-kagent-http day17-kagent-a2a; do \
		accepted=""; \
		for attempt in $$(seq 1 30); do \
			accepted="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab \
				get httproute "$$route" \
				-o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}')"; \
			test "$$accepted" = "True" && break; \
			sleep 1; \
		done; \
		printf '%s-accepted=%s\n' "$$route" "$$accepted"; test "$$accepted" = "True"; \
	done

lab-03-runtime-a2a: lab-03-runtime-a2a-reproduce lab-03-runtime-a2a-run

lab-03-runtime-a2a-reproduce: lab-03-runtime-a2a-up
	helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
		--version "$(KAGENT_VERSION)" --namespace kagent --kubeconfig "$(DAY16_KUBECONFIG)" \
		-f "$(DAY16_CONFIG)/kagent-values.yaml" \
		--set-string controller.a2aBaseUrl="$(DAY17_GATEWAY_HOST)/api/a2a" \
		--wait --timeout 6m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n kagent rollout status \
		deployment/kagent-controller --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab exec -i \
		deployment/synthetic-llm -- python - \
		--gateway-base "$(DAY17_GATEWAY_HOST)/api/a2a/day16-lab/day16-agent" \
		--expect-routing-failure \
		< "$(LAB03)/src/gateway_runtime/a2a_path.py"

lab-03-runtime-a2a-run: lab-03-runtime-a2a-up
	@test "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)" = "$(DAY16_CONTEXT)"
	helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
		--version "$(KAGENT_VERSION)" --namespace kagent --kubeconfig "$(DAY16_KUBECONFIG)" \
		-f "$(DAY16_CONFIG)/kagent-values.yaml" \
		--set-string controller.a2aBaseUrl="$(DAY17_GATEWAY_HOST)" \
		--wait --timeout 6m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n kagent rollout status \
		deployment/kagent-controller --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab exec -i \
		deployment/synthetic-llm -- python - \
		--gateway-base "$(DAY17_GATEWAY_HOST)/api/a2a/day16-lab/day16-agent" \
		< "$(LAB03)/src/gateway_runtime/a2a_path.py"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab exec -i \
		deployment/synthetic-llm -- python - \
		--gateway-base "$(DAY17_GATEWAY_HOST)/agents/day16" \
		< "$(LAB03)/src/gateway_runtime/a2a_path.py"
	@logs="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n agentgateway-system \
		logs deployment/agentgateway-proxy --since=5m)"; \
	printf '%s\n' "$$logs" | grep 'a2a.method=SendMessage' | tail -n 1; \
	printf '%s\n' "$$logs" | grep 'a2a.method=SendStreamingMessage' | tail -n 1; \
	printf '%s\n' "$$logs" | grep -q 'a2a.response.outcome=success'; \
	printf '%s\n' "$$logs" | grep -q 'a2a.task.state=TASK_STATE_COMPLETED'; \
	printf 'gateway-a2a-telemetry=PASS\n'

lab-03-runtime-byo:
	$(MAKE) -f "$(SELF_MAKEFILE)" lab-03-runtime-byo-up \
		KIND_BIN="$(KIND_BIN)" KUBECTL_BIN="$(KUBECTL_BIN)" \
		DAY16_KUBECONFIG="$(DAY16_KUBECONFIG)"
	$(MAKE) -f "$(SELF_MAKEFILE)" lab-03-runtime-byo-run \
		KIND_BIN="$(KIND_BIN)" KUBECTL_BIN="$(KUBECTL_BIN)" \
		DAY16_KUBECONFIG="$(DAY16_KUBECONFIG)"

lab-03-runtime-byo-up:
	$(MAKE) -f "$(SELF_MAKEFILE)" lab-03-runtime-kagent-up KAGENT_VERSION="$(DAY18_KAGENT_VERSION)" \
		KIND_BIN="$(KIND_BIN)" KUBECTL_BIN="$(KUBECTL_BIN)" \
		DAY16_KUBECONFIG="$(DAY16_KUBECONFIG)"
	docker build --pull=false -f "$(DAY18_BYO_FIXTURE)/Containerfile" \
		-t "$(DAY18_BYO_IMAGE)" "$(DAY18_BYO_FIXTURE)"
	"$(KIND_BIN)" load docker-image "$(DAY18_BYO_IMAGE)" --name "$(DAY16_KIND_NAME)"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" apply -f "$(DAY18_CONFIG)/kagent-resources.yaml"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab wait \
		--for=condition=Accepted agentgatewaybackend/day18-byo-a2a --timeout=2m
	@accepted=""; \
	for attempt in $$(seq 1 30); do \
		accepted="$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab \
			get httproute day18-byo-a2a \
			-o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}')"; \
		test "$$accepted" = "True" && break; \
		sleep 1; \
	done; \
	printf 'day18-byo-a2a-accepted=%s\n' "$$accepted"; test "$$accepted" = "True"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab rollout status \
		deployment/day18-synthetic-llm --timeout=3m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab wait \
		--for=condition=Accepted modelconfig/day18-parent-model --timeout=2m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab wait \
		--for=condition=Ready agent/day18-byo --timeout=4m
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab wait \
		--for=condition=Ready agent/day18-parent --timeout=4m

lab-03-runtime-byo-run:
	@test "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)" = "$(DAY16_CONTEXT)"
	@mkdir -p "$(LAB03)/artifacts/day18-live"
	@set -o pipefail; "$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day16-lab exec -i \
		deployment/synthetic-llm -- python - \
		--parent-url http://day18-parent.day18-lab.svc.cluster.local:8080/ \
		--byo-url http://day18-byo.day18-lab.svc.cluster.local:8080/ \
		< "$(LAB03)/src/gateway_runtime/byo_boundary.py" \
		| tee "$(LAB03)/artifacts/day18-live/terminal.txt"
	"$(KUBECTL_BIN)" --kubeconfig "$(DAY16_KUBECONFIG)" -n day18-lab get agents \
		-o custom-columns='NAME:.metadata.name,TYPE:.spec.type,READY:.status.conditions[?(@.type=="Ready")].status' \
		| tee "$(LAB03)/artifacts/day18-live/agent-status.txt"

lab-03-runtime-kagent-down:
	uv run --directory "$(LAB03)" gateway-runtime kagent-context-guard \
		--kubeconfig "$(DAY16_KUBECONFIG)" \
		--context "$$($(KUBECTL_BIN) --kubeconfig "$(DAY16_KUBECONFIG)" config current-context)"
	"$(KIND_BIN)" delete cluster --name "$(DAY16_KIND_NAME)" --kubeconfig "$(DAY16_KUBECONFIG)"

lab-03-runtime-down:
	uv run --directory "$(LAB03)" gateway-runtime clean --lab-root "$(LAB03)"
