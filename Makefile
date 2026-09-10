# paperful maintainer docs + Docker targets.

.DEFAULT_GOAL := help

.PHONY: help docs docs-clean pages-site docker-build docker-doctor

help:
	@echo "paperful Makefile"
	@echo ""
	@echo "Docker (preferred deploy):"
	@echo "  docker-build      Build the paperful image via Compose"
	@echo "  docker-doctor     Run paperful doctor in the container"
	@echo ""
	@echo "Docs:"
	@echo "  docs              Build Sphinx HTML into docs/_build/html (requires .[docs])"
	@echo "  docs-clean        Remove Sphinx build artifacts"
	@echo "  pages-site        Assemble website/ + Sphinx guide into _site/ (GitHub Pages)"
	@echo ""
	@echo "Usage: docker compose run --rm paperful <cmd>"
	@echo "       uv sync --extra docs && make docs"

docker-build:
	docker compose build

docker-doctor:
	docker compose run --rm paperful doctor

docs:
	@bash scripts/release/build_docs.sh

docs-clean:
	@echo "Cleaning Sphinx build artifacts..."
	@rm -rf docs/_build _site
	@echo "Documentation build cleaned."

pages-site:
	@bash scripts/release/assemble_pages_site.sh
