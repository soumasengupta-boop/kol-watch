"""Synthetic demo data so the dashboard can be previewed without any API keys.

All demo posts are invented and prefixed "[DEMO]". They are written to a separate
throwaway folder, never to your real data/ directory.
"""
from __future__ import annotations

import random
from datetime import timedelta

from .config import POSTS_FILE, load_kols, upsert_jsonl, utcnow

TEMPLATES = [
    ("Lp(a)HORIZON full data today: pelacarsen lowered Lp(a) but no MACE benefit. Is the Lp(a) hypothesis in trouble or was the trial population wrong? Not convinced it is dead.", ["https://www.nejm.org/doi/full/10.1056/NEJMoa-demo1"]),
    ("Thread on what Lp(a)HORIZON means for OCEAN(a) and ACCLAIM-Lp(a). Absolute Lp(a) reduction matters. Caution before over-reading.", []),
    ("VESALIUS-CV follow-up: evolocumab in primary prevention, LDL ~45 mg/dL. Earlier is better for LDL lowering.", ["https://www.jacc.org/doi/10.1016/j.jacc.demo2"]),
    ("STAREE: atorvastatin cut MACE 30% in adults 70+ without CVD, but no disability-free survival gain. Shared decision-making in older adults.", ["https://www.nejm.org/doi/full/10.1056/NEJMoa2607314"]),
    ("SYNCHRONIZE-CVOT readout Monday at AHA. Survodutide CV safety in obesity - what endpoints will matter?", []),
    ("Plaque, not stenosis: CCTA-guided prevention changes management. SCOT-HEART 5-year data still underused.", ["https://www.ahajournals.org/doi/10.1161/demo3"]),
    ("CAC score of zero in a 55 yo with LDL 160 - do we still treat? Risk enhancers and Lp(a) testing matter.", []),
    ("AI plaque quantification from coronary CTA is moving into practice. Need outcome trials, not just accuracy studies.", []),
    ("ZEUS negative: ziltivekimab lowered hsCRP but no MACE reduction. Inflammation hypothesis takes a hit; colchicine data still stands.", ["https://www.thelancet.com/journals/lancet/article/demo4"]),
    ("Tirzepatide vs dulaglutide SURPASS-CVOT cardiorenal analysis: broader endpoint benefit. GLP-1 era of prevention.", []),
    ("Intensive BP lowering in ESPRIT confirms SPRINT-like benefit across populations. Hypertension control is still the biggest lever globally.", []),
    ("Women remain underrepresented in lipid trials; sex-specific risk enhancers like preeclampsia belong in risk assessment.", []),
    ("Polypill and low-cost prevention for LMIC: implementation, not discovery, is the bottleneck.", []),
    ("Obicetrapib BROADWAY: CETP inhibition back? PREVAIL outcomes will decide. Skeptical until MACE data.", ["https://www.nejm.org/doi/full/10.1056/NEJMoa2415820"]),
    ("Great to see colleagues in Chicago for #AHA26!", []),
    ("FFR-CT plus plaque assessment in chest pain pathways: fewer invasive angiograms without missed events.", []),
]

# topic emphasis drifts week to week so the trend lines move
WEEK_BIAS = {0: [0, 1, 4, 8], 1: [8, 9, 3], 2: [3, 2], 3: [9, 13], 4: [5, 6, 7], 5: [10, 11], 6: [2, 12], 7: [5, 15]}


def seed(weeks: int = 8, seed_value: int = 7) -> int:
    rnd = random.Random(seed_value)
    kols = [k for k in load_kols() if k.type == "person"]
    now = utcnow()
    posts = []
    for w in range(weeks):
        n = rnd.randint(45, 75)
        for i in range(n):
            if rnd.random() < 0.45:
                ti = rnd.choice(WEEK_BIAS[w])
            else:
                ti = rnd.randrange(len(TEMPLATES))
            text, links = TEMPLATES[ti]
            k = rnd.choice(kols)
            ts = now - timedelta(days=7 * w + rnd.uniform(0, 7))
            plat = "linkedin" if rnd.random() < 0.3 else "bluesky"
            posts.append({
                "id": f"demo:{w}:{i}", "platform": plat, "kol": k.name, "author_handle": "demo",
                "is_repost": rnd.random() < 0.15,
                "url": "https://bsky.app/" if plat == "bluesky" else "https://www.linkedin.com/",
                "created_at": ts.isoformat(), "text": "[DEMO] " + text, "links": links,
                "likes": int(rnd.paretovariate(1.4) * 8), "reposts": int(rnd.paretovariate(1.6) * 2),
                "replies": int(rnd.paretovariate(1.8) * 2),
            })
    upsert_jsonl(POSTS_FILE, posts)
    return len(posts)
