.PHONY: help activate test lint format clean build-container test-container

help:
	@echo "Available targets:"
	@echo ""
	@echo "  make activate - Create venv and install dev dependencies"
	@echo "  make test     - Run tests with coverage"
	@echo "  make lint     - Run linters"
	@echo "  make format   - Format code"
	@echo "  make clean    - Clean development environment"
	@echo "  make build-container - Build the CTIT runner Docker image"
	@echo "  make test-container  - Test the CTIT runner Docker image"

activate:
	@echo "Setting up development environment..."
	python3 -m venv venv
	venv/bin/pip install -e ".[dev]"
	@echo "Done!"

test:
	@echo "Running tests..."
	venv/bin/python3 -m unittest discover -s tests -v
  
format:
	@echo "Formatting Python files..."
	venv/bin/black --exclude '/(llvm-project|test-projects|test_projects|venv)/' .

lint:
	@failed=""; \
	output=$$(venv/bin/black --check --color --exclude '/(llvm-project|test-projects|test_projects|venv)/' . 2>&1) || { echo "$$output"; failed="$$failed black"; }; \
	output=$$(venv/bin/yamllint -f colored -c .yamllint.yaml .github/ 2>&1) || { echo "$$output"; failed="$$failed yamllint"; }; \
	output=$$(venv/bin/shellcheck --wiki-link-count=0 --color=always build.sh apply_patch.sh tests/*.sh 2>&1) || { echo "$$output"; failed="$$failed shellcheck"; }; \
	output=$$(venv/bin/validate-pyproject pyproject.toml 2>&1) || { echo "$$output"; failed="$$failed validate-pyproject"; }; \
	output=$$(FORCE_COLOR=1 venv/bin/ruff check . 2>&1) || { echo "$$output"; failed="$$failed ruff"; }; \
	output=$$(venv/bin/mypy --color-output . 2>&1) || { echo "$$output"; failed="$$failed mypy"; }; \
	output=$$(venv/bin/zizmor --color=always --no-online-audits --config .zizmor.yml .github/ 2>&1) || { echo "$$output"; failed="$$failed zizmor"; }; \
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

CONTAINER_IMAGE = ctit-runner

build-container:
	@echo "Building CTIT runner container..."
	docker build -t $(CONTAINER_IMAGE) .github/workflows/containers/ctit-runner/

test-container: build-container
	bash tests/test_container.sh $(CONTAINER_IMAGE)

clean:
	rm -rf logs/
	rm -rf __pycache__/ testers/__pycache__/ tests/__pycache__/
	rm -rf *.egg-info/
