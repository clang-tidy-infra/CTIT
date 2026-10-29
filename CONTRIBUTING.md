# Contributing to CTIT

## Development setup

```bash
make activate          # create venv/ and install CTIT with dev dependencies
make test              # run the unit tests
make lint              # run black, ruff, mypy, yamllint, shellcheck, zizmor, and more
make format            # format Python code with black
make build-container   # build the runner image locally
make test-container    # build the runner image and run its smoke tests
```

Running the analysis itself needs Linux and the tools listed in
[Run CTIT locally](docs/local-usage.md#requirements).

Pull request titles follow [Conventional Commits](https://www.conventionalcommits.org/).

## Releases

To publish a new version, see [docs/releasing.md](docs/releasing.md).
