"""Discover and safely download directory-hosted ODeR index packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import os
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from core import oder_package


MEDIA_TYPE = "application/vnd.oder+zip"
RELATION = "oder-index"
ROOT_CANDIDATES = ("index.oder", "directory.oder", ".well-known/oder.oder")
MAX_ADVERTISEMENT_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = oder_package.MAX_CACHE_BYTES + (16 * 1024 * 1024)


class HostedIndexStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class HostedIndexResult:
    status: str
    source: str
    discovered_via: str
    requests: int
    etag: str | None = None
    last_modified: str | None = None
    info: oder_package.PackageInfo | None = None
    package_path: str | None = None
    cache_path: str | None = None
    bytes_downloaded: int = 0

    def source_record(self) -> dict:
        record = {
            "mode": "hosted_oder",
            "source": self.source,
            "discovered_via": self.discovered_via,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.info is not None:
            record.update({
                "package_created_at": self.info.created_at,
                "package_app_version": self.info.app_version,
                "cache_entries": self.info.cache_entries,
                "cache_folders": self.info.cache_folders,
                "cache_files": self.info.cache_files,
            })
        return record


class _AdvertisementParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): value for key, value in attrs}
        tag = tag.lower()
        href = values.get("href")
        rel = {part.casefold() for part in str(values.get("rel") or "").split()}
        if tag == "link" and href and RELATION in rel:
            self.urls.append(href)
        elif tag == "meta" and str(values.get("name") or "").casefold() in {
            RELATION, "oder:package", "oder-package",
        }:
            if values.get("content"):
                self.urls.append(values["content"])
        elif tag == "a" and href:
            path = urlsplit(href).path.casefold()
            if RELATION in rel or "data-oder-index" in values or path.endswith(".oder"):
                self.urls.append(href)


def _http_url(value: str, base_url: str | None = None) -> str | None:
    value = urljoin(base_url, str(value or "").strip()) if base_url else str(value or "").strip()
    parts = urlsplit(value)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def advertised_package_urls(base_url: str, html_text: str, link_header: str = "") -> list[str]:
    """Extract standard HTTP and HTML advertisements in priority order."""
    values = []
    for match in re.finditer(r"<([^>]+)>\s*((?:;\s*[^,]+)*)", str(link_header or "")):
        params = match.group(2)
        rel_match = re.search(r";\s*rel\s*=\s*\"?([^\";,]+)", params, re.IGNORECASE)
        relations = {part.casefold() for part in (rel_match.group(1).split() if rel_match else [])}
        type_match = re.search(r";\s*type\s*=\s*\"?([^\";,]+)", params, re.IGNORECASE)
        media_type = type_match.group(1).casefold() if type_match else ""
        if RELATION in relations or media_type == MEDIA_TYPE:
            values.append(match.group(1))
    parser = _AdvertisementParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass
    values.extend(parser.urls)
    result = []
    seen = set()
    for value in values:
        url = _http_url(value, base_url)
        if url and url not in seen:
            result.append(url)
            seen.add(url)
    return result


def _response_text_limited(response) -> str:
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        remaining = MAX_ADVERTISEMENT_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= MAX_ADVERTISEMENT_BYTES:
            break
    encoding = getattr(response, "encoding", None) or "utf-8"
    try:
        return b"".join(chunks).decode(encoding, errors="replace")
    except LookupError:
        return b"".join(chunks).decode("utf-8", errors="replace")


def _remote_advertisements(session, base_url: str, timeout: float) -> tuple[list[str], int]:
    response = None
    try:
        response = session.get(
            base_url,
            timeout=timeout,
            headers={"Accept": f"text/html, application/xhtml+xml, {MEDIA_TYPE};q=0.8"},
            stream=True,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return [], 1
        html_text = _response_text_limited(response)
        headers = getattr(response, "headers", {}) or {}
        return advertised_package_urls(
            getattr(response, "url", None) or base_url,
            html_text,
            headers.get("Link", ""),
        ), 1
    except Exception:
        return [], 1
    finally:
        if response is not None:
            response.close()


def _download_candidate(session, url: str, via: str, timeout: float,
                        package_path: str, cache_path: str, previous: dict | None,
                        stop_check=None, progress_cb=None, log=print):
    headers = {"Accept": MEDIA_TYPE}
    if previous and previous.get("source") == url:
        if previous.get("etag"):
            headers["If-None-Match"] = str(previous["etag"])
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = str(previous["last_modified"])
    conditional_sent = "If-None-Match" in headers or "If-Modified-Since" in headers
    response = None
    try:
        response = session.get(
            url, timeout=timeout, headers=headers, stream=True, allow_redirects=True,
        )
        final_url = _http_url(getattr(response, "url", None) or url) or url
        response_headers = getattr(response, "headers", {}) or {}
        if (response.status_code == 304 and conditional_sent
                and previous and previous.get("source") == url):
            return HostedIndexResult(
                status="unchanged", source=url, discovered_via=via, requests=1,
                etag=response_headers.get("ETag") or previous.get("etag"),
                last_modified=response_headers.get("Last-Modified") or previous.get("last_modified"),
            )
        if response.status_code != 200:
            return None
        try:
            expected_size = int(response_headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            expected_size = 0
        if expected_size > MAX_PACKAGE_BYTES:
            log(f"hosted .oder is too large to download automatically: {final_url}")
            return None
        for path in (package_path, cache_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        downloaded = 0
        saw_header = False
        with open(package_path, "wb") as target:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if stop_check and stop_check():
                    raise HostedIndexStopped("stopped by user")
                if not chunk:
                    continue
                if not saw_header:
                    saw_header = True
                    if not chunk.startswith(b"PK"):
                        log(f"ignored non-package response from hosted .oder candidate: {final_url}")
                        return None
                downloaded += len(chunk)
                if downloaded > MAX_PACKAGE_BYTES:
                    raise oder_package.PackageError("The hosted .oder package exceeds the automatic download limit.")
                target.write(chunk)
                if progress_cb:
                    progress_cb({
                        "phase": "hosted_download", "current": final_url,
                        "bytes_downloaded": downloaded, "bytes_total": expected_size,
                    })
        info = oder_package.inspect_package(package_path, cache_destination=cache_path)
        return HostedIndexResult(
            status="downloaded", source=final_url, discovered_via=via, requests=1,
            etag=response_headers.get("ETag"),
            last_modified=response_headers.get("Last-Modified"),
            info=info, package_path=package_path, cache_path=cache_path,
            bytes_downloaded=downloaded,
        )
    except HostedIndexStopped:
        raise
    except (OSError, oder_package.PackageError, ValueError) as exc:
        log(f"ignored hosted .oder candidate {url}: {exc}")
        return None
    except Exception as exc:
        log(f"could not retrieve hosted .oder candidate {url}: {exc}")
        return None
    finally:
        if response is not None:
            response.close()


def fetch_hosted_index(session, base_url: str, package_path: str, cache_path: str,
                       timeout: float = 20, explicit_url: str | None = None,
                       previous: dict | None = None, auto_detect: bool = True,
                       stop_check=None, progress_cb=None, log=print) -> HostedIndexResult | None:
    """Find, conditionally download, and validate a full hosted package."""
    base_url = base_url if base_url.endswith("/") else base_url + "/"
    requests_made = 0
    seen = set()

    def attempt(value, via):
        nonlocal requests_made
        url = _http_url(value, base_url)
        if not url or url in seen:
            return None
        seen.add(url)
        if progress_cb:
            progress_cb({"phase": "hosted_check", "current": url})
        result = _download_candidate(
            session, url, via, timeout, package_path, cache_path, previous,
            stop_check=stop_check, progress_cb=progress_cb, log=log,
        )
        requests_made += 1
        if result is None:
            return None
        if result.status == "downloaded":
            if not result.info or not result.info.has_cache:
                log(f"ignored hosted definition-only package: {result.source}")
                return None
            if result.info.base_url != base_url:
                log(
                    f"ignored hosted .oder for a different directory: {result.info.base_url} "
                    f"(expected {base_url})"
                )
                return None
        return HostedIndexResult(**{**result.__dict__, "requests": requests_made})

    initial = []
    if explicit_url:
        initial.append((explicit_url, "explicit"))
    elif previous and previous.get("mode") == "hosted_oder" and previous.get("source"):
        initial.append((previous["source"], "previous"))
    for value, via in initial:
        result = attempt(value, via)
        if result:
            return result

    if not auto_detect:
        return None
    advertisements, advertisement_requests = _remote_advertisements(session, base_url, timeout)
    requests_made += advertisement_requests
    for value in advertisements:
        result = attempt(value, "advertised")
        if result:
            return HostedIndexResult(**{**result.__dict__, "requests": requests_made})
    for filename in ROOT_CANDIDATES:
        result = attempt(urljoin(base_url, filename), "convention")
        if result:
            return HostedIndexResult(**{**result.__dict__, "requests": requests_made})
    return None
