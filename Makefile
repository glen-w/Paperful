# paperful maintainer docs + optional Docker targets.

.DEFAULT_GOAL := help

.PHONY: help docs docs-clean pages-site docker-build docker-build-heavy docker-doctor e2e-nba e2e-stack

help:
	@echo "paperful Makefile"
	@echo ""
	@echo "Usual path: docker compose up  → http://127.0.0.1:8765  (see README)"
	@echo ""
	@echo "Docker (optional pack):"
	@echo "  docker-build        Build image (PAPERFUL_IMAGE_MODE from .env, else light)"
	@echo "  docker-build-heavy  Build heavy image (llm + rag + browser-agent)"
	@echo "  docker-doctor       Run paperful doctor in the container"
	@echo ""
	@echo "Docs:"
	@echo "  docs              Build Sphinx HTML into docs/_build/html (requires .[docs]; DOCS_STRICT=1 for CI parity)"
	@echo "  docs-clean        Remove Sphinx build artifacts"
	@echo "  pages-site        Assemble website/ + Sphinx guide into _site/ (GitHub Pages)"
	@echo ""
	@echo "E2E (opt-in, not CI):"
	@echo "  e2e-stack         All-in live E2E: TOPIC=... EFFORT=low|med|high [QUERY=] [YEAR_FROM=] [YEAR_TO=]"
	@echo "  e2e-nba           Alias: TOPIC=NBA EFFORT=low"
	@echo ""
	@echo "Usage: uv run paperful <cmd>"
	@echo "       docker compose run --rm paperful <cmd>   # optional image"
	@echo "       uv sync --extra docs && make docs"

docker-build:
	docker compose build

docker-build-heavy:
	PAPERFUL_IMAGE_MODE=heavy docker compose build

docker-doctor:
	docker compose run --rm paperful doctor --guide

docs:
	@bash scripts/release/build_docs.sh

docs-clean:
	@echo "Cleaning Sphinx build artifacts..."
	@rm -rf docs/_build _site
	@echo "Documentation build cleaned."

pages-site:
	@bash scripts/release/assemble_pages_site.sh

e2e-stack:
	@test -n "$(TOPIC)" || (echo "Usage: make e2e-stack TOPIC='your keyword' EFFORT=low|med|high [QUERY='...']"; exit 1)
	PAPERFUL_E2E=1 uv run python scripts/e2e_stack.py --topic "$(TOPIC)" --effort "$(or $(EFFORT),low)" \
		$(if $(QUERY),--query "$(QUERY)",) \
		$(if $(YEAR_FROM),--year-from $(YEAR_FROM),) \
		$(if $(YEAR_TO),--year-to $(YEAR_TO),)

e2e-nba:
	$(MAKE) e2e-stack TOPIC=NBA EFFORT=low
