"""Toolchain profiles: an installed Clang and C++ standard library to test with.

A profile is a JSON file that selects an already installed Clang compiler and
C++ standard library. It only changes how test projects are configured and
built; the clang-tidy binary under test stays the same.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass

RECORD_FILE = "ctit-toolchain.json"

_STDLIB_FIELDS = {"libstdc++": "gcc_install_dir", "libc++": "include_dir"}
_COMMON_FIELDS = ("name", "stdlib", "cc", "cxx", "library_dir")
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def is_clang(compiler: str) -> bool:
    """Check if a compiler path/name is clang-based."""
    return "clang" in os.path.basename(compiler)


@dataclass(frozen=True)
class Toolchain:
    name: str
    stdlib: str
    cc: str
    cxx: str
    library_dir: str
    gcc_install_dir: str | None = None
    include_dir: str | None = None

    def fields(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @property
    def key(self) -> str:
        """The name plus a hash of every field, unique per configuration."""
        canonical = json.dumps(self.fields(), sort_keys=True)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return f"{self.name}-{digest}"

    def cxx_flags(self) -> list[str]:
        """Flags selecting the C++ headers; C compiles do not get them.

        CMake also passes CMAKE_CXX_FLAGS to C++ link lines. Link-only flags
        go to linker_flags(), because Clang warns about them when compiling.
        """
        if self.stdlib == "libstdc++":
            return [f"--gcc-install-dir={self.gcc_install_dir}"]
        return ["-nostdinc++", "-isystem", str(self.include_dir)]

    def linker_flags(self) -> list[str]:
        """Flags that link and run against the selected library directory.

        Clang ignores -stdlib when linking C, and CMake's feature checks see
        these flags, unlike CMAKE_CXX_STANDARD_LIBRARIES.
        """
        flags = [f"-L{self.library_dir}", f"-Wl,-rpath,{self.library_dir}"]
        if self.stdlib == "libc++":
            flags = ["-stdlib=libc++", *flags, "-lc++abi"]
        return flags

    def cmake_flags(self) -> list[str]:
        cxx_flags = " ".join(self.cxx_flags())
        linker_flags = " ".join(self.linker_flags())
        return [
            f"-DCMAKE_C_COMPILER={self.cc}",
            f"-DCMAKE_CXX_COMPILER={self.cxx}",
            f"-DCMAKE_CXX_FLAGS={cxx_flags}",
            f"-DCMAKE_EXE_LINKER_FLAGS={linker_flags}",
            f"-DCMAKE_SHARED_LINKER_FLAGS={linker_flags}",
            f"-DCMAKE_MODULE_LINKER_FLAGS={linker_flags}",
        ]


def load_toolchain(path: str) -> Toolchain:
    """Read and validate a profile; raises ValueError describing every problem."""
    with open(path) as f:
        data = json.load(f)
    stdlib = data.get("stdlib") if isinstance(data, dict) else None
    if stdlib not in _STDLIB_FIELDS:
        choices = ", ".join(_STDLIB_FIELDS)
        raise ValueError(
            f"{path}: expected a JSON object with 'stdlib' one of: {choices}"
        )

    expected = {*_COMMON_FIELDS, _STDLIB_FIELDS[stdlib]}
    errors = [f"missing field '{k}'" for k in sorted(expected - data.keys())]
    errors += [f"unknown field '{k}'" for k in sorted(data.keys() - expected)]
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))

    name = data["name"]
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        errors.append("'name' may only contain letters, digits, '.', '_' and '-'")
    for key in sorted(expected - {"name", "stdlib"}):
        value = data[key]
        if (
            not isinstance(value, str)
            or not os.path.isabs(value)
            or any(c.isspace() for c in value)
        ):
            errors.append(f"'{key}' must be an absolute path without whitespace")
        elif not os.path.exists(value):
            errors.append(f"'{key}' does not exist: {value}")
    for key in ("cc", "cxx"):
        if isinstance(data[key], str) and not is_clang(data[key]):
            errors.append(f"'{key}' must be a clang compiler: {data[key]}")
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))

    return Toolchain(**data)


def write_record(directory: str, toolchain: Toolchain | None) -> None:
    """Record which profile produced the builds or logs in a directory.

    The default toolchain has no record, so a stale one is removed.
    """
    path = os.path.join(directory, RECORD_FILE)
    if toolchain is None:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(directory, exist_ok=True)
    record = {**toolchain.fields(), "key": toolchain.key}
    with open(path, "w") as f:
        json.dump(record, f, indent=2, sort_keys=True)
        f.write("\n")


def read_record(directory: str) -> dict[str, str] | None:
    """The profile recorded in a directory, or None for the default toolchain."""
    path = os.path.join(directory, RECORD_FILE)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        record: dict[str, str] = json.load(f)
    return record
