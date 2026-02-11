import os
import glob
import re
import sys

LOG_DIR = "logs"
OUTPUT_FILE = "issue.md"

# TODO: In the future, we can dynamically get the commit hash.
PROJECT_URLS = {
    "cppcheck": "https://github.com/danmar/cppcheck/blob/main",
}

def parse_log_file(log_path):
    project_name = os.path.basename(log_path).replace(".log", "")

    warnings = 0
    errors = 0
    crash = False
    details = []

    # Regex to capture standard clang-tidy output:
    issue_pattern = re.compile(r'^(.+):(\d+):(\d+): (warning|error): (.+) \[(.+)\]$')

    try:
        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            line = line.strip()

            # Check for crash indicators
            if "Segmentation fault" in line or "Stack dump:" in line:
                crash = True
                continue

            match = issue_pattern.match(line)
            if match:
                file_path, line_num, col_num, severity, message, check_name = match.groups()

                if severity == "warning":
                    warnings += 1
                elif severity == "error":
                    errors += 1

                if f"test-projects/{project_name}/" in file_path:
                    rel_path = file_path.split(f"test-projects/{project_name}/")[1]
                else:
                    rel_path = os.path.basename(file_path)

                context = ""
                if i + 1 < len(lines) and lines[i+1].strip() and not lines[i+1].startswith("/"):
                     context = lines[i+1].strip()

                details.append({
                    "project": project_name,
                    "file": rel_path,
                    "line": line_num,
                    "col": col_num,
                    "severity": severity,
                    "message": message,
                    "check": check_name,
                    "context": context
                })

    except Exception as e:
        print(f"Error parsing {log_path}: {e}")

    return {
        "project": project_name,
        "warnings": warnings,
        "errors": errors,
        "crash": crash,
        "details": details
    }

def generate_markdown(results):
    with open(OUTPUT_FILE, 'w') as f:
        f.write("### 🧪 Clang-Tidy Integration Test Results\n\n")
        f.write("| Project | Status | Warnings | Errors | Crash |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- |\n")

        for res in results:
            status = "✅ Pass"
            if res['crash']: status = "💥 CRASH"
            elif res['errors'] > 0: status = "❌ Fail"
            elif res['warnings'] > 0: status = "⚠️ Warnings"

            crash_mark = "YES" if res['crash'] else "-"
            f.write(f"| **{res['project']}** | {status} | {res['warnings']} | {res['errors']} | {crash_mark} |\n")
        f.write("\n---\n")
        for res in results:
            if not res['details'] and not res['crash']:
                continue

            f.write(
                f"\n<details>\n<summary><strong>🔍 {res['project']} Details ({res['warnings']} warnings, {res['errors']} errors)</strong></summary>\n\n"
            )

            if res["crash"]:
                f.write("🚨 **CRASH DETECTED** in this project!\n\n")

            files_dict = {}
            for item in res['details']:
                if item['file'] not in files_dict:
                    files_dict[item['file']] = []
                files_dict[item['file']].append(item)

            for file_path, items in files_dict.items():
                base_url = PROJECT_URLS.get(res['project'], "#")

                f.write(f"#### 📄 `{file_path}`\n")

                for item in items:
                    if base_url != "#":
                         link = f"{base_url}/{file_path}#L{item['line']}"
                         loc_text = f"[{item['line']}:{item['col']}]({link})"
                    else:
                         loc_text = f"{item['line']}:{item['col']}"

                    icon = "🛑" if item['severity'] == "error" else "⚠️"

                    f.write(f"- {icon} **{loc_text}**: {item['message']} `[{item['check']}]`\n")
                    if item['context']:
                        f.write(f"  ```cpp\n  {item['context']}\n  ```\n")

            f.write("\n</details>\n")

if __name__ == "__main__":
    if not os.path.exists(LOG_DIR):
        print(f"Log directory '{LOG_DIR}' not found.")
        sys.exit(0)

    log_files = glob.glob(os.path.join(LOG_DIR, "*.log"))
    if not log_files:
        print("No log files found.")
        sys.exit(0)

    all_results = []
    for log_file in log_files:
        all_results.append(parse_log_file(log_file))

    all_results.sort(key=lambda x: x['project'])

    generate_markdown(all_results)
    print(f"Report generated: {OUTPUT_FILE}")
