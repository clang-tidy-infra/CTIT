#!/bin/bash
set -euo pipefail

SOURCE_DIR="llvm-project/llvm"
BUILD_DIR="llvm-project/build"
CMAKE_BUILD_TYPE="Release"
LLVM_ENABLE_PROJECTS="clang;clang-tools-extra"

echo "Starting build process"

mkdir -p "$BUILD_DIR"

CMAKE_EXTRA_ARGS=()
if [ -n "${LLVM_USE_LINKER:-}" ]; then
    CMAKE_EXTRA_ARGS+=("-DLLVM_USE_LINKER=$LLVM_USE_LINKER")
fi

echo "Configuring CMake"
CMAKE_EXTRA_ARGS=()
if [ -n "${LLVM_USE_LINKER:-}" ]; then
    CMAKE_EXTRA_ARGS+=("-DLLVM_USE_LINKER=$LLVM_USE_LINKER")
fi

if command -v sccache >/dev/null 2>&1; then
    echo "Using sccache"
    CMAKE_EXTRA_ARGS+=("-DCMAKE_C_COMPILER_LAUNCHER=sccache")
    CMAKE_EXTRA_ARGS+=("-DCMAKE_CXX_COMPILER_LAUNCHER=sccache")
fi

cmake -G Ninja \
    -S "$SOURCE_DIR" \
    -B "$BUILD_DIR" \
    -DLLVM_ENABLE_PROJECTS="$LLVM_ENABLE_PROJECTS" \
    -DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE" \
    -DLLVM_ENABLE_ASSERTIONS=ON \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DLLVM_TARGETS_TO_BUILD="X86" \
    -DLLVM_INCLUDE_BENCHMARKS=OFF \
    -DLLVM_INCLUDE_EXAMPLES=OFF \
    -DLLVM_INCLUDE_TESTS=OFF \
    -DCLANG_TIDY_ENABLE_STATIC_ANALYZER=OFF \
    "${CMAKE_EXTRA_ARGS[@]}"

echo "Building clang-tidy"
ninja -C "$BUILD_DIR" clang-tidy

echo "Build completed successfully!"
