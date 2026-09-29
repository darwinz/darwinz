#!/usr/bin/env python3
"""Chart the languages in code darwinz has actually written.

Clones every source repo (personal + Fullspec-Studio), sums the lines added
in darwinz's own commits per language, and writes:

    <out>/languages.svg   the chart, styled like assets/spectrum.svg
    <out>/languages.json  the raw numbers

Needs `gh` signed in with read access to the private repos, and git set up to
use it (`gh auth setup-git`), so no token ever goes into a clone URL.

    /usr/bin/python3 scripts/build_languages.py --out dist [--limit 20]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import subprocess
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OWNERS = ["darwinz", "Fullspec-Studio"]

# Names and emails my commits have been authored under (matched by `git log --author`).
AUTHORS = [
    "darwinz",
    "Brandon Johnson",
    "brandon@moov.io",
    "brandon.johnson@moov.io",
]

MAX_REPO_KB = 1_000_000  # skip repos over ~1 GB
CLONE_TIMEOUT = 300
MAX_FILE_LINES = 5_000  # a single file change bigger than this is almost always generated or imported
MAX_COMMIT_LINES = 10_000  # nobody hand-writes this much in one commit; it's a framework or site import

# Markup, styling, and build files: still counted toward MAX_COMMIT_LINES, but left off
# the chart, which is about programming languages. HCL stays in as infrastructure code.
NOT_CHARTED = {"HTML", "CSS", "SCSS", "Makefile", "Dockerfile"}

# extension (or exact file name) -> (language, GitHub linguist color)
LANGUAGES = {
    ".go": ("Go", "#00ADD8"),
    ".py": ("Python", "#3572A5"),
    ".ts": ("TypeScript", "#3178c6"),
    ".tsx": ("TypeScript", "#3178c6"),
    ".mts": ("TypeScript", "#3178c6"),
    ".js": ("JavaScript", "#f1e05a"),
    ".jsx": ("JavaScript", "#f1e05a"),
    ".mjs": ("JavaScript", "#f1e05a"),
    ".cjs": ("JavaScript", "#f1e05a"),
    ".php": ("PHP", "#4F5D95"),
    ".rb": ("Ruby", "#701516"),
    ".ex": ("Elixir", "#6e4a7e"),
    ".exs": ("Elixir", "#6e4a7e"),
    ".rs": ("Rust", "#dea584"),
    ".java": ("Java", "#b07219"),
    ".kt": ("Kotlin", "#A97BFF"),
    ".scala": ("Scala", "#c22d40"),
    ".lua": ("Lua", "#000080"),
    ".swift": ("Swift", "#F05138"),
    ".dart": ("Dart", "#00B4AB"),
    ".m": ("Objective-C", "#438eff"),
    ".c": ("C", "#555555"),
    ".h": ("C", "#555555"),
    ".cpp": ("C++", "#f34b7d"),
    ".cc": ("C++", "#f34b7d"),
    ".cs": ("C#", "#178600"),
    ".sh": ("Shell", "#89e051"),
    ".bash": ("Shell", "#89e051"),
    ".zsh": ("Shell", "#89e051"),
    ".tf": ("HCL", "#844FBA"),
    ".hcl": ("HCL", "#844FBA"),
    ".sql": ("SQL", "#e38c00"),
    ".html": ("HTML", "#e34c26"),
    ".css": ("CSS", "#663399"),
    ".scss": ("SCSS", "#c6538c"),
    ".vue": ("Vue", "#41b883"),
    ".svelte": ("Svelte", "#ff3e00"),
    ".astro": ("Astro", "#ff5a03"),
    ".vim": ("Vim Script", "#199f4b"),
    ".proto": ("Protocol Buffer", "#6a9fb5"),
    ".graphql": ("GraphQL", "#e10098"),
    ".gql": ("GraphQL", "#e10098"),
    ".groovy": ("Groovy", "#4298b8"),
    ".pl": ("Perl", "#0298c3"),
    ".r": ("R", "#198CE7"),
    "Dockerfile": ("Dockerfile", "#384d54"),
    "Makefile": ("Makefile", "#427819"),
}

SKIP_PATH = re.compile(
    r"(^|/)(vendor|node_modules|dist|build|out|\.next|coverage|third_party|__generated__|generated)/"
    # editor installs committed with dotfiles: language servers, plugin managers, backups
    r"|(^|/)(lsp_servers|mason|plugged)/|(^|/)pack/[^/]+/(start|opt)/|packer_compiled\.lua$|\.bak/"
    # frameworks and CMSs committed alongside the code written on top of them
    r"|(^|/)(wp-admin|wp-includes)/|(^|/)wp-content/(plugins|themes/twenty\w*)/|(^|/)app/code/(core|community)/"
    r"|(^|/)(lib|js|skin)/(mage|varien|prototype|scriptaculous|extjs)/|(^|/)(site-packages|venv|\.venv|env/lib)/"
    r"|\.min\.(js|css)$|\.(pb|gen|generated)\.\w+$|_pb2\.py$|\.d\.ts$|(^|/)package-lock\.json$"
)

BG, BORDER, CREAM, MUTED = "#1a1b27", "#e4e2e2", "#f5ecd9", "#9aa0b8"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def run(*cmd: str, cwd: Path | None = None, timeout: int | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, timeout=timeout).stdout


def list_repos() -> list[dict]:
    repos = []
    for owner in OWNERS:
        out = run("gh", "repo", "list", owner, "--source", "--limit", "1000", "--json", "nameWithOwner,diskUsage,isEmpty")
        repos += [r for r in json.loads(out) if not r["isEmpty"]]
    return repos


def language_for(path: str) -> tuple[str, str] | None:
    if SKIP_PATH.search(path):
        return None
    name = path.rsplit("/", 1)[-1]
    if name in LANGUAGES:
        return LANGUAGES[name]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return LANGUAGES.get(ext)


LAYER_WINDOW_DAYS = 90

# Commits whose diffs mention these count their code toward the AI layer.
AI_PATTERN = (
    r"anthropic|openai|bedrock|langchain|llama_?index|@ai-sdk|modelcontextprotocol|FastMCP"
    r"|embeddings?\(|chat\.completions|messages\.create"
)
CODE_EXT = {
    ".go", ".py", ".rb", ".ex", ".exs", ".rs", ".java", ".kt", ".scala", ".php", ".cs",
    ".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs", ".swift", ".dart",
}
FRONTEND_EXT = {".tsx", ".jsx", ".vue", ".svelte", ".astro", ".css", ".scss", ".html", ".swift", ".dart"}
BACKEND_EXT = {".go", ".py", ".rb", ".ex", ".exs", ".rs", ".java", ".scala", ".php", ".cs", ".ts", ".mts", ".js", ".mjs", ".cjs"}

LAYER_RULES = [
    ("Systems Design", re.compile(
        r"(^|/)(adrs?|rfcs?|architecture|design)/.*\.mdx?$|(openapi|swagger|asyncapi)[^/]*\.(ya?ml|json)$"
        r"|\.proto$|\.(graphql|gql)$"
    )),
    ("DevOps", re.compile(
        r"(^|/)\.github/workflows/|(^|/)\.gitlab-ci|(^|/)\.circleci/|(^|/)(Jenkinsfile|Makefile|Taskfile\.ya?ml)$"
        r"|(^|/)\.goreleaser|(^|/)(prometheus|grafana|alertmanager|loki)/|\.(sh|bash|zsh)$"
    )),
    ("Infra", re.compile(
        r"\.(tf|tfvars|hcl|nomad)$|(^|/)Dockerfile[^/]*$|(^|/)docker-compose[^/]*$|(^|/)(fly\.toml|vercel\.json|serverless\.ya?ml)$"
        r"|(^|/)(k8s|kubernetes|helm|charts|manifests|deploy|infra|infrastructure|cdk|packer|ansible|terraform)/"
    )),
    ("Data", re.compile(
        r"\.(sql|ipynb|prisma)$|(^|/)(migrations?|alembic|dbt|seeds?|dags|etl|pipelines?)/"
    )),
    ("AI", re.compile(r"(^|/)(prompts?|evals?|agents?|llm|rag|embeddings?|mcp)/|\.prompt$")),
]


def layer_for(path: str, ai_commit: bool) -> str | None:
    """Which layer of the spectrum a changed file belongs to, if any."""
    if SKIP_PATH.search(path):
        return None
    name = path.rsplit("/", 1)[-1]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for layer, rule in LAYER_RULES:
        if rule.search(path):
            return layer
    if ai_commit and ext in CODE_EXT:
        return "AI"
    if ext in FRONTEND_EXT:
        return "Frontend"
    if ext in {".ts", ".js", ".mjs"} and re.search(r"(^|/)(components|pages|app|ui|frontend|web|client|views|hooks|routes)/", path):
        return "Frontend"
    if ext in BACKEND_EXT:
        return "Backend"
    return None


def renamed_target(path: str) -> str:
    """`src/{old => new}/a.go` or `old.go => new.go` -> the new path."""
    if "=>" not in path:
        return path
    if "{" in path:
        return re.sub(r"\{[^{}]*? => ([^{}]*?)\}", r"\1", path).replace("//", "/")
    return path.split(" => ", 1)[1]


def analyze(repo: str, workdir: Path) -> tuple[str, list, list, str | None]:
    """Returns (repo, [(commit, language, lines)], [(commit, layer, lines)] for recent commits, error)."""
    dest = workdir / repo.replace("/", "__")
    since = f"--since={LAYER_WINDOW_DAYS} days ago"
    try:
        run("git", "clone", "--bare", "--quiet", f"https://github.com/{repo}.git", str(dest), timeout=CLONE_TIMEOUT)
        author_args = [f"--author={a}" for a in AUTHORS]
        log = run(
            "git", "log", "HEAD", "--no-merges", "--numstat", "--format=@%H %ct", *author_args,
            cwd=dest, timeout=CLONE_TIMEOUT,
        )
        ai_commits = set(run(
            "git", "log", "HEAD", "--no-merges", since, "-E", f"-G{AI_PATTERN}", "--format=%H", *author_args,
            cwd=dest, timeout=CLONE_TIMEOUT,
        ).split())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return repo, [], [], (getattr(e, "stderr", "") or str(e)).strip().splitlines()[-1][:200]
    finally:
        subprocess.run(["rm", "-rf", str(dest)])

    cutoff = dt.datetime.now().timestamp() - LAYER_WINDOW_DAYS * 86400
    rows, layer_rows = [], []
    commit, recent, langs, layers = None, False, [], []

    def flush() -> None:
        # bulk imports are dropped from both charts
        if langs and sum(n for _, _, n in langs) <= MAX_COMMIT_LINES:
            rows.extend(r for r in langs if r[1] not in NOT_CHARTED)
        if layers and sum(n for _, _, n in layers) <= MAX_COMMIT_LINES:
            layer_rows.extend(layers)
        langs.clear()
        layers.clear()

    for line in log.splitlines():
        if line.startswith("@"):
            flush()
            commit, ts = line[1:].split()
            recent = int(ts) >= cutoff
            continue
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":  # blank line or binary file
            continue
        added, path = int(parts[0]), renamed_target(parts[2])
        if not 0 < added <= MAX_FILE_LINES:
            continue
        lang = language_for(path)
        if lang:
            langs.append((commit, lang[0], added))
        if recent:
            layer = layer_for(path, commit in ai_commits)
            if layer:
                layers.append((commit, layer, added))
    flush()
    return repo, rows, layer_rows, None


def readable(hex_color: str) -> str:
    """Lighten colors that would vanish on the dark card (e.g. Lua's navy)."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum >= 70:
        return hex_color
    t = 0.45
    return "#" + "".join(f"{round(c + (255 - c) * t):02x}" for c in (r, g, b))


def compact(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


def render(stats: dict) -> str:
    W, PAD, TOP = 840, 24, 12
    colors = {name: color for name, color in LANGUAGES.values()}
    total = 100.0
    top = stats["languages"][:TOP]
    rest = stats["languages"][TOP:]
    other = total - sum(l["percent"] for l in top)
    cols, row_h = 4, 44
    rows = -(-len(top) // cols)

    # everything past the top 12, in order, wrapped to at most two lines of ~115 monospace chars
    also_lines, line = [], "Also:"
    for lang in rest:
        piece = f" {lang['name']} ·"
        if len(line) + len(piece) > 115:
            also_lines.append(line)
            line = ""
            if len(also_lines) == 2:
                break
        line += piece
    else:
        also_lines.append(line)
    also_lines = [l.rstrip(" ·").strip() for l in also_lines if l.strip()]
    H = 100 + rows * row_h + 16 * len(also_lines) + (8 if also_lines else 0) + 34
    band_y, band_h, gap = 58, 12, 3
    inner = W - 2 * PAD

    segs = [(l["name"], l["percent"], readable(colors[l["name"]])) for l in top]
    if other > 0.05:
        segs.append(("Other", other, "#4b5063"))
    usable = inner - gap * (len(segs) - 1)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        'aria-labelledby="title desc">',
        '<title id="title">Languages I\'ve written</title>',
        '<desc id="desc">'
        + "; ".join(f"{l['name']} {l['percent']:.1f}%" for l in top)
        + "</desc>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="4.5" fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="{PAD}" y="38" fill="{CREAM}" font-family="{SANS}" font-size="12" font-weight="600" '
        "letter-spacing=\"2.4\">LANGUAGES I'VE WRITTEN</text>",
        f'<text x="{W - PAD}" y="38" text-anchor="end" fill="{MUTED}" font-family="{SANS}" font-size="12" '
        'font-style="italic">weighted by commits and lines · every repo, all time</text>',
        f'<clipPath id="band"><rect x="{PAD}" y="{band_y}" width="{inner}" height="{band_h}" rx="3"/></clipPath>',
        '<g clip-path="url(#band)">',
    ]
    x = PAD
    for i, (_, share, color) in enumerate(segs):
        w = max(usable * share / total, 2)
        if i == len(segs) - 1:
            w = PAD + inner - x
        out.append(f'<rect x="{x:.2f}" y="{band_y}" width="{w:.2f}" height="{band_h}" fill="{color}"/>')
        x += w + gap
    out.append("</g>")

    col_w = inner / cols
    for i, lang in enumerate(top):
        cx = PAD + (i % cols) * col_w
        cy = band_y + 42 + (i // cols) * row_h
        color = readable(colors[lang["name"]])
        out += [
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>',
            f'<text x="{cx + 16}" y="{cy}" fill="{CREAM}" font-family="{SANS}" font-size="13" '
            f'font-weight="600">{lang["name"]}</text>',
            f'<text x="{cx + 16}" y="{cy + 18}" fill="{MUTED}" font-family="{MONO}" font-size="11">'
            f'{lang["percent"]:.1f}% · {lang["commits"]:,} commits</text>',
        ]

    also_y = band_y + 42 + rows * row_h
    for i, text in enumerate(also_lines):
        out.append(
            f'<text x="{PAD}" y="{also_y + i * 16}" fill="{MUTED}" font-family="{MONO}" font-size="11">{text}</text>'
        )

    out += [
        f'<text x="{PAD}" y="{H - 20}" fill="{MUTED}" font-family="{SANS}" font-size="11">'
        f'{stats["commits"]:,} commits across {stats["repos_with_commits"]} repos</text>',
        f'<text x="{W - PAD}" y="{H - 20}" text-anchor="end" fill="{MUTED}" font-family="{SANS}" font-size="11">'
        f'updated {stats["updated"]}</text>',
        "</svg>",
    ]
    return "\n".join(out) + "\n"


def score_commits(per_commit: dict[str, list[tuple[str, int]]]) -> tuple[Counter, Counter, Counter, Counter]:
    """Every commit counts, and bigger commits count more, but only logarithmically
    (a 1,000-line commit is worth ~10x a 1-line commit, not 1,000x). Each commit's
    score is split across the keys it touched in proportion to its lines.

    Returns (lines, fractional commits, score, commits touching) per key.
    """
    lines, commits, score, touched = Counter(), Counter(), Counter(), Counter()
    for entries in per_commit.values():
        size = sum(added for _, added in entries)
        weight = math.log2(1 + size)
        touched.update({key for key, _ in entries})
        for key, added in entries:
            lines[key] += added
            commits[key] += added / size
            score[key] += weight * added / size
    return lines, commits, score, touched


LAYERS = ["Systems Design", "Infra", "DevOps", "Data", "AI", "Backend", "Frontend"]


def layer_stats(layer_commits: dict[str, list[tuple[str, int]]]) -> dict:
    """Each layer's share of recent work, for the spectrum band's brightness."""
    _, _, score, touched = score_commits(layer_commits)
    total = sum(score.values()) or 1
    return {
        "window_days": LAYER_WINDOW_DAYS,
        "commits": len(layer_commits),
        "percent": {name: 100 * score[name] / total for name in LAYERS},
        "commits_by_layer": {name: touched[name] for name in LAYERS},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--limit", type=int, default=0, help="only analyze the first N repos (for local testing)")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument(
        "--verbose", action="store_true",
        help="print private repo names and per-repo totals; local use only, since CI logs are public",
    )
    args = ap.parse_args()

    repos = list_repos()
    skipped = [r["nameWithOwner"] for r in repos if r["diskUsage"] > MAX_REPO_KB]
    names = [r["nameWithOwner"] for r in repos if r["diskUsage"] <= MAX_REPO_KB]
    if args.limit:
        names = names[: args.limit]
    print(f"analyzing {len(names)} repos ({len(skipped)} skipped as too large)")
    if args.verbose and skipped:
        print("  too large: " + ", ".join(skipped))

    per_commit: dict[str, list[tuple[str, int]]] = {}
    layer_commits: dict[str, list[tuple[str, int]]] = {}
    commit_repo: dict[str, str] = {}
    repo_totals: dict[str, Counter] = {}
    repos_with_commits, failures = set(), []
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(analyze, name, Path(tmp)) for name in names]
        for fut in as_completed(futures):
            repo, rows, layer_rows, err = fut.result()
            if err:
                failures.append(f"{repo}: {err}")
                continue
            for commit, lang, added in rows:
                # the same commit can live in more than one repo (templates, copies); count it
                # only for the first repo it was seen in
                if commit_repo.setdefault(commit, repo) == repo:
                    per_commit.setdefault(commit, []).append((lang, added))
                    repos_with_commits.add(repo)
                    repo_totals.setdefault(repo, Counter())[lang] += added
            for commit, layer, added in layer_rows:
                if commit_repo.setdefault(commit, repo) == repo:
                    layer_commits.setdefault(commit, []).append((layer, added))

    lines, commits, score, touched = score_commits(per_commit)
    total = sum(lines.values())
    if not total:
        raise SystemExit("no lines found; check AUTHORS and repo access")
    total_score, total_commits = sum(score.values()), sum(commits.values())

    stats = {
        "updated": dt.date.today().isoformat(),
        "repos_analyzed": len(names),
        "repos_with_commits": len(repos_with_commits),
        "commits": len(per_commit),
        "total_lines": total,
        "languages": [
            {
                "name": name,
                "percent": 100 * value / total_score,
                "lines": lines[name],
                "commits": touched[name],
                "percent_by_lines": 100 * lines[name] / total,
                "percent_by_commits": 100 * commits[name] / total_commits,
            }
            for name, value in score.most_common()
        ],
        "repos_failed": len(failures),
        "layers": layer_stats(layer_commits),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "languages.json").write_text(json.dumps(stats, indent=2) + "\n")
    (out / "languages.svg").write_text(render(stats))
    print(f"{stats['commits']} commits in {stats['repos_with_commits']} repos, {total:,} lines")
    print(f"  {'language':<16} {'score':>6} {'commits':>8} {'lines':>7}")
    for lang in stats["languages"][:12]:
        print(
            f"  {lang['name']:<16} {lang['percent']:5.1f}% {lang['percent_by_commits']:7.1f}% "
            f"{lang['percent_by_lines']:6.1f}%"
        )
    print(f"layers, last {LAYER_WINDOW_DAYS} days ({stats['layers']['commits']} commits):")
    for name, pct in stats["layers"]["percent"].items():
        print(f"  {name:<16} {pct:5.1f}%")
    # repo names stay out of CI output: this repo and its Actions logs are public
    print(f"{len(failures)} repos failed")
    if args.verbose:
        print("\n".join(f"  {f}" for f in failures))
        print("biggest repos:")
        for repo, counts in sorted(repo_totals.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
            langs = ", ".join(f"{l} {compact(n)}" for l, n in counts.most_common(3))
            print(f"  {repo:<45} {compact(sum(counts.values())):>6}  {langs}")


if __name__ == "__main__":
    main()
