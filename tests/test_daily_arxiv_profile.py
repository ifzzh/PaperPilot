from ipaper.tools.basic_tools.daily_arxiv_profile import (
    DEFAULT_RESEARCH_TOPICS,
    score_paper_topics,
    select_daily_candidates,
)


def paper(arxiv_id, title, category):
    return {"arxiv_id": arxiv_id, "title": title, "abstract": title, "categories": [category]}


def test_broad_agent_or_llm_words_do_not_select_a_paper():
    assert score_paper_topics(paper("1", "A General LLM Agent Benchmark", "cs.CL")) == []


def test_context_and_category_topics_are_matched():
    matches = score_paper_topics(paper("1", "World Models for Robot Failure Recovery", "cs.RO"))
    assert {match["id"] for match in matches} >= {"embodied-context"}


def test_global_selection_deduplicates_and_caps_at_12_8_4():
    candidates = []
    candidates += [paper(f"r{i}", f"Vision Language Action Robot Policy {i}", "cs.RO") for i in range(16)]
    candidates += [paper(f"s{i}", f"Cloud Native Tail Latency Scheduling {i}", "cs.DC") for i in range(12)]
    candidates += [paper(f"m{i}", f"Embodied Memory and Failure Recovery {i}", "cs.AI") for i in range(8)]
    candidates.append(dict(candidates[0]))
    selected = select_daily_candidates(candidates, DEFAULT_RESEARCH_TOPICS, 24)
    assert len(selected) == 24
    assert len({item["arxiv_id"] for item in selected}) == 24
    primary = [item["matched_topics"][0]["id"] for item in selected]
    assert primary.count("robotics-vla") == 12
    assert primary.count("cloud-systems") == 8
    assert primary.count("embodied-context") == 4
