"""Add readable page metadata and public GitHub repo context to saved tabs."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

DATA = Path.home() / "Downloads" / "tabs.final.enriched.json"
CHECKPOINT_EVERY = 20
WORKERS = 8
MAX_READ_BYTES = 1_500_000
MAX_CONTEXT_CHARS = 7000
SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|session[_-]?id)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|[A-Fa-f0-9]{32,})\b")


def clean(text: str) -> str:
    text = SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    return TOKEN_RE.sub("[redacted]", text)


def github_repo(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if parts.netloc.lower().removeprefix("www.") != "github.com":
        return None
    path = [p for p in parts.path.split("/") if p]
    if len(path) < 2 or path[0].lower() in {
        "about", "collections", "features", "marketplace", "orgs", "settings",
        "sponsors", "topics", "trending", "users",
    }:
        return None
    return path[0], path[1].removesuffix(".git")


def request_bytes(url: str, headers: dict[str, str], timeout: int = 20) -> tuple[bytes, dict[str, str]]:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        return response.read(MAX_READ_BYTES), dict(response.headers.items())


def fetch_github(key: tuple[str, str], token: str, need_readme: bool) -> dict:
    owner, repo = key
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "tabs-metadata-enrichment/1.0",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        raw, _ = request_bytes(url, headers)
        data = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"status": f"repo_error:{getattr(exc, 'code', type(exc).__name__)}"}
    result = {
        "status": "ok",
        "private": bool(data.get("private")),
        "name": data.get("full_name") or f"{owner}/{repo}",
        "description": clean(data.get("description") or ""),
        "topics": data.get("topics") or [],
        "language": data.get("language"),
        "homepage": data.get("homepage"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
    }
    if result["private"] or not need_readme:
        return result
    readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    raw_headers = {**headers, "Accept": "application/vnd.github.raw+json"}
    try:
        content, response_headers = request_bytes(readme_url, raw_headers)
        if "json" in response_headers.get("content-type", ""):
            item = json.loads(content)
            content = base64.b64decode(item.get("content", "")) if item.get("content") else b""
        result["readme_excerpt"] = clean(content.decode("utf-8", "replace"))[:MAX_CONTEXT_CHARS]
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        result["readme_status"] = f"readme_error:{getattr(exc, 'code', type(exc).__name__)}"
    return result


class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.body_depth = 0
        self.main_depth = 0
        self.skip_depth = 0
        self.body_parts: list[str] = []
        self.main_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.title = True
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "body":
            self.body_depth += 1
        if tag in {"main", "article"}:
            self.main_depth += 1
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            value = attrs.get("content") or ""
            if key and value:
                self.meta[key] = value

    def handle_endtag(self, tag):
        if tag == "title":
            self.title = False
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == "body":
            self.body_depth = max(0, self.body_depth - 1)
        if tag in {"main", "article"}:
            self.main_depth = max(0, self.main_depth - 1)

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self.title:
            self.title_parts.append(text)
        if self.body_depth and not self.skip_depth:
            self.body_parts.append(text)
            if self.main_depth:
                self.main_parts.append(text)

    def result(self):
        content = self.main_parts if self.main_parts else self.body_parts
        return {
            "title": clean(" ".join(self.title_parts))[:300],
            "description": clean(
                self.meta.get("og:description") or self.meta.get("description")
                or self.meta.get("twitter:description") or ""
            )[:1200],
            "content_excerpt": clean(" ".join(content))[:MAX_CONTEXT_CHARS],
        }


def fetch_page(url: str) -> dict:
    parts = urlsplit(url)
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    try:
        raw, _ = request_bytes(safe_url, {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (compatible; TabsMetadata/1.0)",
        })
        parser = PageParser()
        parser.feed(raw.decode("utf-8", "replace"))
        return {"status": "ok", **parser.result()}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {"status": f"fetch_error:{getattr(exc, 'code', type(exc).__name__)}"}


def write_data(data: dict) -> None:
    mode = stat.S_IMODE(DATA.stat().st_mode)
    fd, temporary = tempfile.mkstemp(prefix=".tabs-context-", suffix=".tmp", dir=DATA.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, mode)
        os.replace(temporary, DATA)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    tabs = data["tabs"]
    backup = DATA.with_name(f"{DATA.name}.pre-context.{datetime.now(UTC):%Y%m%dT%H%M%SZ}.bak")
    shutil.copy2(DATA, backup)
    groups: dict[tuple[str, str], list[dict]] = {}
    for tab in tabs:
        key = github_repo(tab.get("url") or "")
        if key:
            groups.setdefault(key, []).append(tab)

    github_pending = [key for key, items in groups.items()
                      if not all((item.get("source_metadata") or {}).get("github", {}).get("status") == "ok" for item in items)]
    pages: dict[str, list[dict]] = {}
    for tab in tabs:
        if github_repo(tab.get("url") or ""):
            continue
        if tab.get("text") and len(tab["text"]) >= 1000:
            continue
        url = tab.get("url") or ""
        host = urlsplit(url).netloc.lower()
        if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}:
            continue
        metadata = (tab.get("source_metadata") or {}).get("page") or {}
        if metadata.get("status") == "ok" and metadata.get("content_excerpt"):
            continue
        pages.setdefault(url, []).append(tab)

    token = subprocess.check_output(["gh", "auth", "token"], text=True).strip() if github_pending else ""
    print(f"tabs={len(tabs)} unique_github_repos={len(groups)} github_to_fetch={len(github_pending)} pages_to_fetch={len(pages)} backup={backup}", flush=True)
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {}
            for key in github_pending:
                need_readme = not any(len(item.get("text") or "") >= 1000 for item in groups[key])
                futures[pool.submit(fetch_github, key, token, need_readme)] = ("github", key)
            for url, items in pages.items():
                futures[pool.submit(fetch_page, url)] = ("page", url)
            for future in as_completed(futures):
                kind, key = futures[future]
                result = future.result()
                if kind == "github":
                    for tab in groups[key]:
                        tab.setdefault("source_metadata", {})["github"] = result
                else:
                    for tab in pages[key]:
                        tab.setdefault("source_metadata", {})["page"] = result
                        if result.get("status") == "ok" and result.get("title") and not tab.get("title"):
                            tab["title"] = result["title"]
                        if result.get("status") == "ok" and result.get("content_excerpt"):
                            tab["text"] = " ".join(filter(None, [tab.get("text"), result["content_excerpt"]]))[:MAX_CONTEXT_CHARS]
                done += 1
                if done % CHECKPOINT_EVERY == 0 or done == len(futures):
                    write_data(data)
                if done % 50 == 0 or done == len(futures):
                    print(f"enriched={done}/{len(futures)}", flush=True)
    except BaseException:
        write_data(data)
        raise
    finally:
        write_data(data)
    gh_ok = sum((t.get("source_metadata") or {}).get("github", {}).get("status") == "ok" for t in tabs)
    page_ok = sum((t.get("source_metadata") or {}).get("page", {}).get("status") == "ok" for t in tabs)
    print(f"github_rows_with_metadata={gh_ok} page_rows_with_metadata={page_ok}")


if __name__ == "__main__":
    main()
