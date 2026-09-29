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


def renamed_target(path: str) -> str:
    """`src/{old => new}/a.go` or `old.go => new.go` -> the new path."""
    if "=>" not in path:
        return path
    if "{" in path:
        return re.sub(r"\{[^{}]*? => ([^{}]*?)\}", r"\1", path).replace("//", "/")
    return path.split(" => ", 1)[1]


def analyze(repo: str, workdir: Path) -> tuple[str, list[tuple[str, str, int]], str | None]:
    """Returns (repo, [(commit, language, lines added)], error)."""
    dest = workdir / repo.replace("/", "__")
    try:
        run("git", "clone", "--bare", "--quiet", f"https://github.com/{repo}.git", str(dest), timeout=CLONE_TIMEOUT)
        author_args = [f"--author={a}" for a in AUTHORS]
        log = run(
            "git", "log", "HEAD", "--no-merges", "--numstat", "--format=@%H", *author_args,
            cwd=dest, timeout=CLONE_TIMEOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return repo, [], (getattr(e, "stderr", "") or str(e)).strip().splitlines()[-1][:200]
    finally:
        subprocess.run(["rm", "-rf", str(dest)])

    rows, commit = [], None
    for line in log.splitlines():
        if line.startswith("@"):
            commit = line[1:]
            continue
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":  # blank line or binary file
            continue
        added = int(parts[0])
        lang = language_for(renamed_target(parts[2]))
        if lang and 0 < added <= MAX_FILE_LINES:
            rows.append((commit, lang[0], added))
    return repo, rows, None


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
    W, PAD, TOP = 840, 24, 8
    colors = {name: color for name, color in LANGUAGES.values()}
    total = stats["total_lines"]
    top = stats["languages"][:TOP]
    other = total - sum(l["lines"] for l in top)
    cols, row_h = 4, 44
    rows = -(-len(top) // cols)
    H = 100 + rows * row_h + 34
    band_y, band_h, gap = 58, 12, 3
    inner = W - 2 * PAD

    segs = [(l["name"], l["lines"], readable(colors[l["name"]])) for l in top]
    if other > 0:
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
        'font-style="italic">lines added in my commits · every repo, all time</text>',
        f'<clipPath id="band"><rect x="{PAD}" y="{band_y}" width="{inner}" height="{band_h}" rx="3"/></clipPath>',
        '<g clip-path="url(#band)">',
    ]
    x = PAD
    for i, (_, lines, color) in enumerate(segs):
        w = max(usable * lines / total, 2)
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
            f'{lang["percent"]:.1f}% · {compact(lang["lines"])} lines</text>',
        ]

    out += [
        f'<text x="{PAD}" y="{H - 20}" fill="{MUTED}" font-family="{SANS}" font-size="11">'
        f'{stats["commits"]:,} commits across {stats["repos_with_commits"]} repos</text>',
        f'<text x="{W - PAD}" y="{H - 20}" text-anchor="end" fill="{MUTED}" font-family="{SANS}" font-size="11">'
        f'updated {stats["updated"]}</text>',
        "</svg>",
    ]
    return "\n".join(out) + "\n"


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
    commit_repo: dict[str, str] = {}
    repo_totals: dict[str, Counter] = {}
    repos_with_commits, failures = set(), []
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(analyze, name, Path(tmp)) for name in names]
        for fut in as_completed(futures):
            repo, rows, err = fut.result()
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

    totals = Counter()
    for entries in per_commit.values():
        for lang, added in entries:
            totals[lang] += added
    total = sum(totals.values())
    if not total:
        raise SystemExit("no lines found; check AUTHORS and repo access")

    stats = {
        "updated": dt.date.today().isoformat(),
        "repos_analyzed": len(names),
        "repos_with_commits": len(repos_with_commits),
        "commits": len(per_commit),
        "total_lines": total,
        "languages": [
            {"name": name, "lines": lines, "percent": 100 * lines / total} for name, lines in totals.most_common()
        ],
        "repos_failed": len(failures),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "languages.json").write_text(json.dumps(stats, indent=2) + "\n")
    (out / "languages.svg").write_text(render(stats))
    print(f"{stats['commits']} commits in {stats['repos_with_commits']} repos, {total:,} lines")
    for lang in stats["languages"][:12]:
        print(f"  {lang['name']:<16} {lang['percent']:5.1f}%  {lang['lines']:>10,}")
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
