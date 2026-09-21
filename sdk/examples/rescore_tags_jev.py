"""Rescore each tab against a compact, readable Jev tag vocabulary."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from jevx import Client, Noul

DATA = Path.home() / "Downloads" / "tabs.final.enriched.json"
METHOD = "jev_compact_multilabel_v1"
THRESHOLD = 0.70
MAX_TOPICS = 2
MAX_FORMATS = 1
CHECKPOINT_EVERY = 5

TOPICS = {
    "ai_and_machine_learning": ("AI and machine learning", "Machine learning methods, language models, model training, evaluation, and prompt design."),
    "ai_agents_and_retrieval": ("AI agents and retrieval", "Tool-using agents, agent frameworks, search, retrieval, and grounded generation."),
    "model_inference_and_serving": ("Model inference and serving", "Serving models, inference performance, decoding, accelerators, and deployment."),
    "software_engineering_and_open_source": ("Software engineering and open-source tools", "Software architecture, testing, developer tools, and open-source software projects."),
    "programming_languages_and_ecosystems": ("Programming languages and ecosystems", "Programming language design and practical ecosystems such as Python, Rust, JavaScript, and TypeScript."),
    "web_development_and_interface_design": ("Web development and interface design", "Web applications, frontend development, interaction design, and user experience."),
    "cloud_and_platform_infrastructure": ("Cloud and platform infrastructure", "Cloud services, hosting, networking, operations, and platform infrastructure."),
    "databases_and_data_analysis": ("Databases and data analysis", "Database systems, data platforms, analytics, statistics, and data exploration."),
    "security_and_privacy": ("Security and privacy", "Computer security, privacy, abuse prevention, and defensive practice."),
    "robotics_and_autonomous_systems": ("Robotics and autonomous systems", "Robots, autonomous machines, embodied AI, and physical control systems."),
    "electronics_and_hardware": ("Electronics and hardware", "Electronic circuits, chips, devices, and computing hardware."),
    "business_and_product_strategy": ("Business and product strategy", "Business operations, markets, startups, product strategy, and product management."),
    "career_and_productivity": ("Career and productivity", "Careers, workplace practice, professional development, and personal work management."),
    "education_and_learning": ("Education and learning", "Teaching, study, courses, and educational practice."),
    "science_and_mathematics": ("Science and mathematics", "Scientific topics and mathematical methods outside the computing tags above."),
    "finance": ("Finance", "Payments, financial systems, investing, and personal finance."),
    "writing_and_communication": ("Writing and communication", "Writing, publishing, editing, and communication practice."),
    "social_media_and_communities": ("Social media and online communities", "Social platforms, online communities, and audience building."),
}

FORMATS = {
    "research_paper": ("Research paper", "A scholarly paper or technical research report."),
    "book_or_course": ("Book or course", "A book, course, lecture series, or class material."),
    "documentation_or_reference": ("Documentation or reference", "Product documentation, API docs, specifications, or lookup material."),
    "guide_or_tutorial": ("Guide or tutorial", "A practical, instructional, step-by-step guide."),
    "news_or_commentary": ("News or commentary", "A news report, opinion article, or personal essay."),
    "product_or_service": ("Product or service", "A page primarily presenting a product, service, or launch."),
    "dataset": ("Dataset", "A dataset or a page whose main purpose is to provide a dataset."),
    "video_or_podcast": ("Video or podcast", "A video, stream, or podcast episode."),
}

TAGS = {**TOPICS, **FORMATS}
PRIVATE_TAG_MERGE = {
    "academic_paper": "Research paper",
    "ai_agents": "AI agents and retrieval",
    "book": "Book or course",
    "business_strategy": "Business and product strategy",
    "career_work": "Career and productivity",
    "cloud_operations": "Cloud and platform infrastructure",
    "course_material": "Book or course",
    "data_analysis": "Databases and data analysis",
    "databases": "Databases and data analysis",
    "dataset": "Dataset",
    "design_ux": "Web development and interface design",
    "developer_tools": "Software engineering and open-source tools",
    "documentation": "Documentation or reference",
    "education": "Education and learning",
    "evaluation_benchmarks": "AI and machine learning",
    "finance": "Finance",
    "hardware": "Electronics and hardware",
    "how_to_guide": "Guide or tutorial",
    "inference_serving": "Model inference and serving",
    "javascript_typescript": "Programming languages and ecosystems",
    "large_language_models": "AI and machine learning",
    "machine_learning": "AI and machine learning",
    "mathematics": "Science and mathematics",
    "model_training": "AI and machine learning",
    "news_article": "News or commentary",
    "open_source": "Software engineering and open-source tools",
    "opinion_piece": "News or commentary",
    "product_page": "Product or service",
    "productivity": "Career and productivity",
    "programming_languages": "Programming languages and ecosystems",
    "prompting": "AI and machine learning",
    "python": "Programming languages and ecosystems",
    "reference_material": "Documentation or reference",
    "retrieval_rag": "AI agents and retrieval",
    "robotics": "Robotics and autonomous systems",
    "rust": "Programming languages and ecosystems",
    "science": "Science and mathematics",
    "security_privacy": "Security and privacy",
    "social_media": "Social media and online communities",
    "software_architecture": "Software engineering and open-source tools",
    "software_repository": "Software engineering and open-source tools",
    "startups_products": "Business and product strategy",
    "testing": "Software engineering and open-source tools",
    "video_or_podcast": "Video or podcast",
    "web_development": "Web development and interface design",
    "writing": "Writing and communication",
}
SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|session[_-]?id)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|[A-Fa-f0-9]{32,})\b")


def safe_state(tab: dict) -> dict:
    parts = urlsplit(tab.get("url") or "")
    path = re.sub(r"(?i)([0-9a-f]{8}-[0-9a-f-]{27,}|[A-Za-z0-9_-]{32,})", "[id]", parts.path)
    url = urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    def safe_text(value, limit=4500):
        text = " ".join(str(value or "").split())[:limit]
        text = SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", text)
        return TOKEN_RE.sub("[redacted]", text)

    metadata = tab.get("source_metadata") or {}
    github = metadata.get("github") or {}
    page = metadata.get("page") or {}
    state = {
        "kind": tab.get("kind") or "web page",
        "title": safe_text(tab.get("title"), 500),
        "url": url,
        "page_text": safe_text(tab.get("text")),
    }
    if github and not github.get("private"):
        state["public_github_repository"] = {
            "name": safe_text(github.get("name"), 300),
            "description": safe_text(github.get("description"), 1500),
            "topics": [safe_text(topic, 120) for topic in github.get("topics", [])[:40]],
            "language": safe_text(github.get("language"), 100),
            "homepage": safe_text(github.get("homepage"), 500),
            "readme_excerpt": safe_text(github.get("readme_excerpt"), 4500),
        }
    elif page:
        state["page_metadata"] = {
            "title": safe_text(page.get("title"), 500),
            "description": safe_text(page.get("description"), 1500),
            "content_excerpt": safe_text(page.get("content_excerpt"), 4500),
        }
    return state


def questions() -> dict[str, Noul]:
    return {
        key: Noul(
            instructions={
                "question": f"Is {label} a useful tag for this saved page?",
                "definition": description,
                "focus": "True only when the tag describes the page's main or substantial subject or its clear format. Ignore incidental mentions.",
            },
            criteria={
                "true": "The page is centrally or substantially about this topic or has this format.",
                "false": "The page mentions it only incidentally, or the available evidence does not support the tag.",
            },
        )
        for key, (label, description) in TAGS.items()
    }


def write_data(data: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".tabs-jev-tags-", suffix=".tmp", dir=DATA.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, stat.S_IMODE(DATA.stat().st_mode))
        os.replace(temporary, DATA)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="rescore at most this many tabs")
    parser.add_argument("--index", type=int, help="rescore one tab by zero-based JSON index")
    args = parser.parse_args()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tabs = data["tabs"]
    pending = [(i, tab) for i, tab in enumerate(tabs)
               if tab.get("tagging", {}).get("method") != METHOD
               and not ((tab.get("source_metadata") or {}).get("github") or {}).get("private")]
    if args.index is not None:
        pending = [(i, tab) for i, tab in pending if i == args.index]
    if args.limit is not None:
        pending = pending[:args.limit]
    backup = DATA.with_name(f"{DATA.name}.pre-jev-tags.{datetime.now(UTC):%Y%m%dT%H%M%SZ}.bak")
    with backup.open("xb") as stream:
        stream.write(DATA.read_bytes())
    private_merged = 0
    for tab in tabs:
        github = ((tab.get("source_metadata") or {}).get("github") or {})
        if not github.get("private"):
            continue
        previous_tags = tab.get("tags", [])
        merged = list(dict.fromkeys(
            PRIVATE_TAG_MERGE.get(tag, tag) for tag in previous_tags
        ))
        if merged != previous_tags:
            previous = tab.get("tagging") or {}
            tab["tags"] = merged
            tab["tagging"] = {
                "method": "private_local_tag_merge_v1",
                "previous_tags": previous_tags,
                "previous": previous,
            }
            private_merged += 1
    if private_merged:
        write_data(data)
    q = questions()
    print(f"tabs={len(tabs)} pending={len(pending)} private_github_merged_locally={private_merged} candidate_tags={len(TAGS)} backup={backup}", flush=True)
    client = Client()

    def evaluate(tab: dict) -> tuple[dict[str, float], dict]:
        response = client.system_one(state=safe_state(tab), questions=q)
        scores = {key: float(response.nouls[key].noul) for key in TAGS}
        usage = getattr(response, "usage", None)
        return scores, usage.model_dump(mode="json") if hasattr(usage, "model_dump") else (usage or {})

    done = 0
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for (index, tab), result in zip(pending, pool.map(lambda pair: evaluate(pair[1]), pending)):
                scores, usage = result
                topics = sorted(((key, score) for key, score in scores.items()
                                 if key in TOPICS and score >= THRESHOLD), key=lambda item: item[1], reverse=True)[:MAX_TOPICS]
                formats = sorted(((key, score) for key, score in scores.items()
                                  if key in FORMATS and score >= THRESHOLD), key=lambda item: item[1], reverse=True)[:MAX_FORMATS]
                selected = topics + formats
                previous = tab.get("tagging") or {}
                previous_tags = tab.get("tags", [])
                tab["tags"] = [TAGS[key][0] for key, _ in selected]
                tab["tagging"] = {
                    "method": METHOD,
                    "model": getattr(client, "model", None),
                    "previous_tags": previous_tags,
                    "previous": previous,
                    "tag_scores": {TAGS[key][0]: round(score, 3) for key, score in scores.items()},
                    "usage": usage,
                }
                done += 1
                if done % CHECKPOINT_EVERY == 0 or done == len(pending):
                    write_data(data)
                if done % 25 == 0 or done == len(pending):
                    print(f"rescored={done}/{len(pending)}", flush=True)
    except BaseException:
        write_data(data)
        raise
    finally:
        write_data(data)
        client.close()
    print(f"processed={done} tagged={sum(bool(t.get('tags')) for t in tabs)} tagless={sum(not t.get('tags') for t in tabs)}")


if __name__ == "__main__":
    main()
