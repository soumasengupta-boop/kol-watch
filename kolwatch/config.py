"""Paths, settings and small shared helpers."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import yaml

try:  # .env is optional; GitHub Actions passes secrets as env vars
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(os.environ.get("KOLWATCH_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"

KOLS_CSV = CONFIG_DIR / "kols.csv"
TOPICS_YAML = CONFIG_DIR / "topics.yaml"

POSTS_FILE = DATA_DIR / "posts.jsonl"          # every collected post, deduped by id
TAGS_FILE = DATA_DIR / "tags.jsonl"            # tagger output, keyed by post id
CANDIDATES_FILE = DATA_DIR / "handle_candidates.csv"  # resolver suggestions for review
REPORTS_DIR = DATA_DIR / "reports"             # archived weekly HTML + JSON summaries

TAG_MODEL = os.environ.get("KOLWATCH_TAG_MODEL", "claude-haiku-5-5")
DIGEST_MODEL = os.environ.get("KOLWATCH_DIGEST_MODEL", "claude-sonnet-5-5")
RESOLVE_MODEL = os.environ.get("KOLWATCH_RESOLVE_MODEL", "claude-sonnet-5-5")

BRIGHTDATA_POSTS_DATASET = os.environ.get("BRIGHTDATA_POSTS_DATASET", "gd_lyy3tktm25m4avu764")
LINKEDIN_POSTS_PER_PROFILE = int(os.environ.get("KOLWATCH_LINKEDIN_POSTS_PER_PROFILE", "15"))

USER_AGENT = "kolwatch/0.1 (personal research dashboard)"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    """Parse ISO-ish timestamps from Bluesky / Bright Data into aware UTC datetimes."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(v, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- KOL roster
@dataclass
class KOL:
    name: str
    type: str = "person"
    region: str = ""
    country: str = ""
    affiliation: str = ""
    focus_tags: str = ""
    why_included: str = ""
    bluesky_handle: str = ""
    linkedin_url: str = ""
    x_handle: str = ""
    notes: str = ""
    include: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def industry(self) -> bool:
        return "INDUSTRY" in self.notes.upper()

    @property
    def region_bucket(self) -> str:
        r = self.region.lower()
        if "north america" in r and "/" not in r:
            return "North America"
        if r.startswith("europe"):
            return "Europe"
        if "asia" in r:
            return "Asia-Pacific"
        if "latin" in r:
            return "Latin America"
        if "africa" in r:
            return "Africa"
        return "Global"


KOL_COLUMNS = [
    "include", "name", "type", "region", "country", "affiliation_to_verify", "focus_tags",
    "why_included", "bluesky_handle", "linkedin_url", "x_handle", "notes",
]


def load_kols(include_only: bool = True) -> list[KOL]:
    out: list[KOL] = []
    with open(KOLS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            inc = row.get("include", "Y").upper() not in ("N", "NO", "0", "FALSE")
            if include_only and not inc:
                continue
            out.append(
                KOL(
                    name=row["name"],
                    type=row.get("type", "person") or "person",
                    region=row.get("region", ""),
                    country=row.get("country", ""),
                    affiliation=row.get("affiliation_to_verify", ""),
                    focus_tags=row.get("focus_tags", ""),
                    why_included=row.get("why_included", ""),
                    bluesky_handle=row.get("bluesky_handle", "").lstrip("@"),
                    linkedin_url=row.get("linkedin_url", ""),
                    x_handle=row.get("x_handle", "").lstrip("@"),
                    notes=row.get("notes", ""),
                    include=inc,
                    extra={k: v for k, v in row.items() if k not in KOL_COLUMNS},
                )
            )
    return out


def update_kol_fields(updates: dict[str, dict[str, str]]) -> int:
    """Write handle/URL updates back into kols.csv. updates = {name: {column: value}}.
    Only fills empty cells, so manual edits are never overwritten."""
    with open(KOLS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or KOL_COLUMNS
        rows = list(reader)
    changed = 0
    for row in rows:
        upd = updates.get(row.get("name", ""))
        if not upd:
            continue
        for col, val in upd.items():
            if val and not (row.get(col) or "").strip():
                row[col] = val
                changed += 1
    with open(KOLS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return changed


def load_topics() -> dict:
    with open(TOPICS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- JSONL store
def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def upsert_jsonl(path: Path, records: Iterable[dict], key: str = "id") -> tuple[int, int]:
    """Merge records into a JSONL file keyed by `key`. Returns (added, updated)."""
    existing = {r[key]: r for r in read_jsonl(path) if key in r}
    added = updated = 0
    for r in records:
        k = r.get(key)
        if not k:
            continue
        if k in existing:
            if existing[k] != r:
                existing[k] = {**existing[k], **r}
                updated += 1
        else:
            existing[k] = r
            added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in sorted(existing.values(), key=lambda x: x.get("created_at", "")):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return added, updated
