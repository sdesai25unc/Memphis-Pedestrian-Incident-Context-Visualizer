r"""
24_build_search.py
================

MAP SEARCH FEATURE (additive) — builds a precomputed search index and injects a
type-ahead corridor / intersection / address search into the existing public map.
Does NOT change any existing layer, toggle, chart, or stat; the search is purely
additive and idempotent (re-running replaces only the injected block).

PART 1 — search index (data/processed/search_index.json, also embedded in the page):
  - CORRIDORS: every named street with >=1 crash. Crash counts use the SAME
    Street_Name grouping as the deadliest-corridor card (so they match exactly):
    total, fatal, ownership split (City / TDOT / Limited-access), deadliest rank,
    # signalized intersections on the corridor (covered corridors only, else
    "not yet analyzed"), simplified centerline geometry, and safe-crossing stats
    ONLY for Union (from union_safe_summary.json) — "not yet analyzed" elsewhere.
  - INTERSECTIONS: covered junction nodes that have >=1 crash OR are signalized:
    crashes, deaths, signalized (yes/no), nearest safe crossing (Union only), location.

PART 2 — injects the search UI + logic into outputs/interactive_map/index.html
  (embedded for file:// use). Address queries dispatch to the free, no-key US Census
  geocoder client-side, with graceful failure.

Run it AFTER script 18 (rebuilding index.html drops the injection; just re-run this):
    .\.venv\Scripts\python.exe scripts\24_build_search.py
"""

import sys
import json
import re
from pathlib import Path

import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
HTML = ROOT / "outputs" / "interactive_map" / "index.html"
INDEX_JSON = PROC / "search_index.json"

FINAL = PROC / "shelby_crashes_final.csv"
SIGNALS = PROC / "shelby_crashes_signals.csv"
NODES = PROC / "intersection_nodes_all.geojson"        # EVERY junction citywide (script 25)
NODES_COVERED = PROC / "intersection_nodes_covered.geojson"  # old covered set (for Union safe-dist transfer)
COVERED_OUT = PROC / "covered_corridors.json"           # authoritative covered-corridor set (script 25)
RULEBOOK = PROC / "road_ownership_rulebook.geojson"
UNION_SUM = PROC / "union_safe_summary.json"

CRS_M, CRS_GEO = "EPSG:32136", "EPSG:4326"
FATAL = "Fatal"
CAT3 = {"City of Memphis": "City", "TDOT state route": "TDOT",
        "Interstate (TDOT)": "Limited", "Interstate ramp (TDOT)": "Limited",
        "Limited-access (TDOT)": "Limited"}
SUFFIX = {"AVE": "Avenue", "ST": "Street", "RD": "Road", "BLVD": "Boulevard",
          "DR": "Drive", "PKWY": "Parkway", "HWY": "Highway", "LN": "Lane",
          "CT": "Court", "PL": "Place", "CIR": "Circle", "PIKE": "Pike",
          "EXT": "Ext", "WAY": "Way", "COVE": "Cove", "TER": "Terrace"}


def titlecase_street(name):
    out = []
    for w in str(name).split():
        out.append(SUFFIX.get(w, w.capitalize() if not w.isdigit() else w))
    return " ".join(out)


def build_index():
    f = pd.read_csv(FINAL)
    f["cat3"] = f["Ownership"].map(CAT3)
    g = f.groupby("Street_Name")
    agg = g.agg(
        total=("MstrRecNbrTxt", "size"),
        fatal=("InjuryClass", lambda s: int((s == FATAL).sum())),
        city=("cat3", lambda s: int((s == "City").sum())),
        tdot=("cat3", lambda s: int((s == "TDOT").sum())),
        limited=("cat3", lambda s: int((s == "Limited").sum())),
    )
    ranked = agg.sort_values(["total", "fatal"], ascending=False).reset_index()
    ranked["rank"] = range(1, len(ranked) + 1)
    rank_map = dict(zip(ranked["Street_Name"], ranked["rank"]))

    # ALL junctions citywide (script 25 -- true geometric intersection)
    nodes = gpd.read_file(NODES)
    nodes_geo = nodes.to_crs(CRS_GEO)
    # covered corridors come from script 25's sidecar (authoritative); a corridor not in this
    # set has no signal inventory -> n_signalized stays None ("not yet analyzed").
    covered = set(json.loads(COVERED_OUT.read_text())) if COVERED_OUT.exists() else set()
    sig_count = {}
    for _, nd in nodes.iterrows():
        if not bool(nd["signalized"]):
            continue
        for s in [s.strip() for s in str(nd["streets"]).split(";") if s.strip()]:
            if s in covered:
                sig_count[s] = sig_count.get(s, 0) + 1

    union = json.loads(UNION_SUM.read_text()) if UNION_SUM.exists() else {}
    union_safe = {
        "n_safe": union.get("n_safe"), "n_signalized": union.get("n_signalized"),
        "n_marked_only": union.get("n_marked_only"), "longest_gap_ft": union.get("longest_gap_ft"),
        "pct_over_250ft": union.get("pct_over_250ft"), "median_spacing_ft": union.get("median_spacing_ft"),
    } if union else None
    # Union per-node nearest-safe distances were keyed by the OLD covered-node ids; transfer them
    # to the rebuilt Union nodes by location (nearest old covered node within 25 m).
    union_node_dist = {int(k): v for k, v in union.get("node_nearest_safe_m", {}).items()}
    new_union_safe_m = {}
    if union_node_dist and NODES_COVERED.exists():
        oldc = gpd.read_file(NODES_COVERED).to_crs(CRS_M)
        oldc = oldc[oldc["node_id"].isin(union_node_dist.keys())].copy()
        oldc["safe_m"] = oldc["node_id"].map(union_node_dist)
        new_union = nodes.to_crs(CRS_M)
        new_union = new_union[new_union["streets"].str.contains("UNION AVE", na=False)]
        if len(oldc) and len(new_union):
            mt = gpd.sjoin_nearest(new_union[["node_id", "geometry"]],
                                   oldc[["safe_m", "geometry"]], how="left", distance_col="d")
            mt = mt[~mt.index.duplicated(keep="first")]
            for nid, sm, d in zip(mt["node_id"], mt["safe_m"], mt["d"]):
                if d <= 25:
                    new_union_safe_m[int(nid)] = float(sm)

    # corridor centerlines (simplified) for highlight + address nearest-corridor
    rb = gpd.read_file(RULEBOOK).to_crs(CRS_M)
    corridors = []
    for name in agg.index:
        r = agg.loc[name]
        segs = rb[rb["Street_Name"] == name]
        paths = []
        if len(segs):
            geo = segs.copy()
            geo["geometry"] = geo.geometry.simplify(20, preserve_topology=False)
            for gm in geo.to_crs(CRS_GEO).geometry:
                if gm is None or gm.is_empty:
                    continue
                lines = gm.geoms if gm.geom_type == "MultiLineString" else [gm]
                for ln in lines:
                    paths.append([[round(y, 5), round(x, 5)] for x, y in ln.coords])
        corridors.append({
            "disp": titlecase_street(name), "raw": name,
            "total": int(r.total), "fatal": int(r.fatal),
            "city": int(r.city), "tdot": int(r.tdot), "limited": int(r.limited),
            "rank": int(rank_map[name]),
            "n_signalized": (sig_count.get(name, 0) if name in covered else None),
            "safe": (union_safe if name == "UNION AVE" else None),
            "geom": paths,
        })

    # intersections: EVERY junction citywide (crash counts/deaths/signalized precomputed by script 25).
    # Packed as compact arrays [disp, lat, lon, crashes, deaths, sig, near_safe_ft] to keep the
    # embedded index small; sig in {"y": signalized, "n": covered+unsignalized, "u": no signal coverage}.
    # 0-crash nodes are INCLUDED and searchable (they honestly report "0 incidents reported here").
    intersections = []
    with_crash = 0
    for _, nd in nodes_geo.iterrows():
        nid = int(nd["node_id"])
        sts = [titlecase_street(s.strip()) for s in str(nd["streets"]).split(";") if s.strip()]
        c = nd.geometry.centroid
        cr = int(nd["crashes"]); dt = int(nd["deaths"])
        if cr:
            with_crash += 1
        sig = "y" if bool(nd["signalized"]) else ("n" if bool(nd["on_covered"]) else "u")
        nsf = new_union_safe_m.get(nid)
        intersections.append([" & ".join(sts), round(c.y, 5), round(c.x, 5), cr, dt, sig,
                              (round(nsf / 0.3048) if nsf is not None else None)])

    idx = {"corridors": corridors, "intersections": intersections,
           "meta": {"n_corridors": len(corridors), "n_intersections": len(intersections),
                    "n_intersections_with_crash": with_crash, "total_crashes": int(f.shape[0])}}
    return idx, f, agg


def reconcile(idx, f):
    # independent recompute of the deadliest top-25 (same method script 18 uses)
    g = f.groupby("Street_Name").agg(
        total=("MstrRecNbrTxt", "size"),
        fatal=("InjuryClass", lambda s: int((s == FATAL).sum())))
    top = g.sort_values(["total", "fatal"], ascending=False).head(25).reset_index()
    by_rank = {c["rank"]: c for c in idx["corridors"]}
    print("\n=== RECONCILIATION: index corridors vs deadliest-card method (top 12 shown) ===")
    print(f"{'#':>2} {'street':<22} {'idx total/fatal':>16} {'card total/fatal':>17}  match")
    ok = True
    for i, row in top.iterrows():
        rank = i + 1
        ic = by_rank[rank]
        m = (ic["raw"] == row["Street_Name"] and ic["total"] == int(row["total"])
             and ic["fatal"] == int(row["fatal"]))
        ok = ok and m
        if rank <= 12:
            print(f"{rank:>2} {ic['disp']:<22} {str(ic['total'])+'/'+str(ic['fatal']):>16} "
                  f"{str(int(row['total']))+'/'+str(int(row['fatal'])):>17}  {'OK' if m else 'MISMATCH'}")
    tot = sum(c["total"] for c in idx["corridors"])
    print(f"\nAll 25 deadliest match exactly: {ok}")
    print(f"Sum of all corridor totals = {tot} (expected {f.shape[0]}) "
          f"{'OK' if tot == f.shape[0] else 'MISMATCH'}")
    return ok


def inject(idx):
    blob = json.dumps(idx, separators=(",", ":"))
    block = ("<!-- SEARCH-FEATURE-START -->\n" + _CSS +
             '<div id="searchWrap"><input id="searchBox" autocomplete="off" '
             'placeholder="Search a street, intersection, or address…">'
             '<div id="searchDrop"></div><div id="searchCard"></div></div>\n'
             '<script>window.SEARCH_INDEX=' + blob + ';</script>\n'
             "<script>\n" + _JS + "\n</script>\n<!-- SEARCH-FEATURE-END -->\n")
    html = HTML.read_text(encoding="utf-8")
    pat = re.compile(r"<!-- SEARCH-FEATURE-START -->.*?<!-- SEARCH-FEATURE-END -->\n?", re.S)
    html = pat.sub("", html)
    html = html.replace("</body>", block + "</body>")
    HTML.write_text(html, encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    idx, f, agg = build_index()
    blob = json.dumps(idx, separators=(",", ":"))
    INDEX_JSON.write_text(blob, encoding="utf-8")
    ok = reconcile(idx, f)
    inject(idx)

    html_kb = HTML.stat().st_size / 1024
    print(f"\nIndex: {idx['meta']['n_corridors']} corridors, "
          f"{idx['meta']['n_intersections']:,} intersections "
          f"({idx['meta']['n_intersections_with_crash']:,} carry >=1 crash; the rest are searchable "
          f"and report '0 incidents reported here').")
    print(f"  embedded index size: {len(blob)/1024:.0f} KB  ->  index.html now {html_kb:.0f} KB "
          f"({'OK to embed' if html_kb < 4096 else 'LARGE -- consider lazy-load'})")

    # three example lookups
    print("\n=== EXAMPLE LOOKUPS ===")
    c = next(x for x in idx["corridors"] if x["raw"] == "POPLAR AVE")
    print(f"[corridor] {c['disp']}: rank #{c['rank']}, {c['total']} crashes / {c['fatal']} fatal, "
          f"owner City {c['city']}/TDOT {c['tdot']}/Limited {c['limited']}, "
          f"signalized intersections {c['n_signalized']}, safe-crossing "
          f"{'not yet analyzed' if not c['safe'] else c['safe']}")
    u = next(x for x in idx["corridors"] if x["raw"] == "UNION AVE")
    print(f"[corridor] {u['disp']}: rank #{u['rank']}, {u['total']}/{u['fatal']}, "
          f"SAFE={u['safe']}")
    SIGMAP = {"y": "signalized", "n": "unsignalized", "u": "no signal coverage"}
    it = max(idx["intersections"], key=lambda x: x[3])  # packed: [disp,lat,lon,crashes,deaths,sig,nsf]
    print(f"[intersection] {it[0]}: {it[3]} crashes / {it[4]} fatal, signal={SIGMAP[it[5]]}, "
          f"nearest safe crossing={(str(it[6])+' ft') if it[6] is not None else 'not yet analyzed'}")
    uc = next((x for x in idx["intersections"]
               if "Union Avenue" in x[0] and "Cleveland" in x[0]), None)
    print(f"[ACCEPTANCE] Union & S Cleveland -> "
          + (f"FOUND '{uc[0]}': {uc[3]} crashes / {uc[4]} fatal, signal={SIGMAP[uc[5]]} "
             f"(searchable: yes)" if uc else "*** NOT IN INDEX ***"))
    print("[address] e.g. '125 N Main St' -> geocoded via the /api/geocode serverless proxy "
          "(server-side US Census call; needs the deployed site, not file://); card shows nearest "
          "corridor + nearest intersection + crashes within 50 m (graceful failure if unreachable).")
    print(f"\nAll 25 deadliest corridors match the published card: {ok}. "
          "Search is additive; existing map/layers/toggles/charts untouched.")


_CSS = """<style>
#searchWrap{position:absolute;z-index:1200;top:13px;right:300px;width:min(360px,42vw);font-family:system-ui,Segoe UI,Roboto,sans-serif}
@media(max-width:900px){#searchWrap{right:12px;top:60px;width:min(360px,92vw)}}
#searchBox{width:100%;box-sizing:border-box;padding:10px 13px;border:1px solid #b9c4cc;border-radius:9px;font-size:14px;box-shadow:0 2px 10px rgba(0,0,0,.18)}
#searchDrop{background:#fff;border-radius:9px;margin-top:5px;box-shadow:0 4px 16px rgba(0,0,0,.22);overflow:hidden;display:none}
#searchDrop .it{padding:8px 13px;cursor:pointer;font-size:13px;border-bottom:1px solid #eef1f3}
#searchDrop .it:hover,#searchDrop .it.sel{background:#eaf3f7}
#searchDrop .it b{color:#14303f}
#searchDrop .it .ty{float:right;color:#8aa;font-size:11px;text-transform:uppercase}
#searchCard{background:#fff;border-radius:10px;margin-top:6px;box-shadow:0 4px 16px rgba(0,0,0,.22);padding:13px 15px;font-size:13px;line-height:1.55;display:none}
#searchCard h2{margin:0 0 6px;font-size:16px;color:#14303f}
#searchCard .na{color:#a06000;font-style:italic}
#searchCard .x{float:right;cursor:pointer;color:#8aa;font-weight:700}
#searchCard .row{margin:2px 0}
</style>"""

_JS = r"""
(function(){
 var IDX=window.SEARCH_INDEX, box=document.getElementById('searchBox'),
     drop=document.getElementById('searchDrop'), card=document.getElementById('searchCard');
 var layer=L.layerGroup().addTo(map);
 function norm(s){return (s||'').toLowerCase().replace(/\band\b/g,'&').replace(/[^a-z0-9& ]/g,' ').replace(/\s+/g,' ').trim();}
 function toks(s){return norm(s).replace(/&/g,' ').split(' ').filter(Boolean);}
 // searchable items (intersections arrive packed as [disp,lat,lon,crashes,deaths,sig,near_safe_ft])
 var items=[];
 var INTERS=IDX.intersections.map(function(a){return {disp:a[0],lat:a[1],lon:a[2],crashes:a[3],deaths:a[4],sig:a[5],near_safe_ft:a[6]};});
 IDX.corridors.forEach(function(c){items.push({t:'corridor',disp:c.disp,blob:norm(c.disp),score:c.total,ref:c});});
 INTERS.forEach(function(n){items.push({t:'intersection',disp:n.disp,blob:norm(n.disp),score:n.crashes,ref:n});});
 function meters(a,b){var R=111320,la=(a[0]+b[0])/2*Math.PI/180;var dx=(a[1]-b[1])*Math.cos(la)*R,dy=(a[0]-b[0])*R;return Math.sqrt(dx*dx+dy*dy);}
 function ptSeg(p,a,b){var la=p[0]*Math.PI/180,kx=111320*Math.cos(la),ky=111320;
   var px=p[1]*kx,py=p[0]*ky,ax=a[1]*kx,ay=a[0]*ky,bx=b[1]*kx,by=b[0]*ky;
   var dx=bx-ax,dy=by-ay,L=dx*dx+dy*dy,t=L?((px-ax)*dx+(py-ay)*dy)/L:0;t=Math.max(0,Math.min(1,t));
   var cx=ax+t*dx,cy=ay+t*dy;return Math.sqrt((px-cx)*(px-cx)+(py-cy)*(py-cy));}
 function corridorDist(p,c){var m=1e9;c.geom.forEach(function(path){for(var i=0;i<path.length-1;i++){m=Math.min(m,ptSeg(p,path[i],path[i+1]));}});return m;}
 var FT=function(m){return Math.round(m/0.3048);};

 function clear(){layer.clearLayers();}
 function showCard(html){card.innerHTML='<span class="x" onclick="this.parentNode.style.display=\'none\'">✕</span>'+html;card.style.display='block';}
 function row(k,v){return '<div class="row"><b>'+k+':</b> '+v+'</div>';}
 function na(){return '<span class="na">not yet analyzed</span>';}

 function openCorridor(c){
   clear();
   // interactive:false => the highlight never captures pointer events, so crash dots
   // beneath it stay clickable. Lower opacity => the dots remain visible through the wash.
   L.polyline(c.geom,{color:'#ffe11a',weight:11,opacity:.22,interactive:false}).addTo(layer); // soft glow
   var pl=L.polyline(c.geom,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer); // highlighter
   try{map.fitBounds(pl.getBounds().pad(0.2));}catch(e){}
   var own='City '+c.city+' · TDOT '+c.tdot+' · Limited-access '+c.limited;
   var sig=c.n_signalized==null?na():(c.n_signalized+' signalized');
   var safe=c.safe?(c.safe.n_safe+' safe crossings ('+c.safe.n_signalized+' signalized + '+c.safe.n_marked_only+
     ' marked-only) · '+c.safe.pct_over_250ft+'% of crossing-relevant crashes >250 ft from one · longest gap '+
     c.safe.longest_gap_ft.toLocaleString()+' ft'):na();
   showCard('<h2>'+c.disp+'</h2>'+row('Deadliest rank','#'+c.rank)+row('Crashes',c.total+' ('+c.fatal+' fatal)')+
     row('Road owner',own)+row('Signalized intersections',sig)+row('Safe crossings',safe));
 }
 function openInter(n){
   // interactive:false + low fill => the node ring marks the spot but the crash dot(s)
   // underneath stay visible and clickable.
   clear();L.circleMarker([n.lat,n.lon],{radius:14,color:'#bfa600',weight:2,opacity:.65,fillColor:'#ffe11a',fillOpacity:.3,interactive:false}).addTo(layer);
   map.setView([n.lat,n.lon],16);
   var safe=n.near_safe_ft==null?na():(n.near_safe_ft+' ft');
   var crashes=n.crashes>0?(n.crashes+' ('+n.deaths+' fatal)'):'<span class="na">0 incidents reported here</span>';
   var sig=n.sig==='y'?'yes':(n.sig==='n'?'no':na());   // 'u' = no signal coverage -> not yet analyzed
   showCard('<h2>'+n.disp+'</h2>'+row('Crashes',crashes)+
     row('Signalized',sig)+row('Nearest safe crossing',safe));
 }
 function openAddress(q){
   showCard('<h2>Searching…</h2><div class="row">geocoding "'+q+'"</div>');clear();
   // Address geocoding goes through our own /api/geocode serverless proxy (Vercel). The US
   // Census geocoder sends no CORS header, so the browser cannot call it directly; the proxy
   // appends "Memphis, TN", calls Census server-side, and returns {matchedAddress,lat,lon}
   // with CORS allowed. NOTE: this needs the deployed server -- on file:// there is no
   // /api, so it falls through to the graceful "Address not found" message (corridor &
   // intersection search still work on file:// because that data is embedded in the page).
   fetch('/api/geocode?address='+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(j){
     if(!j||typeof j.lat!=='number'){throw 0;}
     var p=[j.lat,j.lon];
     var nc=null,ncd=1e9;IDX.corridors.forEach(function(c){var d=corridorDist(p,c);if(d<ncd){ncd=d;nc=c;}});
     if(nc){L.polyline(nc.geom,{color:'#ffe11a',weight:5,opacity:.5,interactive:false}).addTo(layer);}  // nearest corridor (transparent, click-through)
     L.marker(p).addTo(layer);map.setView(p,16);
     var ni=null,nid=1e9;INTERS.forEach(function(n){var d=meters(p,[n.lat,n.lon]);if(d<nid){nid=d;ni=n;}});
     var n50=0,f50=0;(window.CRASHES||[]).forEach(function(c){if(meters(p,[c[0],c[1]])<=50){n50++;if(c[3])f50++;}});
     showCard('<h2>'+(j.matchedAddress||q)+'</h2>'+
       row('Nearest corridor',(nc?nc.disp+' ('+FT(ncd)+' ft) — <a href="#" onclick="return false">rank #'+nc.rank+'</a>':'—'))+
       row('Nearest intersection',(ni?ni.disp+' ('+FT(nid)+' ft)':'—'))+
       row('Crashes within 50 m',n50+' ('+f50+' fatal)'));
     window._openNC=function(){openCorridor(nc);};
   }).catch(function(){showCard('<h2>Address not found</h2><div class="row">Couldn’t find that address — try a street or intersection.</div>');});
 }

 var sel=-1,cur=[];
 function render(list){cur=list;sel=-1;if(!list.length){drop.style.display='none';return;}
   drop.innerHTML=list.map(function(it,i){return '<div class="it" data-i="'+i+'"><b>'+it.disp+'</b><span class="ty">'+it.t+'</span></div>';}).join('');
   drop.style.display='block';
   Array.prototype.forEach.call(drop.children,function(el){el.onclick=function(){pick(cur[+el.dataset.i]);};});
 }
 function pick(it){box.value=it.disp;drop.style.display='none';if(it.t==='corridor')openCorridor(it.ref);else openInter(it.ref);}
 box.addEventListener('input',function(){
   var q=box.value.trim();if(q.length<2){drop.style.display='none';return;}
   var tq=toks(q);
   var matches=items.filter(function(it){return tq.every(function(t){return it.blob.indexOf(t)>=0;});})
     .sort(function(a,b){return b.score-a.score;}).slice(0,8);
   if(/\d/.test(q)&&/\d+\s+\S/.test(q)){matches.unshift({t:'address',disp:'Search address: "'+q+'"',addr:q});}
   else if(!matches.length){matches=[{t:'address',disp:'Search address: "'+q+'"',addr:q}];}
   render(matches);
 });
 box.addEventListener('keydown',function(e){
   if(drop.style.display==='none')return;
   if(e.key==='ArrowDown'){sel=Math.min(sel+1,cur.length-1);}
   else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0);}
   else if(e.key==='Enter'){var it=cur[sel<0?0:sel];if(it){if(it.t==='address')openAddress(it.addr);else pick(it);drop.style.display='none';}return;}
   else return;
   Array.prototype.forEach.call(drop.children,function(el,i){el.className='it'+(i===sel?' sel':'');});
   e.preventDefault();
 });
 document.addEventListener('click',function(e){if(!document.getElementById('searchWrap').contains(e.target))drop.style.display='none';});
 // allow clicking the "Search address" row
 drop.addEventListener('click',function(e){var el=e.target.closest('.it');if(el&&cur[+el.dataset.i]&&cur[+el.dataset.i].t==='address'){openAddress(cur[+el.dataset.i].addr);drop.style.display='none';}});
})();
"""


if __name__ == "__main__":
    main()
