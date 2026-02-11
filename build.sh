#!/bin/bash
set -euo pipefail

SOURCE_DIR="llvm-project/llvm"
BUILD_DIR="llvm-project/build"
CMAKE_BUILD_TYPE="Release"
LLVM_ENABLE_PROJECTS="clang;clang-tools-extra"

echo "Starting build process"

mkdir -p "$BUILD_DIR"

echo "Configuring CMake"
cmake -G Ninja \
    -S "$SOURCE_DIR" \
    -B "$BUILD_DIR" \
    -DLLVM_ENABLE_PROJECTS="$LLVM_ENABLE_PROJECTS" \
    -DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE" \
    -DLLVM_ENABLE_ASSERTIONS=ON \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

echo "Building clang-tidy"
ninja -C "$BUILD_DIR" clang-tidy

echo "Build completed successfully!"
