# Short commands for running Retrace. Each one needs Docker to be running.

# The demo commands run Retrace together with the built-in payment system.
COMPOSE = docker compose -f docker-compose.yml -f docker-compose.demo.yml

SCENARIO ?= double_refund
TRIALS ?= 3

.PHONY: demo eval test reset stop

demo: ## Start everything and cause one incident to investigate
	$(COMPOSE) up -d --build
	@echo "Waiting for the services to start..."
	@until curl -sf localhost:8000/openapi.json >/dev/null && curl -sf localhost:8002/openapi.json >/dev/null; do sleep 1; done
	$(COMPOSE) run --rm dev python -m scenarios.run $(SCENARIO)
	@echo "Open http://localhost:5173, select the incident and click Investigate."

eval: ## Measure how often the agent finds the right cause
	$(COMPOSE) run --rm dev python -m evals.run --trials $(TRIALS)

test: ## Run the linter and the tests
	$(COMPOSE) run --rm dev sh -c "ruff check . && pytest -q"

reset: ## Put the test-bed back to healthy
	$(COMPOSE) run --rm dev python -m scenarios.run reset

stop: ## Stop everything
	$(COMPOSE) down
