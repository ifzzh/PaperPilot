"""Deterministic Daily arXiv topic recall and quota allocation."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable


DEFAULT_RESEARCH_TOPICS = [
    {
        "id": "robotics-vla",
        "name": "机器人、VLA、机器人学习与时序动作分割",
        "quota": 12,
        "categories": ["cs.RO", "cs.CV", "cs.AI", "cs.LG"],
        "phrases": [
            "vision language action", "vision-language-action", "vla", "robot learning",
            "robot manipulation", "robot policy", "robotic manipulation", "embodied agent",
            "temporal action segmentation", "action segmentation", "long-horizon manipulation",
            "imitation learning", "dexterous manipulation", "navigation policy",
        ],
        "contextGroups": [["robot", "policy"], ["robot", "learning"], ["embodied", "robot"]],
        "exclude": ["surgical robot", "traffic robot"],
    },
    {
        "id": "cloud-systems",
        "name": "云原生系统、SLO、尾延迟、多资源调度与隔离",
        "quota": 8,
        "categories": ["cs.DC", "cs.NI", "cs.OS", "cs.PF"],
        "phrases": [
            "cloud native", "cloud-native", "service level objective", "slo",
            "tail latency", "resource scheduling", "multi-resource scheduling",
            "resource isolation", "cluster scheduling", "container scheduling",
            "microservice", "kubernetes", "serverless", "datacenter network",
        ],
        "contextGroups": [["latency", "scheduling"], ["resource", "isolation"], ["cloud", "scheduling"]],
        "exclude": ["point cloud", "cloud removal"],
    },
    {
        "id": "embodied-context",
        "name": "具身智能的上下文、记忆、世界模型与失败恢复",
        "quota": 4,
        "categories": ["cs.RO", "cs.CV", "cs.AI", "cs.LG", "cs.CL"],
        "phrases": [
            "embodied memory", "agent memory", "world model", "failure recovery",
            "error recovery", "context-aware embodied", "long-term memory",
            "episodic memory", "continual adaptation", "test-time adaptation",
        ],
        "contextGroups": [
            ["embodied", "memory"], ["robot", "memory"], ["embodied", "context"],
            ["robot", "recovery"], ["world model", "robot"],
        ],
        "exclude": ["memory allocator", "database recovery"],
    },
]

BROAD_TERMS = {"llm", "agent", "agents", "ai", "learning", "model", "models"}


def normalize_research_topics(value: Any) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) and value else DEFAULT_RESEARCH_TOPICS
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in source:
        if not isinstance(item, dict):
            continue
        topic_id = str(item.get("id") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", topic_id) or topic_id in seen:
            continue
        seen.add(topic_id)
        normalized.append({
            "id": topic_id,
            "name": str(item.get("name") or topic_id).strip()[:120],
            "quota": max(1, min(24, int(item.get("quota") or 1))),
            "categories": [str(v).strip() for v in item.get("categories", []) if str(v).strip()],
            "phrases": [str(v).strip().lower() for v in item.get("phrases", []) if str(v).strip()],
            "contextGroups": [
                [str(term).strip().lower() for term in group if str(term).strip()]
                for group in item.get("contextGroups", []) if isinstance(group, list)
            ],
            "exclude": [str(v).strip().lower() for v in item.get("exclude", []) if str(v).strip()],
        })
    return normalized or deepcopy(DEFAULT_RESEARCH_TOPICS)


def score_paper_topics(paper: dict[str, Any], topics: Any = None) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", " ", f"{paper.get('title', '')} {paper.get('abstract', '')}".lower())
    categories = {str(v).strip() for v in (paper.get("categories") or [])}
    primary = str(paper.get("primary_category") or paper.get("subject") or "").strip()
    if primary:
        categories.add(primary)
    matches: list[dict[str, Any]] = []
    for topic in normalize_research_topics(topics):
        if any(term in text for term in topic["exclude"]):
            continue
        phrases = [term for term in topic["phrases"] if term not in BROAD_TERMS and term in text]
        contexts = [group for group in topic["contextGroups"] if group and all(term in text for term in group)]
        if not phrases and not contexts:
            continue
        category_hit = bool(categories.intersection(topic["categories"]))
        if "cs.CL" in categories and not (phrases or contexts):
            continue
        score = len(phrases) * 4.0 + len(contexts) * 5.0 + (1.5 if category_hit else 0.0)
        if not category_hit:
            score -= 1.0
        matches.append({"id": topic["id"], "name": topic["name"], "score": round(score, 2)})
    return sorted(matches, key=lambda item: (-item["score"], item["id"]))


def select_daily_candidates(
    candidates: Iterable[dict[str, Any]], topics: Any = None, max_total: int = 24
) -> list[dict[str, Any]]:
    """Globally deduplicate candidates and fill per-topic quotas with redistribution."""
    profile = normalize_research_topics(topics)
    topic_by_id = {item["id"]: item for item in profile}
    deduped: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        paper = dict(raw)
        paper_id = str(paper.get("arxiv_id") or paper.get("id") or "").split("v", 1)[0]
        if not paper_id:
            continue
        matches = score_paper_topics(paper, profile)
        if not matches:
            continue
        paper["matched_topics"] = matches
        paper["relevance_score"] = matches[0]["score"]
        paper["selection_reason"] = f"命中主题：{matches[0]['name']}"
        previous = deduped.get(paper_id)
        if previous is None or paper["relevance_score"] > previous["relevance_score"]:
            deduped[paper_id] = paper

    ranked = sorted(deduped.values(), key=lambda p: (-p["relevance_score"], str(p.get("arxiv_id", ""))))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for topic in profile:
        eligible = [p for p in ranked if any(m["id"] == topic["id"] for m in p["matched_topics"])]
        for paper in eligible[: topic["quota"]]:
            paper_id = str(paper.get("arxiv_id") or paper.get("id"))
            if paper_id not in selected_ids and len(selected) < max_total:
                selected.append(paper)
                selected_ids.add(paper_id)
    for paper in ranked:
        paper_id = str(paper.get("arxiv_id") or paper.get("id"))
        if len(selected) >= max_total:
            break
        if paper_id not in selected_ids:
            selected.append(paper)
            selected_ids.add(paper_id)
    return selected
