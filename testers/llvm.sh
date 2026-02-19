#!/bin/bash
set -euo pipefail

CHECK_NAME="${1:-""}"

if [ -z "$CHECK_NAME" ]; then
    echo "Error: Check name is required."
    echo "Usage: $0 <check_name>"
    exit 1
fi

ROOT_DIR=$(pwd)
SOURCE_DIR="$ROOT_DIR/llvm-project"
BUILD_DIR="$SOURCE_DIR/build"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/llvm.log"
CLANG_TIDY_BIN="$BUILD_DIR/bin/clang-tidy"
RUN_TIDY_SCRIPT="$SOURCE_DIR/clang-tools-extra/clang-tidy/tool/run-clang-tidy.py"

echo "[LLVM] Starting integration test for check: $CHECK_NAME"

mkdir -p "$LOG_DIR"

if [ ! -f "$CLANG_TIDY_BIN" ]; then
    echo "Error: clang-tidy binary not found at $CLANG_TIDY_BIN"
    echo "Please run ./build.sh first to build llvm and clang-tidy."
    exit 1
fi

if [ ! -f "$RUN_TIDY_SCRIPT" ]; then
    echo "Error: run-clang-tidy.py not found at $RUN_TIDY_SCRIPT"
    exit 1
fi

if [ ! -f "$BUILD_DIR/compile_commands.json" ]; then
    echo "Error: compile_commands.json not found in $BUILD_DIR"
    echo "Please run ./build.sh first."
    exit 1
fi

echo "[LLVM] Removing existing .clang-tidy files..."
find "$SOURCE_DIR" -name ".clang-tidy" -delete

echo "[LLVM] Building additional targets required for analyzing clang..."

ninja -C "$BUILD_DIR" \
    clang \
    clangAnalysisFlowSensitiveResources \
    clang-nvlink-wrapper \
    clang-sycl-linker \
    clang-installapi \
    clang-scan-deps \
    clang-linker-wrapper

echo "[LLVM] Running clang-tidy on Clang codebase..."

TARGET_DIR="$SOURCE_DIR/clang"
TARGET_REGEX="^$TARGET_DIR/.*(?<!\.S)$"

TIDY_ARGS=("-clang-tidy-binary" "$CLANG_TIDY_BIN" "-p" "$BUILD_DIR" "-checks=-*,$CHECK_NAME" "-quiet")
if [ -n "${TIDY_CONFIG:-}" ]; then
    TIDY_ARGS+=("-config=$TIDY_CONFIG")
fi

python3 "$RUN_TIDY_SCRIPT" \
    "${TIDY_ARGS[@]}" \
    "$TARGET_REGEX" \
    2>&1 | tee "$LOG_FILE" || true

echo "[LLVM] Finished. Log saved to $LOG_FILE"
