(function(){"use strict";const Z={python:{color:"#3b82f6",name:"Python"},php:{color:"#8b5cf6",name:"PHP"},ruby:{color:"#ef4444",name:"Ruby"},nodejs:{color:"#22c55e",name:"Node.js"}};function Et(){const t=document.getElementById("app"),n=(t==null?void 0:t.dataset.framework)??"python",o=t==null?void 0:t.dataset.color,r=Z[n]??Z.python;return{framework:n,color:o??r.color,name:r.name}}function Tt(t){const n=document.documentElement;n.style.setProperty("--primary",t.color),n.style.setProperty("--bg","#0f172a"),n.style.setProperty("--surface","#1e293b"),n.style.setProperty("--border","#334155"),n.style.setProperty("--text","#e2e8f0"),n.style.setProperty("--muted","#94a3b8"),n.style.setProperty("--success","#22c55e"),n.style.setProperty("--danger","#ef4444"),n.style.setProperty("--warn","#f59e0b"),n.style.setProperty("--info","#3b82f6")}const Mt=`
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }

.dev-admin { display: flex; flex-direction: column; height: 100vh; }
.dev-header { display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 1rem; background: var(--surface); border-bottom: 1px solid var(--border); }
.dev-header h1 { font-size: 1rem; font-weight: 700; }
.dev-header h1 span { color: var(--primary); }

.dev-tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); background: var(--surface); padding: 0 0.5rem; overflow-x: auto; }
.dev-tab { padding: 0.5rem 0.75rem; border: none; background: none; color: var(--muted); cursor: pointer; font-size: 0.8rem; font-weight: 500; white-space: nowrap; border-bottom: 2px solid transparent; transition: all 0.15s; }
.dev-tab:hover { color: var(--text); }
.dev-tab.active { color: var(--primary); border-bottom-color: var(--primary); }

.dev-content { flex: 1; overflow-y: auto; }
.dev-panel { padding: 1rem; display: none; }
.dev-panel.active { display: block; }
.dev-panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
.dev-panel-header h2 { font-size: 0.95rem; font-weight: 600; }

.btn { padding: 0.35rem 0.75rem; border: 1px solid var(--border); border-radius: 0.375rem; background: var(--surface); color: var(--text); cursor: pointer; font-size: 0.8rem; transition: all 0.15s; height: 30px; line-height: 1; }
.btn:hover { background: var(--border); }
.btn-primary { background: var(--primary); border-color: var(--primary); color: white; }
.btn-primary:hover { opacity: 0.9; }
.btn-danger { background: var(--danger); border-color: var(--danger); color: white; }
.btn-sm { padding: 0.2rem 0.5rem; font-size: 0.75rem; }

.input { padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 0.375rem; background: var(--bg); color: var(--text); font-size: 0.8rem; height: 30px; }
select.input { height: 30px; }
.input:focus { outline: none; border-color: var(--primary); }
textarea.input { font-family: "SF Mono", "Fira Code", Consolas, monospace; resize: vertical; height: auto; }

table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; padding: 0.5rem; color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }
td { padding: 0.5rem; border-bottom: 1px solid var(--border); }
tr:hover { background: rgba(255,255,255,0.03); }

.badge { display: inline-block; padding: 0.1rem 0.4rem; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; }
.badge-success { background: rgba(34,197,94,0.15); color: var(--success); }
.badge-danger { background: rgba(239,68,68,0.15); color: var(--danger); }
.badge-warn { background: rgba(245,158,11,0.15); color: var(--warn); }
.badge-info { background: rgba(59,130,246,0.15); color: var(--info); }
.badge-muted { background: rgba(148,163,184,0.15); color: var(--muted); }

.method { font-weight: 700; font-size: 0.7rem; padding: 0.1rem 0.3rem; border-radius: 0.2rem; }
.method-get { color: var(--success); }
.method-post { color: var(--info); }
.method-put { color: var(--warn); }
.method-patch { color: var(--warn); }
.method-delete { color: var(--danger); }
.method-any { color: var(--muted); }

.flex { display: flex; }
.gap-sm { gap: 0.5rem; }
.items-center { align-items: center; }
.text-mono { font-family: "SF Mono", "Fira Code", Consolas, monospace; }
.text-sm { font-size: 0.8rem; }
.text-muted { color: var(--muted); }
.empty-state { text-align: center; padding: 2rem; color: var(--muted); }

.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }
.metric-card { background: var(--surface); border: 1px solid var(--border); border-radius: 0.5rem; padding: 0.75rem; }
.metric-card .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.metric-card .value { font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }

.chat-container { display: flex; flex-direction: column; height: calc(100vh - 140px); }
.chat-messages { flex: 1; overflow-y: auto; padding: 0.75rem; }
.chat-msg { padding: 0.5rem 0.75rem; border-radius: 0.5rem; margin-bottom: 0.5rem; font-size: 0.85rem; line-height: 1.5; max-width: 85%; }
.chat-user { background: var(--primary); color: white; margin-left: auto; }
.chat-bot { background: var(--surface); border: 1px solid var(--border); }
.chat-input-row { display: flex; gap: 0.5rem; padding: 0.75rem; border-top: 1px solid var(--border); }
.chat-input-row input { flex: 1; }

.error-trace { background: var(--bg); border: 1px solid var(--border); border-radius: 0.375rem; padding: 0.5rem; font-family: monospace; font-size: 0.75rem; white-space: pre-wrap; max-height: 200px; overflow-y: auto; margin-top: 0.5rem; }

.bubble-chart { width: 100%; height: 400px; background: var(--surface); border: 1px solid var(--border); border-radius: 0.5rem; overflow: hidden; }
`,St="/__dev/api";async function x(t,n="GET",o){const r={method:n,headers:{}};return o&&(r.headers["Content-Type"]="application/json",r.body=JSON.stringify(o)),(await fetch(St+t,r)).json()}function s(t){const n=document.createElement("span");return n.textContent=t,n.innerHTML}function It(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>Routes <span id="routes-count" class="text-muted text-sm"></span></h2>
      <button class="btn btn-sm" onclick="window.__loadRoutes()">Refresh</button>
    </div>
    <table>
      <thead><tr><th>Method</th><th>Path</th><th>Auth</th><th>Handler</th></tr></thead>
      <tbody id="routes-body"></tbody>
    </table>
  `,tt()}async function tt(){const t=await x("/routes"),n=document.getElementById("routes-count");n&&(n.textContent=`(${t.count})`);const o=document.getElementById("routes-body");o&&(o.innerHTML=(t.routes||[]).map(r=>`
    <tr>
      <td><span class="method method-${r.method.toLowerCase()}">${s(r.method)}</span></td>
      <td class="text-mono"><a href="${s(r.path)}" target="_blank" style="color:inherit;text-decoration:underline dotted">${s(r.path)}</a></td>
      <td>${r.auth_required?'<span class="badge badge-warn">auth</span>':'<span class="badge badge-success">open</span>'}</td>
      <td class="text-sm text-muted">${s(r.handler||"")} <small>(${s(r.module||"")})</small></td>
    </tr>
  `).join(""))}window.__loadRoutes=tt;let H=[],z=[],S=JSON.parse(localStorage.getItem("tina4_query_history")||"[]");function Lt(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>Database</h2>
      <button class="btn btn-sm" onclick="window.__loadTables()">Refresh</button>
    </div>
    <div style="display:flex;gap:1rem;height:calc(100vh - 140px)">
      <div style="width:200px;flex-shrink:0;overflow-y:auto;border-right:1px solid var(--border);padding-right:0.75rem">
        <div style="font-weight:600;font-size:0.75rem;color:var(--muted);text-transform:uppercase;margin-bottom:0.5rem">Tables</div>
        <div id="db-table-list"></div>
        <div style="margin-top:1.5rem;border-top:1px solid var(--border);padding-top:0.75rem">
          <div style="font-weight:600;font-size:0.75rem;color:var(--muted);text-transform:uppercase;margin-bottom:0.5rem">Seed Data</div>
          <select id="db-seed-table" class="input" style="width:100%;margin-bottom:0.5rem">
            <option value="">Pick table...</option>
          </select>
          <div class="flex gap-sm">
            <input type="number" id="db-seed-count" class="input" value="10" style="width:60px">
            <button class="btn btn-sm btn-primary" onclick="window.__seedTable()">Seed</button>
          </div>
        </div>
      </div>
      <div style="flex:1;display:flex;flex-direction:column;min-width:0">
        <div class="flex gap-sm items-center" style="margin-bottom:0.5rem;flex-wrap:wrap">
          <select id="db-type" class="input" style="width:80px">
            <option value="sql">SQL</option>
            <option value="graphql">GraphQL</option>
          </select>
          <span class="text-sm text-muted">Limit</span>
          <select id="db-limit" class="input" style="width:60px">
            <option value="20">20</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="500">500</option>
          </select>
          <span class="text-sm text-muted">Offset</span>
          <input type="number" id="db-offset" class="input" value="0" style="width:60px" min="0">
          <button class="btn btn-primary" onclick="window.__runQuery()">Run</button>
          <button class="btn" onclick="window.__copyCSV()">Copy CSV</button>
          <button class="btn" onclick="window.__copyJSON()">Copy JSON</button>
          <button class="btn" onclick="window.__showPaste()">Paste</button>
          <span class="text-sm text-muted">Ctrl+Enter</span>
        </div>
        <div class="flex gap-sm items-center" style="margin-bottom:0.25rem">
          <select id="db-history" class="input text-mono" style="flex:1" onchange="window.__loadHistory(this.value)">
            <option value="">Query history...</option>
          </select>
          <button class="btn btn-sm" onclick="window.__clearHistory()" title="Clear history" style="height:30px">Clear</button>
        </div>
        <textarea id="db-query" class="input text-mono" style="width:100%;height:80px;resize:vertical" placeholder="SELECT * FROM users" onkeydown="if(event.ctrlKey&&event.key==='Enter')window.__runQuery()"></textarea>
        <div id="db-result" style="flex:1;overflow:auto;margin-top:0.75rem"></div>
      </div>
    </div>
    <div id="db-paste-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:1000;display:none;align-items:center;justify-content:center">
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;padding:1.5rem;width:600px;max-height:80vh;overflow:auto">
        <h3 style="margin-bottom:0.75rem;font-size:0.9rem">Paste Data</h3>
        <p class="text-sm text-muted" style="margin-bottom:0.5rem">Paste CSV or JSON array. First row = column headers for CSV.</p>
        <div class="flex gap-sm items-center" style="margin-bottom:0.5rem">
          <select id="paste-table" class="input" style="flex:1"><option value="">Select existing table...</option></select>
          <span class="text-sm text-muted">or</span>
          <input type="text" id="paste-new-table" class="input" placeholder="New table name..." style="flex:1">
        </div>
        <textarea id="paste-data" class="input text-mono" style="width:100%;height:200px" placeholder='CSV data or JSON'></textarea>
        <div class="flex gap-sm" style="margin-top:0.75rem;justify-content:flex-end">
          <button class="btn" onclick="window.__hidePaste()">Cancel</button>
          <button class="btn btn-primary" onclick="window.__doPaste()">Import</button>
        </div>
      </div>
    </div>
  `,X(),J()}async function X(){const n=(await x("/tables")).tables||[],o=document.getElementById("db-table-list");o&&(o.innerHTML=n.length?n.map(l=>`<div style="padding:0.3rem 0.5rem;cursor:pointer;border-radius:0.25rem;font-size:0.8rem;font-family:monospace" class="db-table-item" onclick="window.__selectTable('${s(l)}')" onmouseover="this.style.background='var(--border)'" onmouseout="this.style.background=''">${s(l)}</div>`).join(""):'<div class="text-sm text-muted">No tables</div>');const r=document.getElementById("db-seed-table");r&&(r.innerHTML='<option value="">Pick table...</option>'+n.map(l=>`<option value="${s(l)}">${s(l)}</option>`).join(""));const a=document.getElementById("paste-table");a&&(a.innerHTML='<option value="">Select table...</option>'+n.map(l=>`<option value="${s(l)}">${s(l)}</option>`).join(""))}function Y(t){var o;(o=document.getElementById("db-limit"))!=null&&o.value;const n=document.getElementById("db-query");n&&(n.value=`SELECT * FROM ${t}`),document.querySelectorAll(".db-table-item").forEach(r=>{r.style.background=r.textContent===t?"var(--border)":""}),et()}function Ct(){var o;const t=document.getElementById("db-query"),n=((o=document.getElementById("db-limit"))==null?void 0:o.value)||"20";t!=null&&t.value&&(t.value=t.value.replace(/LIMIT\s+\d+/i,`LIMIT ${n}`))}function At(t){const n=t.trim();n&&(S=S.filter(o=>o!==n),S.unshift(n),S.length>50&&(S=S.slice(0,50)),localStorage.setItem("tina4_query_history",JSON.stringify(S)),J())}function J(){const t=document.getElementById("db-history");t&&(t.innerHTML='<option value="">Query history...</option>'+S.map((n,o)=>`<option value="${o}">${s(n.length>80?n.substring(0,80)+"...":n)}</option>`).join(""))}function Bt(t){const n=parseInt(t);if(isNaN(n)||!S[n])return;const o=document.getElementById("db-query");o&&(o.value=S[n]),document.getElementById("db-history").selectedIndex=0}function Ht(){S=[],localStorage.removeItem("tina4_query_history"),J()}async function et(){var a,l,h;const t=document.getElementById("db-query"),n=(a=t==null?void 0:t.value)==null?void 0:a.trim();if(!n)return;At(n);const o=document.getElementById("db-result"),r=((l=document.getElementById("db-type"))==null?void 0:l.value)||"sql";o&&(o.innerHTML='<p class="text-muted">Running...</p>');try{const w=parseInt(((h=document.getElementById("db-limit"))==null?void 0:h.value)||"20"),v=await x("/query","POST",{query:n,type:r,limit:w});if(v.error){o&&(o.innerHTML=`<p style="color:var(--danger)">${s(v.error)}</p>`);return}v.rows&&v.rows.length>0?(z=Object.keys(v.rows[0]),H=v.rows,o&&(o.innerHTML=`<p class="text-sm text-muted" style="margin-bottom:0.5rem">${v.count??v.rows.length} rows</p>
        <div style="overflow-x:auto"><table><thead><tr>${z.map(_=>`<th>${s(_)}</th>`).join("")}</tr></thead>
        <tbody>${v.rows.map(_=>`<tr>${z.map(b=>`<td class="text-sm">${s(String(_[b]??""))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`)):v.affected!==void 0?(o&&(o.innerHTML=`<p class="text-muted">${v.affected} rows affected. ${v.success?"Success.":""}</p>`),H=[],z=[]):(o&&(o.innerHTML='<p class="text-muted">No results</p>'),H=[],z=[])}catch(w){o&&(o.innerHTML=`<p style="color:var(--danger)">${s(w.message)}</p>`)}}function zt(){if(!H.length)return;const t=z.join(","),n=H.map(o=>z.map(r=>{const a=String(o[r]??"");return a.includes(",")||a.includes('"')?`"${a.replace(/"/g,'""')}"`:a}).join(","));navigator.clipboard.writeText([t,...n].join(`
`))}function Pt(){H.length&&navigator.clipboard.writeText(JSON.stringify(H,null,2))}function Ot(){const t=document.getElementById("db-paste-modal");t&&(t.style.display="flex")}function nt(){const t=document.getElementById("db-paste-modal");t&&(t.style.display="none")}async function jt(){var a,l,h,w,v;const t=(a=document.getElementById("paste-table"))==null?void 0:a.value,n=(h=(l=document.getElementById("paste-new-table"))==null?void 0:l.value)==null?void 0:h.trim(),o=n||t,r=(v=(w=document.getElementById("paste-data"))==null?void 0:w.value)==null?void 0:v.trim();if(!o||!r){alert("Select a table or enter a new table name, and paste data.");return}try{let _;try{_=JSON.parse(r),Array.isArray(_)||(_=[_])}catch{const M=r.split(`
`).map($=>$.trim()).filter(Boolean);if(M.length<2){alert("CSV needs at least a header row and one data row.");return}const C=M[0].split(",").map($=>$.trim().replace(/[^a-zA-Z0-9_]/g,""));_=M.slice(1).map($=>{const I=$.split(",").map(k=>k.trim()),A={};return C.forEach((k,P)=>{A[k]=I[P]??""}),A})}if(!_.length){alert("No data rows found.");return}if(n){const C=["id INTEGER PRIMARY KEY AUTOINCREMENT",...Object.keys(_[0]).filter(I=>I.toLowerCase()!=="id").map(I=>`"${I}" TEXT`)],$=await x("/query","POST",{query:`CREATE TABLE IF NOT EXISTS "${n}" (${C.join(", ")})`,type:"sql"});if($.error){alert("Create table failed: "+$.error);return}}let b=0;for(const M of _){const C=n?Object.keys(M).filter(k=>k.toLowerCase()!=="id"):Object.keys(M),$=C.map(k=>`"${k}"`).join(","),I=C.map(k=>`'${String(M[k]).replace(/'/g,"''")}'`).join(","),A=await x("/query","POST",{query:`INSERT INTO "${o}" (${$}) VALUES (${I})`,type:"sql"});if(A.error){alert(`Row ${b+1} failed: ${A.error}`);break}b++}document.getElementById("paste-data").value="",document.getElementById("paste-new-table").value="",document.getElementById("paste-table").selectedIndex=0,nt(),X(),b>0&&Y(o)}catch(_){alert("Import error: "+_.message)}}async function Nt(){var o,r;const t=(o=document.getElementById("db-seed-table"))==null?void 0:o.value,n=parseInt(((r=document.getElementById("db-seed-count"))==null?void 0:r.value)||"10");if(t)try{const a=await x("/seed","POST",{table:t,count:n});a.error?alert(a.error):Y(t)}catch(a){alert("Seed error: "+a.message)}}window.__loadTables=X,window.__selectTable=Y,window.__updateLimit=Ct,window.__runQuery=et,window.__copyCSV=zt,window.__copyJSON=Pt,window.__showPaste=Ot,window.__hidePaste=nt,window.__doPaste=jt,window.__seedTable=Nt,window.__loadHistory=Bt,window.__clearHistory=Ht;function Rt(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>Errors <span id="errors-count" class="text-muted text-sm"></span></h2>
      <div class="flex gap-sm">
        <button class="btn btn-sm" onclick="window.__loadErrors()">Refresh</button>
        <button class="btn btn-sm btn-danger" onclick="window.__clearErrors()">Clear All</button>
      </div>
    </div>
    <div id="errors-body"></div>
  `,V()}async function V(){const t=await x("/broken"),n=document.getElementById("errors-count"),o=document.getElementById("errors-body");if(!o)return;const r=t.errors||[];if(n&&(n.textContent=`(${r.length})`),!r.length){o.innerHTML='<div class="empty-state">No errors</div>';return}o.innerHTML=r.map((a,l)=>`
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;padding:0.75rem;margin-bottom:0.75rem">
      <div class="flex items-center" style="justify-content:space-between">
        <div>
          <span class="badge badge-danger">UNRESOLVED</span>
          <strong style="margin-left:0.5rem;font-size:0.85rem">${s(a.error||a.message||"Unknown error")}</strong>
        </div>
        <div class="flex gap-sm">
          <button class="btn btn-sm" onclick="window.__resolveError('${s(a.id||String(l))}')">Resolve</button>
          <button class="btn btn-sm btn-primary" onclick="window.__askAboutError(${l})">Ask Tina4</button>
        </div>
      </div>
      ${a.traceback?`<div class="error-trace">${s(a.traceback)}</div>`:""}
      <div class="text-sm text-muted" style="margin-top:0.5rem">${s(a.timestamp||"")}</div>
    </div>
  `).join(""),window.__errorData=r}async function qt(t){await x("/broken/resolve","POST",{id:t}),V()}async function Ft(){await x("/broken/clear","POST"),V()}function Dt(t){const o=(window.__errorData||[])[t];if(!o)return;const r=document.querySelector('[data-tab="chat"]');r&&r.click(),setTimeout(()=>{const a=document.getElementById("chat-input");a&&(a.value=`I have this error: ${o.error||o.message}

${o.traceback||""}`,a.focus())},100)}window.__loadErrors=V,window.__clearErrors=Ft,window.__resolveError=qt,window.__askAboutError=Dt;function Vt(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>System</h2>
      <button class="btn btn-sm" onclick="window.__loadSystem()">Refresh</button>
    </div>
    <div id="system-grid" class="metric-grid"></div>
  `,ot()}async function ot(){const t=await x("/system"),n=document.getElementById("system-grid");if(!n)return;const o=[{label:"Framework",value:t.framework||"Tina4"},{label:"Version",value:t.version||"?"},{label:"Runtime",value:t.runtime||t.python_version||t.php_version||t.ruby_version||t.node_version||"?"},{label:"Database",value:t.database||t.db_type||"none"},{label:"Uptime",value:t.uptime||"?"},{label:"Memory",value:t.memory||"?"},{label:"Platform",value:t.platform||"?"},{label:"Routes",value:String(t.route_count??t.routes??"?")},{label:"Debug",value:t.debug?"ON":"OFF"}];n.innerHTML=o.map(r=>`
    <div class="metric-card">
      <div class="label">${s(r.label)}</div>
      <div class="value" style="font-size:1.1rem">${s(r.value)}</div>
    </div>
  `).join("")}window.__loadSystem=ot;function Qt(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>Code Metrics</h2>
      <div class="flex gap-sm">
        <button class="btn" onclick="window.__loadQuickMetrics()">Quick Scan</button>
        <button class="btn btn-primary" onclick="window.__loadFullMetrics()">Full Analysis</button>
      </div>
    </div>
    <div id="metrics-quick" class="metric-grid"></div>
    <div id="metrics-scan-info" class="text-sm text-muted" style="margin:0.5rem 0"></div>
    <div id="metrics-chart" style="display:none;margin:1rem 0"></div>
    <div id="metrics-complex" style="margin-top:1rem"></div>
    <div id="metrics-detail" style="margin-top:1rem"></div>
  `,rt()}async function Xt(){const t=await x("/metrics"),n=document.getElementById("metrics-quick");!n||t.error||(n.innerHTML=[y("Files",t.file_count),y("Lines of Code",t.total_loc),y("Blank Lines",t.total_blank),y("Comments",t.total_comment),y("Classes",t.classes),y("Functions",t.functions),y("Routes",t.route_count),y("ORM Models",t.orm_count),y("Templates",t.template_count),y("Migrations",t.migration_count),y("Avg File Size",(t.avg_file_size??0)+" LOC")].join(""))}async function rt(){var l;const t=document.getElementById("metrics-chart"),n=document.getElementById("metrics-complex"),o=document.getElementById("metrics-scan-info");t&&(t.style.display="block",t.innerHTML='<p class="text-muted">Analyzing...</p>');const r=await x("/metrics/full");if(r.error||!r.file_metrics){t&&(t.innerHTML=`<p style="color:var(--danger)">${s(r.error||"No data")}</p>`);return}o&&(o.textContent=`${r.files_analyzed} files analyzed | ${r.total_functions} functions | Mode: ${r.scan_mode||"project"}`);const a=document.getElementById("metrics-quick");a&&(a.innerHTML=[y("Files Analyzed",r.files_analyzed),y("Total Functions",r.total_functions),y("Avg Complexity",r.avg_complexity),y("Avg Maintainability",r.avg_maintainability),y("Scan Mode",r.scan_mode||"project")].join("")),t&&r.file_metrics.length>0?Yt(r.file_metrics,t,r.dependency_graph||{}):t&&(t.innerHTML='<p class="text-muted">No files to visualize</p>'),n&&((l=r.most_complex_functions)!=null&&l.length)&&(n.innerHTML=`
      <h3 style="font-size:0.85rem;margin-bottom:0.5rem">Most Complex Functions</h3>
      <table>
        <thead><tr><th>Function</th><th>File</th><th>Line</th><th>Complexity</th><th>LOC</th></tr></thead>
        <tbody>${r.most_complex_functions.slice(0,15).map(h=>`
          <tr>
            <td class="text-mono">${s(h.name)}</td>
            <td class="text-sm text-muted" style="cursor:pointer;text-decoration:underline dotted" onclick="window.__drillDown('${s(h.file)}')">${s(h.file)}</td>
            <td>${h.line}</td>
            <td><span class="${h.complexity>10?"badge badge-danger":h.complexity>5?"badge badge-warn":"badge badge-success"}">${h.complexity}</span></td>
            <td>${h.loc}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    `)}function Yt(t,n,o){var ht,vt,ft,xt,wt,_t;n.clientWidth;const r=450,a=Math.max(...t.map(e=>e.loc||1)),l=18,h=50,w=1e3,v=1e3,b=[...t].sort((e,i)=>{const c=(e.avg_complexity??0)*2+(e.loc||0);return(i.avg_complexity??0)*2+(i.loc||0)-c}).map(e=>({...e,r:Math.max(l,Math.min(h,Math.sqrt((e.loc||1)/a)*h)),x:w,y:v}));for(let e=0;e<b.length;e++){if(e===0)continue;let i=0,c=0,m=!1;for(;!m;){const d=w+Math.cos(i)*c,g=v+Math.sin(i)*c;let p=!1;for(let f=0;f<e;f++){const L=d-b[f].x,D=g-b[f].y;if(Math.sqrt(L*L+D*D)<b[e].r+b[f].r+4){p=!0;break}}p||(b[e].x=d,b[e].y=g,m=!0),i+=.3,c+=.5}}let M=1/0,C=-1/0,$=1/0,I=-1/0;for(const e of b)M=Math.min(M,e.x-e.r-15),C=Math.max(C,e.x+e.r+15),$=Math.min($,e.y-e.r-15),I=Math.max(I,e.y+e.r+25);const A=30,k=M-A,P=$-A,O=C-M+A*2,j=I-$+A*2,B=Math.max(20,Math.round(Math.max(O,j)/20));n.innerHTML=`
    <div style="position:relative;display:flex;gap:0">
      <div style="flex:1;position:relative">
        <div style="position:absolute;top:8px;left:8px;z-index:2;display:flex;gap:4px;flex-direction:column">
          <button class="btn btn-sm" id="metrics-zoom-in" style="width:28px;height:28px;padding:0;font-size:14px;font-weight:700;line-height:1">+</button>
          <button class="btn btn-sm" id="metrics-zoom-out" style="width:28px;height:28px;padding:0;font-size:14px;font-weight:700;line-height:1">&minus;</button>
          <button class="btn btn-sm" id="metrics-zoom-fit" style="width:28px;height:28px;padding:0;font-size:10px;font-weight:700;line-height:1">Fit</button>
        </div>
        <svg id="metrics-svg" width="100%" height="${r}" viewBox="${k} ${P} ${O} ${j}" style="background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;cursor:grab"></svg>
      </div>
      <div id="metrics-hover-panel" style="width:200px;flex-shrink:0;background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;padding:0.75rem;font-size:0.75rem;margin-left:0.5rem;overflow-y:auto;height:${r}px">
        <div class="text-muted" style="text-align:center;padding-top:2rem">Hover a bubble<br>to see stats</div>
      </div>
    </div>
  `;const E=document.getElementById("metrics-svg");if(!E)return;const W={};for(const e of b)e.path&&(W[e.path]={x:e.x,y:e.y,r:e.r});let T="";const mt=Math.floor((k-O)/B)*B,ut=Math.ceil((k+O*3)/B)*B,pt=Math.floor((P-j)/B)*B,bt=Math.ceil((P+j*3)/B)*B;T+='<g class="metrics-grid">';for(let e=mt;e<=ut;e+=B)T+=`<line x1="${e}" y1="${pt}" x2="${e}" y2="${bt}" stroke="var(--border)" stroke-width="0.5" stroke-opacity="0.4" />`;for(let e=pt;e<=bt;e+=B)T+=`<line x1="${mt}" y1="${e}" x2="${ut}" y2="${e}" stroke="var(--border)" stroke-width="0.5" stroke-opacity="0.4" />`;T+="</g>",T+='<g class="dep-lines">';for(const[e,i]of Object.entries(o)){const c=W[e];if(c)for(const m of i){const d=Object.entries(W).find(([g])=>{var f;const p=((f=g.split("/").pop())==null?void 0:f.replace(/\.\w+$/,""))||"";return g===m||p===m||g.endsWith("/"+m)||g.endsWith("/"+m+".py")});if(d){const[,g]=d;T+=`<line x1="${c.x}" y1="${c.y}" x2="${g.x}" y2="${g.y}" stroke="var(--info)" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="4 3" />`}}}T+="</g>";for(const e of b){const i=e.maintainability??50,m=`hsl(${Math.min(120,Math.max(0,i*1.2))}, 80%, 45%)`,d=((ht=e.path)==null?void 0:ht.split("/").pop())||"?",g=e.has_tests===!0,p=e.dep_count??0;if(T+=`<circle cx="${e.x}" cy="${e.y}" r="${e.r}" fill="${m}" fill-opacity="0.6" stroke="${m}" stroke-width="1.5" style="cursor:pointer" data-drill="${s(e.path)}" />`,T+=`<title>${s(e.path)}
LOC: ${e.loc} | CC: ${e.avg_complexity} | MI: ${i}${g?" | Tested":""}${p>0?" | Deps: "+p:""}</title>`,e.r>15){const f=d.length>12?d.substring(0,10)+"..":d;T+=`<text x="${e.x}" y="${e.y+2}" text-anchor="middle" fill="white" font-size="8" font-weight="600" style="pointer-events:none" data-for="${s(e.path)}" data-role="label">${s(f)}</text>`}if(g){const f=e.x+e.r*.6,L=e.y-e.r*.6;T+=`<circle cx="${f}" cy="${L}" r="7" fill="var(--success)" stroke="var(--surface)" stroke-width="1" data-for="${s(e.path)}" data-role="t-circle" />`,T+=`<text x="${f}" y="${L+3}" text-anchor="middle" fill="white" font-size="7" font-weight="700" style="pointer-events:none" data-for="${s(e.path)}" data-role="t-text">T</text>`}if(p>0){const f=e.x-e.r*.6,L=e.y-e.r*.6;T+=`<circle cx="${f}" cy="${L}" r="7" fill="var(--info)" stroke="var(--surface)" stroke-width="1" data-for="${s(e.path)}" data-role="d-circle" />`,T+=`<text x="${f}" y="${L+3}" text-anchor="middle" fill="white" font-size="7" font-weight="700" style="pointer-events:none" data-for="${s(e.path)}" data-role="d-text">D</text>`}}E.innerHTML=T;let q=!1,Q=!1,N=null,F={x:0,y:0,vbX:0,vbY:0},u={x:k,y:P,w:O,h:j};const ee={x:k,y:P,w:O,h:j},gt=4,ne=document.getElementById("metrics-hover-panel");function K(){E.setAttribute("viewBox",`${u.x} ${u.y} ${u.w} ${u.h}`)}function yt(e){const i=u.x+u.w/2,c=u.y+u.h/2;u.w*=e,u.h*=e,u.x=i-u.w/2,u.y=c-u.h/2,K()}function oe(e,i){const c=E.getBoundingClientRect();return{x:u.x+(e-c.left)/c.width*u.w,y:u.y+(i-c.top)/c.height*u.h}}function re(){E.querySelectorAll(".dep-lines line").forEach(i=>i.remove());const e=E.querySelector(".dep-lines");if(e)for(const[i,c]of Object.entries(o)){const m=b.find(d=>d.path===i);if(m)for(const d of c){const g=b.find(p=>{var L,D,$t,kt;const f=((D=(L=p.path)==null?void 0:L.split("/").pop())==null?void 0:D.replace(/\.\w+$/,""))||"";return p.path===d||f===d||(($t=p.path)==null?void 0:$t.endsWith("/"+d))||((kt=p.path)==null?void 0:kt.endsWith("/"+d+".py"))});if(g){const p=document.createElementNS("http://www.w3.org/2000/svg","line");p.setAttribute("x1",String(m.x)),p.setAttribute("y1",String(m.y)),p.setAttribute("x2",String(g.x)),p.setAttribute("y2",String(g.y)),p.setAttribute("stroke","var(--info)"),p.setAttribute("stroke-width","1"),p.setAttribute("stroke-opacity","0.3"),p.setAttribute("stroke-dasharray","4 3"),e.appendChild(p)}}}E.querySelectorAll("[data-drill]").forEach(i=>{const c=i.getAttribute("data-drill"),m=b.find(d=>d.path===c);m&&(i.setAttribute("cx",String(m.x)),i.setAttribute("cy",String(m.y)))}),E.querySelectorAll("[data-for]").forEach(i=>{const c=i.getAttribute("data-for"),m=i.getAttribute("data-role"),d=b.find(g=>g.path===c);d&&(m==="label"?(i.setAttribute("x",String(d.x)),i.setAttribute("y",String(d.y+2))):m==="t-circle"?(i.setAttribute("cx",String(d.x+d.r*.6)),i.setAttribute("cy",String(d.y-d.r*.6))):m==="t-text"?(i.setAttribute("x",String(d.x+d.r*.6)),i.setAttribute("y",String(d.y-d.r*.6+3))):m==="d-circle"?(i.setAttribute("cx",String(d.x-d.r*.6)),i.setAttribute("cy",String(d.y-d.r*.6))):m==="d-text"&&(i.setAttribute("x",String(d.x-d.r*.6)),i.setAttribute("y",String(d.y-d.r*.6+3))))})}function ie(e){const i=e.maintainability??0,m=`hsl(${Math.min(120,Math.max(0,i*1.2))}, 80%, 45%)`;ne.innerHTML=`
      <div style="font-weight:700;font-size:0.85rem;margin-bottom:0.5rem;word-break:break-all">${s(e.path||"?")}</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:0.5rem">
        <div><span class="text-muted">LOC</span><br><strong>${e.loc??0}</strong></div>
        <div><span class="text-muted">Lines</span><br><strong>${e.total_lines??e.loc??0}</strong></div>
        <div><span class="text-muted">Complexity</span><br><strong>${e.avg_complexity??0}</strong></div>
        <div><span class="text-muted">MI</span><br><strong style="color:${m}">${i}</strong></div>
        <div><span class="text-muted">Functions</span><br><strong>${e.function_count??0}</strong></div>
        <div><span class="text-muted">Deps</span><br><strong>${e.dep_count??0}</strong></div>
      </div>
      <div style="margin-bottom:0.25rem">${e.has_tests?'<span class="badge badge-success">Tested</span>':'<span class="badge badge-muted">No tests</span>'}</div>
      ${(e.dep_count??0)>0?'<div><span class="badge badge-info">'+e.dep_count+" dependencies</span></div>":""}
      <div style="margin-top:0.75rem;font-size:0.7rem;color:var(--muted)">Click to drill down</div>
    `}E.querySelectorAll("[data-drill]").forEach(e=>{e.addEventListener("mouseenter",()=>{const i=e.getAttribute("data-drill"),c=b.find(m=>m.path===i);c&&ie(c)}),e.addEventListener("click",i=>{if(q)return;i.stopPropagation();const c=e.getAttribute("data-drill");c&&it(c)})}),E.addEventListener("mousedown",e=>{var m;if(e.button!==0)return;q=!1;const i=e.target,c=(m=i==null?void 0:i.getAttribute)==null?void 0:m.call(i,"data-drill");if(c){const d=b.find(g=>g.path===c);if(d){N=d,E.style.cursor="move",e.preventDefault();return}}Q=!0,F={x:e.clientX,y:e.clientY,vbX:u.x,vbY:u.y}}),window.addEventListener("mousemove",e=>{if(N){q=!0;const d=oe(e.clientX,e.clientY);N.x=d.x,N.y=d.y,re();return}if(!Q)return;const i=e.clientX-F.x,c=e.clientY-F.y;if(!q&&Math.abs(i)<gt&&Math.abs(c)<gt)return;q=!0,E.style.cursor="grabbing";const m=E.getBoundingClientRect();u.x=F.vbX-i/m.width*u.w,u.y=F.vbY-c/m.height*u.h,K()}),window.addEventListener("mouseup",()=>{N&&(N=null,E.style.cursor="grab"),Q&&(Q=!1,E.style.cursor="grab")}),(vt=document.getElementById("metrics-zoom-in"))==null||vt.addEventListener("click",()=>yt(.7)),(ft=document.getElementById("metrics-zoom-out"))==null||ft.addEventListener("click",()=>yt(1.4)),(xt=document.getElementById("metrics-zoom-fit"))==null||xt.addEventListener("click",()=>{u={...ee},K()});const G=document.createElement("div");G.style.cssText="position:absolute;bottom:8px;left:8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 10px;font-size:11px;line-height:1.6;opacity:0.9;z-index:2",G.innerHTML=`
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:hsl(0,80%,45%);vertical-align:middle"></span> Low MI &nbsp;
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:hsl(60,80%,45%);vertical-align:middle"></span> Med &nbsp;
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:hsl(120,80%,45%);vertical-align:middle"></span> High MI &nbsp;
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--success);vertical-align:middle"></span> T &nbsp;
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--info);vertical-align:middle"></span> D &nbsp;
    <span style="color:var(--info)">---</span> Dep
  `,(_t=(wt=n.querySelector("div > div:first-child"))==null?void 0:wt.parentElement)==null||_t.appendChild(G)}async function it(t){const n=document.getElementById("metrics-detail");if(!n)return;n.innerHTML='<p class="text-muted">Loading file analysis...</p>';const o=await x("/metrics/file?path="+encodeURIComponent(t));if(o.error){n.innerHTML=`<p style="color:var(--danger)">${s(o.error)}</p>`;return}const r=o.functions||[],a=o.warnings||[];n.innerHTML=`
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;padding:1rem">
      <div class="flex items-center" style="justify-content:space-between;margin-bottom:0.75rem">
        <h3 style="font-size:0.9rem">${s(o.path)}</h3>
        <button class="btn btn-sm" onclick="document.getElementById('metrics-detail').innerHTML=''">Close</button>
      </div>
      <div class="metric-grid" style="margin-bottom:0.75rem">
        ${y("LOC",o.loc)}
        ${y("Total Lines",o.total_lines)}
        ${y("Classes",o.classes)}
        ${y("Functions",r.length)}
      </div>
      ${r.length?`
        <table>
          <thead><tr><th>Function</th><th>Line</th><th>Complexity</th><th>LOC</th><th>Args</th></tr></thead>
          <tbody>${r.map(l=>`
            <tr>
              <td class="text-mono">${s(l.name)}</td>
              <td>${l.line}</td>
              <td><span class="${l.complexity>10?"badge badge-danger":l.complexity>5?"badge badge-warn":"badge badge-success"}">${l.complexity}</span></td>
              <td>${l.loc}</td>
              <td class="text-sm text-muted">${(l.args||[]).join(", ")}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      `:'<p class="text-muted">No functions</p>'}
      ${a.length?`
        <div style="margin-top:0.75rem">
          <h4 style="font-size:0.8rem;color:var(--warn);margin-bottom:0.25rem">Warnings</h4>
          ${a.map(l=>`<p class="text-sm" style="color:var(--warn)">Line ${l.line}: ${s(l.message)}</p>`).join("")}
        </div>
      `:""}
    </div>
  `}function y(t,n){return`<div class="metric-card"><div class="label">${s(t)}</div><div class="value">${s(String(n??0))}</div></div>`}window.__loadQuickMetrics=Xt,window.__loadFullMetrics=rt,window.__drillDown=it;let at="anthropic",R="";function Jt(t){t.innerHTML=`
    <div class="dev-panel-header">
      <h2>Code With Me</h2>
      <div class="flex gap-sm items-center">
        <select id="ai-provider" class="input" style="width:120px" onchange="window.__setProvider(this.value)">
          <option value="anthropic">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Ollama</option>
        </select>
        <input type="password" id="ai-key" class="input" placeholder="API key..." style="width:200px">
        <button class="btn btn-sm btn-primary" onclick="window.__setAiKey()">Set</button>
        <span class="text-sm text-muted" id="ai-status">${R?"Key set":"No key"}</span>
      </div>
    </div>
    <div class="chat-container">
      <div class="chat-messages" id="chat-messages">
        <div class="chat-msg chat-bot">Hi! I'm Tina4. Ask me to build routes, templates, models — or ask questions about your project. I can read and write files directly.</div>
      </div>
      <div class="chat-input-row">
        <input type="text" id="chat-input" class="input" placeholder="Ask Tina4 to build something..." onkeydown="if(event.key==='Enter')window.__sendChat()" style="flex:1">
        <button class="btn btn-primary" onclick="window.__sendChat()">Send</button>
        <button class="btn btn-sm" onclick="window.__undoChat()" title="Undo last file change">Undo</button>
      </div>
    </div>
  `}async function Ut(){var a;const t=document.getElementById("chat-input"),n=(a=t==null?void 0:t.value)==null?void 0:a.trim();if(!n)return;t.value="";const o=document.getElementById("chat-messages");if(!o)return;o.innerHTML+=`<div class="chat-msg chat-user">${s(n)}</div>`,o.innerHTML+='<div class="chat-msg chat-bot" id="chat-loading" style="color:var(--muted)">Thinking...</div>',o.scrollTop=o.scrollHeight;const r={message:n,provider:at};R&&(r.api_key=R);try{const l=await x("/chat","POST",r),h=document.getElementById("chat-loading");h&&h.remove();let w=Zt(l.reply||"No response");l.files_changed&&l.files_changed.length>0&&(w+='<div style="margin-top:0.5rem;padding:0.5rem;background:var(--bg);border-radius:0.375rem;border:1px solid var(--border)">',w+='<div class="text-sm" style="color:var(--success);font-weight:600;margin-bottom:0.25rem">Files changed:</div>',l.files_changed.forEach(v=>{w+=`<div class="text-sm text-mono">${s(v)}</div>`}),w+="</div>"),o.innerHTML+=`<div class="chat-msg chat-bot">${w}</div>`,o.innerHTML+=`<div class="text-sm text-muted" style="text-align:right;margin-bottom:0.25rem">${s(l.source||"")}</div>`,o.scrollTop=o.scrollHeight}catch{const l=document.getElementById("chat-loading");l&&(l.textContent="Error connecting",l.id="")}}async function Wt(){try{const t=await x("/chat/undo","POST"),n=document.getElementById("chat-messages");n&&(n.innerHTML+=`<div class="chat-msg chat-bot" style="color:var(--warn)">${s(t.message||"Undo complete")}</div>`,n.scrollTop=n.scrollHeight)}catch{alert("Nothing to undo")}}function Kt(){const t=document.getElementById("ai-key");R=(t==null?void 0:t.value)||"";const n=document.getElementById("ai-status");n&&(n.textContent=R?"Key set":"No key")}function Gt(t){at=t}function Zt(t){return t.replace(/```(\w*)\n([\s\S]*?)```/g,'<pre style="background:var(--bg);padding:0.5rem;border-radius:0.375rem;overflow-x:auto;margin:0.5rem 0;font-size:0.8rem"><code>$2</code></pre>').replace(/`([^`]+)`/g,'<code style="background:var(--bg);padding:0.1rem 0.25rem;border-radius:0.2rem;font-size:0.8em">$1</code>').replace(/\n/g,"<br>")}window.__sendChat=Ut,window.__undoChat=Wt,window.__setAiKey=Kt,window.__setProvider=Gt;const st=document.createElement("style");st.textContent=Mt,document.head.appendChild(st);const dt=Et();Tt(dt);const lt=[{id:"chat",label:"Code With Me",render:Jt},{id:"routes",label:"Routes",render:It},{id:"database",label:"Database",render:Lt},{id:"errors",label:"Errors",render:Rt},{id:"metrics",label:"Metrics",render:Qt},{id:"system",label:"System",render:Vt}];let U="chat";function te(){const t=document.getElementById("app");if(!t)return;t.innerHTML=`
    <div class="dev-admin">
      <div class="dev-header">
        <h1><span>Tina4</span> Dev Admin</h1>
        <span class="text-sm text-muted">${dt.name} &bull; v3.10</span>
      </div>
      <div class="dev-tabs" id="tab-bar"></div>
      <div class="dev-content" id="tab-content"></div>
    </div>
  `;const n=document.getElementById("tab-bar");n.innerHTML=lt.map(o=>`<button class="dev-tab ${o.id===U?"active":""}" data-tab="${o.id}" onclick="window.__switchTab('${o.id}')">${o.label}</button>`).join(""),ct(U)}function ct(t){U=t,document.querySelectorAll(".dev-tab").forEach(a=>{a.classList.toggle("active",a.dataset.tab===t)});const n=document.getElementById("tab-content");if(!n)return;const o=document.createElement("div");o.className="dev-panel active",n.innerHTML="",n.appendChild(o);const r=lt.find(a=>a.id===t);r&&r.render(o)}window.__switchTab=ct,te()})();
