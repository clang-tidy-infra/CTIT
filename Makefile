.PHONY: help activate test lint format clean

help:
	@echo "Available targets:"
	@echo ""
	@echo "  make activate - Create venv and install dev dependencies"
	@echo "  make test     - Run tests with coverage"
	@echo "  make lint     - Run linters"
	@echo "  make format   - Format code"
  @echo "  make clean    - Clean development environment"

activate:
	@echo "Setting up development environment..."
	python3 -m venv venv
	venv/bin/pip install -e ".[dev]"
	@echo "Done!"

test:
	@echo "Running tests..."
	python3 -m unittest discover -s tests -v
  
format:
	@echo "Formatting Python files..."
	venv/bin/black --exclude '/(llvm-project|test-projects|venv)/' .

lint:
	@failed=""; \
	output=$$(venv/bin/black --check --color --exclude '/(llvm-project|test-projects|venv)/' . 2>&1) || { echo "$$output"; failed="$$failed black"; }; \
	output=$$(venv/bin/yamllint -c .yamllint.yaml .github/ 2>&1) || { echo "$$output"; failed="$$failed yamllint"; }; \
	output=$$(venv/bin/shellcheck --wiki-link-count=0 --color=always build.sh apply_patch.sh testers/*.sh 2>&1) || { echo "$$output"; failed="$$failed shellcheck"; }; \
	output=$$(venv/bin/validate-pyproject pyproject.toml 2>&1) || { echo "$$output"; failed="$$failed validate-pyproject"; }; \
	if [ -n "$$failed" ]; then \
		msg="FAILED LINTERS:$$failed"; \
		line=$$(printf '%*s' $${#msg} '' | tr ' ' '-'); \
		echo "\n$$line"; \
		echo "$$msg"; \
		echo "$$line"; \
		exit 1; \
	else \
		echo "All linters passed."; \
	fi

clean:
	rm -rf logs/
	rm -rf __pycache__/ testers/__pycache__/ tests/__pycache__/
	rm -rf *.egg-info/
