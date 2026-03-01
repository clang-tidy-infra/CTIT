# AGENTS.md - False Positive Analysis Instructions

You are a static analysis expert. Your job is to analyze clang-tidy warnings
from integration test results and determine whether each warning is a
**True Positive (TP)** or **False Positive (FP)**.

## Project Layout

```text
.
├── issue.md                          # Generated report with all warnings
├── test_projects/<project>/          # Cloned source of each test project
│   └── <relative_path>               # Files referenced in warnings
├── llvm-project/                     # LLVM monorepo (with PR patch applied)
│   └── clang-tools-extra/
│       ├── clang-tidy/<module>/      # Check implementations (.cpp/.h)
│       └── docs/clang-tidy/checks/
│           └── <module>/<name>.rst   # Check documentation
└── projects.json                     # Test project definitions
```

### Locating warning source code

Warnings in `issue.md` show relative paths like `src/foo.cpp` under a project
heading. The full path is `test_projects/<project_name>/<relative_path>`.

### Locating the check implementation and documentation

For a check named `<module>-<rest>` (e.g. `bugprone-argument-comment`):

- **Source** - search under `llvm-project/clang-tools-extra/clang-tidy/<module>/`
  for files whose name matches the check (hyphen-separated names map to
  CamelCase filenames, e.g. `ArgumentCommentCheck.cpp`).
- **Docs** - `llvm-project/clang-tools-extra/docs/clang-tidy/checks/<module>/<rest>.rst`
  (e.g. `bugprone/argument-comment.rst`).

## Analysis Procedure

Process **every** warning in `issue.md`, in the order they appear:

1. **Read the warning** - note the project, file, line, message, and check name.
2. **Read the source code** - open the file and read ±30 lines around the
   flagged line to understand intent and surrounding context.
3. **Read the check documentation** - understand what the check is designed to
   detect and any documented limitations.
4. **Read the check implementation** (when the doc alone is insufficient) —
   look at matcher logic and diagnostic conditions to understand edge cases.
5. **Render a verdict**:
   - **TP** - the warning correctly identifies a real defect, code smell, or
     deviation from the check's documented rule.
   - **FP** - the warning is incorrect; the flagged code is valid, intentional,
     or the check misfires due to an edge case (e.g. macros, templates,
     platform-specific code, intentional patterns).
   - **Uncertain** - you lack enough context to decide confidently.
6. **Write a rationale** - 1–3 sentences explaining your reasoning.

## Output Format

Append your analysis to the **end** of `issue.md`.
Do **NOT** modify anything that already exists in the file.
Use exactly this format:

```markdown

---

### 🤖 AI FP Analysis

| # | Project | File | Line | Verdict | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | project | path/to/file.cpp | 42 | TP | Brief explanation |
| 2 | project | path/to/other.cpp | 17 | FP | Brief explanation |

**Summary**: X True Positives, Y False Positives, Z Uncertain out of N total warnings.
```

## Rules

- Process warnings **sequentially** in the order they appear.
- If a project section shows **CRASH** with no warnings, skip it.
- If `issue.md` contains **no warnings**, append only:
  `No warnings to analyze.`
- Be **conservative** - only mark FP when you are confident the warning is wrong.
- Never remove or rewrite existing content in `issue.md`.
