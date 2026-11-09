"""Email the weekly report: a phone-friendly summary in the body, full dashboard attached.

Two ways to send (the first one configured wins):
1. Resend (recommended): RESEND_API_KEY + REPORT_EMAIL_TO. The key can only send mail.
   Without your own domain, Resend sends from onboarding@resend.dev and only to the
   email address you signed up to Resend with, which is all a personal report needs.
2. Any SMTP server: SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL_TO (+ optional SMTP_HOST, SMTP_PORT).
Optional: REPORT_EMAIL_FROM.

Email clients ignore most CSS and block SVG, so the body uses a separate inline-styled template.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import requests
from jinja2 import Environment, select_autoescape

from .config import REPORTS_DIR

log = logging.getLogger(__name__)

INK, MUTED, LINE, ACCENT, UP, DOWN, LINK = "#1b1b1f", "#6b6b73", "#e6e4df", "#b4232a", "#0f7b4f", "#9a5a00", "#1c4f9c"

EMAIL_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f7f6f3;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f6f3;">
<tr><td align="center" style="padding:16px 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:{{ C.INK }};font-size:15px;line-height:1.5;">

<tr><td style="padding:4px 4px 12px;">
  <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{{ C.ACCENT }};font-weight:700;">Cardiology KOL Watch</div>
  <div style="font-size:22px;font-weight:700;line-height:1.25;margin:2px 0 4px;">{{ s.label }}</div>
  <div style="font-size:13px;color:{{ C.MUTED }};">{{ c.posts_relevant }} relevant posts · {{ c.kols_active }} active KOLs · {{ s.trials|length }} trials discussed{% if dash_url %} · <a href="{{ dash_url }}" style="color:{{ C.LINK }};text-decoration:none;">Open dashboard</a>{% endif %}</div>
</td></tr>

{% macro card() %}<tr><td style="background:#ffffff;border:1px solid {{ C.LINE }};border-radius:12px;padding:14px 15px;">{% endmacro %}
{% macro endcard() %}</td></tr><tr><td style="height:12px;line-height:12px;font-size:0;">&nbsp;</td></tr>{% endmacro %}
{% macro h(t) %}<div style="font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:{{ C.MUTED }};font-weight:700;margin-bottom:8px;">{{ t }}</div>{% endmacro %}

{{ card() }}
  {{ h("This week") }}
  <div style="font-size:17px;font-weight:650;line-height:1.35;margin-bottom:6px;">{{ d.headline }}</div>
  {% for k in d.key_points %}
  <div style="padding:8px 0;border-top:1px solid {{ C.LINE }};">
    <div style="font-weight:700;">{{ k.title }}</div>
    <div>{{ k.body }}</div>
    {% if k.post_ids %}<div style="font-size:12px;margin-top:2px;">{% for pid in k.post_ids[:4] %}{% set pp = links.get(pid) %}{% if pp %}<a href="{{ pp.url }}" style="color:{{ C.LINK }};text-decoration:none;margin-right:10px;">{{ pp.kol.split(' ')[-1] }} ↗</a>{% endif %}{% endfor %}</div>{% endif %}
  </div>
  {% endfor %}
{{ endcard() }}

{% if d.debates %}{{ card() }}{{ h("Debates & pushback") }}
  {% for x in d.debates %}<div style="padding:5px 0;">• {{ x }}</div>{% endfor %}
{{ endcard() }}{% endif %}

{{ card() }}
  {{ h("Topic share vs prior week") }}
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
  {% for t in s.topics[:10] %}{% if t.posts %}
    <tr>
      <td style="padding:6px 0;border-top:1px solid {{ C.LINE }};">
        <span style="font-weight:600;">{{ t.label }}</span>{% if t.trending %} <span style="background:{{ C.ACCENT }};color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px;">RISING</span>{% elif t.cooling %} <span style="color:{{ C.DOWN }};font-size:10px;font-weight:700;">COOLING</span>{% endif %}
        <div style="font-size:12px;color:{{ C.MUTED }};">{{ t.posts }} posts · {{ t.n_kols }} KOLs</div>
        <div style="background:{{ C.LINE }};height:5px;border-radius:3px;margin-top:3px;"><div style="background:{{ C.ACCENT if t.trending else C.MUTED }};height:5px;border-radius:3px;width:{{ [t.share / max_share * 100, 2]|max|round|int }}%;"></div></div>
      </td>
      <td align="right" style="padding:6px 0 6px 10px;border-top:1px solid {{ C.LINE }};white-space:nowrap;vertical-align:top;">
        <div style="font-weight:700;">{{ t.share }}%</div>
        <div style="font-size:12px;color:{{ C.UP if t.delta > 0 else C.DOWN if t.delta < 0 else C.MUTED }};">{{ '%+.1f'|format(t.delta) }} pts</div>
      </td>
    </tr>
  {% endif %}{% endfor %}
  </table>
{{ endcard() }}

{% if s.trials %}{{ card() }}{{ h("Trials in the conversation") }}
  {% for t in s.trials[:10] %}<div style="padding:5px 0;border-top:1px solid {{ C.LINE }};"><b>{{ t.name }}</b>{% if t.new %} <span style="color:{{ C.UP }};font-size:11px;font-weight:700;">NEW</span>{% endif %}
    <span style="float:right;color:{{ C.MUTED }};font-size:13px;">{{ t.posts }} posts · {{ t.n_kols }} KOLs</span></div>{% endfor %}
{{ endcard() }}{% endif %}

{% if s.papers %}{{ card() }}{{ h("Most-shared papers") }}
  {% for p in s.papers[:6] %}<div style="padding:6px 0;border-top:1px solid {{ C.LINE }};">
    <a href="{{ p.url }}" style="color:{{ C.LINK }};text-decoration:none;">{{ p.domain }} › {{ p.url.split('/')[-1][:50] }}</a>
    <span style="color:{{ C.MUTED }};font-size:12px;"> · {{ p.n_kols }} KOL{{ 's' if p.n_kols != 1 }}</span>
    <div style="font-size:13px;color:{{ C.MUTED }};">{{ p.context|truncate(130) }}</div></div>{% endfor %}
{{ endcard() }}{% endif %}

{{ card() }}{{ h("Top posts") }}
  {% for p in s.top_posts[:6] %}<div style="padding:8px 0;border-top:1px solid {{ C.LINE }};">
    <a href="{{ p.url }}" style="color:{{ C.INK }};font-weight:700;text-decoration:none;">{{ p.kol }}</a>{% if p.industry %} <span style="color:{{ C.DOWN }};font-size:11px;">industry</span>{% endif %}
    <span style="color:{{ C.MUTED }};font-size:12px;"> {{ p.platform }} · {{ p.created_at }} · ♥ {{ p.likes }}</span>
    <div style="font-size:14px;">{{ (p.summary or p.text)|truncate(220) }}</div></div>{% endfor %}
{{ endcard() }}

<tr><td style="padding:4px;font-size:12px;color:{{ C.MUTED }};text-align:center;">
  Full dashboard with 8-week trends, regions and archive is attached ({{ attachment_name }}).<br>
  Public posts only · AI-generated tags and digest; check sources before relying on them.
</td></tr>
</table></td></tr></table></body></html>"""


def _latest() -> tuple[dict, dict, Path] | None:
    files = sorted(REPORTS_DIR.glob("*.json"))
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    return data["stats"], data["digest"], files[-1].with_suffix(".html")


def render_email(stats: dict, digest: dict, dash_url: str = "", attachment_name: str = "") -> str:
    env = Environment(autoescape=select_autoescape(default=True))
    tpl = env.from_string(EMAIL_TEMPLATE)
    shares = [t["share"] for t in stats["topics"] if t["posts"]] or [1]
    return tpl.render(
        s=stats, d=digest, c=stats["coverage"], links=stats.get("post_links", {}),
        max_share=max(max(shares), 1), dash_url=dash_url, attachment_name=attachment_name,
        C=dict(INK=INK, MUTED=MUTED, LINE=LINE, ACCENT=ACCENT, UP=UP, DOWN=DOWN, LINK=LINK),
    )


def _plain(stats: dict, digest: dict) -> str:
    lines = [f"Cardiology KOL Watch: {stats['label']}", "", digest.get("headline", ""), ""]
    for k in digest.get("key_points", []):
        lines += [f"* {k['title']}: {k['body']}"]
    lines += ["", "Topics:"]
    lines += [f"  {t['label']}: {t['share']}% ({t['delta']:+.1f})" for t in stats["topics"][:8] if t["posts"]]
    lines += ["", "Full dashboard attached."]
    return "\n".join(lines)


def send(dry_run_path: Path | None = None) -> bool:
    latest = _latest()
    if latest is None:
        log.warning("No report found in %s; nothing to email", REPORTS_DIR)
        return False
    stats, digest, html_path = latest
    attach_name = f"kol-watch-{stats['end'][:10]}.html"
    body = render_email(stats, digest, os.environ.get("KOLWATCH_DASHBOARD_URL", ""), attach_name)

    if dry_run_path:
        dry_run_path.write_text(body, encoding="utf-8")
        log.info("Email preview written to %s", dry_run_path)
        return True

    subject = f"KOL Watch {stats['label']}: {digest.get('headline', '')}"[:200]
    attachment = html_path.read_bytes() if html_path.exists() else None

    if os.environ.get("RESEND_API_KEY"):
        return _send_resend(subject, body, _plain(stats, digest), attach_name, attachment)

    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    to = os.environ.get("REPORT_EMAIL_TO", "") or user
    if not (user and password and to):
        log.warning("No email settings (RESEND_API_KEY or SMTP_*) found; skipping email")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("REPORT_EMAIL_FROM", "") or user
    msg["To"] = to
    msg.set_content(_plain(stats, digest))
    msg.add_alternative(body, subtype="html")
    if attachment:
        msg.add_attachment(attachment, maintype="text", subtype="html", filename=attach_name)

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
    log.info("Emailed report to %s", to)
    return True


def _send_resend(subject: str, html: str, text: str, attach_name: str, attachment: bytes | None) -> bool:
    to = os.environ.get("REPORT_EMAIL_TO", "")
    if not to:
        log.warning("REPORT_EMAIL_TO not set (must be the email you signed up to Resend with); skipping email")
        return False
    payload = {
        "from": os.environ.get("REPORT_EMAIL_FROM", "") or "KOL Watch <onboarding@resend.dev>",
        "to": [to], "subject": subject, "html": html, "text": text,
    }
    if attachment:
        payload["attachments"] = [{"filename": attach_name, "content": base64.b64encode(attachment).decode()}]
    r = requests.post("https://api.resend.com/emails", json=payload, timeout=60,
                      headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
    if r.status_code >= 400:
        log.warning("Resend error %s: %s", r.status_code, r.text[:300])
        if r.status_code == 403:
            log.warning("Without a verified domain, REPORT_EMAIL_TO must equal your Resend sign-up email.")
        return False
    log.info("Emailed report to %s via Resend (id %s)", to, r.json().get("id"))
    return True
