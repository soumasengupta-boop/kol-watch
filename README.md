# Cardiology KOL Watch

A weekly, phone-friendly dashboard of what preventive, imaging and international cardiology
key opinion leaders (KOLs) are posting on **Bluesky** and **LinkedIn**.

```
config/kols.csv ──► collect ──► tag (Claude) ──► trends + digest (Claude) ──► site/index.html ──► Cloudflare Pages
 (your roster)     Bluesky API     topics, trials,     8-week topic share,          mobile dashboard      (login-protected)
                   Bright Data     drugs, stance       papers, debates, regions
```

Runs every Monday on GitHub Actions. You can also start it by hand from the GitHub app,
from your laptop, or run everything locally.

---

## One-time setup (≈15 minutes)

### 1. Create the repo
Create a **private** GitHub repo (e.g. `kol-watch`) and push this folder to it.

### 2. Add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `BRIGHTDATA_API_KEY` | Bright Data → Account settings → API key |
| `CLOUDFLARE_API_TOKEN` | Cloudflare → My Profile → API Tokens → *Create token* → template **"Edit Cloudflare Workers"** or a custom token with **Account › Cloudflare Pages › Edit** |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard → right sidebar of any page (Account ID) |

The Cloudflare secrets are optional. Without them the dashboard is still built and saved as a
downloadable artifact on each workflow run, and archived in `data/reports/`.

### 3. Create the Cloudflare Pages project (optional, for phone access)
1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Upload assets**, name it `kol-watch`
   (or set a repo variable `CLOUDFLARE_PAGES_PROJECT` to a different name). Upload any placeholder file.
2. Lock it to you: **Zero Trust → Access → Applications → Add → Self-hosted**.
   Domain `kol-watch.pages.dev` (add a second one for `*.kol-watch.pages.dev` to cover preview URLs),
   policy **Allow → Include → Emails →** your email. You'll log in with a one-time code sent to that email.

### 4. Find the KOLs' handles
Actions → **kol-report → Run workflow →** mode **`resolve-handles`**.

- Bluesky handles come from Bluesky's free search; LinkedIn URLs from Claude web search.
- High-confidence matches are written into `config/kols.csv` (blank cells only, never overwriting your edits).
- Everything it found, including lower-confidence suggestions, is in `data/handle_candidates.csv`.
  Review it and paste any correct ones into `kols.csv`. Delete wrong auto-matches.

### 5. First run with history
Run workflow → mode **`run`**, days **`56`**, **skip LinkedIn ✓**. This backfills 8 weeks of Bluesky posts
(free) so the trend lines have history from day one. After that the Monday job takes care of itself.

---

## Running it

| From | How |
|---|---|
| Phone | GitHub app → repo → **Actions → kol-report → Run workflow** |
| Laptop (cloud run) | `gh workflow run kol-report -f mode=run` |
| Laptop (local run) | see below |

**Local run**
```bash
git pull                          # get the latest stored data
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill in ANTHROPIC_API_KEY and BRIGHTDATA_API_KEY
python -m kolwatch run            # collect + tag + report -> site/index.html
python -m kolwatch run --skip-linkedin --days 14
python -m kolwatch report         # re-render from stored data only
python -m kolwatch demo           # preview with fake data, no keys needed -> demo-site/index.html
```
If you run locally and want the data kept, commit and push `data/` and `config/kols.csv`.

---

## Editing what it tracks

- **KOLs:** `config/kols.csv`. Set `include` to `N` to pause someone. Add a row with just a name and run
  `resolve-handles` to find their accounts. Put `INDUSTRY` in `notes` to badge company-affiliated people.
- **Topics:** `config/topics.yaml`. The tagger reads each topic's `description`, so edit those to
  change what counts. New topics apply to newly tagged posts (delete `data/tags.jsonl` to re-tag everything).
- **Models:** set `KOLWATCH_TAG_MODEL` / `KOLWATCH_DIGEST_MODEL` (defaults: `claude-haiku-5-5`, `claude-sonnet-5-5`).

## What it costs (rough)

- **Bluesky:** free.
- **Bright Data:** at most 15 posts per profile per week (`KOLWATCH_LINKEDIN_POSTS_PER_PROFILE`).
  With ~80 LinkedIn profiles that's ≤1,200 records/week; usually far fewer, since most people post less.
- **Anthropic:** tagging uses the small model in batches of 25 and caches results, plus one digest call per week:
  typically well under $1/week. The one-time `resolve-handles` run uses web search (a few dollars at most).

## Data and privacy notes

- Only public posts are collected. LinkedIn data comes through Bright Data's logged-out collection;
  you never connect your own LinkedIn account. Bright Data knows your account; LinkedIn does not.
- The dashboard is `noindex` and, with Cloudflare Access, visible only to you.
- Tags and digests are AI-generated. The digest is instructed to use only the week's posts, but always
  check the linked source before relying on a claim.

## Files

```
config/kols.csv              roster (edit me)
config/topics.yaml           topic taxonomy (edit me)
data/posts.jsonl             all collected posts (deduped)
data/tags.jsonl              tag cache
data/handle_candidates.csv   resolver suggestions to review
data/reports/                weekly archive (HTML + JSON)
kolwatch/                    code
.github/workflows/kol-report.yml
```

## Troubleshooting

- **LinkedIn step fails with a Bright Data error:** the run continues with Bluesky only. Check the
  error in the Actions log; if Bright Data renamed its posts dataset, set `BRIGHTDATA_POSTS_DATASET`.
  You can test it alone locally: `python -m kolwatch collect --days 8 --strict`.
- **A KOL shows no posts:** check their handle/URL in `kols.csv`, or they may simply not have posted.
- **Wrong person matched:** fix or clear the cell in `kols.csv`; the resolver never overwrites a filled cell.
