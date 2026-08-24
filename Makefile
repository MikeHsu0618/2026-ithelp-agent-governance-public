LAB01 := $(CURDIR)/labs/01-unsafe-agent

.PHONY: lab-01-up lab-01-test lab-01-check lab-01-fixture lab-01-live lab-01-replay lab-01-down

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

lab-01-replay:
	@test -n "$(TRACE_ID)" || (printf '%s\n' 'usage: make lab-01-replay TRACE_ID=<32-hex-trace-id>' >&2; exit 2)
	uv run --directory "$(LAB01)" unsafe-agent replay --trace-id "$(TRACE_ID)"

lab-01-down:
	uv run --directory "$(LAB01)" unsafe-agent clean --lab-root .
