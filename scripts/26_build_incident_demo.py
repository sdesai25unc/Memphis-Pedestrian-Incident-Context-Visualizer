r"""
26_build_incident_demo.py  --  injects the "Report a New Incident" tab INTO index.html (in place).

index.html (from script 24) exposes window.CountA.facts. This injects a button + modal that shows
(1) a deterministic FACTS card, (2) an AI-drafted paragraph, (3) framing notes. The facts card and
the data-derived framing notes render immediately and independently of the AI, so an API hiccup
never breaks the page. The AI paragraph is fetched from /api/incident-context:
  - on Vercel  -> outputs/interactive_map/api/incident-context.js (key from the OPENAI_API_KEY env var)
  - locally    -> scripts/incident_demo_server.py (key from openai_key.txt)
If neither is reachable (e.g. a plain file:// open), the tab just shows "AI summary unavailable".

Idempotent: re-running replaces only the marked block. RUN AFTER script 24 (it re-creates index.html):
    .\.venv\Scripts\python.exe scripts\24_build_search.py
    .\.venv\Scripts\python.exe scripts\26_build_incident_demo.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / "interactive_map" / "index.html"
OUT = SRC   # inject in place -> the deployed page carries the tab

BLOCK = r"""
<!-- INCIDENT-TAB-START (injected by scripts/26_build_incident_demo.py) -->
<style>
#icOpen{position:absolute;z-index:1250;left:14px;bottom:14px;padding:9px 14px;border:none;border-radius:9px;
  background:#14303f;color:#fff;font:600 13px system-ui,Segoe UI,Roboto,sans-serif;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.3)}
#icOpen:hover{background:#1d4257}
#icWrap{position:fixed;inset:0;z-index:2000;background:rgba(10,20,26,.45);display:none;align-items:flex-start;justify-content:center;overflow:auto}
#icModal{background:#fff;margin:34px 14px;width:min(640px,96vw);border-radius:12px;box-shadow:0 10px 40px rgba(0,0,0,.4);
  font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif;color:#1c2b33}
#icHd{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e9edf0}
#icHd h2{margin:0;font-size:17px;color:#14303f}
#icHd .x{cursor:pointer;color:#8aa;font-weight:700;font-size:18px}
#icBody{padding:16px 18px}
#icBody label{display:block;font-weight:600;font-size:12px;color:#54646c;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.03em}
#icBody input,#icBody textarea{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #cdd6dc;border-radius:8px;font-size:14px;font-family:inherit}
#icBody textarea{min-height:64px;resize:vertical}
#icGo{margin-top:14px;padding:9px 16px;border:none;border-radius:8px;background:#2a6f97;color:#fff;font-weight:600;cursor:pointer}
#icGo:disabled{opacity:.6;cursor:default}
#icErr{color:#a0331f;font-size:13px;margin-top:8px;display:none}
#icOut{margin-top:16px}
.ic-card{background:#f6f8f9;border:1px solid #e4eaed;border-radius:10px;padding:12px 14px;margin-top:12px}
.ic-card h3{margin:0 0 8px;font-size:14px;color:#14303f;text-transform:uppercase;letter-spacing:.03em}
.ic-row{margin:3px 0}
.ic-row b{color:#33444c}
.ic-beta{display:inline-block;font-size:10px;font-weight:700;color:#7a5b00;background:#ffedb0;border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:middle}
.ic-para{white-space:pre-wrap}
.ic-na{color:#a06000;font-style:italic}
.ic-reframe{margin:6px 0;padding:7px 10px;background:#fff;border:1px solid #e4eaed;border-radius:8px;font-size:13px}
.ic-reframe .o{color:#a0331f}.ic-reframe .s{color:#1b6b3a}.ic-reframe .w{color:#54646c;font-size:12px}
.ic-note{font-size:11px;color:#8a9aa2;margin-top:8px}
.ic-fn{margin:4px 0 4px 18px}
</style>
<button id="icOpen">&#128221; Report a New Incident</button>
<div id="icWrap"><div id="icModal">
  <div id="icHd"><h2>Report a New Incident <span class="ic-beta">demo</span></h2><span class="x" id="icClose">&times;</span></div>
  <div id="icBody">
    <label>Location &mdash; address or coordinates</label>
    <input id="icLoc" placeholder="e.g. 1779 Union Ave  —  or  35.137, -90.017" autocomplete="off">
    <label>Description (optional)</label>
    <textarea id="icDesc" placeholder="Paste a sentence or report snippet. Leave blank to skip language suggestions."></textarea>
    <button id="icGo">Get facts &amp; draft</button>
    <div id="icErr"></div>
    <div id="icOut"></div>
  </div>
</div></div>
<script>
(function(){
  var wrap=document.getElementById('icWrap'),loc=document.getElementById('icLoc'),desc=document.getElementById('icDesc'),
      go=document.getElementById('icGo'),out=document.getElementById('icOut'),err=document.getElementById('icErr');
  document.getElementById('icOpen').onclick=function(){wrap.style.display='flex';loc.focus();};
  function close(){wrap.style.display='none';}
  document.getElementById('icClose').onclick=close;
  wrap.addEventListener('click',function(e){if(e.target===wrap)close();});

  function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  function resolveLoc(s){
    s=(s||'').trim();
    var m=s.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if(m){var la=+m[1],lo=+m[2];
      if(la>=34.9&&la<=35.5&&lo>=-90.5&&lo<=-89.5) return Promise.resolve({lat:la,lon:lo,label:'Coordinates '+la.toFixed(5)+', '+lo.toFixed(5)});
      return Promise.reject('Those coordinates are outside the Memphis area.');}
    return fetch('/api/geocode?address='+encodeURIComponent(s)).then(function(r){return r.json();}).then(function(j){
      if(typeof j.lat!=='number') throw 0; return {lat:j.lat,lon:j.lon,label:j.matchedAddress||s};
    }).catch(function(){throw 'Could not find that address (is the demo server running?).';});
  }

  // -- deterministic renders (data only; never touch the AI) --
  function factsCard(F,label){
    var r=function(k,v){return '<div class="ic-row"><b>'+k+':</b> '+v+'</div>';};
    var t=F.time_window, s=F.stretch;
    var recent='12mo '+t.last_12_months.incidents+'/'+t.last_12_months.deaths+
               ' &middot; 6mo '+t.last_6_months.incidents+'/'+t.last_6_months.deaths+
               ' &middot; 3mo '+t.last_3_months.incidents+'/'+t.last_3_months.deaths+
               ' &middot; 1mo '+t.last_1_month.incidents+'/'+t.last_1_month.deaths+' (incidents/fatal)';
    return '<div class="ic-card"><h3>Facts (from the data)</h3>'+
      r('Location',esc(label)+' &mdash; '+F.location.lat+', '+F.location.lon)+
      r('Road',esc(F.road.name)+' &mdash; <b>'+esc(F.road.owner)+'</b>-owned'+(F.road.owner_varies?' (ownership varies along the corridor)':''))+
      r('Snapped to road',F.road.snap_distance_m+' m from the point to the centerline')+
      (F.sidewalk?r('Sidewalk (city inventory)',esc(F.sidewalk.status)):'')+
      r('On this &plusmn;'+s.window_m+' m stretch',s.crashes+' incident(s), '+s.fatal+' fatal'+
        (s.pieces>1?(' &middot; connected section ~'+s.connected_length_m+' m'+(s.road_split_by_gaps?', road split by gaps':'')):''))+
      r('Whole road ('+t.coverage_start+' &rarr; '+t.coverage_end+')',t.total_incidents+' incident(s), '+t.total_deaths+' fatal')+
      r('Recent (whole road)',recent)+
      (F.nearest_intersection?r('Nearest intersection',esc(F.nearest_intersection.name)+' ('+F.nearest_intersection.distance_m+' m, '+
        (F.nearest_intersection.signalized?'signalized':'not signalized in the TDOT inventory')+', '+F.nearest_intersection.crashes+' incident(s))'):'')+
      (F.nearest_safe_crossing_ft!=null?r('Nearest safe crossing','~'+F.nearest_safe_crossing_ft+' ft'):'')+
      '</div>';
  }
  function framingNotes(F){
    var n=[],s=F.stretch,t=F.time_window;
    if(F.road.owner==='TDOT / State') n.push('This is a TDOT state route (state-owned) &mdash; design responsibility sits with the Tennessee DOT, not the City of Memphis.');
    else if(F.road.owner==='City of Memphis') n.push('This is a City of Memphis street (city-owned).');
    else if(F.road.owner.indexOf('Limited')===0) n.push('This is a limited-access (TDOT) facility.');
    n.push(s.crashes+' pedestrian/non-motorist incident(s), '+s.fatal+' fatal, are recorded within &plusmn;'+s.window_m+
           ' m of this point along the connected road; '+t.total_incidents+' ('+t.total_deaths+' fatal) along the whole road over '+
           t.coverage_start+'&ndash;'+t.coverage_end+'.');
    if(F.nearest_intersection && !F.nearest_intersection.signalized)
      n.push('The nearest mapped intersection ('+esc(F.nearest_intersection.name)+') is not signalized in the TDOT inventory.');
    if(F.nearest_safe_crossing_ft!=null && F.nearest_safe_crossing_ft>250)
      n.push('The nearest safe crossing on record is about '+F.nearest_safe_crossing_ft+' ft away.');
    var html='<div class="ic-card"><h3>Framing notes (from the data)</h3><ul style="margin:0;padding:0">';
    n.forEach(function(x){html+='<li class="ic-fn">'+x+'</li>';});
    return html+'</ul><div id="icReframes"></div></div>';
  }

  go.onclick=function(){
    err.style.display='none';out.innerHTML='';
    var address=loc.value,description=desc.value.trim();
    if(!address.trim()){err.textContent='Enter a location.';err.style.display='block';return;}
    go.disabled=true;go.textContent='Locating…';
    resolveLoc(address).then(function(P){
      var F=(window.CountA&&window.CountA.facts)?window.CountA.facts(P.lat,P.lon):null;
      if(!F) throw 'No road data available for that point.';
      // (1) FACTS + (3) data framing render immediately, independent of the AI
      out.innerHTML=factsCard(F,P.label)+
        '<div class="ic-card"><h3>AI-generated draft <span class="ic-beta">beta</span></h3>'+
          '<div id="icPara" class="ic-para ic-na">Drafting context…</div></div>'+
        framingNotes(F);
      go.disabled=false;go.textContent='Get facts & draft';
      // (2) AI paragraph + language reframes -- resilient: facts already shown
      var code=(window.localStorage&&localStorage.getItem('ic_access'))||'';
      var ctrl=('AbortController' in window)?new AbortController():null;
      var timer=setTimeout(function(){if(ctrl)ctrl.abort();},50000);
      fetch('/api/incident-context',{method:'POST',
        headers:{'Content-Type':'application/json','x-access-code':code},
        signal:ctrl?ctrl.signal:undefined,body:JSON.stringify({facts:F,description:description,access_code:code})})
        .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
        .then(function(res){clearTimeout(timer);
          var para=document.getElementById('icPara');
          if(res.j&&res.j.error==='unauthorized'){        // optional access-code gate is enabled server-side
            para.className='ic-para ic-na';
            var entered=window.prompt('This AI feature requires an access code:');
            if(entered&&window.localStorage){localStorage.setItem('ic_access',entered);
              para.textContent='Access code saved -- click "Get facts & draft" again.';}
            else{para.textContent='AI summary unavailable (access code required). The facts above stand on their own.';}
            return;
          }
          if(!res.ok||!res.j||!res.j.paragraph){
            para.className='ic-para ic-na';
            para.textContent='AI summary unavailable'+((res.j&&res.j.error)?(' ('+res.j.error+')'):'')+'. The facts above stand on their own.';
            return;
          }
          para.className='ic-para';para.textContent=res.j.paragraph;
          var rf=res.j.reframes||[],box=document.getElementById('icReframes');
          if(rf.length&&box){var h='<h3 style="margin-top:10px">Language reframes</h3>';
            rf.forEach(function(x){h+='<div class="ic-reframe"><div class="o">&ldquo;'+esc(x.original)+'&rdquo;</div>'+
              '<div class="s">&rarr; &ldquo;'+esc(x.suggested)+'&rdquo;</div>'+(x.why?'<div class="w">'+esc(x.why)+'</div>':'')+'</div>';});
            box.innerHTML=h;}
        })
        .catch(function(){clearTimeout(timer);var para=document.getElementById('icPara');
          para.className='ic-para ic-na';para.textContent='AI summary unavailable (timeout or network). The facts above stand on their own.';});
    }).catch(function(e){go.disabled=false;go.textContent='Get facts & draft';
      err.textContent=(typeof e==='string')?e:'Something went wrong.';err.style.display='block';});
  };
})();
</script>
<!-- INCIDENT-TAB-END -->
"""


def main():
    if not SRC.exists():
        sys.exit(f"build index.html first (run script 24). Missing: {SRC}")
    html = SRC.read_text(encoding="utf-8")
    if "window.CountA" not in html:
        sys.exit("index.html does not expose window.CountA -- run script 24 (updated) first.")
    # idempotent: strip any previously-injected tab (by markers), then inject after </body>'s content
    html = re.sub(r"<!-- INCIDENT-TAB-START.*?<!-- INCIDENT-TAB-END -->\n?", "", html, flags=re.S)
    html = html.replace("</body>", BLOCK + "\n</body>")
    OUT.write_text(html, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"injected Report-a-New-Incident tab into {OUT.name}  ({kb:.0f} KB). "
          f"AI draft needs /api/incident-context (Vercel env key, or the local demo server).")


if __name__ == "__main__":
    main()
