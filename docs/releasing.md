# Releasing CTIT

A release is a GitHub release with a `vX.Y.Z` tag. Publishing it starts the
[Release](../.github/workflows/release.yaml) workflow, which builds the package
and uploads it to [PyPI](https://pypi.org/project/ctit/).
The package version is taken from the tag.

## Steps

1. Go to [Releases](https://github.com/clang-tidy-infra/CTIT/releases) and
   click **Draft a new release**.
2. Under **Choose a tag**, type the new tag, e.g. `v0.3.0`, and select
   **Create new tag on publish**. Leave the target as `main`.
3. Click **Generate release notes** and edit them if you want.
4. Click **Publish release**.
5. Check that the [Release run](https://github.com/clang-tidy-infra/CTIT/actions/workflows/release.yaml)
   passed and the new version is on [PyPI](https://pypi.org/project/ctit/).
