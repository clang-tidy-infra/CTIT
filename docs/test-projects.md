# Test projects

CTIT runs each check on these projects, each pinned to a fixed commit:

| Project    | Repository                                                |
|------------|-----------------------------------------------------------|
| Cppcheck   | [danmar/cppcheck](https://github.com/danmar/cppcheck)     |
| LLVM/Clang | [llvm/llvm-project](https://github.com/llvm/llvm-project) |
| Doxygen    | [doxygen/doxygen](https://github.com/doxygen/doxygen)     |
| POCO       | [pocoproject/poco](https://github.com/pocoproject/poco)   |
| Abseil     | [abseil/abseil-cpp](https://github.com/abseil/abseil-cpp) |
| curl       | [curl/curl](https://github.com/curl/curl)                 |
| stdexec    | [NVIDIA/stdexec](https://github.com/NVIDIA/stdexec)       |
| zstd       | [facebook/zstd](https://github.com/facebook/zstd)         |
| libuv      | [libuv/libuv](https://github.com/libuv/libuv)             |
| libgit2    | [libgit2/libgit2](https://github.com/libgit2/libgit2)     |
| Catch2     | [catchorg/Catch2](https://github.com/catchorg/Catch2)     |
| yaml-cpp   | [jbeder/yaml-cpp](https://github.com/jbeder/yaml-cpp)     |
| Assimp     | [assimp/assimp](https://github.com/assimp/assimp)         |

## Add a project

Projects are defined in [`testers/projects.json`](../testers/projects.json).
Each entry looks like this:

```json
"my-project": {
  "url": "https://github.com/example/my-project.git",
  "commit": "<full commit SHA>",
  "cmake_flags": ["-DBUILD_TESTING=OFF", "-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON"],
  "build_targets": ["generated_headers"],
  "cmake_source_subdir": "build/cmake",
  "file_regex": "(?!third_party/).*"
}
```

| Field                 | Required | Description                                                                                                                         |
|-----------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------|
| `url`                 | Yes      | Git URL to clone.                                                                                                                   |
| `commit`              | Yes      | Commit to pin. Pinning keeps results comparable between runs.                                                                       |
| `cmake_flags`         | No       | Extra CMake flags. Existing projects pass `-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON` and turn off tests and examples they do not need. |
| `build_targets`       | No       | Ninja targets to build before analysis, for projects that generate headers or sources.                                              |
| `cmake_source_subdir` | No       | Subdirectory containing the top-level `CMakeLists.txt`.                                                                             |
| `file_regex`          | No       | Regular expression, relative to the project root, selecting which files to analyze. Use it to skip vendored or generated code.      |

To try the new project before opening a pull request, run it locally as
described in [Run CTIT locally](local-usage.md).
