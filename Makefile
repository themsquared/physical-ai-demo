# physical-ai-demo — every target maps to a pillar (see CLAUDE.md / PRD §2)

COMPOSE ?= docker compose
PY ?= python3
VENV = .venv
VENVPY = $(VENV)/bin/python

.PHONY: setup jwts up down ci-up lint test \
        verify-m0 verify-m1 verify-failover verify-safety verify-m4 \
        verify-speed verify-repeat verify-all bench demo

$(VENV):
	$(PY) -m venv $(VENV)
	$(VENVPY) -m pip -q install -U pip
	$(VENVPY) -m pip -q install -r requirements-dev.txt

setup: $(VENV) jwts  ## venv + JWT material

jwts: $(VENV)
	$(VENVPY) scripts/gen-jwts.py gateway/jwt

up: jwts            ## demo stack, reproducible deterministic brain (no models/GPU)
	$(COMPOSE) up -d --build world amr-1 amr-2 arm-1 mock-llm mock-edge gateway \
		orchestrator amr-1-cognition amr-2-cognition arm-1-cognition \
		otel-collector prometheus grafana

up-ollama: jwts     ## add the real Ollama rungs (first run pulls models; slow on Mac CPU)
	$(COMPOSE) up -d ollama-primary ollama-fallback
	@echo "set PRIMARY_BASE_URL/FALLBACK_BASE_URL to the ollama rungs in .env, then: make up"

ci-up: jwts         ## CI stack: deterministic brains only, no Ollama
	$(COMPOSE) up -d --build world amr-1 amr-2 arm-1 mock-llm mock-edge gateway \
		orchestrator amr-1-cognition amr-2-cognition arm-1-cognition \
		otel-collector

down:
	$(COMPOSE) down -v --remove-orphans

lint: $(VENV)
	$(VENVPY) -m ruff check .
	$(VENVPY) -m ruff format --check .

test: $(VENV)
	$(VENVPY) -m pytest tests/unit -q

# ---- verify matrix (acceptance contract) ----

verify-m0:
	$(COMPOSE) config -q && echo "compose config OK"
	$(MAKE) lint test

verify-m1: $(VENV)
	$(VENVPY) -m pytest tests/integration/test_m1_world_robots.py -q -x

verify-failover:
	bash scripts/verify-failover.sh

verify-safety: $(VENV)
	$(VENVPY) -m pytest tests/integration/test_governance.py -q -x
	bash scripts/verify-budget.sh

verify-m4: $(VENV)
	bash scripts/run-mission.sh --verify
	$(VENVPY) -m pytest tests/integration/test_m4_fleet.py -q -x

verify-speed: $(VENV)
	$(VENVPY) bench/bench.py --assert-slo

verify-repeat: $(VENV)
	bash scripts/verify-repeat.sh

verify-chaos: $(VENV)
	$(VENVPY) -m pytest tests/integration/test_chaos.py -q

verify-all: verify-m0 verify-m1 verify-failover verify-safety verify-m4 verify-speed verify-repeat verify-chaos

bench: $(VENV)
	$(VENVPY) bench/bench.py

demo:
	bash demo.sh
