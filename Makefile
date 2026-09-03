LAB01 := $(CURDIR)/labs/01-unsafe-agent
LAB02 := $(CURDIR)/labs/02-identity-boundary

.PHONY: lab-01-up lab-01-test lab-01-check lab-01-fixture lab-01-live lab-01-replay lab-01-down \
	lab-02-up lab-02-test lab-02-check lab-02-demo lab-02-delegation lab-02-passthrough lab-02-oauth lab-02-down \
	lab-03-check lab-03-fixture lab-03-live

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

lab-02-down:
	uv run --directory "$(LAB02)" identity-boundary clean --lab-root "$(LAB02)"
