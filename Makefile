.PHONY: help activate test lint clean

help:
	@echo "Available targets:"
	@echo ""
	@echo "  make activate - Create venv and install dev dependencies"
	@echo "  make lint     - Run linters/formatters"

activate:
	@echo "Setting up development environment..."
	python3 -m venv venv
	venv/bin/pip install -e ".[dev]"
	@echo "Done!"

lint:
	@echo "Running black formatter..."
	venv/bin/black .
	@echo "Running yamllint..."
	venv/bin/yamllint -c .yamllint.yaml .github/
	@echo "Validating pyproject.toml..."
	venv/bin/validate-pyproject pyproject.toml
