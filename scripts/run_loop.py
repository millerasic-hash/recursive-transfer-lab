#!/usr/bin/env python3
"""Run one recursive transfer loop.

The script is intentionally small and read-only toward external systems:
- GitHub is accessed through `gh repo list`.
- OpenAlex is accessed through its public API.
- Reports are written locally under reports/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "experiment.json"
REPORTS = ROOT / "reports"
LOOP_REPORTS = REPORTS / "loop"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", exc.stderr or "timeout"
    return proc.returncode, proc.stdout, proc.stderr


def github_inventory(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    owner = config["github"]["owner"]
    limit = str(config["github"].get("repo_limit", 100))
    fields = [
        "name",
        "nameWithOwner",
        "url",
        "description",
        "isPrivate",
        "isArchived",
        "isFork",
        "primaryLanguage",
        "updatedAt",
        "pushedAt",
        "stargazerCount",
        "forkCount",
        "diskUsage",
        "repositoryTopics",
        "licenseInfo",
    ]
    code, out, err = run(["gh", "repo", "list", owner, "--limit", limit, "--json", ",".join(fields)])
    warnings: list[str] = []
    if code != 0:
        warnings.append(f"GitHub inventory failed: {err.strip() or out.strip() or code}")
        return [], warnings
    try:
        repos = json.loads(out)
    except json.JSONDecodeError as exc:
        warnings.append(f"GitHub inventory JSON decode failed: {exc}")
        return [], warnings
    return repos, warnings


def fetch_openalex(query: dict[str, str], config: dict[str, Any], offline: bool) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if offline:
        return [], ["offline mode: OpenAlex fetch skipped"]
    params = {
        "search": query["search"],
        "filter": config["openalex"]["filter"],
        "per-page": str(config["openalex"].get("per_query", 5)),
        "sort": "cited_by_count:desc",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "recursive-transfer-lab/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        code, out, err = run(["curl", "-fsSL", url], timeout=30)
        if code != 0:
            warnings.append(f"OpenAlex fetch failed for {query['id']}: {exc}; curl fallback: {err.strip() or code}")
            return [], warnings
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as decode_error:
            warnings.append(f"OpenAlex curl JSON decode failed for {query['id']}: {decode_error}")
            return [], warnings
    return payload.get("results", []), warnings


def abstract_text(work: dict[str, Any]) -> str:
    inverted = work.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        if isinstance(positions, list):
            for pos in positions:
                if isinstance(pos, int):
                    pairs.append((pos, word))
    return " ".join(word for _, word in sorted(pairs))


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def extract_signals(text: str, config: dict[str, Any]) -> dict[str, list[str]]:
    haystack = normalize_text(text)
    found: dict[str, list[str]] = {}
    for group, terms in config["signals"].items():
        matched = []
        for term in terms:
            if normalize_text(term) in haystack:
                matched.append(term)
        found[group] = matched
    return found


def normalize_repo_topics(repo: dict[str, Any]) -> list[str]:
    topics = repo.get("repositoryTopics") or []
    values = []
    for item in topics:
        if isinstance(item, dict):
            name = item.get("name") or item.get("topic", {}).get("name")
            if name:
                values.append(str(name))
        elif item:
            values.append(str(item))
    return sorted(set(values))


def repo_text(repo: dict[str, Any]) -> str:
    lang = repo.get("primaryLanguage") or {}
    lang_name = lang.get("name") if isinstance(lang, dict) else lang
    return " ".join(
        [
            repo.get("nameWithOwner") or "",
            repo.get("description") or "",
            lang_name or "",
            " ".join(normalize_repo_topics(repo)),
        ]
    )


def normalize_work(work: dict[str, Any], query: dict[str, str], config: dict[str, Any]) -> dict[str, Any]:
    text = " ".join([work.get("display_name") or "", abstract_text(work)])
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    return {
        "id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("display_name"),
        "year": work.get("publication_year"),
        "query_id": query["id"],
        "query_label": query["label"],
        "cited_by_count": work.get("cited_by_count", 0),
        "source": source.get("display_name"),
        "url": primary.get("landing_page_url") or work.get("doi") or work.get("id"),
        "signals": extract_signals(text, config),
    }


def score_candidate(paper: dict[str, Any], repo: dict[str, Any], config: dict[str, Any]) -> tuple[float, list[str]]:
    repo_signals = extract_signals(repo_text(repo), config)
    paper_terms = set(sum((paper["signals"].get(group, []) for group in paper["signals"]), []))
    repo_terms = set(sum((repo_signals.get(group, []) for group in repo_signals), []))
    topic_terms = set(normalize_repo_topics(repo))
    shared = sorted(paper_terms & (repo_terms | topic_terms))
    text = normalize_text(repo_text(repo))
    title_hits = [term for term in paper_terms if normalize_text(term) and normalize_text(term) in text]
    shared = sorted(set(shared + title_hits))
    score = min(0.95, 0.18 * len(shared) + 0.05 * math.log1p(repo.get("stargazerCount") or 0))
    return score, shared


def transfer_candidates(papers: list[dict[str, Any]], repos: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for paper in papers:
        for repo in repos:
            score, shared = score_candidate(paper, repo, config)
            if score >= 0.18 and shared:
                candidates.append(
                    {
                        "type": "paper_repo_transfer",
                        "confidence": round(score, 2),
                        "shared_signals": shared[:8],
                        "paper": {
                            "title": paper["title"],
                            "doi": paper["doi"],
                            "url": paper["url"],
                            "query_label": paper["query_label"],
                        },
                        "repo": {
                            "name": repo.get("nameWithOwner"),
                            "url": repo.get("url"),
                            "description": repo.get("description"),
                        },
                        "hypothesis": "A paper-level method signal overlaps with an existing GitHub implementation surface.",
                        "next_verification": "Inspect README and tests before treating this as an implementation bridge.",
                    }
                )

    by_method: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        for method in paper["signals"].get("methods", []):
            by_method.setdefault(method, []).append(paper)
    for method, grouped in by_method.items():
        query_ids = {item["query_id"] for item in grouped}
        if len(grouped) >= 2 and len(query_ids) >= 2:
            candidates.append(
                {
                    "type": "paper_paper_bridge",
                    "confidence": min(0.85, round(0.25 + 0.08 * len(grouped) + 0.08 * len(query_ids), 2)),
                    "shared_signals": [method],
                    "paper_count": len(grouped),
                    "domains": sorted(query_ids),
                    "examples": [
                        {
                            "title": item["title"],
                            "doi": item["doi"],
                            "url": item["url"],
                            "query_label": item["query_label"],
                        }
                        for item in grouped[:5]
                    ],
                    "hypothesis": f"The method signal '{method}' appears across multiple query domains.",
                    "next_verification": "Check whether the papers cite each other or are rediscovering the same structure.",
                }
            )

    return sorted(candidates, key=lambda item: item["confidence"], reverse=True)


def github_suggestions(repos: list[dict[str, Any]]) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    suggestions: list[dict[str, Any]] = []
    for repo in repos:
        pushed_at = repo.get("pushedAt") or repo.get("updatedAt")
        age_days = None
        if pushed_at:
            try:
                parsed = dt.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                age_days = (now - parsed).days
            except ValueError:
                age_days = None
        topics = normalize_repo_topics(repo)
        license_info = repo.get("licenseInfo") or {}
        actions = []
        if not topics:
            actions.append("add_topics")
        if not license_info:
            actions.append("add_license_or_mark_private")
        if age_days is not None and age_days > 365 and not repo.get("isArchived"):
            actions.append("review_archive_status")
        if "research" in normalize_text(repo.get("description")) or "experiment" in normalize_text(repo.get("description")):
            actions.append("consider_citation_cff")
        if actions:
            suggestions.append(
                {
                    "repo": repo.get("nameWithOwner"),
                    "url": repo.get("url"),
                    "age_days": age_days,
                    "is_private": repo.get("isPrivate"),
                    "is_fork": repo.get("isFork"),
                    "topics": topics,
                    "actions": actions,
                }
            )
    return {
        "repo_count": len(repos),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }


def choose_frequency(state: dict[str, Any], candidates: list[dict[str, Any]], warnings: list[str], config: dict[str, Any]) -> str:
    policy = config["frequency_policy"]
    prior_runs = int(state.get("run_count", 0))
    high_conf = [item for item in candidates if item.get("confidence", 0) >= 0.5]
    if warnings:
        return policy["bootstrap"]
    if prior_runs < 3:
        return policy["bootstrap"]
    if high_conf:
        return policy["active_learning"]
    if candidates:
        return policy["stable"]
    return policy["maintenance"]


def write_markdown(
    path: Path,
    *,
    run_id: str,
    papers: list[dict[str, Any]],
    repos: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    gh_summary: dict[str, Any],
    warnings: list[str],
    next_frequency: str,
) -> None:
    lines = [
        "# Recursive Transfer Loop Summary",
        "",
        f"- run_id: `{run_id}`",
        f"- papers_observed: `{len(papers)}`",
        f"- github_repos_observed: `{len(repos)}`",
        f"- candidates: `{len(candidates)}`",
        f"- github_suggestions: `{gh_summary['suggestion_count']}`",
        f"- next_frequency: `{next_frequency}`",
        "",
        "## Top Candidates",
        "",
    ]
    if not candidates:
        lines.append("暂无候选。下一轮应扩大查询词或补充目标领域。")
    for item in candidates[:10]:
        lines.extend(
            [
                f"### {item['type']} / confidence {item['confidence']}",
                "",
                f"- shared_signals: `{', '.join(item.get('shared_signals', []))}`",
                f"- hypothesis: {item['hypothesis']}",
                f"- next_verification: {item['next_verification']}",
                "",
            ]
        )
        if item["type"] == "paper_repo_transfer":
            lines.extend(
                [
                    f"- paper: {item['paper']['title']}",
                    f"- paper_url: {item['paper']['url']}",
                    f"- repo: {item['repo']['name']}",
                    f"- repo_url: {item['repo']['url']}",
                    "",
                ]
            )
        if item["type"] == "paper_paper_bridge":
            lines.append(f"- domains: `{', '.join(item['domains'])}`")
            for example in item["examples"][:3]:
                lines.append(f"- example: {example['title']} ({example['url']})")
            lines.append("")
    lines.extend(["## GitHub Organization Signals", ""])
    for suggestion in gh_summary["suggestions"][:20]:
        lines.append(f"- `{suggestion['repo']}` -> {', '.join(suggestion['actions'])}")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Skip OpenAlex network fetch.")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH, {})
    state_path = LOOP_REPORTS / "state.json"
    state = load_json(state_path, {"run_count": 0, "stable_rounds": 0})
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    warnings: list[str] = []

    repos, repo_warnings = github_inventory(config)
    warnings.extend(repo_warnings)

    papers: list[dict[str, Any]] = []
    raw_payload: dict[str, Any] = {}
    for query in config["openalex"]["queries"]:
        works, query_warnings = fetch_openalex(query, config, args.offline)
        warnings.extend(query_warnings)
        raw_payload[query["id"]] = works
        papers.extend(normalize_work(work, query, config) for work in works)

    gh_summary = github_suggestions(repos)
    candidates = transfer_candidates(papers, repos, config)
    next_frequency = choose_frequency(state, candidates, warnings, config)

    round_dir = LOOP_REPORTS / f"round-{run_id}"
    save_json(round_dir / "openalex_raw.json", raw_payload)
    save_json(round_dir / "papers.json", papers)
    save_json(round_dir / "github_repos.json", repos)
    save_json(REPORTS / "github_inventory.json", gh_summary)
    save_json(REPORTS / "transfer_candidates.json", candidates)

    new_state = {
        "schema": "recursive-transfer-loop-state-v1",
        "updated_at": utc_now(),
        "run_id": run_id,
        "run_count": int(state.get("run_count", 0)) + 1,
        "papers_observed": len(papers),
        "github_repos_observed": len(repos),
        "candidate_count": len(candidates),
        "warning_count": len(warnings),
        "next_frequency": next_frequency,
        "status": "verified" if not warnings else "pending",
        "truth_surfaces": [
            str(round_dir.relative_to(ROOT) / "papers.json"),
            str(round_dir.relative_to(ROOT) / "github_repos.json"),
            "reports/transfer_candidates.json",
            "reports/github_inventory.json",
        ],
    }
    save_json(state_path, new_state)

    write_markdown(
        LOOP_REPORTS / "latest_summary.md",
        run_id=run_id,
        papers=papers,
        repos=repos,
        candidates=candidates,
        gh_summary=gh_summary,
        warnings=warnings,
        next_frequency=next_frequency,
    )
    write_markdown(
        round_dir / "summary.md",
        run_id=run_id,
        papers=papers,
        repos=repos,
        candidates=candidates,
        gh_summary=gh_summary,
        warnings=warnings,
        next_frequency=next_frequency,
    )

    inventory_lines = [
        "# GitHub Inventory",
        "",
        f"- repo_count: `{gh_summary['repo_count']}`",
        f"- suggestion_count: `{gh_summary['suggestion_count']}`",
        "",
    ]
    for suggestion in gh_summary["suggestions"]:
        inventory_lines.append(f"- `{suggestion['repo']}`: {', '.join(suggestion['actions'])}")
    (REPORTS / "github_inventory.md").write_text("\n".join(inventory_lines) + "\n", encoding="utf-8")

    print(f"wrote {LOOP_REPORTS / 'latest_summary.md'}")
    print(f"next_frequency={next_frequency}")
    print(f"candidates={len(candidates)} github_suggestions={gh_summary['suggestion_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
