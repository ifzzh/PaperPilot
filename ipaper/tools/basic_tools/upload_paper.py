"""
arXiv and DBLP metadata lookup helpers.

Untrusted PDF parsing belongs exclusively to the isolated Document Worker.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import arxiv
import html
import xml.etree.ElementTree as ET

from ipaper.tools.basic_tools.arxiv_client import get_bibtex_enhanced
from ipaper.tools.basic_tools.arxiv_network import arxiv_get, configure_arxiv_client

# ============================================================================
# Utility function
# ============================================================================


def _make_arxiv_client(*args: Any, **kwargs: Any) -> arxiv.Client:
    return configure_arxiv_client(arxiv.Client(*args, **kwargs))


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """
    standardization arXiv ID

    Args:
        arxiv_id: may be "arXiv:2502.05383", "2502.05383", "2502.05383v1" etc format

    Returns:
        standardized arXiv ID(like "2502.05383"), remove the version number
    """
    # Remove "arXiv:" prefix (case insensitive)
    arxiv_id = re.sub(r"^arxiv\s*:\s*", "", arxiv_id.strip(), flags=re.IGNORECASE)

    # Remove version number (v1, v2 wait)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)

    # Extract core ID（YYYY.NNNNN Format)
    match = re.search(r"(\d{4}\.\d{4,5})", arxiv_id)
    if match:
        return match.group(1)

    return arxiv_id


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """
    from URL extracted from arXiv ID

    Args:
        url: may be "https://arxiv.org/abs/2511.13720v1" or "https://doi.org/10.48550/arXiv.2511.13720"

    Returns:
        extracted arXiv ID, return on failure None
    """
    patterns = [
        r"arxiv\.org/(?:abs|pdf)/([\d.]+(?:v\d+)?)",
        r"doi\.org/10\.48550/arXiv\.([\d.]+)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            return _normalize_arxiv_id(arxiv_id)

    return None


def _extract_arxiv_id_from_filename(filename: str) -> Optional[str]:
    """
    Extract from file name arXiv ID

    Supported formats:
    - 1706.03762v7.pdf
    - arXiv:1706.03762v7.pdf
    - 1706.03762.pdf

    Args:
        filename: PDF file name

    Returns:
        extracted arXiv ID, return on failure None
    """
    # Remove .pdf suffix
    base = os.path.splitext(filename)[0]

    # match YYYY.NNNNNvN Format
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", base)
    if match:
        return _normalize_arxiv_id(match.group(0))

    # match arXiv:YYYY.NNNNNvN Format
    match = re.search(r"arxiv[:\-\s]?(\d{4}\.\d{4,5})(v\d+)?", base, re.IGNORECASE)
    if match:
        return _normalize_arxiv_id(match.group(0))

    return None


# ============================================================================
# Way1: pass arXiv ID Get paper information
# ============================================================================


def fetch_paper_by_arxiv_id_fast(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    Quick version: Pass only arXiv API Get paper information (without waiting DBLP）

    Args:
        arxiv_id: arXiv ID(like "2502.05383" or "arXiv:2502.05383"）

    Returns:
        Dissertation Information Dictionary,bibtex The field is empty (followed by DBLP filling)
    """
    try:
        # standardization arXiv ID
        arxiv_id = _normalize_arxiv_id(arxiv_id)
        print(f"[arXiv Fast] pass arXiv ID Get the paper: {arxiv_id}")

        def _clean_text(text: Optional[str]) -> Optional[str]:
            if not text:
                return None
            return re.sub(r"\s+", " ", text).strip() or None

        def _fetch_via_atom_api(normalized_arxiv_id: str) -> Optional[Dict[str, Any]]:
            try:
                api_urls = [
                    "https://export.arxiv.org/api/query",
                    "https://arxiv.org/api/query",
                ]
                response_text = None
                last_exc: Optional[Exception] = None
                headers = {"User-Agent": "iPaper/1.0"}

                for api_url in api_urls:
                    try:
                        response = arxiv_get(
                            api_url,
                            params={"id_list": normalized_arxiv_id},
                            headers=headers,
                            timeout=20,
                        )
                        response.raise_for_status()
                        response_text = response.text
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        continue

                if not response_text:
                    if last_exc:
                        raise last_exc
                    return None

                root = ET.fromstring(response_text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entry = root.find("atom:entry", ns)
                if entry is None:
                    return None

                title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns))
                summary = entry.findtext("atom:summary", default="", namespaces=ns)
                published = _clean_text(
                    entry.findtext("atom:published", default="", namespaces=ns)
                )

                authors = [
                    _clean_text(author.findtext("atom:name", default="", namespaces=ns))
                    for author in entry.findall("atom:author", ns)
                ]
                authors = [a for a in authors if a]
                authors_str = ", ".join(authors)

                categories = [
                    cat.attrib.get("term")
                    for cat in entry.findall("atom:category", ns)
                    if cat.attrib.get("term")
                ]
                primary_category = categories[0] if categories else None

                year = None
                if published and len(published) >= 4:
                    year = published[:4]

                return {
                    "title": title,
                    "authors": authors_str,
                    "abstract": _clean_text(summary),
                    "summary": summary,
                    "year": year,
                    "arxiv_id": normalized_arxiv_id,
                    "arxiv_url": f"https://arxiv.org/abs/{normalized_arxiv_id}",
                    "bibtex": "",
                    "published_date": published,
                    "pdf_url": f"https://arxiv.org/pdf/{normalized_arxiv_id}.pdf",
                    "primary_category": primary_category,
                    "categories": categories,
                }
            except Exception as exc:  # noqa: BLE001
                print(f"[arXiv Atom] ❌ Failed to get metadata: {exc}")
                return None

        def _fetch_via_abs_page(normalized_arxiv_id: str) -> Optional[Dict[str, Any]]:
            try:
                abs_url = f"https://arxiv.org/abs/{normalized_arxiv_id}"
                response = arxiv_get(
                    abs_url,
                    headers={"User-Agent": "iPaper/1.0"},
                    timeout=20,
                )
                response.raise_for_status()
                page = response.text

                title_match = re.search(
                    r'<h1[^>]*class="title[^"]*"[^>]*>(?P<body>[\s\S]*?)</h1>',
                    page,
                    flags=re.IGNORECASE,
                )
                if not title_match:
                    return None
                title_body = title_match.group("body")
                title_body = re.sub(r"<[^>]+>", " ", title_body)
                title_body = html.unescape(title_body)
                title_body = re.sub(r"^\s*Title:\s*", "", title_body).strip()
                title = _clean_text(title_body)
                if not title:
                    return None

                authors_match = re.search(
                    r'<div[^>]*class="authors"[^>]*>(?P<body>[\s\S]*?)</div>',
                    page,
                    flags=re.IGNORECASE,
                )
                authors_str = ""
                if authors_match:
                    authors_body = authors_match.group("body")
                    authors = re.findall(r">([^<]+)</a>", authors_body, flags=re.IGNORECASE)
                    authors = [html.unescape(a).strip() for a in authors]
                    authors = [a for a in authors if a]
                    authors_str = ", ".join(authors)

                abstract_match = re.search(
                    r'<blockquote[^>]*class="abstract[^"]*"[^>]*>(?P<body>[\s\S]*?)</blockquote>',
                    page,
                    flags=re.IGNORECASE,
                )
                abstract = None
                if abstract_match:
                    abstract_body = abstract_match.group("body")
                    abstract_body = re.sub(r"<[^>]+>", " ", abstract_body)
                    abstract_body = html.unescape(abstract_body)
                    abstract_body = re.sub(r"^\s*Abstract:\s*", "", abstract_body).strip()
                    abstract = _clean_text(abstract_body)

                return {
                    "title": title,
                    "authors": authors_str,
                    "abstract": abstract,
                    "summary": abstract or "",
                    "year": None,
                    "arxiv_id": normalized_arxiv_id,
                    "arxiv_url": abs_url,
                    "bibtex": "",
                    "published_date": None,
                    "pdf_url": f"https://arxiv.org/pdf/{normalized_arxiv_id}.pdf",
                    "primary_category": None,
                    "categories": None,
                }
            except Exception as exc:  # noqa: BLE001
                print(f"[arXiv HTML] ❌ Failed to get metadata: {exc}")
                return None

        result: Optional[Dict[str, Any]] = None

        try:
            client = _make_arxiv_client()
            search = arxiv.Search(id_list=[arxiv_id])

            paper = next(client.results(search), None)
            if paper and getattr(paper, "title", None):
                authors_list = [author.name for author in paper.authors]
                authors_str = ", ".join(authors_list)

                title = _clean_text(paper.title)
                summary = getattr(paper, "summary", "") or ""
                published_date = paper.published.isoformat() if paper.published else None
                year = str(paper.published.year) if paper.published else None

                result = {
                    "title": title,
                    "authors": authors_str,
                    "abstract": _clean_text(summary),
                    "summary": summary,
                    "year": year,
                    "arxiv_id": arxiv_id,
                    "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                    "bibtex": "",
                    "published_date": published_date,
                    "pdf_url": getattr(paper, "pdf_url", None),
                    "primary_category": getattr(paper, "primary_category", None),
                    "categories": getattr(paper, "categories", None),
                }
        except Exception as exc:  # noqa: BLE001
            print(f"[arXiv Fast] arxiv lib failed, fallback to Atom API: {exc}")

        if not result or not result.get("title"):
            result = _fetch_via_atom_api(arxiv_id)

        if not result or not result.get("title"):
            result = _fetch_via_abs_page(arxiv_id)

        if not result or not result.get("title"):
            print(f"[arXiv Fast] not found arXiv ID: {arxiv_id}")
            return None

        print(f"[arXiv Fast] ✅ Successfully obtained the paper: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[arXiv Fast] ❌ Failed to get the paper: {exc}")
        import traceback

        traceback.print_exc()
        return None


def fetch_bibtex_from_dblp(title: str, authors: str, arxiv_id: str) -> Optional[str]:
    """
    from DBLP get BibTeX(Can be called in the background)

    Args:
        title: Paper title
        authors: author string
        arxiv_id: arXiv ID

    Returns:
        BibTeX String, returned on failure None
    """
    try:
        print(f"[DBLP] get BibTeX: {title[:50]}...")
        bibtex = get_bibtex_enhanced(title=title, authors=authors, arxiv_id=arxiv_id)
        if bibtex:
            print(f"[DBLP] ✅ successfully obtained BibTeX")
        else:
            print(f"[DBLP] ❌ Not obtained BibTeX")
        return bibtex
    except Exception as exc:
        print(f"[DBLP] ❌ get BibTeX fail: {exc}")
        return None


def fetch_paper_by_arxiv_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    Way1: pass arXiv ID Get complete paper information (including DBLP BibTeX）

    process:
    1. standardization arXiv ID
    2. call arXiv API Get basic information (title, authors, abstract, yearwait)
    3. use title + authors from DBLP get better BibTeX(overwrite if found)

    Args:
        arxiv_id: arXiv ID(like "2502.05383" or "arXiv:2502.05383"）

    Returns:
        Paper information dictionary, including the following fields:
        - title: Paper title
        - authors: Author string (comma separated)
        - abstract: summary
        - year: year of publication
        - arxiv_id: arXiv ID
        - bibtex: BibTeX Quote (priority DBLP, use after failure arXiv）
        - published_date: release date
        - pdf_url: PDF Download link
        - primary_category: Main categories
        If failed return None
    """
    # Get it quickly first arXiv information
    result = fetch_paper_by_arxiv_id_fast(arxiv_id)
    if not result:
        return None

    # then get DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result



def search_arxiv_by_title_and_author_fast(
    title: str, author: str
) -> Optional[Dict[str, Any]]:
    """
    Quick version: Search using title and author arXiv Thesis (no waiting DBLP）

    Args:
        title: Paper title
        author: Author name (can be the first author)

    Returns:
        Dissertation Information Dictionary,bibtex Field is empty
    """
    try:
        # Clean special characters (like colons) in titles
        clean_title = title.replace(":", " ")

        # Construct query string
        query = f'ti:"{clean_title}" AND au:"{author}"'
        print(f"[Way2.3 Fast] Use titles+Author search arXiv: [{query}]")

        # use arxiv library search
        client = _make_arxiv_client()
        search = arxiv.Search(
            query=query, max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[Way2.3 Fast] No matching paper found")
            return None

        # extract arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # Get author information
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"[Way2.3 Fast] ✅ Find matching papers: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[Way2.3 Fast] ❌ Search failed: {exc}")
        import traceback

        traceback.print_exc()
        return None


def search_arxiv_by_title_only_fast(title: str) -> Optional[Dict[str, Any]]:
    """
    Quick version: search using title only arXiv Thesis (no waiting DBLP）

    Args:
        title: Paper title

    Returns:
        Dissertation Information Dictionary,bibtex Field is empty
    """
    try:
        print(f"[Way2.4 Fast] Search using titles arXiv: {title[:50]}...")

        # use arxiv library search
        client = _make_arxiv_client()
        search = arxiv.Search(
            query=f'ti:"{title}"', max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[Way2.4 Fast] No matching paper found")
            return None

        # extract arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # Get author information
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"[Way2.4 Fast] ✅ Find matching papers: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[Way2.4 Fast] ❌ Search failed: {exc}")
        import traceback

        traceback.print_exc()
        return None


def search_arxiv_by_title_and_author(
    title: str, author: str
) -> Optional[Dict[str, Any]]:
    """
    Search using title and author arXiv Papers (including DBLP BibTeX）

    use arXiv Query syntax: ti:"title" AND au:"author"

    Args:
        title: Paper title
        author: Author name (can be the first author)

    Returns:
        Paper information dictionary (the format is the same as fetch_paper_by_arxiv_id), return on failure None
    """
    # Get it quickly first arXiv information
    result = search_arxiv_by_title_and_author_fast(title, author)
    if not result:
        return None

    # then get DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result


def search_arxiv_by_title_only(title: str) -> Optional[Dict[str, Any]]:
    """
    Search using title only arXiv Papers (including DBLP BibTeX）

    Args:
        title: Paper title

    Returns:
        Paper information dictionary (the format is the same as fetch_paper_by_arxiv_id), return on failure None
    """
    # Get it quickly first arXiv information
    result = search_arxiv_by_title_only_fast(title)
    if not result:
        return None

    # then get DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result
