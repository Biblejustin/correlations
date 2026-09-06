#!/usr/bin/env python3
"""Check three official release pages once per calendar month; never adopt data.

Copy release_review_seed_2026-09.json to STATE_DIR/2026-09.json at migration.
The runner supplies the America/Chicago date. A failed or interrupted attempt is
retained until next month; it requires review rather than repeated daily fetches.
Adopted versions below change only after an explicit source-version review.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SOURCES = {
    "cru_cy": {"adopted_version": "4.10", "product": "CRU-CY country averages",
               "url": "https://crudata.uea.ac.uk/cru/data/hrg/"},
    "ucdp_annual": {"adopted_version": "26.1", "product": "UCDP Country-Year Organized Violence within Country Borders",
                    "url": "https://ucdp.uu.se/downloads/"},
    "vdem_core": {"adopted_version": "16", "product": "V-Dem Country-Year Core",
                  "url": "https://www.v-dem.net/data/the-v-dem-dataset/"},
}
MAX_PAGE_BYTES = 2_000_000
MONTH_NAMES = "January February March April May June July August September October November December".split()
MONTH_PATTERN = "(?:" + "|".join(MONTH_NAMES) + ")"


class AmbiguousRelease(ValueError):
    """Expected same-product release evidence is absent or contradictory."""


def version_key(value):
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise AmbiguousRelease("Unexpected version format")
    parts = tuple(map(int, value.split(".")))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def normalized(value):
    return " ".join(value.split())


class Page(HTMLParser):
    """Keep visible text, links, and heading bounds; ignore executable/style text."""
    def __init__(self, payload):
        super().__init__(convert_charrefs=True)
        self.parts, self.headings, self.links = [], [], []
        self.list_stack, self.list_items = [], []
        self.skip = 0
        self.heading = None
        self.feed(payload.decode("utf-8", errors="replace"))
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.skip += 1
        if self.skip:
            return
        if tag == "li":
            self.list_stack.append(len(self.parts))
        if re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n")
            self.heading = (int(tag[1]), len(self.parts))
        elif tag in {"li", "p", "div", "tr", "br", "section"}:
            self.parts.append("\n")
        else:
            self.parts.append(" ")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"} and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "li" and self.list_stack:
            start = self.list_stack.pop()
            self.list_items.append(normalized("".join(self.parts[start:])))
        if re.fullmatch(r"h[1-6]", tag) and self.heading:
            level, start = self.heading
            self.headings.append({"level": level, "start": start, "body": len(self.parts),
                                  "title": normalized("".join(self.parts[start:]))})
            self.heading = None
        self.parts.append("\n" if tag in {"li", "p", "div", "tr", "section"} or re.fullmatch(r"h[1-6]", tag) else " ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    @property
    def text(self):
        return "".join(self.parts)

    def section(self, title):
        matching = [(i, h) for i, h in enumerate(self.headings) if re.fullmatch(title, h["title"], re.I)]
        if len(matching) != 1:
            raise AmbiguousRelease("Expected exactly one same-product heading")
        index, heading = matching[0]
        end = next((h["start"] for h in self.headings[index + 1:] if h["level"] <= heading["level"]), len(self.parts))
        return normalized("".join(self.parts[heading["body"]:end]))


def parse_cru(payload, as_of):
    page = Page(payload)
    releases = []
    pattern = rf"\b(\d{{1,2}}\s+{MONTH_PATTERN}\s+\d{{4}})\s+([^\n]*?\bCRU-CY\s*v?(\d+(?:\.\d+)+)\s+released)\b"
    for item in page.list_items:
        for match in re.finditer(pattern, item, re.I):
            published = dt.datetime.strptime(match[1], "%d %B %Y").date()
            if published <= as_of:
                releases.append((match[3], published, normalized(match[0])))
    if not releases:
        raise AmbiguousRelease("No dated, already-released CRU-CY announcement found")
    latest, published, evidence = max(releases, key=lambda r: version_key(r[0]))
    mentioned = re.findall(r"\bCRU-CY\s*v?(\d+(?:\.\d+)+)\b", page.text, re.I)
    if any(version_key(v) > version_key(latest) for v in mentioned):
        raise AmbiguousRelease("Higher CRU-CY version mentioned without a verified past release announcement")
    return {"latest_version": latest, "publication_date": published.isoformat(),
            "publication_date_precision": "day", "evidence": evidence}


def parse_ucdp(payload, as_of):
    page = Page(payload)
    pattern = r"UCDP\s+Country-Year\s+Dataset\s+on\s+Organized\s+Violence\s+within\s+Country\s+Borders\s+version\s+(\d+\.\d+(?:\.\d+)*)\b"
    matches = list(re.finditer(pattern, normalized(page.text), re.I))
    versions = {m[1] for m in matches}
    if len(versions) != 1:
        raise AmbiguousRelease("Missing or contradictory annual country-year release headings")
    latest = versions.pop()
    expected_path = "/downloads/organizedviolencecy/organizedviolencecy-" + latest.replace(".", "") + "-csv.zip"
    links = [urljoin(SOURCES["ucdp_annual"]["url"], link) for link in page.links]
    if not any(urlparse(url).scheme == "https" and urlparse(url).hostname == "ucdp.uu.se"
               and urlparse(url).path == expected_path for url in links):
        raise AmbiguousRelease("Annual country-year heading lacks matching official CSV release link")
    return {"latest_version": latest, "publication_date": None,
            "publication_date_precision": "not stated in verified release heading",
            "evidence": matches[0][0], "download_url": "https://ucdp.uu.se" + expected_path}


def parse_vdem(payload, as_of):
    body = Page(payload).section(r"Country-Year\s*:\s*V-Dem\s+Core")
    versions = set(re.findall(r"\bVersion\s*[:|]?\s*v?(\d+(?:\.\d+)*)\b", body, re.I))
    dates = re.findall(rf"\bPublished\s*[:|]?\s*({MONTH_PATTERN})\s+(\d{{4}})\b", body, re.I)
    if len(versions) != 1 or len(set(dates)) != 1:
        raise AmbiguousRelease("Missing or contradictory Core version/publication fields")
    month, year = dates[0]
    published = dt.date(int(year), [m.lower() for m in MONTH_NAMES].index(month.lower()) + 1, 1)
    if published > as_of:
        raise AmbiguousRelease("Core publication month lies in the future")
    latest = versions.pop()
    return {"latest_version": latest, "publication_date": published.strftime("%Y-%m"),
            "publication_date_precision": "month", "evidence": f"Country-Year: V-Dem Core; Version {latest}; Published {month} {year}"}


PARSERS = {"cru_cy": parse_cru, "ucdp_annual": parse_ucdp, "vdem_core": parse_vdem}


def fetch_page(url):
    request = Request(url, headers={"User-Agent": "Biblejustin-correlations-release-review/1.0"})
    with urlopen(request, timeout=30) as response:
        original, final = urlparse(url), urlparse(response.url)
        if final.scheme != "https" or final.hostname.removeprefix("www.") != original.hostname.removeprefix("www."):
            raise ValueError("Release page redirected outside its configured official origin")
        payload = response.read(MAX_PAGE_BYTES + 1)
    if not payload or len(payload) > MAX_PAGE_BYTES:
        raise ValueError("Release page empty or exceeds size limit")
    return payload


def atomic_json(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".release-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def problem(month, reason, *, status="incomplete", attention=True):
    return {"schema_version": 1, "month": month, "status": status,
            "review_needed": False, "attention_required": attention,
            "error": reason, "source_or_code_changes_made": False}


def cached_result(path, month):
    try:
        result = json.loads(path.read_text())
        if result["month"] != month or dt.date.fromisoformat(result["as_of"]).strftime("%Y-%m") != month:
            raise ValueError("Wrong monthly cache date")
        dt.datetime.fromisoformat(result["checked_at"])
        checks = result["checks"]
        if len(checks) != len(SOURCES) or {c["source_id"] for c in checks} != set(SOURCES):
            raise ValueError("Wrong monthly cache product membership")
        if any(c["adopted_version"] != SOURCES[c["source_id"]]["adopted_version"] for c in checks):
            raise ValueError("Adopted version changed since this monthly check; manual review required")
        if not isinstance(result["attention_required"], bool) or not isinstance(result["review_needed"], bool):
            raise ValueError("Invalid monthly cache status")
        known = {"current", "newer_release_review_candidate", "ambiguous", "fetch_or_capture_failed"}
        if any(c["status"] not in known or not isinstance(c["review_needed"], bool) for c in checks):
            raise ValueError("Invalid cached product status")
        for check in checks:
            if check["status"] in {"current", "newer_release_review_candidate"}:
                comparison = version_key(check["latest_version"]) > version_key(check["adopted_version"])
                if version_key(check["latest_version"]) < version_key(check["adopted_version"]):
                    raise ValueError("Cached current release predates adopted release")
                if comparison != (check["status"] == "newer_release_review_candidate") or comparison != check["review_needed"]:
                    raise ValueError("Cached release comparison is inconsistent")
            elif check["review_needed"]:
                raise ValueError("Failed check cannot assert a verified newer release")
        review = any(c["review_needed"] for c in checks)
        incomplete = any(c["status"] in {"ambiguous", "fetch_or_capture_failed"} for c in checks)
        expected_status = "incomplete" if incomplete else "review_candidate" if review else "current"
        if result["status"] != expected_status or result["review_needed"] != review or result["attention_required"] != (review or incomplete):
            raise ValueError("Cached summary is inconsistent with product checks")
        return {**result, "cached": True}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return problem(month, f"Existing monthly cache is invalid; no refetch: {error}")


def review_releases(state_dir, as_of=None, fetcher=None):
    """Return status/review_needed/attention_required; all writes stay in state_dir.

    review_needed identifies a verified newer release. attention_required also
    covers failed or ambiguous checks. Neither changes publication success.
    """
    day = dt.date.fromisoformat(str(as_of)) if as_of else dt.datetime.now(ZoneInfo("America/Chicago")).date()
    month = day.strftime("%Y-%m")
    folder = Path(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    result_path, started_path = folder / f"{month}.json", folder / f"{month}.started.json"
    with (folder / ".lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return problem(month, "Another monthly release review is running", status="pending", attention=False)
        if result_path.exists():
            return cached_result(result_path, month)
        if started_path.exists():
            return problem(month, "Prior monthly attempt did not finish; no automatic refetch this month")
        checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
        # as_of is the scheduler's local date; checked_at always records actual UTC.
        atomic_json(started_path, {"month": month, "as_of": day.isoformat(), "checked_at": checked_at})
        checks = []
        fetch = fetcher or fetch_page
        evidence_dir = folder / "evidence" / month
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for source_id, source in SOURCES.items():
            row = {"source_id": source_id, **source, "status": "unknown", "review_needed": False}
            phase = "fetch"
            try:
                payload = fetch(source["url"])
                if not isinstance(payload, bytes) or not payload or len(payload) > MAX_PAGE_BYTES:
                    raise ValueError("Invalid release page payload")
                raw_path = evidence_dir / f"{source_id}.html"
                raw_path.write_bytes(payload)
                row.update(page_sha256=hashlib.sha256(payload).hexdigest(), page_bytes=len(payload),
                           evidence_path=str(raw_path))
                phase = "parse"
                row.update(PARSERS[source_id](payload, day))
                latest, adopted = version_key(row["latest_version"]), version_key(row["adopted_version"])
                if latest < adopted:
                    raise AmbiguousRelease("Official parsed version predates adopted version; page may be stale")
                row.update(status="newer_release_review_candidate" if latest > adopted else "current",
                           review_needed=latest > adopted)
            except AmbiguousRelease as error:
                row.update(status="ambiguous", error=str(error))
            except Exception as error:
                row.update(status="ambiguous" if phase == "parse" else "fetch_or_capture_failed",
                           error=f"{type(error).__name__}: {error}")
            checks.append(row)
        review_needed = any(c["review_needed"] for c in checks)
        incomplete = any(c["status"] not in {"current", "newer_release_review_candidate"} for c in checks)
        result = {"schema_version": 1, "month": month, "as_of": day.isoformat(), "checked_at": checked_at,
                  "status": "incomplete" if incomplete else "review_candidate" if review_needed else "current",
                  "review_needed": review_needed, "attention_required": incomplete or review_needed,
                  "checks": checks, "source_or_code_changes_made": False,
                  "interpretation": "Release labels only. Changes remain review candidates; no data adoption, splicing, plan changes or external notification."}
        atomic_json(result_path, result)
        return {**result, "cached": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--as-of", help="America/Chicago calendar date, YYYY-MM-DD")
    args = parser.parse_args()
    result = review_releases(args.state_dir, args.as_of)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 2 if result["attention_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
