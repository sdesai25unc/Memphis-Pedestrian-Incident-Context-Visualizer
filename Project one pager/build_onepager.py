r"""
build_onepager.py
=================

Builds the self-contained one-page flyer (Project one pager/index.html).

Style: clean WHITE page (no pattern) with dark teal-navy cards, a single green
accent (no amber), Street Fair fonts (Manrope headings + Poppins body), a large
hero photo that extends down behind the headline AND the stat boxes, and a big
crash-map panel. Fonts are embedded as base64 (offline / file://); photos and a
black-recolored Street Fair logo are written to ./images/.

Re-run after changing logos, the hero photo, or copy:
    .\.venv\Scripts\python.exe "Project one pager\build_onepager.py"
"""

import base64
import re
from pathlib import Path

import requests
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
LOGOS = HERE / "logos"
IMAGES = HERE / "images"
OUT = HERE / "index.html"
FONT_CACHE = HERE / ".fonts_cache.css"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FONT_CSS_URLS = {
    "Manrope": "https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800",
    "Poppins": "https://fonts.googleapis.com/css2?family=Poppins:ital,wght@0,400;0,600;0,700;1,400",
}
LOGO_NAMES = ["morehead_cain", "innovate_memphis", "street_fair", "hyde_foundation"]


def build_fontface_css():
    if FONT_CACHE.exists():
        print("  using cached embedded fonts (.fonts_cache.css)")
        return FONT_CACHE.read_text(encoding="utf-8")
    faces = []
    for family, url in FONT_CSS_URLS.items():
        css = requests.get(url, headers={"User-Agent": UA}, timeout=60).text
        for block in css.split("@font-face"):
            if "unicode-range" not in block or "U+0000-00FF" not in block:
                continue
            style = "italic" if "font-style: italic" in block else "normal"
            weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
            src = re.search(r"src:\s*url\((https://[^)]+\.woff2)\)", block).group(1)
            data = requests.get(src, headers={"User-Agent": UA}, timeout=60).content
            b64 = base64.b64encode(data).decode("ascii")
            faces.append(
                f"@font-face{{font-family:'{family}';font-style:{style};"
                f"font-weight:{weight};font-display:swap;"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
            )
    css = "\n".join(faces)
    FONT_CACHE.write_text(css, encoding="utf-8")
    return css


def prep_images():
    """Optimize the hero photo, crop the crash map, and recolor the Street Fair
    logo's white 'STREET' to black (it blended into the white footer)."""
    IMAGES.mkdir(exist_ok=True)
    made = {}

    ped = next((p for p in LOGOS.glob("pedestrian_image.*")), None) \
        or next((p for p in IMAGES.glob("pedestrian_image.*")), None)
    if ped:
        im = Image.open(ped).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(IMAGES / "pedestrian.jpg", "JPEG", quality=84, optimize=True)
        made["pedestrian"] = True

    src = HERE.parent / "outputs" / "prototype_crash_map.png"
    if src.exists():
        im = Image.open(src).convert("RGB")
        w, h = im.size
        im = im.crop((int(w*0.27), int(h*0.24), int(w*0.72), int(h*0.82)))
        im.thumbnail((1000, 1000))
        im.save(IMAGES / "map_thumb.jpg", "JPEG", quality=86, optimize=True)
        made["map"] = True

    sf = next((p for p in LOGOS.glob("street_fair.*")), None)
    if sf:
        a = np.array(Image.open(sf).convert("RGBA"))
        white = (a[..., 0] > 165) & (a[..., 1] > 165) & (a[..., 2] > 165)
        a[white, 0] = 17; a[white, 1] = 17; a[white, 2] = 17  # near-black, keep alpha
        Image.fromarray(a).save(IMAGES / "street_fair_dark.png")
        made["street_fair(recolored)"] = True

    inv = next((p for p in LOGOS.glob("innovate_memphis.*")), None)
    if inv:
        im = Image.open(inv).convert("RGBA")
        al = np.array(im)[..., 3]
        cols = np.where((al > 30).any(axis=0))[0]
        on = (al > 30).mean(axis=1) > 0.02
        bands, i, H = [], 0, len(on)
        while i < H:
            if on[i]:
                j = i
                while j < H and on[j]:
                    j += 1
                bands.append((i, j - 1)); i = j
            else:
                i += 1
        keep = bands[:-1] if len(bands) >= 2 else bands  # drop the bottom tagline band
        x0, x1 = int(cols.min()), int(cols.max())
        im.crop((x0, keep[0][0], x1 + 1, keep[-1][1] + 1)).save(IMAGES / "innovate_trim.png")
        made["innovate(trimmed)"] = True

    return made


def logo_report():
    found, missing = [], []
    for name in LOGO_NAMES:
        hits = list(LOGOS.glob(f"{name}.*")) if LOGOS.exists() else []
        (found if hits else missing).append(name)
    return found, missing


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Memphis Pedestrian Safety, Project One-Pager</title>
<style>
__FONTFACE__

@page { size: letter portrait; margin: 0; }

:root{
  --navy:#11313b; --navy2:#0c2630; --green:#2fa14e; --green-bright:#4cc173;
  --ink:#15323b; --body:#45575f; --muted:#71848c;
  --cardtext:#c4d2d8; --cardmuted:#90a4ab; --line:#dce3e5;
  --nborder:rgba(255,255,255,.15); --nborder2:rgba(255,255,255,.24);
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font-family:'Poppins',-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--body); background:#cfd8da; font-size:10pt; line-height:1.4;
  -webkit-print-color-adjust:exact; print-color-adjust:exact;}
h1,h2,h3,h4{font-family:'Manrope',-apple-system,"Segoe UI",Arial,sans-serif; margin:0;}

.sheet{width:8.5in; min-height:11in; margin:16px auto; padding:0.27in;
  background:#ffffff; box-shadow:0 12px 44px rgba(0,0,0,.22);
  display:flex; flex-direction:column; color:var(--body);}
@media print{ body{background:#fff;} .sheet{width:auto; min-height:0; margin:0; box-shadow:none;} }

/* ---------- HEADER (2 rows x 2 cols, aligned) ---------- */
.header{display:grid; grid-template-columns:1fr auto; column-gap:18px; row-gap:5px;
  align-items:center; padding-bottom:10px; border-bottom:1px solid var(--line);}
.h-row1{grid-column:1; grid-row:1; display:flex; align-items:center; gap:13px;}
.h-row1 img{max-height:34px; max-width:165px; display:block;}
.h-row1 .logo-txt{font-family:'Manrope'; color:var(--navy); font-weight:800; font-size:9pt;}
.occasion{font-family:'Manrope'; font-size:13pt; font-weight:800; color:var(--ink); letter-spacing:.005em;}
.occasion .dot{color:var(--green);}
.proj{grid-column:2; grid-row:1; text-align:right; font-family:'Manrope'; font-size:13pt;
  font-weight:800; color:var(--ink);}
.team{grid-column:1; grid-row:2; font-size:8.4pt; color:var(--muted); white-space:nowrap;}
.tag{grid-column:2; grid-row:2; text-align:right; font-size:8.4pt; color:var(--green); font-weight:600;}

/* ---------- HERO (photo extends behind text + stat boxes) ---------- */
.hero{position:relative; border-radius:14px; overflow:hidden; margin-top:11px;
  background:var(--navy); box-shadow:0 8px 26px rgba(17,49,59,.28);}
.hero .bg{position:absolute; inset:0; width:100%; height:100%; object-fit:cover; display:block;}
.hero .scrim{position:absolute; inset:0;
  background:linear-gradient(95deg, rgba(10,33,40,.94) 0%, rgba(10,33,40,.72) 44%, rgba(10,33,40,.05) 100%);}
.hero-inner{position:relative; z-index:2; display:flex; flex-direction:column;}
.htext{padding:12px 24px 9px; max-width:69%;}
.kicker{font-family:'Manrope'; font-size:8pt; font-weight:800; letter-spacing:.2em;
  text-transform:uppercase; color:var(--green-bright); margin-bottom:7px;}
.kicker .arw{letter-spacing:-.05em; margin-right:6px;}
.htext h1{font-size:15pt; line-height:1.1; color:#fff; font-weight:800; letter-spacing:-.015em;}
.htext p{font-size:8.8pt; line-height:1.36; color:#d7e1e5; margin:5px 0 0; max-width:97%;}
.htext p .hl{color:#fff; font-weight:600;}
.stats{display:flex; background:rgba(8,28,35,.84); border-top:1px solid rgba(255,255,255,.12);}
.stat{flex:1; padding:7px 14px; border-left:1px solid rgba(255,255,255,.12);}
.stat:first-child{border-left:none;}
.stat .n{font-family:'Manrope'; font-size:13pt; font-weight:800; color:var(--green-bright); line-height:1;}
.stat .l{font-size:7.7pt; color:#aebec4; margin-top:3px; line-height:1.22;}
.stat.kc .n{font-size:10.5pt; color:#fff;}

/* ---------- TRACKS (navy cards) ---------- */
.tracks-head{margin:8px 0 5px;}
.tracks-head .t{font-family:'Manrope'; font-size:12.5pt; font-weight:800; color:var(--ink);}
.tracks-head .s{font-size:8.3pt; color:var(--muted); margin-left:9px;}
.tracks{display:flex; flex-direction:column; gap:6px; flex:1; justify-content:space-between;}
.track{background:var(--navy); border-radius:12px; padding:8px 14px; break-inside:avoid;
  box-shadow:0 4px 14px rgba(17,49,59,.16);}
.track.imgcard{display:grid; grid-template-columns:1fr 2.0in; gap:16px; align-items:stretch;}
.t-top{display:flex; align-items:center; gap:10px; margin-bottom:5px;}
.t-num{font-family:'Manrope'; border:2px solid var(--green-bright); color:var(--green-bright); font-weight:800;
  font-size:9pt; width:23px; height:23px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; flex:none;}
.t-title{font-family:'Manrope'; font-size:11.5pt; font-weight:800; color:#fff;}
.doing{font-size:8.9pt; line-height:1.36; color:var(--cardtext); margin:0;}
.doing .next{color:#fff; font-weight:600;}
.help{margin-top:8px; padding-left:12px; border-left:3px solid var(--green-bright);}
.help .label{font-family:'Manrope'; display:block; font-size:7.5pt; font-weight:800; letter-spacing:.12em;
  text-transform:uppercase; color:var(--green-bright); margin-bottom:2px;}
.help .txt{font-size:8.9pt; line-height:1.34; color:#dbe4e7;}
.help .txt b{color:#fff; font-weight:600;}
.map-wrap{display:flex; flex-direction:column;}
.map-thumb{flex:1; border-radius:11px; overflow:hidden; border:1px solid var(--nborder2); min-height:1.5in;}
.map-thumb img{width:100%; height:100%; object-fit:cover; display:block;}
.map-cap{font-size:7pt; color:var(--cardmuted); text-align:center; margin-top:4px;}

/* ---------- CONTACT ---------- */
.contact{margin-top:8px; background:var(--green); border-radius:11px; padding:9px 16px;
  text-align:center; font-size:9.5pt; color:#eafaef; box-shadow:0 4px 14px rgba(47,161,78,.28);}
.contact b{color:#fff; font-weight:600;}
.contact .email{font-family:'Manrope'; color:#fff; font-weight:800; font-size:11.5pt; white-space:nowrap; margin-left:4px;}

/* ---------- ORG FOOTER (big logos) ---------- */
.orgs{margin-top:8px; border-top:1px solid var(--line); padding-top:7px;}
.orgs .line{font-size:8.3pt; color:var(--muted); text-align:center; margin-bottom:7px;}
.orgs .line b{font-family:'Manrope'; color:var(--ink); font-weight:700;}
.orgs .row{display:flex; align-items:center; justify-content:space-around; gap:24px;}
.orgs .org{display:flex; flex-direction:column; align-items:center; justify-content:flex-end;}
.orgs .org img{max-height:44px; max-width:155px; display:block;}
.orgs .org.host img{max-height:48px; max-width:165px;}
.orgs .org .role{display:block; font-family:'Manrope'; font-size:7pt; font-weight:800; letter-spacing:.14em;
  text-transform:uppercase; color:var(--green); margin-top:4px; text-align:center;}
.orgs .org .logo-txt{font-family:'Manrope'; font-weight:800; color:var(--navy); text-align:center; font-size:11pt;}
</style>
</head>
<body>
<div class="sheet">

  <div class="header">
    <div class="h-row1">
      <img src="logos/morehead_cain.png" alt="Morehead-Cain"
           onerror="this.onerror=null;this.outerHTML='&lt;span class=&quot;logo-txt&quot;&gt;MOREHEAD CAIN&lt;/span&gt;'">
      <span class="occasion">Civic Collaboration <span class="dot">2026</span></span>
    </div>
    <div class="proj">Memphis Pedestrian Safety</div>
    <div class="team">Samarth Desai &nbsp;·&nbsp; Emmaline Phillips &nbsp;·&nbsp; Lillian Zaks &nbsp;·&nbsp; Iman Nazir &nbsp;·&nbsp; Wesley Coatney</div>
    <div class="tag">Changing the narrative to change the streets</div>
  </div>

  <div class="hero">
    <img class="bg" src="images/pedestrian.jpg" alt="A Memphis street" onerror="this.style.display='none'">
    <div class="scrim"></div>
    <div class="hero-inner">
      <div class="htext">
        <div class="kicker"><span class="arw">&#9656;&#9656;&#9656;</span>The Dilemma</div>
        <h1>Memphis has one of the worst pedestrian fatality rates of any major U.S. city.</h1>
        <p>Most of these deaths happen on <span class="hl">wide, fast, multi-lane roads</span>, yet coverage blames the victim ("jaywalking"). That framing hides a systemic, solvable infrastructure problem. <span class="hl">We're here to change the story, and the streets.</span></p>
      </div>
      <div class="stats">
        <div class="stat"><div class="n">#1</div><div class="l">in the US for pedestrian fatalities</div></div>
        <div class="stat"><div class="n">1,294</div><div class="l">crashes since 2023</div></div>
        <div class="stat"><div class="n">~75%</div><div class="l">on city-owned roads</div></div>
        <div class="stat kc"><div class="n">Design,<br>not behavior</div><div class="l">the real problem</div></div>
      </div>
    </div>
  </div>

  <div class="tracks-head"><span class="t">Three Tracks</span><span class="s">what we're building, and where we need help</span></div>
  <div class="tracks">

    <div class="track imgcard">
      <div>
        <div class="t-top"><span class="t-num">1</span><span class="t-title">Data &amp; Research</span></div>
        <p class="doing">We built the first Memphis-specific map of pedestrian crashes by <b style="color:#fff">who owns the road, City vs. TDOT</b>, with every crash tagged by street, speed, and lane count. About 75% are on City-owned roads, where the deaths concentrate on wide, fast arterials. <span class="next">Next: a public interactive map and statistics resource.</span></p>
        <div class="help">
          <span class="label">Where we need help · Data</span>
          <span class="txt">To map how far each victim was from the nearest safe crossing, we need <b>pedestrian-infrastructure data</b>: where crosswalks and signals actually are. Does this city data even exist? If it does, we need access. If it doesn't, we need help collecting it and finding funders.</span>
        </div>
      </div>
      <div class="map-wrap">
        <div class="map-thumb"><img src="images/map_thumb.jpg" alt="Crash map" onerror="this.closest('.map-wrap').style.display='none'"></div>
        <div class="map-cap">Our crash map, every crash by road owner</div>
      </div>
    </div>

    <div class="track">
      <div class="t-top"><span class="t-num">2</span><span class="t-title">Incentivizing Meaningful Journalism</span></div>
      <p class="doing">Our <b style="color:#fff">story cards</b> use an AI ingestor that builds the real context behind each incident, well beyond the date and location: where the nearest signalized crossing was, how many crashes have hit that corridor in recent months, whether it sits on a known high-risk road. That makes reporting both faster for journalists and far more thorough.</p>
      <div class="help">
        <span class="label">Where we need help</span>
        <span class="txt">Connections to <b>local newsrooms and reporters</b> willing to pilot the tool, and partners who can help sustain it.</span>
      </div>
    </div>

    <div class="track">
      <div class="t-top"><span class="t-num">3</span><span class="t-title">Pedestrian Testimonials</span></div>
      <p class="doing">With <b style="color:#fff">Street Fair Memphis</b>, we're collecting pedestrian perspectives and victim testimonials, so each incident is seen as a person, not a dot on a map.</p>
      <div class="help">
        <span class="label">Where we need help</span>
        <span class="txt"><b>People willing to share their stories</b>: first-hand accounts from Memphis pedestrians, and connections to those affected.</span>
      </div>
    </div>

  </div>

  <div class="contact">
    Interested in supporting this mission or helping guide the process? Reach out:
    <span class="email">weslimemphis@gmail.com</span>
  </div>

  <div class="orgs">
    <div class="line"><b>Hosted by Innovate Memphis.</b> In partnership with Street Fair Memphis and the Hyde Family Foundation.</div>
    <div class="row">
      <div class="org host">
        <img src="images/innovate_trim.png" alt="Innovate Memphis"
             onerror="this.onerror=null;this.outerHTML='&lt;span class=&quot;logo-txt&quot;&gt;Innovate Memphis&lt;/span&gt;'">
        <span class="role">Host</span>
      </div>
      <div class="org">
        <img src="images/street_fair_dark.png" alt="Street Fair Memphis"
             onerror="this.onerror=null;this.outerHTML='&lt;span class=&quot;logo-txt&quot;&gt;Street Fair Memphis&lt;/span&gt;'">
        <span class="role">Partner</span>
      </div>
      <div class="org">
        <img src="logos/hyde_foundation.png" alt="Hyde Family Foundation"
             onerror="this.onerror=null;this.outerHTML='&lt;span class=&quot;logo-txt&quot;&gt;Hyde Family Foundation&lt;/span&gt;'">
        <span class="role">Partner</span>
      </div>
    </div>
  </div>

</div>
</body>
</html>
"""


def main():
    print("Optimizing images...")
    made = prep_images()
    print(f"  images ready: {', '.join(made) if made else '(none found)'}")
    print("Embedding fonts...")
    html = HTML.replace("__FONTFACE__", build_fontface_css())
    OUT.write_text(html, encoding="utf-8")
    found, missing = logo_report()
    print("Logos:")
    for n in found:   print(f"  FOUND   -> logos/{n}.*")
    for n in missing: print(f"  MISSING -> text fallback: {n}")
    print(f"\nWrote {OUT}  ({OUT.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
