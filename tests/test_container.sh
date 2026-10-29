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
)

for cmd in "${commands[@]}"; do
    echo "---"
    echo "Running: $cmd"
    docker run --rm "$IMAGE" bash -c "$cmd"
done

echo "---"
echo "All container tests passed!"
