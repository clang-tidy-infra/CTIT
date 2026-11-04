#!/bin/bash
set -euo pipefail

# Written in shell so CI can run it without Python dependencies.

IMAGE="${1:-ctit-runner}"

echo "Testing container image: $IMAGE"

commands=(
    "cmake --version"
    "ninja --version"
    "python3 -c \"import yaml; print('yaml OK')\""
    "git --version"
    "clang-21 --version"
    "mold --version"
    "echo '#include <version>' | clang++-21 -x c++ -dM -E - | grep '_GLIBCXX_RELEASE 15'"
)

for cmd in "${commands[@]}"; do
    echo "---"
    echo "Running: $cmd"
    docker run --rm "$IMAGE" bash -c "$cmd"
done

echo "---"
echo "Checking bundled toolchain profiles"
repo="$(cd "$(dirname "$0")/.." && pwd)"
docker run --rm -v "$repo:/ctit:ro" -w /ctit "$IMAGE" \
    python3 -m unittest -v tests.test_toolchain

echo "---"
echo "All container tests passed!"
