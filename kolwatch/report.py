"""Render the weekly dashboard as a single self-contained, phone-friendly HTML page."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, select_autoescape

from .config import REPORTS_DIR, SITE_DIR


def sparkline(values: list[float], w: int = 96, h: int = 26) -> str:
    if not values:
        return ""
    hi = max(max(values), 1.0)
    n = len(values)
    step = w / max(n - 1, 1)
    pts = [(i * step, h - 2 - (v / hi) * (h - 4)) for i, v in enumerate(values)]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    lx, ly = pts[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<path d="{path}" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.4" fill="currentColor"/></svg>')


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>Cardiology KOL Watch · {{ s.label }}</title>
<style>
:root{
  --bg:#f7f6f3; --card:#fff; --ink:#1b1b1f; --muted:#6b6b73; --line:#e6e4df;
  --accent:#b4232a; --up:#0f7b4f; --down:#9a5a00; --chip:#f0eee9; --link:#1c4f9c;
  --radius:14px;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#111214; --card:#1a1b1f; --ink:#ececf0; --muted:#9a9aa5; --line:#2a2b31;
         --accent:#ff6b6b; --up:#4fd19a; --down:#f0b25a; --chip:#24252b; --link:#8fb6ff; }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  padding:env(safe-area-inset-top) 0 40px}
a{color:var(--link);text-decoration:none}
.wrap{max-width:760px;margin:0 auto;padding:0 14px}
header{padding:22px 2px 10px}
.kicker{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:700}
h1{font-size:24px;line-height:1.2;margin:4px 0 6px;letter-spacing:-.01em}
.meta{color:var(--muted);font-size:13px}
nav.toc{display:flex;gap:6px;overflow-x:auto;padding:10px 0 4px;margin:0 -14px;padding-left:14px;
  scrollbar-width:none;position:sticky;top:0;background:var(--bg);z-index:2}
nav.toc::-webkit-scrollbar{display:none}
nav.toc a{flex:none;font-size:13px;padding:6px 11px;border-radius:999px;background:var(--chip);color:var(--ink)}
section{margin-top:18px}
h2{font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:0 2px 8px;font-weight:700}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px 15px}
.card + .card{margin-top:10px}
.headline{font-size:18px;line-height:1.35;font-weight:650;margin:0 0 4px}
.kp{padding:10px 0;border-top:1px solid var(--line)}
.kp:first-of-type{border-top:0;padding-top:4px}
.kp b{display:block;font-size:15px;margin-bottom:2px}
.kp p{margin:0;color:var(--ink)}
.refs{margin-top:4px;font-size:12px}
.refs a{margin-right:8px}
ul.plain{margin:0;padding-left:18px}
ul.plain li{margin:4px 0}
.topic{display:grid;grid-template-columns:1fr auto;gap:2px 10px;align-items:center;padding:11px 0;border-top:1px solid var(--line)}
.topic:first-child{border-top:0;padding-top:2px}
.tname{font-weight:600}
.tsub{grid-column:1/2;color:var(--muted);font-size:12.5px}
.tright{grid-row:1/3;grid-column:2;text-align:right;color:var(--muted)}
.share{font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink);font-size:15px}
.delta{font-size:12px;font-variant-numeric:tabular-nums}
.up{color:var(--up)} .down{color:var(--down)}
.spark{display:block;margin-left:auto;color:var(--muted)}
.topic.hot .spark{color:var(--accent)}
.badge{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  padding:1px 6px;border-radius:5px;margin-left:6px;vertical-align:2px}
.b-hot{background:var(--accent);color:#fff}
.b-cool{background:var(--chip);color:var(--down)}
.b-new{background:var(--chip);color:var(--up)}
.b-ind{background:var(--chip);color:var(--down)}
details{margin-top:6px}
details summary{cursor:pointer;color:var(--link);font-size:13px;list-style:none}
details summary::-webkit-details-marker{display:none}
.post{padding:10px 0;border-top:1px solid var(--line)}
.post:first-child{border-top:0}
.who{font-weight:600;font-size:14px}
.when{color:var(--muted);font-size:12px;margin-left:6px}
.ptext{margin:3px 0 4px;font-size:14px;white-space:pre-wrap;word-wrap:break-word}
.pfoot{font-size:12px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:4px}
.chip{font-size:11.5px;background:var(--chip);border-radius:6px;padding:1px 7px;color:var(--muted)}
.row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row .l{min-width:0}
.row .r{flex:none;color:var(--muted);font-variant-numeric:tabular-nums;font-size:13px;text-align:right}
.small{font-size:12.5px;color:var(--muted)}
.trunc{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}
table.grid{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
table.grid th{font-weight:600;color:var(--muted);text-align:center;padding:4px 2px;vertical-align:bottom}
table.grid th:first-child,table.grid td:first-child{text-align:left}
table.grid td{padding:6px 2px;text-align:center;border-top:1px solid var(--line)}
.heat{display:inline-block;min-width:22px;border-radius:5px;padding:1px 4px}
.scroll-x{overflow-x:auto}
footer{margin-top:28px;color:var(--muted);font-size:12px;text-align:center}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:9px 10px}
.stat .n{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.stat .k{font-size:11.5px;color:var(--muted)}
@media (max-width:420px){.stats{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="kicker">Cardiology KOL Watch</div>
  <h1>{{ s.label }}</h1>
  <div class="meta">Generated {{ generated }} · {{ "auto summary (no AI digest)" if d.generated_by == "fallback" else "digest: " ~ d.generated_by }}{% if archive %} · <a href="#archive">Archive</a>{% endif %}</div>
  <div class="stats">
    <div class="stat"><div class="n">{{ c.posts_relevant }}</div><div class="k">relevant posts</div></div>
    <div class="stat"><div class="n">{{ c.kols_active }}</div><div class="k">active of {{ c.kols_total }} tracked</div></div>
    <div class="stat"><div class="n">{{ s.trials|length }}</div><div class="k">trials discussed</div></div>
    <div class="stat"><div class="n">{% if c.posts_prev %}{{ '%+d'|format(((c.posts_relevant - c.posts_prev) / c.posts_prev * 100)|round|int) }}%{% else %}–{% endif %}</div><div class="k">volume vs prior wk</div></div>
  </div>
</header>

<nav class="toc">
  <a href="#digest">Digest</a><a href="#topics">Topics</a><a href="#trials">Trials</a>
  <a href="#papers">Papers</a><a href="#debates">Debates</a><a href="#top">Top posts</a>
  <a href="#regions">Regions</a><a href="#kols">KOLs</a>
</nav>

{% macro post(p) -%}
<div class="post">
  <div><a class="who" href="{{ p.url }}">{{ p.kol }}</a>{% if p.industry %}<span class="badge b-ind">industry</span>{% endif %}<span class="when">{{ p.platform }} · {{ p.created_at }}{% if p.is_repost %} · repost{% endif %}</span></div>
  <div class="ptext">{{ p.text|truncate(320) }}</div>
  <div class="pfoot"><span>♥ {{ p.likes }}</span><span>↻ {{ p.reposts }}</span><span>💬 {{ p.replies }}</span>{% if p.stance in ['skeptical','critical'] %}<span class="down">{{ p.stance }}</span>{% endif %}</div>
  {% if p.trials or p.topics %}<div class="chips">{% for t in p.trials %}<span class="chip">{{ t }}</span>{% endfor %}{% for t in p.topics %}<span class="chip">{{ topic_labels.get(t, t) }}</span>{% endfor %}</div>{% endif %}
</div>
{%- endmacro %}

<section id="digest">
  <h2>This week</h2>
  <div class="card">
    <p class="headline">{{ d.headline }}</p>
    {% for k in d.key_points %}
    <div class="kp"><b>{{ k.title }}</b><p>{{ k.body }}</p>
      {% if k.post_ids %}<div class="refs">{% for pid in k.post_ids[:4] %}{% set pp = post_index.get(pid) %}{% if pp %}<a href="{{ pp.url }}">{{ pp.kol.split(' ')[-1] }} ↗</a>{% endif %}{% endfor %}</div>{% endif %}
    </div>
    {% endfor %}
  </div>
  {% if d.regional %}
  <div class="card"><b>Around the world</b>
    <ul class="plain">{% for r in d.regional %}<li><b>{{ r.region }}:</b> {{ r.note }}</li>{% endfor %}</ul></div>
  {% endif %}
  {% if d.watch_next %}
  <div class="card"><b>Watch next</b><ul class="plain">{% for w in d.watch_next %}<li>{{ w }}</li>{% endfor %}</ul></div>
  {% endif %}
</section>

<section id="topics">
  <h2>Topic share · 8-week trend</h2>
  <div class="card">
  {% for t in s.topics %}{% if t.posts %}
    <div class="topic{% if t.trending %} hot{% endif %}">
      <div class="tname">{{ t.label }}{% if t.trending %}<span class="badge b-hot">rising</span>{% elif t.cooling %}<span class="badge b-cool">cooling</span>{% endif %}</div>
      <div class="tright">{{ spark(t.history)|safe }}
        <span class="share">{{ t.share }}%</span>
        <span class="delta {{ 'up' if t.delta > 0 else 'down' if t.delta < 0 else '' }}">{{ '%+.1f'|format(t.delta) }}</span></div>
      <div class="tsub">{{ t.posts }} posts · {{ t.n_kols }} KOLs{% if t.kols %} · {{ t.kols[:3]|map('last_name')|join(', ') }}{% if t.n_kols > 3 %} +{{ t.n_kols - 3 }}{% endif %}{% endif %}</div>
      {% if t.top_posts %}<details style="grid-column:1/3"><summary>Top posts ›</summary>{% for p in t.top_posts %}{{ post(p) }}{% endfor %}</details>{% endif %}
    </div>
  {% endif %}{% endfor %}
  </div>
  <div class="small" style="margin:6px 4px">Share = engagement-weighted fraction of the week's relevant posts. Δ in percentage points vs prior week.</div>
</section>

<section id="trials">
  <h2>Trials in the conversation</h2>
  <div class="card">
  {% for t in s.trials %}
    <div class="row"><div class="l"><b>{{ t.name }}</b>{% if t.new %}<span class="badge b-new">new</span>{% endif %}
      <span class="small trunc">{{ t.kols[:4]|map('last_name')|join(', ') }}{% if t.n_kols > 4 %} +{{ t.n_kols - 4 }}{% endif %}</span></div>
      <div class="r">{{ t.posts }} posts<br>{{ t.n_kols }} KOLs</div></div>
  {% else %}<div class="small">No named trials this week.</div>{% endfor %}
  </div>
</section>

<section id="papers">
  <h2>Most-shared papers & sources</h2>
  <div class="card">
  {% for p in s.papers %}
    <div class="row"><div class="l"><a class="trunc" href="{{ p.url }}">{{ p.domain }} › {{ p.url.split('/')[-1][:60] }}</a>
      <span class="small">{{ p.context|truncate(120) }}</span></div>
      <div class="r">{{ p.n_kols }} KOL{{ 's' if p.n_kols != 1 }}</div></div>
  {% else %}<div class="small">No journal links shared this week.</div>{% endfor %}
  </div>
</section>

<section id="debates">
  <h2>Debates & pushback</h2>
  {% if d.debates %}<div class="card"><ul class="plain">{% for x in d.debates %}<li>{{ x }}</li>{% endfor %}</ul></div>{% endif %}
  <div class="card">{% for p in s.debates %}{{ post(p) }}{% else %}<div class="small">No skeptical or critical posts flagged.</div>{% endfor %}</div>
</section>

<section id="top">
  <h2>Highest-engagement posts</h2>
  <div class="card">{% for p in s.top_posts %}{{ post(p) }}{% endfor %}</div>
</section>

<section id="regions">
  <h2>By region</h2>
  <div class="card scroll-x">
    <table class="grid"><tr><th>Region</th>{% for l in s.region_topic_labels %}<th>{{ l }}</th>{% endfor %}<th>All</th></tr>
    {% for r in s.regions %}<tr><td>{{ r.region }}</td>{% for v in r.cells %}<td>{% if v %}<span class="heat" style="background:color-mix(in srgb, var(--accent) {{ [v * 100 // (r.posts or 1) * 2, 70]|min }}%, transparent)">{{ v }}</span>{% else %}·{% endif %}</td>{% endfor %}<td><b>{{ r.posts }}</b></td></tr>{% endfor %}
    </table>
    <div class="small" style="margin-top:6px">Primary topic of each post. Cell shading = share of that region's posts.</div>
  </div>
</section>

<section id="kols">
  <h2>Most active KOLs</h2>
  <div class="card">{% for k in s.active_kols %}
    <div class="row"><div class="l"><b>{{ k.name }}</b>{% if k.industry %}<span class="badge b-ind">industry</span>{% endif %}<br><span class="small">{{ k.region }}</span></div>
    <div class="r">{{ k.posts }} posts · {{ k.engagement }} eng.</div></div>{% endfor %}
  </div>
  <div class="small" style="margin:6px 4px">Coverage: {{ c.kols_bluesky }} KOLs on Bluesky, {{ c.kols_linkedin }} on LinkedIn ·
    {% for k, v in c.by_platform.items() %}{{ v }} {{ k }} posts{% if not loop.last %}, {% endif %}{% endfor %}.</div>
</section>

{% if archive %}
<section id="archive">
  <h2>Archive</h2>
  <div class="card">{% for a in archive %}<div class="row"><a href="{{ a.href }}">{{ a.label }}</a><span class="r">{{ a.posts }} posts</span></div>{% endfor %}</div>
</section>
{% endif %}

<footer>Personal research dashboard · public posts only · tags and digest are AI-generated, check sources before relying on them.</footer>
</div>
</body>
</html>
"""


def _env() -> Environment:
    env = Environment(autoescape=select_autoescape(default=True))
    env.filters["last_name"] = lambda n: n.split("(")[0].strip().split(" ")[-1]
    return env


def render(stats: dict, digest: dict, archive: list[dict] | None = None) -> str:
    topic_labels = {t["id"]: t["label"] for t in stats["topics"]}
    post_index = {p["id"]: p for p in stats["_digest_posts"]}
    tpl = _env().from_string(TEMPLATE)
    return tpl.render(
        s=stats, d=digest, c=stats["coverage"], spark=sparkline, archive=archive or [],
        topic_labels=topic_labels, post_index=post_index,
        generated=datetime.now().strftime("%a %b %d, %H:%M"),
    )


def publish(stats: dict, digest: dict) -> Path:
    """Archive this week's report and rebuild site/ (index + all past weeks)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = stats["end"][:10]
    summary = {k: v for k, v in stats.items() if not k.startswith("_")}
    (REPORTS_DIR / f"{slug}.json").write_text(json.dumps({"stats": summary, "digest": digest}, indent=1))

    archive = []
    for jf in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(jf.read_text())["stats"]
        except (json.JSONDecodeError, KeyError):
            continue
        archive.append({"slug": jf.stem, "label": meta["label"], "posts": meta["coverage"]["posts_relevant"],
                        "href": f"/archive/{jf.stem}.html"})

    html = render(stats, digest, archive)
    (REPORTS_DIR / f"{slug}.html").write_text(html, encoding="utf-8")

    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    (SITE_DIR / "archive").mkdir(parents=True)
    for hf in REPORTS_DIR.glob("*.html"):
        shutil.copy(hf, SITE_DIR / "archive" / hf.name)
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    (SITE_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    return SITE_DIR / "index.html"
