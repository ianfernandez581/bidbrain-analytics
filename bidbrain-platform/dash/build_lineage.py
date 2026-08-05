"""Build the per-client LINEAGE DIGESTS the internal AI assistant reads (internal_chat.py).

For every clients/client_<c>/ this concatenates the client's README.md (which carries the
data-contract table, cookbook and gotchas) with the header comment of every sql/*.sql view
(where each view documents what it computes and from which raw tables) into
bidbrain-platform/dash/lineage/<c>.txt. The digests are COMMITTED and shipped in the platform
image (Dockerfile COPY lineage), so the assistant can explain any dashboard number's provenance:
raw source -> BigQuery view -> job JSON key -> on-screen figure.

Re-run after a client README or sql/ change that matters to lineage:
    .\\.venv\\Scripts\\python.exe bidbrain-platform\\dash\\build_lineage.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "lineage"
SKIP = {"client_Adriatic_Furniture"}          # open sample dash, not behind the platform
MAX_README = 120_000
MAX_SQL_HEADER_LINES = 30


def sql_header(path):
    """The leading comment block of a view file (-- lines and/or a /* */ block)."""
    lines = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    in_block = False
    for ln in text.splitlines():
        s = ln.strip()
        if in_block:
            lines.append(ln)
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("--"):
            lines.append(ln)
        elif s.startswith("/*"):
            lines.append(ln)
            in_block = "*/" not in s
        elif s == "":
            if lines:
                break
        else:
            break
        if len(lines) >= MAX_SQL_HEADER_LINES:
            break
    return "\n".join(lines)


def build_one(cdir):
    key = re.sub(r"^client_", "", cdir.name).lower()
    parts = [f"# Lineage digest for dashboard '{key}' (from clients/{cdir.name}/)",
             "# Data contract: sql/<view>.sql (BigQuery view) -> job/main.py (data.json key) -> dashboard.html.",
             ""]
    readme = cdir / "README.md"
    if readme.exists():
        parts += ["## README.md (data contract, cookbook, gotchas)", "",
                  readme.read_text(encoding="utf-8", errors="replace")[:MAX_README], ""]
    sqls = sorted((cdir / "sql").glob("*.sql")) if (cdir / "sql").is_dir() else []
    if sqls:
        parts += ["## BigQuery views (sql/) - each header documents what the view computes and its raw sources", ""]
        for f in sqls:
            hdr = sql_header(f) or "(no header comment)"
            parts += [f"### {f.name}", hdr, ""]
    out = OUT / f"{key}.txt"
    out.write_text("\n".join(parts), encoding="utf-8")
    return key, out.stat().st_size


def main():
    OUT.mkdir(exist_ok=True)
    built = []
    for cdir in sorted((ROOT / "clients").iterdir()):
        if not cdir.is_dir() or not cdir.name.startswith("client_") or cdir.name in SKIP:
            continue
        built.append(build_one(cdir))
    for key, size in built:
        print(f"  lineage/{key}.txt  {size/1024:.0f} KB")
    print(f"{len(built)} digests -> {OUT}")


if __name__ == "__main__":
    main()
