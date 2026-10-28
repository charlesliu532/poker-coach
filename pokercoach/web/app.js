const POS_ORDER_6 = { SB: 0, BB: 1, UTG: 2, HJ: 3, CO: 4, BTN: 5 };
const POS_ORDER_8 = { SB: 0, BB: 1, UTG: 2, UTG1: 3, UTG2: 4, MP: 5, HJ: 6, CO: 7, BTN: 8 };
let POS_ORDER = { ...POS_ORDER_6 };
const POS_6 = ["UTG", "HJ", "CO", "BTN", "SB", "BB"];
const POS_8 = ["UTG", "UTG1", "UTG2", "MP", "HJ", "CO", "BTN", "SB", "BB"];
const POS_CN = { UTG: "UTG", UTG1: "UTG1", UTG2: "UTG2", MP: "MP", HJ: "HJ", CO: "CO", BTN: "BTN", SB: "SB", BB: "BB", "*": "任意" };
// 页面上任何 JS 错误都显示到策略树面板，方便远程排查
window.addEventListener('error', (e) => {
  const d = document.getElementById('treeDetail');
  if (d && e.message) d.innerHTML = '<b style="color:#ff6b35">JS 错误：' + e.message + '</b>（' + (e.lineno||'') + ' 行）';
});
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `请求失败 ${r.status}`);
  return data;
}

// ---------------- 状态 ----------------
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const st = s.stats;
    const eff = Math.max(0, (st.cards || 0) - (st.hidden_cards || 0));
    $("#hstats").innerHTML =
      `今日待复习 <b>${st.due}</b> · 卡片 <b>${eff}</b>`
      + ` · 手牌 <b>${st.hands}</b>`
      + (s.llm ? "" : ' · <span class="badge off">离线</span>');
    $("#modeBadge").textContent = s.llm ? `模型：${s.model}` : "未配置模型 · 点「⚙︎ 模型」";
    $("#modeBadge").className = "badge " + (s.llm ? "on" : "off");
    $("#modeBadge").style.cursor = "pointer";
    $("#modeBadge").onclick = openCfg;
  } catch (e) {
    $("#hstats").textContent = "无法连接后端";
  }
}

// ---------------- Tab（6 主 + 子标签） ----------------
// ══════════════════════════════════════════════════════════════
// Spot：唯一真源。所有「谁在打、什么底池、哪些范围」都从这里推导。
// 铁律：任何地方都不许再单独存 hero/villain/pot —— 只能读 Spot.derive()
// ══════════════════════════════════════════════════════════════
const Spot = (() => {
  const S = {
    tableType: "6-max",
    heroStack: "100bb",
    villainStack: "*",
    vsType: "*",
    vsType2: "*",
    street: "翻牌",
    board: [],
    seq: [],          // 翻前序列 [{pos, act, kind, pct}]
    version: 0,
  };

  const POS6 = ["UTG", "HJ", "CO", "BTN", "SB", "BB"];
  const POS8 = ["UTG", "UTG1", "UTG2", "HJ", "CO", "BTN", "SB", "BB"];
  const RAISE_ACTS = ["开池", "3bet", "4bet", "5bet 全下"];

  function positions() {
    return S.tableType.startsWith("8") ? POS8 : POS6;
  }

  // ── 纯函数：从序列推导一切 ──────────────────────────────
  function derive() {
    const seq = S.seq;
    const raisers = seq.filter((x) => RAISE_ACTS.includes(x.act));
    const alive = seq.filter((x) => x.act !== "弃牌");
    // 人数只算「还在牌局里的人」：UTG 开、HJ 3bet、CO 弃、UTG 跟，
    // 这是一个 3bet 底池，不是三人池 —— 弃牌的人不参与翻后。
    const alivePos = [...new Set(alive.map((x) => x.pos))];
    const players = [...new Set(seq.map((x) => x.pos))];
    const last = alive.length ? alive[alive.length - 1] : null;
    const opener = seq.find((x) => x.act === "开池") || null;

    // 底池类型只能由加注轮次推导，绝不允许外部单存
    const n = raisers.length;
    let pot = "SRP";
    if (n >= 3) pot = "4BP";
    else if (n === 2) pot = "3BP";
    if (alivePos.length >= 3) pot = n >= 2 ? "3BP多人" : "3人池";

    const hero = last ? last.pos
      : (positions().includes("BTN") ? "BTN" : positions()[0]);
    const villain = (opener && opener.pos !== hero) ? opener.pos
      : (alivePos.find((p) => p !== hero) || players.find((p) => p !== hero) || "BB");
    const iRaisedLast = last ? RAISE_ACTS.includes(last.act) : true;

    return {
      hero, villain, pot,
      opener: iRaisedLast ? "hero" : "villain",
      involved: alivePos.length ? alivePos : [hero, villain],
      villain2: alivePos.length >= 3 ? alivePos.filter((p) => p !== hero && p !== villain)[0] || "*" : "*",
      raises: n, players: alivePos.length,
      street: S.street,
      tableType: S.tableType,
      heroStack: S.heroStack,
      villainStack: S.villainStack,
      vsType: S.vsType,
      vsType2: S.vsType2,
      board: S.board,
      empty: seq.length === 0,
    };
  }

  // ── 把推导结果写回隐藏字段（兼容老接口）──────────────
  function apply() {
    const d = derive();
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
    set("treeHero", d.hero);
    set("treeVillain", d.villain);
    set("treeVillain2", d.villain2);
    set("treePot", d.pot);
    set("treeOpener", d.opener);
    set("treeVsType", d.vsType);
    set("treeVsType2", d.vsType2);
    set("treeStreet", d.street);
    const pe = document.getElementById("potAuto");
    if (pe) pe.textContent = d.empty
      ? "还没定动作，从下方添加第一步"
      : `${d.pot} · 我 ${d.hero} vs ${d.villain}` + (d.players >= 3 ? `（${d.players} 人池）` : "");
    const s2 = document.getElementById("stepOpp2");
    if (s2) s2.style.display = (d.pot === "3人池" || d.pot === "3BP多人") ? "" : "none";
    return d;
  }

  // ── 变更接口：只改 S，然后统一重绘 ──────────────────
  function bump(fn) {
    fn && fn(S);
    S.version++;
    return apply();
  }

  // 序列 → 给后端的编码：BTN:open>BB:call
  function seqCode(act) {
    const m = {
      "开池": "open", "3bet": "3bet", "4bet": "4bet",
      "5bet": "5bet", "5bet 全下": "5bet", "跟注": "call", "弃牌": "fold",
    };
    return m[String(act || "").trim()] || String(act || "").trim().toLowerCase();
  }
  function line() {
    return S.seq.map((x) => `${x.pos}:${seqCode(x.act)}`).join(">");
  }

  return {
    get state() { return S; },
    positions, derive, apply, bump, line,
    setTableType(v) { return bump((s) => { s.tableType = v; }); },
    setStacks(h, v) { return bump((s) => { s.heroStack = h; s.villainStack = v; }); },
    setVsType(t, t2) { return bump((s) => { s.vsType = t; s.vsType2 = t2; }); },
    setStreet(v) { return bump((s) => { s.street = v; }); },
    setBoard(b) { return bump((s) => { s.board = b; }); },
    addStep(step) { return bump((s) => { s.seq.push(step); }); },
    removeStep(i) { return bump((s) => { s.seq.splice(i, 1); }); },
    clearSeq() { return bump((s) => { s.seq = []; }); },
    nextActions() {
      // 基于「已经发生过几轮加注」决定动作名，同时永远允许跟注/弃牌，
      // 这样多个人可以在同一轮加注里各自动作（UTG 跟注、UTG1 弃牌都能表达）。
      const n = S.seq.filter((x) => RAISE_ACTS.includes(x.act)).length;
      const RAISE_NAME = ["开池", "3bet", "4bet", "5bet 全下", null];
      const out = [];
      if (n === 0) out.push("开池");
      else if (RAISE_NAME[n]) out.push(RAISE_NAME[n]);
      if (n >= 1) out.push("跟注");
      out.push("弃牌");
      return out;
    },
    kindOf(act) {
      const n = S.seq.filter((x) => RAISE_ACTS.includes(x.act)).length;
      if (act === "开池") return "open";
      if (act === "3bet") return "3bet";
      if (act === "4bet") return "4bet";
      if (act === "5bet 全下") return "5bet";
      if (act === "跟注") return n >= 3 ? "call4bet" : "call3bet";
      return "fold";
    },
    // 深链 / 分享：?pf=BTN:open>BB:call 直接还原一条翻前序列
    loadLine(text) {
      const map = {
        open: "开池", "3bet": "3bet", "4bet": "4bet", "5bet": "5bet 全下",
        call: "跟注", fold: "弃牌",
      };
      let raises = 0;
      const steps = [];
      String(text || "").split(">").forEach((chunk) => {
        const [p, a] = String(chunk || "").split(":");
        const pos = String(p || "").trim().toUpperCase();
        const act = map[String(a || "").trim().toLowerCase()];
        if (!pos || !act) return;
        let kind = "fold";
        if (act === "开池") { kind = "open"; raises += 1; }
        else if (act === "3bet") { kind = "3bet"; raises += 1; }
        else if (act === "4bet") { kind = "4bet"; raises += 1; }
        else if (act === "5bet 全下") { kind = "5bet"; raises += 1; }
        else if (act === "跟注") kind = raises >= 3 ? "call4bet" : (raises >= 2 ? "call3bet" : "call_open");
        steps.push({ pos, act, kind, pct: null });
      });
      if (!steps.length) return null;
      return bump((s) => { s.seq = steps; });
    },
  };
})();

function currentTab() {
  const el = document.querySelector(".tab.active");
  return el ? el.id.replace("tab-", "") : "";
}

function activateTab(name, push = true) {
  const btn = document.querySelector(`#tabs button[data-tab="${name}"]`);
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  const sec = $("#tab-" + name);
  if (sec) sec.classList.add("active");

  const parent = btn.dataset.parent || null;
  document.querySelectorAll("#tabs button:not(.sub)").forEach((b) => {
    b.classList.toggle("active", parent ? b.dataset.group === parent : b.dataset.tab === name);
  });
  renderSubbar(parent);
  if (push && location.hash !== "#" + name) history.replaceState(null, "", "#" + name);

  if (name === "cards") loadCards();
  if (name === "plan") loadPlan();
  if (name === "progress") loadProgress();
  if (name === "post") { if ($("#tab-post")) { loadFilterOptions(); loadPresets(); loadPost(); } }
  if (name === "mine") { loadPersonalScenes(); }
  if (name === "rules") loadRules();
  if (name === "ptypes") loadPTypes();
  if (name === "library" && $("#tab-library")) loadLibrary();
  if (name === "campaign") loadCampaign();
  if (name === "sim" && !simState.id) { loadSimTypes(); newHand(); }
  if (name === "review") { loadHands(); loadLeaks(); loadRange(currentPos); loadMismatch(); loadEval(); loadUploads(); }
  if (name === "tree") loadTree().catch((e) => {
    const d = document.getElementById("treeDetail");
    if (d) d.innerHTML = '<b style="color:#ff6b35">策略树出错：' + e.message + '</b>';
    console.error(e);
  });
}

function renderSubbar(parent) {
  const bar = $("#subbar");
  if (!bar) return;
  bar.innerHTML = "";
  if (!parent) return;
  const cur = currentTab();
  document.querySelectorAll(`#tabs button.sub[data-parent="${parent}"]`).forEach((b) => {
    const e = document.createElement("button");
    e.textContent = b.textContent;
    if (b.dataset.tab === cur) e.classList.add("on");
    e.onclick = () => activateTab(b.dataset.tab);
    bar.appendChild(e);
  });
}

document.querySelectorAll("#tabs button").forEach((b) => {
  b.onclick = () => {
    if (b.dataset.group) activateTab(b.dataset.first);
    else activateTab(b.dataset.tab);
  };
});

// ---------------- 模型设置 ----------------
async function openCfg() {
  const dlg = $("#cfgDlg");
  try {
    const c = await api("/api/config");
    $("#cfgKey").value = "";
    $("#cfgKey").placeholder = c.configured ? `已配置 ${c.key_tail}（留空则不修改）` : "sk-…";
    $("#cfgModel").value = c.model || "";
    $("#cfgBase").value = c.base_url || "";
    $("#cfgMsg").textContent = c.configured ? "当前：已配置" : "当前：未配置（离线检索模式）";
    $("#cfgMsg").className = "badge " + (c.configured ? "on" : "off");
  } catch (e) {
    $("#cfgMsg").textContent = e.message;
  }
  dlg.showModal();
}

{ const _e = $("#cfgBtn"); if (_e) _e.onclick = openCfg; }
{ const _e = $("#cfgClose"); if (_e) _e.onclick = () => $("#cfgDlg").close(); }
{ const _e = $("#cfgSave"); if (_e) _e.onclick = async () => {
  const body = { model: $("#cfgModel").value.trim(), base_url: $("#cfgBase").value.trim() };
  const k = $("#cfgKey").value.trim();
  if (k) body.api_key = k;
  try {
    const c = await api("/api/config", body);
    $("#cfgMsg").textContent = c.configured ? `已保存 ${c.key_tail}，可以直接提问了` : "已保存（但没有 Key）";
    $("#cfgMsg").className = "badge " + (c.configured ? "on" : "off");
    await refreshStatus();
    setTimeout(() => $("#cfgDlg").close(), 1200);
  } catch (e) {
    $("#cfgMsg").textContent = e.message;
    $("#cfgMsg").className = "badge off";
  }
} }
{ const _e = $("#cfgClear"); if (_e) _e.onclick = async () => {
  try {
    await api("/api/config", { clear_key: true });
    $("#cfgMsg").textContent = "已清除 Key，回到离线模式";
    $("#cfgMsg").className = "badge off";
    await refreshStatus();
  } catch (e) {
    $("#cfgMsg").textContent = e.message;
  }
} }

// ---------------- 问答 ----------------
function renderMath(math) {
  if (!math) return "";
  let h = '<div class="panel" style="margin:14px 0 0;background:var(--panel2)"><h2>自动计算</h2>';
  if (math.equity) {
    const e = math.equity;
    h += `<div class="big">${e.equity_pct}%<small>${esc(e.hero)} vs ${esc(e.villain)}${e.board ? " · " + esc(e.board) : " · 翻前"}</small></div>
      <div class="bar"><i style="width:${e.equity_pct}%"></i></div>
      <dl class="kv"><dt>赢 / 平 / 输</dt><dd>${e.win_pct}% / ${e.tie_pct}% / ${e.loss_pct}%</dd>
      <dt>方式</dt><dd>${e.exact ? "精确枚举" : `蒙特卡洛 ${e.samples.toLocaleString()} 次${e.stderr_pct ? `（±${e.stderr_pct}%）` : ""}`}</dd></dl>`;
  }
  if (math.odds) {
    const o = math.odds;
    h += `<dl class="kv"><dt>需要胜率</dt><dd>${o.required_equity_pct}%</dd>
      <dt>最低防守频率</dt><dd>${o.mdf_pct}%</dd>
      <dt>诈唬盈亏平衡弃牌率</dt><dd>${o.alpha_pct}%</dd>
      ${o.ev_call !== undefined ? `<dt>跟注 EV</dt><dd>${o.ev_call > 0 ? "+" : ""}${o.ev_call}</dd>` : ""}</dl>`;
  }
  if (math.equity_error) h += `<div class="muted">算牌时出错：${esc(math.equity_error)}</div>`;
  return h + "</div>";
}

{ const _e = $("#askBtn"); if (_e) _e.onclick = async () => {
  const q = $("#q").value.trim();
  if (!q) return;
  const btn = $("#askBtn");
  btn.disabled = true;
  btn.textContent = "思考中…";
  try {
    const d = await api("/api/ask", { q, k: Number($("#askK").value) });
    $("#answer").classList.remove("hidden");
    $("#answerText").textContent = d.answer || "";
    $("#mathBox").innerHTML = renderMath(d.math);
    $("#sources").innerHTML = (d.sources || [])
      .map(
        (s, i) => `<div class="src">
          <div class="src-h"><span class="t">[${i + 1}] ${esc(s.title)}${s.heading ? " / " + esc(s.heading) : ""}${s.time ? " @" + s.time : ""}</span>
          <span class="score">${s.score}</span></div>
          <p>${esc(s.preview)}</p></div>`
      )
      .join("");
    $("#promptWrap").classList.toggle("hidden", d.mode === "llm");
    $("#promptBox").textContent = d.prompt || "";
    if (d.mode === "error") $("#modeBadge").textContent = "模型调用失败：" + d.error;
  } catch (e) {
    $("#answer").classList.remove("hidden");
    $("#answerText").textContent = "出错：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "提问";
  }
} }

// ---------------- 胜率 ----------------
{ const _e = $("#eqBtn"); if (_e) _e.onclick = async () => {
  const btn = $("#eqBtn");
  btn.disabled = true;
  btn.textContent = "计算中…";
  try {
    const d = await api("/api/equity", {
      hero: $("#eqHero").value.trim(),
      villain: $("#eqVillain").value.trim(),
      board: $("#eqBoard").value.trim(),
      n: 40000,
    });
    const box = $("#eqOut");
    if (d.multiway) {
      const m = d.multiway;
      box.innerHTML =
        `<div class="big">${m.equity_pct}%<small>主位胜率</small></div>` +
        `<dl class="kv">${m.multiway_pct.map((x, i) => `<dt>第 ${i + 1} 家</dt><dd>${x}%</dd>`).join("")}</dl>`;
      return;
    }
    const e = d.equity;
    box.innerHTML = `
      <div class="big">${e.equity_pct}%<small>${e.board || "翻前"} 胜率</small></div>
      <div class="bar"><i style="width:${e.equity_pct}%"></i></div>
      <dl class="kv">
        <dt>赢 / 平 / 输</dt><dd>${e.win_pct}% / ${e.tie_pct}% / ${e.loss_pct}%</dd>
        <dt>方式</dt><dd>${e.exact ? "精确枚举" : `蒙特卡洛 ${e.samples.toLocaleString()} 次${e.stderr_pct ? `（±${e.stderr_pct}%）` : ""}`}</dd>
      </dl>`;
  } catch (e) {
    $("#eqOut").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "计算";
  }
} }

// ---------------- 赔率 ----------------
{ const _e = $("#odBtn"); if (_e) _e.onclick = async () => {
  try {
    const d = await api("/api/odds", {
      pot: $("#odPot").value,
      bet: $("#odBet").value,
      equity: $("#odEq").value,
    });
    const o = d.odds;
    let h = `<dl class="kv">
      <dt>需要胜率</dt><dd>${o.required_equity_pct}%</dd>
      <dt>底池赔率</dt><dd>${o.pot_odds} : 1</dd>
      <dt>最低防守频率</dt><dd>${o.mdf_pct}%</dd>
      <dt>对手诈唬的盈亏平衡弃牌率</dt><dd>${o.alpha_pct}%</dd>`;
    if (o.ev_call !== undefined) {
      h += `<dt>跟注 EV</dt><dd>${o.ev_call > 0 ? "+" : ""}${o.ev_call}</dd><dt>边际</dt><dd>${o.edge_pct > 0 ? "+" : ""}${o.edge_pct}%</dd></dl>
        <div class="verdict ${o.ev_call > 0 ? "pos" : "neg"}">${o.verdict}</div>`;
    } else {
      h += `</dl>`;
    }
    $("#odOut").innerHTML = h;
  } catch (e) {
    $("#odOut").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
} }

// ---------------- 漏洞 ----------------
async function loadLeaks() {
  try {
    const d = await api("/api/leaks");
    if (!d.hands) {
      $("#leakMeta").textContent = "还没有手牌";
      $("#leakBox").innerHTML = '<div class="empty">把 GG 的手牌 txt 放到 data/hh/raw，运行 python run.py hh</div>';
      return;
    }
    $("#leakMeta").textContent = `${d.hands.toLocaleString()} 手 · ${d.winrate_bb100 > 0 ? "+" : ""}${d.winrate_bb100} bb/100`;
    const ms = d.metrics || [];
    const bad = ms.filter((m) => m.verdict !== "正常" && m.enough);
    const thin = ms.filter((m) => m.verdict === "正常" && !m.enough);

    $("#leakBox").innerHTML = `
      <div class="muted" style="margin-bottom:8px">
        共 ${ms.length} 个指标，${bad.length} 个偏离标准，${ms.filter((m) => m.enough).length} 个样本充足。
        <span class="dim">样本不足的判定仅供参考。</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="color:#8a929c;text-align:left">
          <th style="padding:6px">指标</th><th style="text-align:right">我的</th>
          <th style="text-align:right">标准</th><th style="text-align:right">偏差</th>
          <th style="text-align:right">样本</th><th>判定</th>
        </tr></thead>
        <tbody>${ms.map((m) => {
          const ok = m.verdict === "正常";
          const color = ok ? "#3ba55d" : (m.enough ? "#c96" : "#8a929c");
          const bar = ok ? 0 : Math.min(100, Math.abs(m.gap) * 4);
          return `<tr style="border-top:1px solid #1e242c">
            <td style="padding:6px">${esc(m.label)}</td>
            <td style="text-align:right;font-weight:600;color:${color}">${m.value}%</td>
            <td style="text-align:right;color:#8a929c">${m.lo}~${m.hi}%</td>
            <td style="text-align:right;color:${color}">${ok ? "—" : (m.gap > 0 ? "+" : "") + m.gap}</td>
            <td style="text-align:right;color:#8a929c">${m.samples.toLocaleString()}</td>
            <td style="color:${color}">${ok ? "正常" : m.verdict + (m.enough ? "" : "（样本少）")}
              ${ok ? "" : `<span style="display:inline-block;width:${bar}px;height:3px;background:${color};margin-left:6px;vertical-align:middle;max-width:60px"></span>`}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>
      ${bad.length ? `<div class="muted" style="margin-top:10px">
        最该先修的顺序：<b>${bad.slice(0, 3).map((m) => m.label).join(" → ")}</b>
      </div>` : ""}
      ${d.priority_topics && d.priority_topics.length ? `<div class="muted" style="margin-top:6px">
        已按这些漏洞给学习路径加权：${esc(d.priority_topics.join(" · "))}
      </div>` : ""}`;
    const btn = $("#toPath");
    if (btn)
      btn.onclick = () => {
        document.querySelector('#tabs button[data-tab="plan"]').click();
      };
  } catch (e) {
    $("#leakMeta").textContent = "";
    $("#leakBox").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

// ---------------- 范围矩阵 ----------------
let currentPos = "BTN";

document.querySelectorAll("#posTabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#posTabs button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    currentPos = b.dataset.pos;
    loadRange(currentPos);
  };
});

function cellClass(c) {
  if (c.ref && c.pct !== null && c.pct >= 70) return "g-good";
  if (c.ref && (c.pct === null || c.pct <= 30)) return "g-miss";
  if (c.ref) return "g-mid";
  if (c.pct !== null && c.pct >= 50) return "g-extra";
  return "g-none";
}

async function loadRange(pos) {
  try {
    const d = await api("/api/range?pos=" + pos);
    if (!d.matrix || !d.matrix.length) {
      $("#rangeGrid").innerHTML = '<div class="empty">还没有手牌数据。</div>';
      $("#rangeMeta").textContent = "";
      return;
    }
    $("#rangeMeta").textContent = `实际 ${d.open_pct}% · 基准 ${d.reference_pct}% · 漏 ${d.missing_count} 类 · 多 ${d.extra_count} 类`;
    $("#rangeGrid").innerHTML = d.matrix
      .map((row) => row.map((c) => `<div class="rcell ${cellClass(c)}" title="${c.hand} 发到${c.n}次 开${c.open}次">${c.hand}</div>`).join(""))
      .join("");
    const miss = d.missing.slice(0, 10).map((c) => c.hand);
    const extra = d.extra.slice(0, 6).map((c) => `${c.hand}(${c.pct}%)`);
    $("#rangeNote").innerHTML = `
      <span class="lg g-miss"></span>该开没开　<span class="lg g-mid"></span>开得不够　
      <span class="lg g-good"></span>正常　<span class="lg g-extra"></span>开得过多<br>
      ${miss.length ? `漏开：<b>${miss.join("、")}</b>` : "没有明显漏开的手牌。"}
      ${extra.length ? `<br>多开：${extra.join("、")}` : ""}`;
  } catch (e) {
    $("#rangeGrid").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

// ---------------- 复盘 ----------------
function handPayload() {
  return {
    stake: $("#hStake").value,
    position: $("#hPos").value,
    pot: $("#hPot").value,
    hero: $("#hHero").value,
    villain: $("#hVillain").value,
    board: $("#hBoard").value,
    action: $("#hAction").value,
    notes: $("#hNotes").value,
    tags: "",
  };
}

function handToQuestion(h) {
  return [
    `复盘这手牌：级别 ${h.stake || "?"}，位置 ${h.position || "?"}，手牌 ${h.hero || "?"}`,
    h.villain ? `对手 ${h.villain}` : "",
    h.board ? `牌面 ${h.board}` : "",
    h.pot ? `底池 ${h.pot}` : "",
    h.action ? `行动线：${h.action}` : "",
    h.notes ? `我的想法：${h.notes}` : "",
    "请按我的笔记判断哪条街错了、错在哪、下次怎么做。",
  ]
    .filter(Boolean)
    .join("\n");
}

{ const _e = $("#handBtn"); if (_e) _e.onclick = async () => {
  try {
    const d = await api("/api/hands", handPayload());
    $("#handMsg").textContent = "已保存 #" + d.id;
    $("#handMsg").className = "badge on";
    loadHands();
  } catch (e) {
    $("#handMsg").textContent = e.message;
    $("#handMsg").className = "badge off";
  }
} }

{ const _e = $("#handAsk"); if (_e) _e.onclick = async () => {
  const p = handPayload();
  await api("/api/hands", p).catch(() => {});
  $("#q").value = handToQuestion(p);
  document.querySelector('#tabs button[data-tab="ask"]').click();
  $("#askBtn").click();
} }



// ---------------- 总体评估 ----------------
async function loadEval() {
  const box = document.getElementById("evalBox");
  if (!box) return;
  try {
    const d = await api("/api/evaluate");
    const meta = document.getElementById("evalMeta");
    const gradeColor = { A: "#3ba55d", B: "#8bc34a", C: "#e0a526", D: "#c96" }[d.grade] || "#8a929c";
    if (meta) meta.textContent = `${d.hands.toLocaleString()} 手 · ${d.winrate_bb100 > 0 ? "+" : ""}${d.winrate_bb100} bb/100`;
    const part = (label, v) => v == null
      ? `<div class="muted">${label} —</div>`
      : `<div><div class="big" style="font-size:20px">${v}</div><div class="muted" style="font-size:11.5px">${label}</div></div>`;
    box.innerHTML = `
      <div class="row" style="gap:26px;margin-top:0;align-items:center">
        <div style="text-align:center">
          <div style="font-size:44px;font-weight:700;color:${gradeColor};line-height:1">${d.grade}</div>
          <div class="muted" style="font-size:12px">${d.overall} 分</div>
        </div>
        <div style="flex:1;min-width:240px">
          <div style="font-size:14px">${esc(d.verdict)}</div>
          ${d.note ? `<div class="muted" style="font-size:12px;margin-top:4px">${esc(d.note)}</div>` : ""}
        </div>
        ${part("指标得分", d.parts["指标得分"])}
        ${part("策略树一致性", d.parts["策略树一致性"])}
        ${part("翻前纪律", d.parts["翻前纪律"])}
      </div>
      <div style="margin-top:14px">
        <b style="font-size:13.5px">最该先修的 ${d.todo.length} 件事</b>
        <div class="list" style="margin-top:6px">
          ${d.todo.map((t, i) => `<div class="item">
            <div style="display:flex;gap:8px"><b style="color:${gradeColor}">${i + 1}</b>
              <span>[${esc(t.kind)}] ${esc(t.name)}</span></div>
            <div class="muted" style="font-size:12.5px">${esc(t.detail)}</div>
          </div>`).join("")}
        </div>
      </div>
      <div style="margin-top:14px">
        <button class="primary" id="autoPlanBtn">按评估重排学习路径</button>
        <span class="badge" id="autoPlanMsg"></span>
      </div>
      <div id="autoPlanBox" style="margin-top:10px"></div>
      ${d.strengths.length ? `<div class="muted" style="margin-top:10px;font-size:12.5px">
        <b style="color:#3ba55d">已验证的优势</b> ${d.strengths.map(esc).join(" · ")}</div>` : ""}`;
    const ab = document.getElementById("autoPlanBtn");
    if (ab) ab.onclick = () => loadAutoPlan();
  } catch (e) {
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function loadAutoPlan() {
  const box = document.getElementById("autoPlanBox");
  const msg = document.getElementById("autoPlanMsg");
  if (!box) return;
  if (msg) msg.textContent = "按当前漏洞重排中…";
  try {
    const d = await api("/api/plan-auto?minutes=25");
    if (msg) msg.textContent = `评分 ${d.score} / ${d.grade}`;
    box.innerHTML = `
      <div class="muted" style="font-size:12.5px;margin-bottom:6px">${esc(d.note)}</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="color:#8a929c;text-align:left">
          <th style="padding:4px">优先</th><th>主题</th><th style="text-align:right">权重</th><th>为什么</th>
        </tr></thead>
        <tbody>${d.focus.map((f, i) => `<tr style="border-top:1px solid #1e242c">
          <td style="padding:5px"><b style="color:${i === 0 ? "#c96" : "#8a929c"}">${i + 1}</b></td>
          <td style="padding:5px"><b>${esc(f.topic)}</b></td>
          <td style="text-align:right;padding:5px">${f.weight}</td>
          <td class="muted" style="padding:5px;font-size:12px">${f.reasons.slice(0, 2).map(esc).join("<br>")}</td>
        </tr>`).join("")}</tbody>
      </table>
      <div class="muted" style="margin-top:8px;font-size:12.5px">
        今日安排：复习 ${d.split.cards} 分钟（${d.cards.length} 张卡）· 精读 ${d.split.reading} 分钟
      </div>
      <div class="list" style="margin-top:8px">
        ${d.cards.slice(0, 5).map((c) => `<div class="item" style="font-size:12.5px">${esc((c.front || "").slice(0, 60))}</div>`).join("")}
      </div>`;
  } catch (e) {
    if (msg) msg.textContent = "";
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

// ---------------- 导入牌谱 ----------------
async function loadUploads() {
  const box = document.getElementById("upList");
  if (!box) return;
  try {
    const d = await api("/api/uploads");
    const meta = document.getElementById("uploadMeta");
    if (meta) meta.textContent = d.uploads.length ? `已导入 ${d.uploads.length} 次` : "还没导入过";
    box.innerHTML = d.uploads.length
      ? d.uploads.map((u) => `<div class="item" style="font-size:12.5px">
          <b>${esc(u.platform || "?")}</b> · ${esc(u.stakes || "?")}
          ${u.period_from || u.period_to ? ` · ${esc(u.period_from || "")}~${esc(u.period_to || "")}` : ""}
          <span class="muted"> · ${u.hands} 手 · ${esc(u.created.slice(0, 16))}</span>
        </div>`).join("")
      : '<div class="empty">还没有导入记录。</div>';
  } catch (e) {
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

document.getElementById("upBtn") && (document.getElementById("upBtn").onclick = async () => {
  const f = document.getElementById("upFile").files[0];
  const msg = document.getElementById("upMsg");
  if (!f) { msg.textContent = "先选文件"; return; }
  msg.textContent = "读取中…";
  const text = await f.text();
  if (!text.trim()) { msg.textContent = "文件是空的"; return; }
  msg.textContent = `上传 ${(text.length / 1048576).toFixed(1)}MB，解析中…`;
  try {
    const r = await api("/api/upload-hh", {
      platform: document.getElementById("upPlatform").value,
      stakes: document.getElementById("upStakes").value,
      period_from: document.getElementById("upFrom").value,
      period_to: document.getElementById("upTo").value,
      filename: f.name,
      text,
    });
    msg.textContent = `✅ 共 ${r.hands_total.toLocaleString()} 手 · ${r.spots.toLocaleString()} 个决策点`;
    loadUploads(); loadEval(); loadLeaks();
  } catch (e) {
    msg.textContent = "失败：" + e.message;
  }
});

async function loadMismatch() {
  const box = document.getElementById("mmBox");
  if (!box) return;
  try {
    const d = await api("/api/tree-mismatch?min_n=10");
    const meta = document.getElementById("mmMeta");
    if (meta) meta.textContent = `${d.total_spots.toLocaleString()} 个决策点 · ${d.nodes.length} 个节点`;
    if (!d.nodes.length) {
      box.innerHTML = '<div class="empty">还没有足够的样本对照策略树。</div>';
      return;
    }
    box.innerHTML = d.nodes.slice(0, 12).map((n) => {
      const color = n.rate >= 30 ? "#c96" : n.rate >= 20 ? "#e0a526" : "#8a929c";
      const ex = (n.examples || []).map((e) =>
        `<div class="muted" style="font-size:12px">${esc(e.matchup)} ${esc(e.board)} · ${esc(e.hand)} · 你${esc(e.action)}（树：${esc(e.should)}）</div>`
      ).join("");
      return `<div class="item">
        <div style="display:flex;gap:10px;align-items:center">
          <b style="color:${color};font-size:15px">${n.rate}%</b>
          <span>${esc(n.pot)} · ${esc(n.street)} · ${esc(n.role)}</span>
          <span class="spacer" style="flex:1"></span>
          <span class="muted">错 ${n.bad}/${n.n} · 规则 ${esc(n.rule)}</span>
        </div>
        <div class="muted" style="font-size:12.5px">
          该打没打 <b>${n.miss_bet}</b> ｜ 不该打却打 <b>${n.over_bet}</b>
        </div>
        ${ex}
      </div>`;
    }).join("");
  } catch (e) {
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function loadPersonalScenes() {
  const box = document.getElementById("personalScenes");
  if (!box) return;
  try {
    const d = await api("/api/practice");
    const list = d.personal || [];
    if (!list.length) {
      box.innerHTML = '<div class="empty">还没有可用的真实牌局题。导入 hh 并跑一次 ingest 就会生成。</div>';
      return;
    }
    const total = list.reduce((a, x) => a + x.n, 0);
    const meta = document.getElementById("personalMeta");
    if (meta) meta.textContent = `${total} 道 · 仅你可见`;
    box.innerHTML = list
      .map((x, i) => `<div class="item" style="display:flex;align-items:center;gap:10px">
        <span style="flex:1">${esc(x.scene.replace("真实牌局：", ""))}</span>
        <span class="muted">${x.n} 题</span>
        <button class="mini-btn" data-pscene="${i}">练</button>
      </div>`)
      .join("");
    box.querySelectorAll("[data-pscene]").forEach((b) => {
      b.onclick = () => startScene(list[Number(b.dataset.pscene)].scene);
    });
  } catch (e) {
    box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function loadHands() {
  const box = document.getElementById("recentHands");
  if (!box) return;                       // 不在复盘页就跳过，别写坏别的容器
  try {
    const d = await api("/api/hands");
    const rows = (d.hands || []).filter((h) => (h.hero || h.board || h.action || h.notes || "").trim());
    if (!rows.length) {
      box.innerHTML = '<div class="empty">还没有记录。打完一场，把最难受的 3 手记下来。</div>';
      return;
    }
    box.innerHTML = rows
      .map(
        (h) => `<div class="item">
          <div><b>${esc(h.hero || "?")}</b>${h.board ? " · " + esc(h.board) : ""}${h.position ? " · " + esc(h.position) : ""}${h.stake ? " · " + esc(h.stake) : ""}</div>
          <div class="muted">${esc(h.action || "")}</div>
          ${h.notes ? `<div class="muted">想法：${esc(h.notes)}</div>` : ""}
        </div>`
      )
      .join("");
  } catch (e) {
    box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// ---------------- 规则审核 ----------------
const STREET_CN2 = { flop: "翻牌", turn: "转牌", river: "河牌" };

async function loadRules() {
  const q = new URLSearchParams();
  if ($("#rulePot") && $("#rulePot").value) q.set("pot", $("#rulePot").value);
  if ($("#ruleStreet").value) q.set("street", $("#ruleStreet").value);
  if ($("#ruleRole").value) q.set("role", $("#ruleRole").value);
  try {
    const d = await api("/api/rules?" + q.toString());
    const c = d.counts || {};
    $("#ruleCount").textContent =
      `${c.total || 0} 条 · 生效 ${c.active || 0} · 并存 ${c.hold || 0} · 归档 ${c.retired || 0}（其中推导 ${c.derived || 0}）`;
    if (!d.rules.length) {
      $("#ruleList").innerHTML = '<div class="empty">这个筛选下没有规则。</div>';
      return;
    }
    const CONF = { 高: "#3ba55d", 中: "#e0a526", 低: "#8a929c" };
    $("#ruleList").innerHTML = d.rules
      .map((r) => {
        const chips = [r.pot, r.street, r.role,
          r.board !== "*" ? r.board : "",
          r.action,
          r.runout !== "*" ? `变化:${r.runout}` : "",
          r.capped !== "*" ? `对手${r.capped === "是" ? "封顶" : "未封顶"}` : "",
          r.vs_type !== "*" ? `对手:${r.vs_type}` : ""].filter(Boolean);
        const statusTxt = r.status === "hold" ? '<span class="chip" style="background:#4a3a12;color:#e0a526">并存</span>'
          : r.status === "retired" ? '<span class="chip" style="background:#3a1f1f;color:#c96">已归档</span>' : "";
        const derived = r.source === "推导"
          ? '<span class="chip" style="background:#2b2b2b;color:#8a929c">⚠ 推导</span>' : "";
        return `<div class="rule-card" data-rule="${esc(r.id)}">
          <div class="rhead">
            <b style="margin-right:8px">${esc(r.id)}</b>
            <span class="conds">${chips.map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</span>
            <span class="spacer"></span>${derived}${statusTxt}
            <span class="chip" style="background:transparent;color:${CONF[r.conf] || "#8a929c"}">${esc(r.conf)}信</span>
          </div>
          <div class="rbody">
            <div><b>尺度</b> ${esc(r.sizing)}　<b>频率</b> ${esc(r.freq)}</div>
            ${r.note ? `<div class="muted">${esc(r.note)}</div>` : ""}
            <div class="rsrc"><span class="muted">来源</span> ${esc(r.source)}</div>
          </div>
        </div>`;
      })
      .join("");
    const byId = {};
    d.rules.forEach((r) => (byId[r.id] = r));
    $("#ruleList").querySelectorAll(".rule-card").forEach((card) => {
      card.onclick = () => openInTree(byId[card.dataset.rule]);
    });
  } catch (e) {
    $("#ruleList").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

function openInTree(r) {
  if (!r) return;
  document.querySelector('#tabs button[data-tab="tree"]').click();
  const set = (id, v) => { const el = document.getElementById(id); if (el && v) el.value = v; };
  set("treePot", r.pot);
  set("treeStreet", r.street);
  set("treeAction", r.action);
  loadTree();
}

{ const _e = $("#rulePot"); if (_e) _e.onchange = loadRules; }
{ const _e = $("#ruleStreet"); if (_e) _e.onchange = loadRules; }
{ const _e = $("#ruleRole"); if (_e) _e.onchange = loadRules; }

function bindRuleCard(card) {
  const id = Number(card.dataset.id);
  card.querySelector('[data-act="edit"]').onclick = () => openRuleEditor(card, id);
  card.querySelector('[data-act="toggle"]').onclick = async () => {
    const isOn = !card.classList.contains("off");
    await api("/api/rules/update", { id, fields: { enabled: isOn ? 0 : 1 } });
    loadRules();
  };
  card.querySelector('[data-act="del"]').onclick = async () => {
    if (!confirm("删除这条规则？")) return;
    await api("/api/rules/delete", { id });
    loadRules();
  };
  const link = card.querySelector("[data-chunk]");
  if (link && Number(link.dataset.chunk)) link.onclick = () => openChunk(Number(link.dataset.chunk));
}

function openRuleEditor(card, id) {
  if (card.querySelector(".redit")) return;
  const body = card.querySelector(".rbody");
  const cur = [...body.querySelectorAll("div")].map((d) => d.textContent).join("\n");
  body.innerHTML = `
    <div class="redit">
      <label>频率 <input id="rf" value=""></label>
      <label>尺度 <input id="rs" value=""></label>
      <label>原理 <input id="rw" value=""></label>
      <label>常见错误 <input id="ra" value=""></label>
      <div class="row"><button class="primary" id="rsave">保存</button>
        <button id="rcancel">取消</button></div>
    </div>`;
  const r = card._rule;
  body.querySelector("#rf").value = r.freq || "";
  body.querySelector("#rs").value = r.size || "";
  body.querySelector("#rw").value = r.why || "";
  body.querySelector("#ra").value = r.avoid || "";
  body.querySelector("#rcancel").onclick = () => loadRules();
  body.querySelector("#rsave").onclick = async () => {
    await api("/api/rules/update", {
      id,
      fields: {
        freq: body.querySelector("#rf").value,
        size: body.querySelector("#rs").value,
        why: body.querySelector("#rw").value,
        avoid: body.querySelector("#ra").value,
      },
    });
    loadRules();
  };
}

// ---------------- 知识库 ----------------
async function loadLibrary() {
  if (!$("#tab-library")) return;
  try {
    const d = await api("/api/library");
    $("#zoneGrid").innerHTML = d.zones
      .map(
        (z) => `<div class="zone" data-tab="${z.tabs[0]}">
          <div class="zname">${esc(z.name)}</div>
          <div class="zdesc">${esc(z.desc)}</div>
          <div class="zgo">→</div>
        </div>`
      )
      .join("");
    $("#zoneGrid").querySelectorAll(".zone").forEach((z) => {
      z.onclick = () => document.querySelector(`#tabs button[data-tab="${z.dataset.tab}"]`).click();
    });

    $("#libSummary").innerHTML = `<div style="white-space:pre-wrap">${esc(d.summary).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")}</div>`;

    $("#libOutline").innerHTML = d.outline
      .map(
        (b) => `<details class="zone-block" open>
          <summary><b>${esc(b.zone)}</b> <span class="muted">${esc(b.desc)}</span></summary>
          ${b.concepts
            .map(
              (c, i) => `<div class="concept">
                <div class="cname">${esc(c.name)}</div>
                <div class="clinks">${(c.hits || [])
                  .map(
                    (h) => `<button class="link" data-chunk="${h.chunk_id}">《${esc(h.title.slice(0, 26))}》${esc(h.heading || "")}</button>`
                  )
                  .join("")}</div>
                <div class="cbtns">
                  <button class="mini-btn" data-review="${esc(c.topic)}">复习</button>
                  <button class="mini-btn" data-practice="${c.level}">练习</button>
                </div>
              </div>`
            )
            .join("")}
        </details>`
      )
      .join("");

    $("#libOutline").querySelectorAll("[data-chunk]").forEach((b) => {
      b.onclick = () => openChunk(Number(b.dataset.chunk));
    });
    $("#libOutline").querySelectorAll("[data-review]").forEach((b) => {
      b.onclick = () => {
        document.querySelector('#tabs button[data-tab="cards"]').click();
        const sel = $("#cardTopic");
        if (sel) {
          sel.value = b.dataset.review;
          sel.onchange && sel.onchange();
        }
      };
    });
    $("#libOutline").querySelectorAll("[data-practice]").forEach((b) => {
      b.onclick = () => {
        document.querySelector('#tabs button[data-tab="campaign"]').click();
        setTimeout(() => startLevel(Number(b.dataset.practice)), 300);
      };
    });
  } catch (e) {
    $("#libOutline").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function openChunk(id) {
  try {
    const d = await api("/api/chunk?id=" + id);
    const c = d.chunk;
    $("#readTitle").textContent = c.title;
    $("#readMeta").textContent = c.heading || "";
    $("#readBody").textContent = c.text;
    $("#readNotion").innerHTML = c.notion_url
      ? `<a href="${c.notion_url}" target="_blank" rel="noopener" style="color:var(--green)">在 Notion 中打开 →</a>`
      : "";
    $("#reader").showModal();
  } catch (e) {
    alert(e.message);
  }
}

// ---------------- 模拟牌桌 ----------------
let simState = { id: null, history: [] };
const SUIT_SYM = { s: "♠", h: "♥", d: "♦", c: "♣" };

function cardHtml(c) {
  const rank = "23456789TJQKA"[Math.floor(c / 4)];
  const suit = "shdc"[c % 4];
  const red = suit === "h" || suit === "d";
  return `<span class="card ${red ? "red" : ""}">${rank}<i>${SUIT_SYM[suit]}</i></span>`;
}

const STREET_CN = { flop: "翻牌", turn: "转牌", river: "河牌" };

function renderTable(st) {
  const facing = st.facing || 0;
  const prompt = facing
    ? `对手 ${st.villain_pos} 下注 ${facing.toFixed(1)}（${Math.round((facing / st.pot) * 100)}% 池）→ 轮到你`
    : `对手 ${st.villain_pos} 过牌 → 轮到你`;
  $("#simTable").innerHTML = `
    <div class="tbl-top">
      <span class="street">${STREET_CN[st.street] || st.street}</span>
      <span>底池 <b>${st.pot.toFixed(1)}</b></span>
      <span>有效筹码 ${st.stack.toFixed(0)}</span>
      <span>你 ${esc(st.hero_pos)} · 对手 ${esc(st.villain_pos)}</span>
    </div>
    <div class="prompt">${esc(prompt)}</div>
    <div class="tbl-board">${st.board.map(cardHtml).join("")}</div>
    <div class="tbl-bottom">
      <div class="hero-cards">${st.hero.map(cardHtml).join("")}<span class="lbl">你的手牌</span></div>
      <div class="eq">胜率 ${st.equity.equity_pct}%<span class="muted"> vs 对手范围</span></div>
    </div>`;
  renderActions(st);
  renderHistory();
}

function renderActions(st) {
  const facing = st.facing || 0;
  const btns = [];
  if (facing > 0) {
    btns.push(`<button data-act="fold">弃牌</button>`);
    btns.push(`<button class="primary" data-act="call">跟注 ${facing.toFixed(1)}</button>`);
    btns.push(`<button data-act="raise" data-amt="2.5">加注到 ${(facing * 2.5).toFixed(1)}</button>`);
  } else {
    btns.push(`<button data-act="check">过牌</button>`);
    btns.push(`<button class="primary" data-act="bet" data-amt="0.33">下注 1/3（${(st.pot / 3).toFixed(1)}）</button>`);
    btns.push(`<button data-act="bet" data-amt="0.66">下注 2/3（${((st.pot * 2) / 3).toFixed(1)}）</button>`);
    btns.push(`<button data-act="bet" data-amt="1">下注满池（${st.pot.toFixed(1)}）</button>`);
  }
  $("#simActions").innerHTML = btns.join("");
  $("#simActions").querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = () => doAction(b.dataset.act, Number(b.dataset.amt || 0), b.textContent);
  });
}

function renderHistory(history) {
  const h = history || simState.history || [];
  if (!h.length) {
    $("#simHistory").innerHTML = "";
    return;
  }
  const cn = { flop: "翻牌", turn: "转牌", river: "河牌" };
  $("#simHistory").innerHTML =
    '<div class="hist-h">这一手的经过</div>' +
    h.map(
      (x) => `<div class="hist-row"><b>${cn[x.street] || x.street}</b>　${esc(x.opp)} →
        <span class="you">你 ${esc(x.hero)}</span></div>`
    ).join("");
}

let simTypes = [];

async function loadSimTypes() {
  try {
    const d = await api("/api/sim/types");
    simTypes = d.types;
    const sel = $("#simStyle");
    const keep = sel.value;
    sel.innerHTML = d.types
      .map((t) => `<option value="${esc(t.id)}">${esc(t.id)}（VPIP ${esc(t.vpip)}）</option>`)
      .join("");
    if (keep) sel.value = keep;
    sel.onchange = () => {
      const t = d.types.find((x) => x.id === sel.value);
      $("#simTypeHint").textContent = t ? `${t.axis}｜${t.adjust}` : "";
    };
    const cur = d.types.find((x) => x.id === sel.value) || d.types[0];
    $("#simTypeHint").textContent = `${cur.axis}｜${cur.adjust}`;

    const ps = $("#ptSel");
    ps.innerHTML = d.types.map((t) => `<option value="${esc(t.id)}">${esc(t.id)}</option>`).join("");
    ps.onchange = fillTypeEditor;
    fillTypeEditor();
  } catch (e) {
    /* 忽略 */
  }
}

function fillTypeEditor() {
  const t = simTypes.find((x) => x.id === $("#ptSel").value);
  if (!t) return;
  $("#ptRange").value = t.range || "";
  $("#ptVpip").value = t.vpip || "";
  $("#ptDesc").value = t.desc || "";
  $("#ptPct").textContent = t.combo_pct ? `约 ${t.combo_pct}% 的手牌组合` : "";
  if (t.caveat) $("#ptEvidence").innerHTML = `<div class="muted">${esc(t.caveat)}</div>`;
  $("#ptMsg").textContent = "";
}

async function saveType(reset) {
  const id = $("#ptSel").value;
  try {
    const body = reset
      ? { id, reset: true }
      : { id, range: $("#ptRange").value, vpip: $("#ptVpip").value, desc: $("#ptDesc").value };
    const d = await api("/api/sim/types", body);
    $("#ptMsg").textContent = reset ? "已恢复默认" : `已保存（约 ${d.combo_pct}% 组合）`;
    $("#ptMsg").className = "badge on";
    await loadSimTypes();
    $("#ptSel").value = id;
    fillTypeEditor();
  } catch (e) {
    $("#ptMsg").textContent = e.message;
    $("#ptMsg").className = "badge off";
  }
}

async function newHand() {
  try {
    const d = await api("/api/sim/new", { pot_type: $("#simPot").value, style: $("#simStyle").value });
    simState = { id: d.id, history: [] };
    $("#simFeedback").innerHTML = "";
    renderTable(d.state);
    loadSimReport();
  } catch (e) {
    $("#simTable").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function doAction(action, amount, label) {
  try {
    const d = await api("/api/sim/act", { id: simState.id, action, amount });
    // 历史由服务端返回，包含对手动作
    const fb = d.feedback || {};
    const adv = d.state && d.state.advice ? d.state.advice : null;
    let html = "";
    if (fb.verdict) html += `<div class="finding ${fb.ev !== undefined && fb.ev < 0 ? "warn" : "ok"}">${esc(fb.verdict)}</div>`;
    if (adv) {
      html += `<div class="advice" style="margin-top:10px">
        <div class="adv-title">教练建议 <span class="badge">${esc(adv.confidence || "")}</span></div>
        <div class="adv-row"><b>频率</b> ${esc(adv.freq)}　<b>尺度</b> ${esc(adv.size)}</div>
        <div class="adv-row">${esc(adv.why)}</div>
        <div class="adv-row avoid">✕ ${esc(adv.avoid)}</div>
        ${adv.source ? `<div class="adv-row" style="color:var(--green)">📖 出自《${esc(adv.source.title)}》${esc(adv.source.heading || "")}</div>` : ""}
      </div>`;
    }
    if (d.note) {
      html += `<div class="finding muted" style="margin-top:8px">📖 你的笔记《${esc(d.note.title)}》${esc(d.note.heading || "")}：${esc(d.note.preview)}</div>`;
    }
    if (d.showdown) html += `<div class="finding ${d.showdown.result === "win" ? "ok" : "warn"}">${esc(d.showdown.text)}</div>`;
    $("#simFeedback").innerHTML = html;

    if (d.showdown) {
      $("#simActions").innerHTML = `<button class="primary" id="simAgain">下一手</button>`;
      $("#simAgain").onclick = newHand;
      renderHistory(d.history || simState.history);
      loadSimReport();
      return;
    }
    if (d.state) {
      simState.history = d.history || d.state.history || [];
      renderTable(d.state);
      renderHistory(simState.history);
      $("#simFeedback").innerHTML = html;
    }
  } catch (e) {
    $("#simFeedback").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function loadSimReport() {
  try {
    const d = await api("/api/sim/report");
    if (!d.hands) return;
    $("#simReportMeta").textContent = `${d.hands} 个决策 · 与建议一致 ${d.agree_pct}%`;
    const streetTxt = (d.by_street || [])
      .map((s) => `${STREET_CN[s.street] || s.street} ${Math.round((s.ok / s.n) * 100)}%`)
      .join(" · ");
    const styleTxt = (d.by_style || [])
      .map((s) => `${s.style} ${Math.round((s.ok / s.n) * 100)}%`)
      .join(" · ");
    $("#simReport").innerHTML =
      `<div>各街一致率：${esc(streetTxt)}</div>` +
      (styleTxt ? `<div>对各类对手：${esc(styleTxt)}</div>` : "") +
      (d.recent || [])
        .slice(0, 5)
        .map(
          (r) =>
            `<div class="item" style="font-size:12.5px">
              <b>${esc(STREET_CN[r.street] || r.street)}</b>
              <span class="muted">牌面</span> ${esc(r.board)}
              <span class="muted">你</span> ${esc(r.hero)}
              · 你选了 <b>${esc(r.action)}</b>
              · 建议 ${esc((r.advice_freq || "").slice(0, 14))}
              ${r.agree === 0 ? "✗" : r.agree === 1 ? "✓" : ""}</div>`
        )
        .join("");
  } catch (e) {
    /* 忽略 */
  }
}

{ const _e = $("#simNew"); if (_e) _e.onclick = newHand; }
{ const _e = $("#ptSave"); if (_e) _e.onclick = () => saveType(false); }
{ const _e = $("#ptReset"); if (_e) _e.onclick = () => saveType(true); }

{ const _e = $("#ptSuggest"); if (_e) _e.onclick = async () => {
  const id = $("#ptSel").value;
  $("#ptMsg").textContent = "正在翻你的笔记…";
  $("#ptEvidence").innerHTML = "";
  try {
    const d = await api("/api/sim/types/suggest", { id });
    if (d.error) throw new Error(d.error);
    $("#ptRange").value = d.range;
    $("#ptPct").textContent = `约 ${d.combo_pct}% 的手牌组合`;
    const conf = d.confidence === "high" ? "笔记里有明确依据" : "笔记只有方向，没给具体范围";
    $("#ptMsg").textContent = conf;
    $("#ptMsg").className = "badge " + (d.confidence === "high" ? "on" : "off");
    $("#ptEvidence").innerHTML =
      `<div>依据：${esc(d.basis || "—")}</div>` +
      (d.sources || [])
        .map((s) => `<div>· 《${esc(s.title)}》${esc(s.heading || "")}：${esc(s.preview)}</div>`)
        .join("");
  } catch (e) {
    $("#ptMsg").textContent = e.message;
    $("#ptMsg").className = "badge off";
  }
} }

// ---------------- 闯关 ----------------
let quizState = { level: 0, questions: [], idx: 0, score: 0, answered: false };
const QUIZ_KEY = "pc_quiz_session";

function loadSaved() {
  try {
    const raw = localStorage.getItem(QUIZ_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d || !d.questions || d.idx >= d.questions.length) return null;
    return d;
  } catch {
    return null;
  }
}
function saveSession() {
  if (quizState.idx >= quizState.questions.length) localStorage.removeItem(QUIZ_KEY);
  else localStorage.setItem(QUIZ_KEY, JSON.stringify(quizState));
}
function clearSession() {
  localStorage.removeItem(QUIZ_KEY);
}

async function loadCampaign() {
  try {
    const d = await api("/api/campaign");
    $("#cRank").textContent = d.rank.name;
    $("#cXp").textContent = `${d.xp} XP`;
    $("#cAcc").textContent = d.accuracy === null ? "—" : d.accuracy + "%";
    $("#cStreak").textContent = d.best_streak;
    $("#cMastered").textContent = d.mastered_cards;
    $("#cDays").textContent = d.days;

    const next = d.rank.next;
    const floor = d.rank.floor;
    const pct = next ? Math.min(100, ((d.xp - floor) / (next - floor)) * 100) : 100;
    $("#xpFill").style.width = pct + "%";
    $("#xpNext").textContent = next ? `距离下一段位还差 ${next - d.xp} XP` : "已经是最高段位";

    const saved = loadSaved();
    $("#levelGrid").innerHTML = d.levels
      .map((lv) => {
        const cls = lv.cleared ? "cleared" : lv.unlocked ? "open" : "locked";
        const resumable = saved && saved.level === lv.level;
        let label = lv.cleared ? "再战" : "开始";
        if (resumable) label = `继续 ${saved.idx}/${saved.questions.length}`;
        const btn = `<button class="mini-btn" data-level="${lv.level}" data-resume="${resumable ? 1 : 0}">${label}</button>`;
        return `<div class="lvcard ${cls}">
          <div class="lvhead"><span class="lvn">L${lv.level}</span><b>${esc(lv.topic)}</b><span class="spacer"></span>${btn}</div>
          <div class="lvbar"><i style="width:${lv.cleared ? 100 : (lv.clear_pct || 0)}%"></i></div>
          <div class="lvmeta">${lv.cleared
            ? `已通关 · 正确率 ${lv.accuracy === null ? "—" : lv.accuracy + "%"}`
            : `题量 ${Math.min(lv.clear_have || 0, lv.clear_need || 10)}/${lv.clear_need || 10} ${(lv.clear_have || 0) >= (lv.clear_need || 10) ? "✅" : ""} · 正确率 ${lv.accuracy === null ? "—" : lv.accuracy + "%"}（需 ≥75%）· 不限制进入`}</div>
          <div class="lvmeta" style="opacity:.6">题库共 ${lv.total} 张，不用一次刷完</div>
        </div>`;
      })
      .join("");

    $("#levelGrid").querySelectorAll("[data-level]").forEach((btn) => {
      btn.onclick = () => startLevel(Number(btn.dataset.level), btn.dataset.resume === "1");
    });

    $("#achGrid").innerHTML = d.achievements
      .map(
        (a) => `<div class="ach ${a.unlocked ? "on" : ""}" title="${esc(a.desc)}">
          <span class="aicon">${a.icon || "★"}</span>
          <div><b>${esc(a.name)}</b><div class="muted">${esc(a.desc)}</div></div>
        </div>`
      )
      .join("");

    loadPracticeScenes();
    if (d.new_achievements && d.new_achievements.length) {
      d.new_achievements.forEach((n) => toast("🏆 解锁成就：" + n));
    }
  } catch (e) {
    $("#levelGrid").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

async function loadPracticeScenes() {
  /* 场景练习已合并进「关卡」：这里不再渲染独立面板。
     场景题（kind=spot）已按内容关键词归入各关，跟着关卡走。 */
  return;
}

async function startScene(scene) {
  try {
    const d = await api("/api/quiz?scene=" + encodeURIComponent(scene) + "&n=10");
    if (!d.questions.length) return toast("这个场景还没有题");
    quizState = { level: 0, scene, title: "场景练习", questions: d.questions, idx: 0, score: 0, answered: false };
    $("#quizPanel").classList.remove("hidden");
    $("#quizPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    renderQuestion();
  } catch (e) {
    toast(e.message);
  }
}

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

async function startLevel(level, resume = false) {
  if (resume) {
    const saved = loadSaved();
    if (saved && saved.level === level) {
      quizState = { ...saved, answered: false };
      $("#quizPanel").classList.remove("hidden");
      $("#quizPanel").scrollIntoView({ behavior: "smooth", block: "start" });
      renderQuestion();
      return;
    }
  }
  try {
    const d = await api(`/api/quiz?level=${level}&n=10`);
    if (!d.questions.length) return toast("这一关还没有可出的题");
    quizState = { level, questions: d.questions, idx: 0, score: 0, answered: false };
    saveSession();
    $("#quizPanel").classList.remove("hidden");
    $("#quizPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    renderQuestion();
  } catch (e) {
    toast(e.message);
  }
}

function renderQuestion() {
  const st = quizState;
  const q = st.questions[st.idx];
  $("#quizTitle").textContent = `${st.title || "L" + st.level} 第 ${st.idx + 1} 题`;
  $("#quizProg").textContent = `${st.score} / ${st.idx}`;
  const opts = q.options
    .map((o, i) => `<button class="qopt" data-i="${i}">${esc(o)}</button>`)
    .join("");
  $("#quizBox").innerHTML = `<div class="qtext">${esc(q.q)}</div><div class="qopts">${opts}</div>
    <div id="qfeedback" class="qfb hidden"></div>`;
  $("#quizBox").querySelectorAll(".qopt").forEach((btn) => {
    btn.onclick = () => answer(Number(btn.dataset.i));
  });
}

async function answer(choice) {
  if (quizState.answered) return;
  quizState.answered = true;
  const q = quizState.questions[quizState.idx];
  try {
    const d = await api("/api/quiz/answer", { id: q.id, choice });
    const btns = $("#quizBox").querySelectorAll(".qopt");
    btns.forEach((b, i) => {
      b.disabled = true;
      if (i === d.answer) b.classList.add("right");
      else if (i === choice) b.classList.add("wrong");
    });
    if (d.correct) quizState.score += 1;
    saveSession();
    (d.new || []).forEach((n) => toast("🏆 解锁成就：" + n));
    const fb = $("#qfeedback");
    fb.classList.remove("hidden");
    fb.innerHTML = `<b class="${d.correct ? "ok" : "bad"}">${d.correct ? "答对了" : "答错了"}</b>
      <div class="muted">${esc(d.explain || "")} · ${d.xp} XP</div>
      <div class="row">
        <button class="primary" id="qnext">${quizState.idx + 1 >= quizState.questions.length ? "看结果" : "下一题"}</button>
        <button class="ghost" id="qflag">这题出得不好</button>
      </div>`;
    $("#qflag").onclick = async () => {
      await api("/api/quiz/flag", { id: q.id }).catch(() => {});
      toast("已删除这张卡，以后不会再出现");
      nextQuestion();
    };
    $("#qnext").onclick = nextQuestion;
  } catch (e) {
    toast(e.message);
    quizState.answered = false;
  }
}

function nextQuestion() {
  quizState.idx += 1;
  quizState.answered = false;
  if (quizState.idx >= quizState.questions.length) {
    const n = quizState.questions.length;
    const pct = Math.round((quizState.score / n) * 100);
    $("#quizBox").innerHTML = `<div class="qtext">这一轮结束：${quizState.score} / ${n}（${pct}%）</div>
      <div class="muted" style="margin:10px 0 16px">${pct >= 80 ? "状态不错，可以进下一关了。" : pct >= 60 ? "及格，但还差一点。错题回去看原文。" : "先回去读这一关的资料，再回来。"}</div>
      <div class="row"><button class="primary" id="again">再来一轮</button><button id="back">回到关卡</button></div>`;
    clearSession();
    const last = quizState;
    $("#again").onclick = () => (last.scene ? startScene(last.scene) : startLevel(last.level));
    $("#back").onclick = () => {
      $("#quizPanel").classList.add("hidden");
      loadCampaign();
    };
    loadCampaign();
  } else {
    renderQuestion();
  }
}

{ const _e = $("#quizClose"); if (_e) _e.onclick = () => {
  saveSession();
  $("#quizPanel").classList.add("hidden");
  loadCampaign();
} }

// ---------------- 翻后决策点 ----------------
let postState = { street: "flop", role: "", group: "high", pot_type: "", high: "", suit: "", paired: "", connected: "", size: "", matchup: "" };

const FILTER_MAP = {
  fHigh: "high", fSuit: "suit", fPaired: "paired", fConn: "connected",
  fSize: "size", fMatch: "matchup", fPot: "pot_type", fLine: "line", fVtype: "vtype", fOline: "oline",
};
const LINE_ORDER = ["CB", "B", "X", "XF", "XC", "XR", "C", "R", "F"];
const LINE_CN = { CB: "持续下注", B: "下注", X: "过牌到底", XF: "过牌弃牌", XC: "过牌跟注", XR: "过牌加注", C: "跟注", R: "加注", F: "弃牌" };

function postQuery() {
  const qs = new URLSearchParams({ group: postState.group, street: postState.street });
  ["role", "pot_type", "high", "suit", "paired", "connected", "size", "matchup", "line", "oline", "vtype"].forEach((k) => {
    if (postState[k]) qs.set(k, postState[k]);
  });
  return qs;
}

function syncFilters() {
  Object.entries(FILTER_MAP).forEach(([id, key]) => {
    const el = $("#" + id);
    if (el && el.value !== postState[key]) el.value = postState[key] || "";
  });
}

async function loadFilterOptions() {
  if (!$('#tab-post')) return;
  try {
    const d = await api("/api/postflop/options");
    $("#fMatch").innerHTML =
      '<option value="">全部</option>' +
      d.matchups.map((m) => `<option value="${esc(m.v)}">${esc(m.v)}（${m.n}）</option>`).join("");
  } catch (e) {
    /* 忽略 */
  }
  ["A高", "双高", "单高", "低牌"].forEach((v) => $("#fHigh").insertAdjacentHTML("beforeend", `<option>${v}</option>`));
  ["单色面", "双花面", "彩虹面"].forEach((v) => $("#fSuit").insertAdjacentHTML("beforeend", `<option>${v}</option>`));
  syncFilters();
}
const ACT_COLOR = { 下注: "#2bb673", 过牌: "#4a5563", 跟注: "#3b82f6", 弃牌: "#c0392b", 加注: "#ffc857", 过牌加注: "#a855f7" };

document.querySelectorAll("#streetTabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#streetTabs button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    postState.street = b.dataset.street;
    postState.runout = "";
    loadPresets();
    loadPost();
  };
});
document.querySelectorAll("#roleTabs button").forEach((b) => {
  if (!b) return;
  b.onclick = () => {
    document.querySelectorAll("#roleTabs button").forEach((x) => x.classList.remove("on"));
    if (!b) return;
    b.classList.add("on");
    postState.role = b.dataset.role;
    loadPost();
  };
});
{
  const gs = $("#groupSel");
  if (gs) gs.onchange = () => {
    postState.group = gs.value;
    loadPost();
  };
}
Object.entries(FILTER_MAP).forEach(([id, key]) => {
  const el = $("#" + id);
  if (!el) return;
  el.onchange = () => {
    postState[key] = el.value;
    loadPost();
  };
});
{
  const rf = $("#resetFilters");
  if (rf) rf.onclick = () => {
    ["high", "suit", "paired", "connected", "size", "matchup", "pot_type"].forEach((k) => (postState[k] = ""));
    syncFilters();
    loadPost();
  };
  const ch = $("#closeHands");
  if (ch) ch.onclick = () => $("#handPanel").classList.add("hidden");
  const cd = $("#closeDetail");
  if (cd) cd.onclick = () => $("#detailPanel").classList.add("hidden");
}

function mixBar(actions, n) {
  const order = ["下注", "过牌", "跟注", "弃牌", "加注", "过牌加注"];
  return `<div class="mixbar">${order
    .filter((a) => actions[a])
    .map((a) => `<i style="width:${(actions[a] / n) * 100}%;background:${ACT_COLOR[a]}" title="${a} ${Math.round((actions[a] / n) * 100)}%"></i>`)
    .join("")}</div>`;
}

async function loadPresets() {
  if (!$('#tab-post')) return;
  try {
    const d = await api("/api/postflop/presets?street=" + postState.street);
    $("#presetRow").innerHTML =
      '<span class="mini" style="margin-right:4px">常用：</span>' +
      d.presets
        .map((p, i) => `<button class="chip" data-i="${i}">${esc(p.name)}</button>`)
        .join("");
    $("#presetRow").querySelectorAll(".chip").forEach((btn) => {
      btn.onclick = () => {
        const p = d.presets[Number(btn.dataset.i)];
        ["high", "suit", "paired", "connected", "size", "matchup", "pot_type"].forEach((k) => (postState[k] = ""));
        Object.assign(postState, p.filters);
        syncFilters();
        loadPost();
      };
    });
  } catch (e) {
    /* 忽略 */
  }
}

function renderAdvice(a) {
  const box = $("#adviceBox");
  if (!a) {
    box.classList.remove("hidden");
    box.innerHTML = '<div class="adv-row" style="color:var(--muted)">选中「进攻 / 防守」后会给出对应的频率和尺度建议。</div>';
    return;
  }
  box.classList.remove("hidden");
  const src = a.source ? `<div class="adv-row" style="color:var(--green)">📖 出自《${esc(a.source.title)}》${esc(a.source.heading || "")}</div>` : "";
  box.innerHTML = `<div class="adv-title">建议 <span class="badge">${esc(a.confidence)}</span></div>
    <div class="adv-row"><b>频率</b> ${esc(a.freq)}　<b>尺度</b> ${esc(a.size)}</div>
    <div class="adv-row">${esc(a.why)}</div>
    ${a.avoid ? `<div class="adv-row avoid">✕ ${esc(a.avoid)}</div>` : ""}${src}`;
}

function renderCombos(list) {
  if (!list || !list.length) {
    $("#comboBox").innerHTML = "";
    return;
  }
  $("#comboBox").innerHTML =
    `<div class="combo-h">偏离最大的组合</div>` +
    list
      .map(
        (c) => `<div class="combo">
          <span class="cname">${esc(c.label)}</span>
          <span class="cval ${c.dev > 0 ? "up" : "dn"}">你 ${c.pct}% / 参考 ${c.ref}%</span>
          <span class="cdev">${c.dev > 0 ? "+" : ""}${c.dev}</span>
          <span class="badge">n=${c.n}</span>
        </div>`
      )
      .join("");
}

async function loadPost() {
  if (!$('#tab-post')) return;
  const qs = postQuery();
  try {
    const d = await api("/api/postflop/findings?" + qs.toString());
    const rows = d.rows || [];
    renderAdvice(d.advice);
    renderCombos(d.combos);
    const total = rows.reduce((a, r) => a + r.n, 0);
    $("#postMeta").textContent = `${total.toLocaleString()} 个决策点`;

    $("#findings").innerHTML = (d.findings || [])
      .map((f) => `<div class="finding ${f.level}">${esc(f.text)}</div>`)
      .join("");

    if (!rows.length) {
      $("#postMatrix").innerHTML = '<div class="empty">这个组合下没有数据。</div>';
      return;
    }
    if (postState.group === "size") {
      const tot = rows.reduce((a, r) => a + r.n, 0) || 1;
      $("#postMatrix").innerHTML = rows
        .map(
          (r) => `<div class="srow" data-label="${esc(r.label)}">
            <div class="slabel">${esc(r.label)}</div>
            <div class="sbar"><div class="mixbar"><i style="width:${(r.n / tot) * 100}%;background:var(--green)"></i></div>
              <div class="smix">占所有下注 <b>${Math.round((r.n / tot) * 100)}%</b></div></div>
            <div class="snum">n=${r.n}</div>
          </div>`
        )
        .join("");
      $("#postMatrix").querySelectorAll(".srow").forEach((el) => {
        el.onclick = () => openSpotHands(el.dataset.label);
      });
      return;
    }
    const present = new Set();
    rows.forEach((r) => Object.keys(r.lines || {}).forEach((k) => present.add(k)));
    const acts = LINE_ORDER.filter((k) => present.has(k));
    const order = ["A高", "双高", "单高", "低牌", "超张", "成花", "成顺", "公对面", "白板"];
    rows.sort((a, b) => {
      const ia = order.indexOf(a.label), ib = order.indexOf(b.label);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || b.n - a.n;
    });
    const tint = (act, v) => {
      const a = Math.min(0.55, (v / 100) * 0.75);
      if (act === "F" || act === "XF") return `rgba(192,57,43,${a})`;
      if (act === "CB" || act === "B" || act === "R" || act === "XR") return `rgba(43,182,115,${a})`;
      return `rgba(90,110,140,${a})`;
    };
    const cols = `style="grid-template-columns:150px repeat(${acts.length},1fr)"`;
    const head = `<div class="mx-row mx-head" ${cols}><div class="mx-l">场景</div>${acts
      .map((a) => `<div class="mx-c" title="${LINE_CN[a]}">${a}</div>`)
      .join("")}</div>`;
    const body = rows
      .map((r) => {
        const cells = acts
          .map((a) => {
            const v = r.lines && r.lines[a] ? Math.round((r.lines[a] / r.n) * 100) : 0;
            const dim = v === 0 ? "zero" : "";
            const style = v ? `style="background:${tint(a, v)}"` : "";
            return `<div class="mx-c ${dim}" ${style} title="${LINE_CN[a]}" data-act="${a}" data-label="${esc(r.label)}">${v || "—"}</div>`;
          })
          .join("");
        return `<div class="mx-row" ${cols} data-label="${esc(r.label)}">
          <div class="mx-l">${esc(r.label)}<span class="mx-n">n=${r.n}</span></div>${cells}
        </div>`;
      })
      .join("");
    $("#postMatrix").innerHTML = head + body;

    $("#postMatrix").querySelectorAll(".mx-c[data-act]").forEach((cell) => {
      cell.onclick = () => openSpotHands(cell.dataset.label, cell.dataset.act);
    });
  } catch (e) {
    $("#postMatrix").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

{ const _e = $("#practiceBtn"); if (_e) _e.onclick = async () => {
  const body = { ...postState };
  $("#coachMsg").textContent = "正在出题…";
  try {
    const d = await api("/api/postflop/practice", body);
    if (d.error) throw new Error(d.error);
    $("#coachMsg").textContent = `已生成 ${d.added} 题，去「闯关」或「卡片」练习`;
    toast(`已为「${d.scene}」生成 ${d.added} 道题`);
  } catch (e) {
    $("#coachMsg").textContent = e.message;
  }
} }

{ const _e = $("#coachBtn"); if (_e) _e.onclick = async () => {
  const qs = postQuery();
  $("#coachMsg").textContent = "分析中…";
  try {
    const d = await api("/api/postflop/coach?" + qs.toString());
    if (d.error) throw new Error(d.error);
    $("#coachBox").classList.remove("hidden");
    $("#coachBox").textContent = d.text;
    $("#coachMsg").textContent = "";
  } catch (e) {
    $("#coachMsg").textContent = e.message;
  }
} }

async function openSpotHands(label, action) {
  const qs = new URLSearchParams({ street: postState.street, limit: 60 });
  qs.set(postState.group, label);
  if (action) qs.set("action", action);
  if (postState.role) qs.set("role", postState.role);
  if (postState.pot_type) qs.set("pot_type", postState.pot_type);
  try {
    const d = await api("/api/spot-hands?" + qs.toString());
    $("#handTitle").textContent = `${label}${action ? " · " + action : ""} · ${d.hands.length} 手`;
    $("#handList").innerHTML = d.hands
      .map(
        (x) => `<div class="item handrow" data-id="${esc(x.hand_id)}">
          <div><b>${esc(x.hand)}</b> · ${esc(x.board)} · ${esc(x.action)} <span class="muted">${esc(x.matchup)}</span></div>
          <div class="muted">${x.net > 0 ? "+" : ""}${x.net.toFixed(2)} · 底池 ${x.pot}</div>
        </div>`
      )
      .join("");
    $("#handList").querySelectorAll(".handrow").forEach((el) => {
      el.onclick = () => showHand(el.dataset.id);
    });
    $("#handPanel").classList.remove("hidden");
    $("#handPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    alert(e.message);
  }
}

async function showHand(id) {
  try {
    const d = await api("/api/hand?id=" + encodeURIComponent(id));
    $("#handDetail").textContent = d.text;
    $("#detailPanel").classList.remove("hidden");
    $("#detailPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    alert(e.message);
  }
}


// ---------------- 玩家类型参数 ----------------
const FREQ_FIELDS = [
  ["vpip", "VPIP"], ["pfr", "PFR"], ["threebet", "3bet"],
  ["call3bet", "被3bet跟注%"], ["fourbet", "4bet"],
];
let ptypesCfg = null;

async function loadPTypes() {
  const box = document.getElementById("ptypesBox");
  if (!box) return;
  try {
    ptypesCfg = await api("/api/adjustments");
    const freq = ptypesCfg.freq || {};
    const width = ptypesCfg.preflop_width || {};
    const tend = ptypesCfg.tendency || {};
    const ids = Object.keys(freq);
    document.getElementById("ptypesMeta").textContent = `${ids.length} 个类型`;
    box.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="color:#8a929c;text-align:left">
          <th style="padding:6px">类型</th>
          ${FREQ_FIELDS.map(([, l]) => `<th>${l}</th>`).join("")}
          <th>开池宽度×</th><th>抓诈</th><th>薄价值</th><th>诈唬</th>
        </tr></thead>
        <tbody>${ids.map((id) => {
          const f = freq[id] || {}, t = tend[id] || {};
          return `<tr style="border-top:1px solid #222">
            <td style="padding:6px"><b>${esc(id)}</b></td>
            ${FREQ_FIELDS.map(([k]) => `<td><input data-t="${esc(id)}" data-k="freq.${k}" value="${f[k] ?? ""}" type="number" style="width:64px;background:#0f141a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px"></td>`).join("")}
            <td><input data-t="${esc(id)}" data-k="preflop_width" value="${width[id] ?? 1}" step="0.05" type="number" style="width:64px;background:#0f141a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px"></td>
            <td><input data-t="${esc(id)}" data-k="tendency.bluff_catch" value="${t.bluff_catch ?? ""}" step="0.05" type="number" style="width:64px;background:#0f141a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px"></td>
            <td><input data-t="${esc(id)}" data-k="tendency.value_thin" value="${t.value_thin ?? ""}" step="0.05" type="number" style="width:64px;background:#0f141a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px"></td>
            <td><input data-t="${esc(id)}" data-k="tendency.bluff" value="${t.bluff ?? ""}" step="0.05" type="number" style="width:64px;background:#0f141a;color:#fff;border:1px solid #333;border-radius:4px;padding:2px 4px"></td>
          </tr>`;
        }).join("")}</tbody>
      </table>`;
  } catch (e) {
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

document.getElementById("ptypesSave") && (document.getElementById("ptypesSave").onclick = async () => {
  const cfg = ptypesCfg || {};
  cfg.freq = cfg.freq || {}; cfg.preflop_width = cfg.preflop_width || {}; cfg.tendency = cfg.tendency || {};
  document.querySelectorAll("#ptypesBox input").forEach((inp) => {
    const t = inp.dataset.t, k = inp.dataset.k, v = parseFloat(inp.value);
    if (Number.isNaN(v)) return;
    if (k.startsWith("freq.")) { cfg.freq[t] = cfg.freq[t] || {}; cfg.freq[t][k.slice(5)] = v; }
    else if (k.startsWith("tendency.")) { cfg.tendency[t] = cfg.tendency[t] || {}; cfg.tendency[t][k.slice(9)] = v; }
    else cfg.preflop_width[t] = v;
  });
  try {
    await api("/api/adjustments", { cfg }, "POST");
    toast("已保存，立刻生效");
    // 保存后必须重绘，否则屏幕上还是旧数据
    try { if (typeof loadTree === "function") loadTree(); } catch (e) {}
  } catch (e) { toast("保存失败：" + e.message); }
});

// ---------------- 进度 ----------------
async function loadProgress() {
  try {
    const [p, m] = await Promise.all([api("/api/progress"), api("/api/mistakes")]);
    const t = p.total;
    $("#ovBox").innerHTML = `
      <div class="row" style="margin-top:0;gap:26px">
        <div><div class="big">${t.mastered_pct}%</div><div class="muted">已掌握 ${t.mastered}/${t.cards}</div></div>
        <div><div class="big">${t.new}</div><div class="muted">未开始</div></div>
        <div><div class="big">${t.learning}</div><div class="muted">在学</div></div>
        <div><div class="big">${t.accuracy_pct === null ? "—" : t.accuracy_pct + "%"}</div>
          <div class="muted">复习正确率${t.accuracy_n != null ? ` · n=${t.accuracy_n}` : ""}</div></div>
      </div>`
      + (t.reps < 30
        ? `<div class="muted" style="margin-top:10px;font-size:12.5px">
             ⚠ 只复习了 <b>${t.reps}</b> 次，正确率还不能当结论用（课程实测口径：单节点要 ≥1,393 次才到 ±2% 不确定性）。
           </div>`
        : "")
      + `<div class="muted" style="margin-top:6px;font-size:12.5px">
           「已掌握」= 间隔被推到 7 天以上的卡。分母已排除质量分 &lt; 6 的隐藏卡。
         </div>`;

    $("#topicBox").innerHTML = p.topics
      .map((x) => {
        const pct = x.mastered_pct;
        return `<div class="topicrow">
          <div class="tname">${esc(x.name)}</div>
          <div class="tbar"><i style="width:${pct}%"></i></div>
          <div class="tnum">${x.mastered}/${x.cards}${x.reps ? ` <span style="opacity:.65">· ${x.reps}次</span>` : ""}</div>
        </div>`;
      })
      .join("");

    $("#missBox").innerHTML = m.mistakes.length
      ? m.mistakes
          .map(
            (c) => `<div class="item">
              <div>${esc(c.front)}</div>
              <div class="muted">忘了 ${c.lapses} 次 · 间隔 ${c.interval} 天 · ${esc(c.doc_title).slice(0, 40)}</div>
              <div style="margin-top:6px"><button class="mini-btn" data-back="${c.card_id}">回看这一节</button></div>
            </div>`
          )
          .join("")
      : '<div class="empty">还没有错题。先去做几张卡。</div>';
    $("#missBox").querySelectorAll("[data-back]").forEach((btn) => {
      const c = m.mistakes.find((x) => String(x.card_id) === btn.dataset.back);
      btn.onclick = () => {
        $("#q").value = `《${c.doc_title}》里「${(c.tags || "").split(" / ").pop()}」这一节讲了什么？结合我的笔记解释。`;
        document.querySelector('#tabs button[data-tab="ask"]').click();
        $("#q").focus();
      };
    });
  } catch (e) {
    $("#ovBox").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

// ---------------- 卡片 ----------------
let cards = [], cardsDue = 0, cardsTrunc = false;
let idx = 0;
let shown = false;
let recall = "";

function keywords(text) {
  const t = (text || "").toLowerCase();
  const set = new Set();
  for (const m of t.matchAll(/[a-z0-9]{2,}/g)) set.add(m[0]);
  for (const run of t.match(/[\u4e00-\u9fff]+/g) || []) {
    for (let i = 0; i < run.length - 1; i++) set.add(run.slice(i, i + 2));
  }
  return [...set];
}

async function loadCardTopics() {
  try {
    const p = await api("/api/progress");
    const sel = $("#cardTopic");
    const cur = sel.value;
    sel.innerHTML =
      '<option value="">全部</option>' +
      p.topics.map((t) => `<option value="${esc(t.name)}">${esc(t.name)}（${t.cards}）</option>`).join("");
    sel.value = cur;
  } catch {
    /* 忽略 */
  }
}

async function loadCards() {
  try {
    const topic = $("#cardTopic") ? $("#cardTopic").value : "";
    const qs = topic ? "?topic=" + encodeURIComponent(topic) : "";
    const d = await api("/api/cards" + qs);
    cards = d.cards || [];
    cardsDue = d.due_total != null ? d.due_total : cards.length;
    cardsTrunc = !!d.truncated;
    idx = 0;
    shown = false;
    recall = "";
    renderCard();
  } catch (e) {
    $("#cardBox").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

function renderCard() {
  const box = $("#cardBox");
  if (!cards.length) {
    box.innerHTML = '<div class="empty">今天没有待复习的卡片。继续往 data/notes 里加笔记，或把新卡片留到明天。</div>';
    $("#cardCount").textContent = "";
    return;
  }
  if (idx >= cards.length) {
    box.innerHTML = `<div class="empty">这一轮复习完了（${cards.length} 张）${cardsTrunc ? `，今日还剩 ${cardsDue - cards.length} 张，再点一次「复习卡」继续` : ""}。</div>`;
    $("#cardCount").textContent = "完成";
    refreshStatus();
    return;
  }
  const c = cards[idx];
  $("#cardCount").textContent = cardsTrunc
    ? `${idx + 1} / ${cards.length}（今日共 ${cardsDue} 张待复习）`
    : `${idx + 1} / ${cards.length}`;
  let h = `<div class="card-front">${esc(c.front)}</div>`;
  if (c.tags) h += `<div style="margin-top:10px"><span class="tag">${esc((c.tags || "").split(" / ").pop())}</span></div>`;
  if (shown) {
    h += `<div class="card-back">${esc(c.back)}</div>`;
    if (recall.trim()) {
      const ks = keywords(c.back);
      const got = ks.filter((k) => recall.toLowerCase().includes(k));
      const pct = ks.length ? Math.round((got.length / ks.length) * 100) : 0;
      const miss = ks.filter((k) => !got.includes(k)).slice(0, 8);
      h += `<div class="recall-score ${pct >= 60 ? "ok" : pct >= 30 ? "mid" : "bad"}">
        关键词命中 ${pct}%${miss.length ? ` · 漏了：${miss.join("、")}` : " · 全对"}</div>`;
    }
    h += `<div class="row">
        <button data-g="0">忘了</button>
        <button data-g="1">勉强</button>
        <button data-g="2">记得</button>
        <button data-g="3">太简单</button>
        <button data-del="1" class="ghost">这张没用</button>
      </div>`;
  } else {
    h += `<div class="field" style="margin-top:12px"><label>先默写（想不起来就留空）</label>
      <textarea id="recall" rows="3" placeholder="用自己的话写出来，再对答案——比直接翻答案记得牢"></textarea></div>`;
    h += `<div class="row"><button class="primary" id="reveal">显示答案</button></div>`;
  }
  box.innerHTML = h;
  if (!shown) {
    const input = $("#recall");
    if (input) input.value = recall;
    $("#reveal").onclick = () => {
      recall = ($("#recall") || {}).value || "";
      shown = true;
      renderCard();
    };
  }
  const del = box.querySelector("[data-del]");
  if (del)
    del.onclick = async () => {
      await api("/api/cards/delete", { card_id: c.id }).catch(() => {});
      cards.splice(idx, 1);
      shown = false;
      recall = "";
      renderCard();
      refreshStatus();
    };
  box.querySelectorAll("[data-g]").forEach((b) => {
    b.onclick = async () => {
      await api("/api/review", { card_id: c.id, grade: Number(b.dataset.g) }).catch(() => {});
      idx += 1;
      shown = false;
      recall = "";
      renderCard();
    };
  });
}

// ---------------- 计划 ----------------
async function loadPlan() {
  const min = Number($("#planMin").value || 25);
  try {
    const [p, o] = await Promise.all([api("/api/plan?minutes=" + min), api("/api/outline")]);
    const split = p.split;
    let h = `<div class="muted" style="color:var(--muted);font-size:13px">${esc(p.note)}</div>
      <dl class="kv" style="margin-top:10px">
        <dt>复习卡片</dt><dd>${p.due_total} 张到期（本次做 ${p.cards.length} 张，约 ${split.cards} 分钟）</dd>
        <dt>精读</dt><dd>${p.reading.length} 节（约 ${split.reading} 分钟）</dd>
      </dl>`;
    if (p.reading.length) {
      h += '<div class="row" style="margin-top:6px">' + p.reading
        .slice(0, 3)
        .map((r, i) => `<button data-read="${i}" class="mini-btn">▸ ${esc(r.heading)}</button>`)
        .join("") + "</div>";
    }
    $("#planBox").innerHTML = h;
    $("#planBox").querySelectorAll("[data-read]").forEach((btn) => {
      btn.onclick = () => {
        const r = p.reading[Number(btn.dataset.read)];
        $("#q").value = `《${r.title}》里「${r.heading}」这一节讲了什么？结合我的笔记解释，并给我一个检查点。`;
        document.querySelector('#tabs button[data-tab="ask"]').click();
        $("#q").focus();
      };
    });

    await loadPath();

    $("#mapBox").innerHTML = o.docs.length
      ? o.docs
          .map(
            (d) => `<div class="item">
              <div><b>${esc(d.title)}</b> <span class="muted">· ${d.chunks} 段 · ${d.cards} 张卡片</span></div>
              <div class="muted">${d.sections.slice(0, 8).map(esc).join(" · ")}${d.sections.length > 8 ? " …" : ""}</div>
            </div>`
          )
          .join("")
      : '<div class="empty">资料库是空的。把笔记放进 data/notes/ 再 ingest，或用 python run.py import notion/evernote 导入。</div>';
  } catch (e) {
    $("#planBox").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}
{ const _e = $("#planBtn"); if (_e) _e.onclick = loadPlan; }
if ($("#cardTopic")) {
  $("#cardTopic").onchange = () => {
    idx = 0;
    shown = false;
    recall = "";
    loadCards();
  };
  loadCardTopics();
}

async function loadPath() {
  try {
    const w = Number($("#pathWeeks").value || 4);
    const p = await api(`/api/path?weeks=${w}&days=5`);
    if (!p.weeks || !p.weeks.length) {
      $("#pathBox").innerHTML = '<div class="empty">资料库是空的。</div>';
      return;
    }
    const themes = (p.topics || []).map((t) => `${esc(t.name)} ${t.sections}`).join(" · ");
    let html = `<div class="muted" style="font-size:12.5px;color:var(--muted)">${p.total_days} 天 · ${p.pool} 个候选章节 · ${themes}</div>`;
    html += p.weeks
      .map(
        (w) => `<details class="week">
          <summary><b>第 ${w.week} 周</b> · ${esc(w.theme)}</summary>
          ${w.days
            .map(
              (d) => `<div class="list"><div class="item">
                <div><span class="tag">Day ${d.day}</span> ${esc(d.topic)} <span class="muted">· 卡片 ${d.cards_target} 张 · ${d.minutes} 分钟</span></div>
                ${d.read.map((r) => `<div class="muted">读：${esc(r.title)} / ${esc(r.heading)}</div>`).join("")}
              </div></div>`
            )
            .join("")}
        </details>`
      )
      .join("");
    $("#pathBox").innerHTML = html;
  } catch (e) {
    $("#pathBox").innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}
{ const _e = $("#pathBtn"); if (_e) _e.onclick = loadPath; }
refreshStatus();
setInterval(refreshStatus, 20000);

// 支持 ?q=... 直接提问（方便做书签/分享）
const params = new URLSearchParams(location.search);
if (params.get("q")) {
  $("#q").value = params.get("q");
  setTimeout(() => $("#askBtn").click(), 100);
}

if (params.get("cfg")) {
  setTimeout(openCfg, 400);
}

if (params.get("hero")) {
  document.querySelector('#tabs button[data-tab="calc"]').click();
  $("#eqHero").value = params.get("hero");
  $("#eqVillain").value = params.get("villain") || "";
  $("#eqBoard").value = params.get("board") || "";
  setTimeout(() => $("#eqBtn").click(), 100);
}

if (params.get("group") && $("#groupSel")) {
  $("#groupSel").value = params.get("group");
  postState.group = params.get("group");
}
["high", "suit", "oline", "size"].forEach((k) => {
  if (params.get(k)) postState[k] = params.get(k);
});

if (params.get("role")) {
  postState.role = params.get("role");
  document.querySelectorAll("#roleTabs button").forEach((b) => {
  if (!b) return;
    b.classList.toggle("on", b.dataset.role === params.get("role"));
  });
}

if (params.get("rule_street") || params.get("rule_role")) {
  document.querySelector('#tabs button[data-tab="rules"]').click();
  if (params.get("rule_street")) $("#ruleStreet").value = params.get("rule_street");
  if (params.get("rule_role")) $("#ruleRole").value = params.get("rule_role");
  setTimeout(loadRules, 400);
}

if (params.get("chunk")) {
  { const _b = document.querySelector('#tabs button[data-tab="library"]') || document.querySelector('#tabs button[data-tab="ask"]'); if (_b) _b.click(); }
  setTimeout(() => openChunk(Number(params.get("chunk"))), 600);
}

if (params.get("sim")) {
  document.querySelector('#tabs button[data-tab="sim"]').click();
  setTimeout(async () => {
    await newHand();
    if (params.get("sim") === "edit") {
      const d = document.querySelector("#tab-sim details");
      if (d) d.open = true;
    }
    if (params.get("sim") === "demo") {
      await doAction("check", 0, "过牌");
      await doAction("check", 0, "过牌");
    }
  }, 400);
}

const initial = (location.hash || "").replace("#", "");
if (initial) {
  const btn = document.querySelector(`#tabs button[data-tab="${initial}"]`);
  if (btn) btn.click();
  else activateTab("ask", false);
} else {
  activateTab("ask", false);
}


// ---------------- 知识页搜索 ----------------
async function libDoSearch() {
  const q = ($("#libSearch").value || "").trim();
  const box = $("#libResults");
  if (!q) { box.innerHTML = ""; return; }
  box.innerHTML = '<div class="empty">搜索中…</div>';
  try {
    const d = await api("/api/search?q=" + encodeURIComponent(q) + "&k=8");
    const rs = d.results || [];
    if (!rs.length) { box.innerHTML = '<div class="empty">没搜到，换个说法试试。</div>'; return; }
    box.innerHTML = rs.map((r) => {
      const txt = (r.text || "").replace(/\s+/g, " ").slice(0, 180);
      return `<div class="concept" style="padding:10px 0;border-bottom:1px solid #ffffff10">
        <div class="cname" style="cursor:pointer" data-chunk="${r.chunk_id}">《${esc(r.title || "")}》${esc(r.heading || "")}</div>
        <div class="muted" style="font-size:12.5px;margin-top:4px">${esc(txt)}…</div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-chunk]").forEach((el) => {
      el.onclick = () => openChunk(el.dataset.chunk);
    });
  } catch (e) {
    box.innerHTML = `<div class="empty">搜索失败：${esc(e.message)}</div>`;
  }
}

// ---------------- 策略树 ----------------
let treeLast = null;

const TREE_SCALE = {
  100: "#ff2d55", 80: "#ff6b35", 60: "#f7b32b", 40: "#4a7c59", 20: "#3f5a6b", 0: "#2a3038",
};
const TREE_TRACK = "#1b1f26";
function treeFill(b) {
  if (b === null || b === undefined) return TREE_TRACK;
  const c = TREE_SCALE[[100, 80, 60, 40, 20, 0].find((x) => b >= x) ?? 0];
  return `linear-gradient(to right, ${c} 0 ${b}%, ${TREE_TRACK} ${b}% 100%)`;
}
function treeFg(b) {
  if (b === null || b === undefined) return "#5a6068";
  if (b >= 60) return "#ffffff";
  if (b >= 20) return "#d8dee6";
  return "#8a929c";
}


function roleFrom(hero, villain, opener, pot) {
  // BvB 只适用于单加注池；其他池型即使 SB vs BB 也按 IP/OOP 判
  const bvbOk = !pot || pot === "SRP";
  if (bvbOk) {
    if (hero === "SB" && villain === "BB") return "BvB-SB";
    if (hero === "BB" && villain === "SB") return "BvB-BB";
    if (opener === "bb") return hero === "SB" ? "BvB-SB" : "BvB-BB";
  }
  const heroIP = (POS_ORDER[hero] ?? -1) > (POS_ORDER[villain] ?? 99);
  if (opener === "hero") return heroIP ? "IP-PFR" : "OOP-PFR";
  return heroIP ? "IP-caller" : "OOP-caller";
}



// ── 牌桌视图：座位 / 底牌 / 公共牌 / 底池 / 动作历史 ──────────
const SUIT_OF = { s: "♠", h: "♥", d: "♦", c: "♣" };
const SUIT_RED = new Set(["h", "d"]);

function parseCards(text) {
  // "A72r" → ["A♠"?] 无花色时用占位；"As7h2c" → 带花色
  const out = [];
  const s = String(text || "").trim();
  for (const m of s.matchAll(/([2-9TJQKA])([shdc])/gi)) out.push({ r: m[1].toUpperCase(), s: m[2].toLowerCase() });
  if (out.length) return out;
  for (const m of s.matchAll(/([2-9TJQKA])/gi)) out.push({ r: m[1].toUpperCase(), s: null });
  return out.slice(0, 5);
}

function cardHTML(c) {
  if (!c) return `<div class="pcard back">–</div>`;
  const suit = c.s ? SUIT_OF[c.s] : "";
  const cls = c.s && SUIT_RED.has(c.s) ? "pcard red" : "pcard";
  return `<div class="${cls}">${c.r}${suit ? `<span style="font-size:13px">${suit}</span>` : ""}</div>`;
}

function seatPos(i, n) {
  // 座位沿椭圆均匀分布：英雄固定在最下方，其余顺时针排开。
  // 之前只定义了 2/3 人布局，6 人桌全退回同一个点 → 座位重叠。
  const LAYOUT = {
    2: [[50, 90], [50, 10]],
    3: [[50, 90], [16, 16], [84, 16]],
    4: [[50, 90], [10, 50], [50, 10], [90, 50]],
    5: [[50, 90], [8, 58], [28, 12], [72, 12], [92, 58]],
    6: [[50, 90], [6, 60], [20, 14], [50, 6], [80, 14], [94, 60]],
    7: [[50, 90], [6, 62], [16, 20], [42, 8], [68, 8], [88, 22], [94, 62]],
    // 8 人桌：英雄占最下方，其余 7 人从左边绕到右边。
    // 旧版最后一个座位在 (50,96)，跟英雄 (50,90) 几乎同一个点 → UTG/BB 叠在一起。
    8: [[50, 90], [8, 64], [12, 26], [32, 10], [52, 6], [72, 10], [90, 26], [94, 64]],
  };
  const pts = LAYOUT[n] || LAYOUT[2];
  const [x, y] = pts[i] || pts[pts.length - 1];
  return { left: `${x}%`, top: `${y}%` };
}

function renderPokerTable(v, ruleInfo) {
  const box = document.getElementById("tableBox");
  if (!box) return;
  // 这张桌子上有几个人：6 人桌默认按标准位置摆，3 人池只摆 3 个
  const multi = v.pot === "3人池" ? 3 : (v.pot === "多人池" || v.pot === "3BP多人") ? 3 : 2;
  // 桌上该画几个座位：跟桌型一致（6-max 画 6 个，8-max 画 8 个），没参与的人灰掉
  const tableType = (document.getElementById("treeTableType") || {}).value || "6-max";
  const seatCount = tableType.startsWith("8") ? 8 : 6;
  // 双方筹码：优先各自的，其次全局的。
  // 注意用 v.heroStack（caller 已经按强抓折半），不要再读下拉框原值。
  const globalStack = (v.heroStack && v.heroStack !== "*")
    ? v.heroStack
    : ((($("#treeHeroStack") || {}).value) || v.stack);
  const vStackSel = ($("#treeVillainStack") && $("#treeVillainStack").value) || "*";
  const stackOf = (who) => {
    if (who === "hero") {
      if (v.heroStack && v.heroStack !== "*") return v.heroStack;
      return (globalStack && globalStack !== "*") ? globalStack : "—";
    }
    // 对手：优先用调用方传进来的（强抓已经把有效筹码折半），
    // 不能直接读下拉框原值，否则英雄 50bb、对手 200bb 对不上。
    if (v.villainStack && v.villainStack !== "*") return v.villainStack;
    if (vStackSel && vStackSel !== "*") return vStackSel;
    return (globalStack && globalStack !== "*") ? globalStack : "—";
  };
  // 全员座位（按桌型），参与的高亮、没参与的灰掉
  const LIST6 = ["UTG","HJ","CO","BTN","SB","BB"];
  const LIST8 = ["UTG","UTG1","UTG2","HJ","CO","BTN","SB","BB"];
  const allPos = tableType.startsWith("8") ? LIST8 : LIST6;
  const involved = new Set([v.hero, v.villain]);
  if (multi >= 3 && v.villain2 && v.villain2 !== "*") involved.add(v.villain2);
  // 座位顺序要让「我」落在最下方：按位置顺序从 hero 开始环排
  const hi = Math.max(0, allPos.indexOf(v.hero));
  const rotated = allPos.slice(hi).concat(allPos.slice(0, hi));
  const seats = rotated.map((pos) => ({
    pos,
    stk: pos === v.hero ? stackOf("hero") : (involved.has(pos) ? stackOf("villain") : "—"),
    hero: pos === v.hero,
    inactive: !involved.has(pos),
  }));
  const n = seats.length;
  const cards = v.street === "翻前" ? [] : parseCards(v.board);
  const needed = { 翻牌: 3, 转牌: 4, 河牌: 5 }[v.street] || 0;
  const shown = [];
  if (needed > 0) {                       // 翻前完全不画牌位
    for (let i = 0; i < needed; i++) shown.push(cards[i] || null);
  }

  const seatHTML = seats.map((s, i) => {
    const p = seatPos(i, n);
    const locked = (window.__locks || []).some((c) => c.pos === s.pos);
    const cls = [s.hero ? "hero" : "", locked ? "locked" : "", s.inactive ? "inactive" : ""].filter(Boolean).join(" ");
    return `<div class="pseat ${cls}" data-lockpos="${esc(s.pos || "")}"
        style="left:${p.left};top:${p.top};transform:translate(-50%,-50%)" title="点击派生新版本">
      <div class="pos">${esc(POS_CN[s.pos] || s.pos || "?")}${s.hero ? " ●我" : ""}${locked ? " ⚖" : ""}</div>
      <div class="stk">${esc(String(s.inactive ? "" : s.stk))}</div>
    </div>`;
  }).join("");

  // 座位点击用事件委托（座位 DOM 是稍后才插入的）
  if (box && !box.dataset.lockBound) {
    box.dataset.lockBound = "1";
    box.addEventListener("click", (ev) => {
      const seat = ev.target.closest("[data-lockpos]");
      if (seat && seat.dataset.lockpos) openLockEditor(seat.dataset.lockpos);
    });
  }
  // 底池：按「开池 2.5bb + 跟注」估算，展示用
  const potTxt = v.street === "翻前" ? "" : (v.pot === "3BP" ? "~20bb" : v.pot === "4BP" ? "~50bb" : v.pot === "3人池" ? "~9bb" : "~6.5bb");
  const acts = (window.__nodeActions || []);
  const btnHTML = acts.map((a) => {
    const cls = a.kind === "allin" ? "pbtn danger" : a.kind === "fold" ? "pbtn muted" : a.kind === "check" ? "pbtn" : "pbtn primary";
    return `<button class="${cls}" data-act="${esc(a.label)}" data-kind="${esc(a.kind)}">${esc(a.label)}</button>`;
  }).join("");

  box.innerHTML = `<div class="ptable">
    ${seatHTML}
    <div class="pcenter">
      <div class="pcards">${shown.map(cardHTML).join("")}</div>
      <div class="ppot">${v.street === "翻前" ? "翻前" : esc(v.board || "")}${potTxt ? `　·　底池 ${esc(potTxt)}` : ""}</div>
    </div>
  </div>
  <div id="playActions" class="play-actions"></div>
`;

  // 动作按钮：点击后提示该动作在范围内的占比（暂时只做提示，不推进树）
  box.querySelectorAll("[data-act]").forEach((b) => {
    b.onclick = () => {
      const detail = document.getElementById("treeDetail");
      if (detail) {
        detail.innerHTML = `<b>${esc(b.dataset.act)}</b>　<span style="color:#8a929c">这个动作在当前范围里的平均使用率：${window.__rangeBetPct ?? "—"}%</span>`
          + `　<span style="color:#6b6b6b">（点格子看具体手牌的混合）</span>`;
      }
      box.querySelectorAll("[data-act]").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
    };
  });
}

// 单牌细分：同一手牌按花色拆开，按牌面同花做阻断调整

function boardSuitCount(board) {
  const cnt = { s: 0, h: 0, d: 0, c: 0 };
  for (const m of String(board || "").matchAll(/([2-9TJQKA])([shdc])/gi)) cnt[m[2].toLowerCase()]++;
  return cnt;
}
function comboVariants(cell, board) {
  // 关键：公共牌上的牌不可能在手上（card removal）
  const combo = cell.combo || "";
  if (combo.length < 3 || cell.folded) return [];
  const r1 = combo[0], r2 = combo[1], kind = combo[2];
  const onBoard = new Set();
  for (const m of String(board || "").matchAll(/([2-9TJQKA])([shdc])/gi)) {
    onBoard.add(m[1].toUpperCase() + m[2].toLowerCase());
  }
  const cnt = boardSuitCount(board);
  const base = cell.bucket === null || cell.bucket === undefined ? null : cell.bucket;
  const out = [];

  const push = (label, suit, dead) => {
    if (dead) {
      out.push({ label, suit, bucket: null, dead: true, adj: 0 });
      return;
    }
    let adj = 0;
    if (cnt[suit] >= 3) adj = kind === "s" ? 18 : 10;
    else if (cnt[suit] === 2) adj = kind === "s" ? 6 : 3;
    out.push({
      label, suit, dead: false, adj,
      bucket: base === null ? null : Math.max(0, Math.min(100, base + adj)),
    });
  };

  if (kind === "s") {
    for (const st of ["s", "h", "d", "c"]) {
      const dead = onBoard.has(r1 + st) || onBoard.has(r2 + st);
      push(`${r1}${SUIT_SYM[st]}${r2}${SUIT_SYM[st]}`, st, dead);
    }
  } else {
    for (const st of ["s", "h", "d", "c"]) {
      const dead = onBoard.has(r1 + st) || onBoard.has(r2 + st);
      push(`${r1}${SUIT_SYM[st]}${r2}`, st, dead);
    }
  }
  return out;
}

// ── 牌面选牌器：点格子选真牌，不再用 "A72r" 这种简写 ──────────
const BP_RANKS = ["A","K","Q","J","T","9","8","7","6","5","4","3","2"];
const BP_SUITS = [
  { code: "s", sym: "♠", red: false },
  { code: "h", sym: "♥", red: true  },
  { code: "d", sym: "♦", red: true  },
  { code: "c", sym: "♣", red: false },
];
let bpCards = [];      // [{r, s}] 最多 5 张

function bpBoardText() {
  // 转成后端认识的形式：As7h2c；两张同花就是两色，三张同花就是单色
  return bpCards.map((c) => c.r + c.s).join("");
}

function bpSync() {
  const hidden = document.getElementById("treeBoard");
  if (hidden) hidden.value = bpBoardText();
}

function bpRender() {
  const box = document.getElementById("boardPicker");
  if (!box) return;
  box.innerHTML = bpCards.map((c, i) => {
    const suit = BP_SUITS.find((x) => x.code === c.s);
    const cls = "bp-slot filled" + (suit && suit.red ? " red" : "");
    return `<div class="${cls}" data-slot="${i}">${c.r}<span style="font-size:12px">${suit ? suit.sym : ""}</span></div>`;
  }).join("") + `<div class="bp-slot" data-slot="${bpCards.length}" title="加一张">＋</div>`;
  box.querySelectorAll("[data-slot]").forEach((el) => {
    el.onclick = (ev) => bpOpen(Number(el.dataset.slot), ev);
  });
  bpSync();
}

function bpOpen(slot, ev) {
  document.querySelectorAll(".bp-pop").forEach((x) => x.remove());
  const pop = document.createElement("div");
  pop.className = "bp-pop";
  const used = new Set(bpCards.map((c) => c.r + c.s));
  pop.innerHTML = BP_RANKS.map((r) => `<div class="bp-row">` + BP_SUITS.map((su) => {
    const key = r + su.code;
    const isUsed = used.has(key) && !(bpCards[slot] && bpCards[slot].r === r && bpCards[slot].s === su.code);
    return `<div class="bp-card${su.red ? " red" : ""}${isUsed ? " used" : ""}" data-card="${key}">${r}<span style="font-size:9px">${su.sym}</span></div>`;
  }).join("") + `</div>`).join("") +
    `<button class="bp-clear" data-clear="1">清空这张 / 收起</button>`;

  const rect = ev.target.getBoundingClientRect();
  pop.style.left = Math.min(rect.left, window.innerWidth - 340) + "px";
  pop.style.top = (rect.bottom + window.scrollY + 6) + "px";
  document.body.appendChild(pop);

  pop.querySelectorAll("[data-card]").forEach((el) => {
    el.onclick = () => {
      const key = el.dataset.card;
      if (el.classList.contains("used")) return;
      const r = key[0], s = key[1];
      const next = bpCards.slice();
      next[slot] = { r, s };
      bpCards = next.filter(Boolean).slice(0, 5);
      pop.remove();
      bpRender();
      if (typeof loadTree === "function") loadTree();
    };
  });
  pop.querySelector("[data-clear]").onclick = () => {
    bpCards = bpCards.filter((_, i) => i !== slot);
    pop.remove();
    bpRender();
    if (typeof loadTree === "function") loadTree();
  };
}

function bpInit(text) {
  // 从 URL 或默认值初始化；支持 "As7h2c" 和旧的 "A72r"
  bpCards = [];
  const t = String(text || "").trim();
  if (/[shdc]/i.test(t)) {
    for (const m of t.matchAll(/([2-9TJQKA])([shdc])/gi)) {
      bpCards.push({ r: m[1].toUpperCase(), s: m[2].toLowerCase() });
    }
  } else {
    // 旧写法 "A72r" → 用黑桃占位（r/tt/m 没有花色信息）
    for (const m of t.matchAll(/([2-9TJQKA])/gi)) bpCards.push({ r: m[1].toUpperCase(), s: "s" });
  }
  bpCards = bpCards.slice(0, 5);
  bpRender();
}

// ── 完整牌局状态机：翻牌 → 转牌 → 河牌 → 结算 ──────────────────
const GAME_STREETS = ["翻牌", "转牌", "河牌"];
let game = null;

function gameInit() {
  const v = window.__treeState || {};
  game = {
    streetIdx: Math.max(0, GAME_STREETS.indexOf(v.street || "翻牌")),
    pot: parseFloat(String(v.pot_bb || 6.5)) || 6.5,
    heroStack: 100, villainStack: 100,
    streetBets: 0,          // 本街已投入
    heroCommitted: 0,
    villainCommitted: 0,
    history: [],
    over: false,
  };
}

function potAfter(bb) {
  if (!game) gameInit();
  game.pot += bb;
  return game.pot;
}

function fmtPot() {
  return (game ? game.pot : 0).toFixed(1) + "bb";
}

function streetName() {
  return game ? GAME_STREETS[game.streetIdx] : "翻牌";
}

// 我下注 X% → 底池增量 = 底池 × X%
function betAmount(pct) {
  if (!game) gameInit();
  return +(game.pot * (pct / 100)).toFixed(2);
}

function nextStreet() {
  if (!game) gameInit();
  game.history.push({ street: streetName(), note: "本街结束" });
  game.streetIdx += 1;
  game.streetBets = 0;
  if (game.streetIdx >= GAME_STREETS.length) {
    game.over = true;
    showShowdown();
    return;
  }
  const sel = document.getElementById("treeStreet");
  if (sel) sel.value = GAME_STREETS[game.streetIdx];
  playReset();
  if (typeof loadTree === "function") loadTree();
}

function showShowdown() {
  const box = document.getElementById("playActions");
  if (!box) return;
  box.innerHTML = `<div class="pa-row">
    <b style="color:#ffd479">河牌结束 · 底池 ${fmtPot()}</b>
    <button class="pbtn primary" onclick="gameInit();playReset();renderActions();">再来一手</button>
  </div>`;
}

// 我下注/加注后，对手的行动（含底池更新）
function heroBetAndVillainTurn(pct, label) {
  const amt = betAmount(pct);
  potAfter(amt);
  game.history.push({ street: streetName(), who: "我", act: label, amt });
  showVillain(1, amt);
}

function villainBetAndHeroTurn(pct, label, node) {
  const amt = betAmount(pct);
  potAfter(amt);
  game.history.push({ street: streetName(), who: "对手", act: label, amt });
  const sel = document.getElementById("treeAction");
  if (sel) sel.value = node || "对手大注";
  playPhase = 0;
  if (typeof loadTree === "function") loadTree();
}

// ── 行动流程：我 → 对手 → 我（可推进到下一街）──────────────────
// 状态：0=我方行动 1=对手响应 2=对手主动（我过牌后）
let playPhase = 0;
let playHeroAct = null;

function playReset() {
  playPhase = 0;
  playHeroAct = null;
}

// ── 对手视角：每种手牌的加注/跟注/弃牌频率 ──────────────────
function renderOpponentFreq() {
  const box = document.getElementById("oppFreqBox");
  if (!box) return;
  const f = window.__opponentFreq;
  if (!f || !f.length) { box.innerHTML = ""; return; }
  const vsRaw = (window.__treeState || {}).vs_type;
  const vs = (!vsRaw || vsRaw === "*") ? "标准" : vsRaw;
  const pos = (window.__treeState || {}).villain || "对手";
  const top = f.filter((x) => x.raise >= 5 || x.call >= 5).slice(0, 24);
  box.innerHTML = `
    <div class="of-head">
      <b>${esc(pos)} 在这里做什么</b>
      <span class="of-sub">按牌力排序 · 对手类型「${esc(vs)}」· 共 ${f.length} 种</span>
    </div>
    <div class="of-table">
      <div class="of-row of-th">
        <span>手牌</span><span>牌力</span><span>加注</span><span>跟注</span><span>弃/过</span>
      </div>` +
    top.map((x) => `<div class="of-row">
        <span class="of-combo">${esc(x.combo)}</span>
        <span class="of-cat">${esc(x.cat || "")}</span>
        <span class="of-bar"><i style="width:${x.raise}%;background:#ffc857"></i><b>${x.raise}</b></span>
        <span class="of-bar"><i style="width:${x.call}%;background:#3b82f6"></i><b>${x.call}</b></span>
        <span class="of-bar"><i style="width:${x.fold}%;background:#6b7280"></i><b>${x.fold}</b></span>
      </div>`).join("") +
    `</div>`;
}
function flowInfoHtml() {
  if (!game) gameInit();
  return `<div class="pa-row" style="margin-bottom:2px">
    <span class="pa-who" style="background:#1d2530;color:#8fa3b8">${esc(streetName())}</span>
    <span class="pa-act">底池 ${fmtPot()}</span>
  </div>`;
}

// ── 翻前分步流程：开池 → 3bet → (4bet/跟注) → (5bet/跟注) ──────
let pfStep = 0;          // 0=开池方 1=3bet方 2=4bet方 3=5bet方
let pfLog = [];          // [{pos, act, pct}]

async function pfShowRange(pos, kind) {
  try {
    const d = await fetch(`/api/preflop/range?pos=${encodeURIComponent(pos)}&opp=${encodeURIComponent((window.__treeState||{}).villain||"BB")}&kind=${kind}&freq=1&vs_type=${encodeURIComponent((document.getElementById("treeVsType")||{}).value||"*")}`).then(x=>x.json());
    if (!d.ok) return null;
    const box = document.getElementById("treeGrid");
    const meta = document.getElementById("treeMeta");
    if (box) {
      box.className = "treegrid";
      box.innerHTML = "";
      d.cells.forEach((c) => {
        const el = document.createElement("div");
        el.className = "treecell";
        const r = c.raise || 0, ca = c.call || 0, fo = c.fold || 0;
        if (r + ca <= 0) {
          el.style.background = "#131313"; el.style.color = "#454545"; el.style.opacity = "0.55";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">弃</span>`;
        } else {
          // 加注(红) → 跟注(蓝) → 弃牌(灰) 横向渐变，一眼看出混合比例
          el.style.background = `linear-gradient(to right, #c0392b 0% ${r}%, #2f6fb5 ${r}% ${r + ca}%, #2a2f36 ${r + ca}% 100%)`;
          el.style.color = "#fff";
          el.style.textShadow = "0 1px 3px rgba(0,0,0,.9)";
          const main = r >= ca ? r : ca;
          const tag = r >= ca ? "加" : "跟";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${tag}${main}</span>`;
          el.title = `${c.combo}｜加注 ${r}% 跟注 ${ca}% 弃牌 ${fo}%`;
        }
        box.appendChild(el);
      });
      const det = document.getElementById("treeDetail");
      const nr = d.cells.filter(x=>x.act==="raise").length;
      const nc = d.cells.filter(x=>x.act==="call").length;
      if (det) det.innerHTML = `<b style="color:#e06c75">■ 加注 ${nr} 类</b>　`
        + `<b style="color:#6aa9ff">■ 跟注 ${nc} 类</b>　`
        + `<b style="color:#6b7280">■ 弃牌 ${169-nr-nc} 类</b>`;
      box.insertAdjacentHTML("beforebegin", "");
    }
    if (meta) meta.innerHTML = `<b style="color:#ffd479">${esc(d.label)}</b> · 总计 ${d.pct}%（${d.cells.filter(c=>c.act!=="fold").length} 类）`;
    return d;
  } catch (e) { console.warn("pf range:", e); return null; }
}

function pfRender() {
  const box = document.getElementById("playActions");
  if (!box) return;
  const me = (document.getElementById("pfMe")||{}).value || "BTN";
  const opp = (document.getElementById("pfOpp")||{}).value || "BB";
  const seq = [
    { who: me,  act: "开池", kind: "open" },
    { who: opp, act: "3bet", kind: "3bet" },
  ];
  if (pfStep >= 2) seq.push({ who: me, act: pfLog[2] ? pfLog[2].act : "4bet", kind: pfLog[2] ? pfLog[2].kind : "4bet" });
  if (pfStep >= 3) seq.push({ who: opp, act: pfLog[3] ? pfLog[3].act : "5bet", kind: pfLog[3] ? pfLog[3].kind : "5bet" });

  let html = `<div class="pa-row" style="margin-bottom:4px">
    <span class="pa-who" style="background:#1d2530;color:#8fa3b8">翻前</span>
    <span class="pa-act">第 ${pfStep + 1} 步 · ${esc(pfStep % 2 === 0 ? me : opp)} 行动</span></div>`;
  pfLog.slice(0, pfStep + 1).forEach((x) => {
    html += `<div class="pa-row"><span class="pa-who">${esc(x.pos)}</span>
      <span class="pa-act">${esc(x.act)}</span>
      <span style="color:#7ddc9f;font-size:12px">${x.pct}%</span></div>`;
  });

  const cur = pfStep % 2 === 0 ? me : opp;
  const opts = pfStep === 0 ? [["开池", "open"]]
    : pfStep === 1 ? [["3bet", "3bet"], ["跟注", "call_open"], ["弃牌", "fold"]]
    : pfStep === 2 ? [["4bet", "4bet"], ["跟注", "call3bet"], ["弃牌", "fold"]]
    : [["5bet 全下", "5bet"], ["跟注", "call4bet"], ["弃牌", "fold"]];

  html += `<div class="pa-row"><span class="pa-who">${esc(cur)}</span>` +
    opts.map(([label, kind]) => `<button class="pbtn ${kind==="fold"?"muted":kind.includes("5bet")?"danger":"primary"}"
      data-pf="${kind}" data-pflabel="${esc(label)}">${esc(label)}</button>`).join("") +
    `<button class="pbtn" data-pf="next">→ 进翻后</button></div>`;

  box.innerHTML = html;
  box.querySelectorAll("[data-pf]").forEach((b) => {
    b.onclick = () => pfAct(b.dataset.pf, b.dataset.pflabel);
  });
}

async function pfAct(kind, label) {
  const me = (document.getElementById("pfMe")||{}).value || "BTN";
  const opp = (document.getElementById("pfOpp")||{}).value || "BB";
  const cur = pfStep % 2 === 0 ? me : opp;
  if (kind === "next") { goPostflop(); return; }
  if (kind === "fold") {
    document.getElementById("playActions").innerHTML =
      `<div class="pa-row"><b style="color:#c96">${esc(cur)} 弃牌 · 这手结束</b>
       <button class="pbtn" onclick="pfReset();pfRender()">重来</button></div>`;
    return;
  }
  const d = await pfShowRange(cur, kind === "call_open" ? "call3bet" : kind);
  const pct = d ? d.pct : "?";
  pfLog[pfStep] = { pos: cur, act: label, kind, pct };
  pfStep += 1;
  // 5bet 之后就没有更多加注了
  if (pfStep > 4 || (kind === "5bet")) {
    document.getElementById("playActions").innerHTML =
      `<div class="pa-row"><b style="color:#ffd479">${esc(cur)} 5bet 全下 · 翻前结束</b></div>`;
    return;
  }
  pfRender();
}

function pfReset() { pfStep = 0; pfLog = []; }

// ── 翻前：一条序列，谁做了什么按顺序排 ──────────────────────

function pfPositionsAll() { return posList(); }

function bindSpotInputs() {
  const on = (id, fn) => {
    const e = document.getElementById(id);
    if (e && !e.dataset.spotBound) { e.dataset.spotBound = "1"; e.addEventListener("change", fn); }
  };
  const val = (id) => { const e = document.getElementById(id); return e ? e.value : ""; };
  on("treeTableType", () => { Spot.setTableType(val("treeTableType")); if (typeof pfSeqRender === "function") pfSeqRender(); });
  on("treeHeroStack", () => Spot.setStacks(val("treeHeroStack"), val("treeVillainStack")));
  on("treeVillainStack", () => Spot.setStacks(val("treeHeroStack"), val("treeVillainStack")));
  on("treeVsType", () => Spot.setVsType(val("treeVsType"), val("treeVsType2")));
  on("treeVsType2", () => Spot.setVsType(val("treeVsType"), val("treeVsType2")));
  on("treeStreet", () => Spot.setStreet(val("treeStreet")));
}

function pfNextCandidates() {
  // 候选 = 还在牌局里的人（没弃牌）。
  // 关键：不能按「还没行动过」过滤 —— 4bet/5bet 就是同一个人再行动一次。
  const folded = new Set(Spot.state.seq.filter((x) => x.kind === "fold").map((x) => x.pos));
  const all = pfPositionsAll();
  const alive = all.filter((p) => !folded.has(p));
  return alive;
}

function pfSeqRender() {
  const box = document.getElementById("pfSeqBox");
  if (!box) return;
  const steps = Spot.state.seq.map((x, i) => {
    const color = x.act.includes("弃") ? "#6b7280" : x.act.includes("跟") ? "#2f6fb5" : "#c0392b";
    return `<span class="pf-chip" data-step="${i}" style="border-color:${color}">
      <b>${esc(x.pos)}</b> ${esc(x.act)}
      ${x.pct != null ? `<i style="color:#7ddc9f">${x.pct}%</i>` : ""}
    </span>`;
  }).join(`<span class="pf-arrow">→</span>`);

  const cands = pfNextCandidates();
  // 按「第几次加注」给动作：开池 → 3bet → 4bet → 5bet(全下)
  const acts = Spot.nextActions();
  box.innerHTML = (steps || `<div class="pf-empty">还没有动作，从下方添加第一步</div>`)
    + `<div class="pf-add">
        <select id="pfNextPos" class="pf-mini">${cands.map((p) => `<option>${p}</option>`).join("")}</select>
        <select id="pfNextAct" class="pf-mini">${acts.map((a) => `<option>${a}</option>`).join("")}</select>
        <button class="pbtn primary pf-mini-btn" id="pfAddBtn">+ 添加</button>
        <button class="pbtn pf-mini-btn" id="pfClearBtn">清空</button>
      </div>`;

  box.querySelectorAll("[data-step]").forEach((el) => {
    el.title = "点一下回退到这一步（后面的会删掉）";
    el.onclick = () => {
      const i = Number(el.dataset.step);
      const keep = Math.min(i + 1, Spot.state.seq.length);
      if (keep < Spot.state.seq.length) {
        Spot.bump((st) => { st.seq = st.seq.slice(0, keep); });
        toast(`已回退到第 ${keep} 步`);
        pfSeqRender();
        if (typeof loadTree === "function") loadTree();
      }
    };
  });
  const add = document.getElementById("pfAddBtn");
  if (add) add.onclick = pfAddStep;
  const clr = document.getElementById("pfClearBtn");
  if (clr) clr.onclick = () => {
    const n = Spot.state.seq.length;
    if (n && !confirm(`清空全部 ${n} 步，重新开始？`)) return;
    Spot.clearSeq();
    pfReset();
    pfSeqRender();
    if (typeof loadTree === "function") loadTree();
  };
}

function pfAddStep() {
  const pos = (document.getElementById("pfNextPos") || {}).value;
  const act = (document.getElementById("pfNextAct") || {}).value;
  if (!pos || !act) return;
  if (act === "弃牌") {
    // 弃牌不进序列（他只影响人数），直接记一笔并重绘
    Spot.addStep({ pos, act, kind: "fold", pct: null });
    pfSeqRender();
    return;
  }
  const kind = Spot.kindOf(act);
  const d = Spot.derive();
  const opp = d.opener === "hero" ? d.villain : (d.seq && d.seq.opener ? d.seq.opener.pos : (d.villain || "BB"));
  Spot.addStep({ pos, act, kind, pct: null });
  const d2 = Spot.derive();
  pfShowRange(pos, kind, d2.villain).then((r) => {
    if (r) {
      const st = Spot.state;
      const last = st.seq[st.seq.length - 1];
      if (last && last.pos === pos) last.pct = r.pct;
    }
    pfSeqRender();
  });
  pfSeqRender();
  if (typeof loadTree === "function") loadTree();
}

async function pfShowRange(pos, kind) {
  try {
    const d = await fetch(`/api/preflop/range?pos=${encodeURIComponent(pos)}&opp=${encodeURIComponent((window.__treeState||{}).villain||"BB")}&kind=${kind}&freq=1&vs_type=${encodeURIComponent((document.getElementById("treeVsType")||{}).value||"*")}`).then(x=>x.json());
    if (!d.ok) return null;
    const box = document.getElementById("treeGrid");
    const meta = document.getElementById("treeMeta");
    if (box) {
      box.className = "treegrid";
      box.innerHTML = "";
      d.cells.forEach((c) => {
        const el = document.createElement("div");
        el.className = "treecell";
        const r = c.raise || 0, ca = c.call || 0, fo = c.fold || 0;
        if (r + ca <= 0) {
          el.style.background = "#131313"; el.style.color = "#454545"; el.style.opacity = "0.55";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">弃</span>`;
        } else {
          // 加注(红) → 跟注(蓝) → 弃牌(灰) 横向渐变，一眼看出混合比例
          el.style.background = `linear-gradient(to right, #c0392b 0% ${r}%, #2f6fb5 ${r}% ${r + ca}%, #2a2f36 ${r + ca}% 100%)`;
          el.style.color = "#fff";
          el.style.textShadow = "0 1px 3px rgba(0,0,0,.9)";
          const main = r >= ca ? r : ca;
          const tag = r >= ca ? "加" : "跟";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${tag}${main}</span>`;
          el.title = `${c.combo}｜加注 ${r}% 跟注 ${ca}% 弃牌 ${fo}%`;
        }
        box.appendChild(el);
      });
      const det = document.getElementById("treeDetail");
      const nr = d.cells.filter(x=>x.act==="raise").length;
      const nc = d.cells.filter(x=>x.act==="call").length;
      if (det) det.innerHTML = `<b style="color:#e06c75">■ 加注 ${nr} 类</b>　`
        + `<b style="color:#6aa9ff">■ 跟注 ${nc} 类</b>　`
        + `<b style="color:#6b7280">■ 弃牌 ${169-nr-nc} 类</b>`;
      box.insertAdjacentHTML("beforebegin", "");
    }
    if (meta) meta.innerHTML = `<b style="color:#ffd479">${esc(d.label)}</b> · 总计 ${d.pct}%（${d.cells.filter(c=>c.act!=="fold").length} 类）`;
    return d;
  } catch (e) { console.warn("pf range:", e); return null; }
}

function pfRender() {
  const box = document.getElementById("playActions");
  if (!box) return;
  const me = (document.getElementById("pfMe")||{}).value || "BTN";
  const opp = (document.getElementById("pfOpp")||{}).value || "BB";
  const seq = [
    { who: me,  act: "开池", kind: "open" },
    { who: opp, act: "3bet", kind: "3bet" },
  ];
  if (pfStep >= 2) seq.push({ who: me, act: pfLog[2] ? pfLog[2].act : "4bet", kind: pfLog[2] ? pfLog[2].kind : "4bet" });
  if (pfStep >= 3) seq.push({ who: opp, act: pfLog[3] ? pfLog[3].act : "5bet", kind: pfLog[3] ? pfLog[3].kind : "5bet" });

  let html = `<div class="pa-row" style="margin-bottom:4px">
    <span class="pa-who" style="background:#1d2530;color:#8fa3b8">翻前</span>
    <span class="pa-act">第 ${pfStep + 1} 步 · ${esc(pfStep % 2 === 0 ? me : opp)} 行动</span></div>`;
  pfLog.slice(0, pfStep + 1).forEach((x) => {
    html += `<div class="pa-row"><span class="pa-who">${esc(x.pos)}</span>
      <span class="pa-act">${esc(x.act)}</span>
      <span style="color:#7ddc9f;font-size:12px">${x.pct}%</span></div>`;
  });

  const cur = pfStep % 2 === 0 ? me : opp;
  const opts = pfStep === 0 ? [["开池", "open"]]
    : pfStep === 1 ? [["3bet", "3bet"], ["跟注", "call_open"], ["弃牌", "fold"]]
    : pfStep === 2 ? [["4bet", "4bet"], ["跟注", "call3bet"], ["弃牌", "fold"]]
    : [["5bet 全下", "5bet"], ["跟注", "call4bet"], ["弃牌", "fold"]];

  html += `<div class="pa-row"><span class="pa-who">${esc(cur)}</span>` +
    opts.map(([label, kind]) => `<button class="pbtn ${kind==="fold"?"muted":kind.includes("5bet")?"danger":"primary"}"
      data-pf="${kind}" data-pflabel="${esc(label)}">${esc(label)}</button>`).join("") +
    `<button class="pbtn" data-pf="next">→ 进翻后</button></div>`;

  box.innerHTML = html;
  box.querySelectorAll("[data-pf]").forEach((b) => {
    b.onclick = () => pfAct(b.dataset.pf, b.dataset.pflabel);
  });
}

async function pfAct(kind, label) {
  const me = (document.getElementById("pfMe")||{}).value || "BTN";
  const opp = (document.getElementById("pfOpp")||{}).value || "BB";
  const cur = pfStep % 2 === 0 ? me : opp;
  if (kind === "next") { goPostflop(); return; }
  if (kind === "fold") {
    document.getElementById("playActions").innerHTML =
      `<div class="pa-row"><b style="color:#c96">${esc(cur)} 弃牌 · 这手结束</b>
       <button class="pbtn" onclick="pfReset();pfRender()">重来</button></div>`;
    return;
  }
  const d = await pfShowRange(cur, kind === "call_open" ? "call3bet" : kind);
  const pct = d ? d.pct : "?";
  pfLog[pfStep] = { pos: cur, act: label, kind, pct };
  pfStep += 1;
  // 5bet 之后就没有更多加注了
  if (pfStep > 4 || (kind === "5bet")) {
    document.getElementById("playActions").innerHTML =
      `<div class="pa-row"><b style="color:#ffd479">${esc(cur)} 5bet 全下 · 翻前结束</b></div>`;
    return;
  }
  pfRender();
}

function pfReset() { pfStep = 0; pfLog = []; }

// ── 翻前：一条序列，谁做了什么按顺序排 ──────────────────────
// pfSeq 已废弃：唯一真源是 Spot.state.seq

async function pfShowRange(pos, kind, oppArg) {
  try {
    const opp = oppArg || (document.getElementById("treeVillain") || {}).value || "BB";
    const d = await fetch(`/api/preflop/range?pos=${encodeURIComponent(pos)}&opp=${encodeURIComponent(opp)}&kind=${kind}&freq=1&vs_type=${encodeURIComponent((document.getElementById("treeVsType")||{}).value||"*")}`).then(x=>x.json());
    if (!d.ok) return null;
    const box = document.getElementById("treeGrid");
    const meta = document.getElementById("treeMeta");
    if (box) {
      box.className = "treegrid";
      box.innerHTML = "";
      d.cells.forEach((c) => {
        const el = document.createElement("div");
        el.className = "treecell";
        const r = c.raise || 0, ca = c.call || 0, fo = c.fold || 0;
        if (r + ca <= 0) {
          el.style.background = "#131313"; el.style.color = "#454545"; el.style.opacity = "0.55";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">弃</span>`;
        } else {
          el.style.background = `linear-gradient(to right, #c0392b 0% ${r}%, #2f6fb5 ${r}% ${r + ca}%, #2a2f36 ${r + ca}% 100%)`;
          el.style.color = "#fff"; el.style.textShadow = "0 1px 3px rgba(0,0,0,.9)";
          el.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${r>=ca?"加":"跟"}${r>=ca?r:ca}</span>`;
          el.title = `${c.combo}｜加 ${r}% 跟 ${ca}% 弃 ${fo}%`;
        }
        box.appendChild(el);
      });
    }
    // ── 同步整屏，别只换网格 ──────────────────────────────
    // 以前只更新 #treeGrid，下面的牌桌/频率条还是上一个节点的
    // （UTG 开池 19.9%），看起来就像「3bet 之后范围变成开池范围」。
    const wOf = (h) => (h.length === 2 ? 6 : (h.endsWith("s") ? 4 : 12));
    const w = { raise: 0, call: 0, fold: 0 };
    let total = 0;
    (d.cells || []).forEach((c) => {
      const n = wOf(c.combo || "");
      total += n;
      w.raise += n * (c.raise || 0) / 100;
      w.call += n * (c.call || 0) / 100;
      w.fold += n * (c.fold || 0) / 100;
    });
    const pctOf = (x) => (total > 0 ? Math.round((x / total) * 1000) / 10 : 0);
    const actCN = kind === "3bet" ? "3bet" : kind === "4bet" ? "4bet" : kind === "5bet" ? "5bet 全下" : "开池";
    const acts = [
      { kind: "raise", label: actCN, color: "#c0392b", combos: Math.round(w.raise * 10) / 10, pct: pctOf(w.raise) },
      { kind: "跟注", label: "跟注", color: "#2e86c1", combos: Math.round(w.call * 10) / 10, pct: pctOf(w.call) },
      { kind: "弃牌", label: "弃牌", color: "#41535f", combos: Math.round(w.fold * 10) / 10, pct: pctOf(w.fold) },
    ].filter((a) => a.pct > 0.05);
    try {
      renderFreqBar({
        freq: { total_combos: Math.round(total), bet_combos: Math.round(w.raise + w.call),
                bet_pct: pctOf(w.raise + w.call), actions: acts },
        preflop: {}, bluff: null,
      }, `翻前范围 · ${pos} ${actCN} ${opp}`);
    } catch (e) { console.warn("pf freq:", e); }
    try {
      const st = Spot.derive();
      const hv = (document.getElementById("treeHeroStack") || {}).value || "100bb";
      const vv = (document.getElementById("treeVillainStack") || {}).value || "*";
      // 强抓：有效筹码按一半算，座位标签也要跟着变（跟 loadTree 同一套）
      const tt = (document.getElementById("treeTableType") || {}).value || "";
      const half = (x) => {
        const n = parseFloat(String(x));
        return Number.isNaN(n) ? x : Math.max(5, Math.round(n / 2)) + "bb";
      };
      const straddle = String(tt).includes("强抓");
      const hShow = straddle ? half(hv) : hv;
      const vShow = straddle ? (vv !== "*" ? half(vv) : hShow) : vv;
      renderPokerTable({
        hero: pos, villain: opp, pot: st.pot || "SRP", street: "翻前",
        heroStack: hShow, villainStack: vShow, stack: hShow, board: "",
      }, {});
      const pa = document.getElementById("playActions");
      if (pa) pa.innerHTML = "";
    } catch (e) { console.warn("pf table:", e); }
    for (const id of ["mixSummary", "lockedPanel", "treeGuarantee"]) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = "";
    }
    const det = document.getElementById("treeDetail");
    if (det) {
      det.innerHTML = `<b style="color:#ffd479">这一步的可选范围</b>：` +
        `加注/3bet <b>${pctOf(w.raise)}%</b>　跟注 <b>${pctOf(w.call)}%</b>　弃牌 <b>${pctOf(w.fold)}%</b>。` +
        ` <span style="color:#8a929c">进翻后只保留你实际选择的那一个动作的范围（点「添加」记录的动作），不会把跟注范围带进去。</span>`;
    }
    window.__treeState = { hero: pos, villain: opp, pot: (Spot.derive() || {}).pot || "SRP", street: "翻前" };
    if (meta) {
      const flat = w.call > 0.5
        ? ` <span style="color:#2e86c1">· 平跟 ${pctOf(w.call)}%</span>`
        : "";
      meta.innerHTML = `<b style="color:#ffd479">${esc(d.label)}</b> · ${d.pct}%${flat}`;
    }
    return d;
  } catch (e) { console.warn("pf range:", e); return null; }
}

// ── 保证标签 + 版本对比 + 锁定清单（按求解工作台的「版本与对比」组织）──
let baselineSnap = null;   // 基线快照，用来做对比

function renderGuarantee(g) {
  const el = document.getElementById("treeGuarantee");
  if (!el) return;
  if (!g) { el.innerHTML = ""; return; }
  el.innerHTML = `<span class="g-badge" style="background:${g.color}22;color:${g.color};border-color:${g.color}55"
      title="${esc(g.why || "")}">● ${esc(g.label)}</span>
    <span class="g-src">${esc(g.source || "")}</span>
    ${g.split ? `<span class="g-split" title="${esc(g.split)}">${esc(g.split)}</span>` : ""}
    ${(window.__locks && window.__locks.length) ? `<span class="g-lock">⚖ ${window.__locks.length} 处锁定</span>` : ""}`;
}

function snapCurrent() {
  const st = window.__treeState || {};
  return {
    rule: (window.__ruleInfo || {}).sizing,
    freq: (window.__ruleInfo || {}).freq,
    avg: window.__rangeBetPct,
    label: (document.getElementById("treeMeta")?.textContent || "").slice(0, 70),
    acts: (window.__nodeActions || []).map((a) => a.label),
    cells: (window.__treeCells || []).map((c) => c.bucket),
  };
}

function takeBaseline() {
  baselineSnap = snapCurrent();
  toast("已把当前设为基线");
  renderVersionBar();
}

function compareWithBaseline() {
  if (!baselineSnap) { toast("先设一个基线"); return; }
  const now = snapCurrent();
  const box = document.getElementById("compareBox");
  if (!box) return;
  const da = now.avg != null && baselineSnap.avg != null ? (now.avg - baselineSnap.avg) : null;
  const changed = (a, b) => (a || []).filter((x, i) => x !== (b || [])[i]).length;
  const nc = changed(now.cells, baselineSnap.cells);
  let concl = "";
  if (da != null && Math.abs(da) >= 0.5) {
    concl = `整体下注率 ${da > 0 ? "+" : ""}${da.toFixed(1)} 个点`;
  }
  if (nc) concl += (concl ? "，" : "") + `${nc} 手牌的混合比例变了`;
  if (now.rule !== baselineSnap.rule) concl += (concl ? "，" : "") + `尺度从 ${baselineSnap.rule} 改成 ${now.rule}`;
  box.innerHTML = `<div class="cmp-head">对比：基线 → 当前</div>
    <div class="cmp-row"><span>尺度</span><b>${esc(baselineSnap.rule || "—")}</b> → <b>${esc(now.rule || "—")}</b></div>
    <div class="cmp-row"><span>范围下注率</span><b>${baselineSnap.avg}%</b> → <b>${now.avg}%</b>
      <i style="color:${da > 0 ? "#3ba55d" : da < 0 ? "#e06c75" : "#8a929c"}">${da != null ? (da > 0 ? "+" : "") + da.toFixed(1) : ""}</i></div>
    <div class="cmp-row"><span>手牌变化</span><b>${nc}</b> 处</div>
    <div class="cmp-concl">${esc(concl || "没有明显变化")}</div>`;
}

// ── 锁定编辑器：点座位 → 派生新版本（对齐求解工作台的设计）─────
let lockEditPos = null;

function openLockEditor(pos) {
  lockEditPos = pos;
  const old = document.getElementById("lockDrawer");
  if (old) old.remove();
  const cur = (window.__locks || []).find((c) => c.pos === pos) || {};
  const types = ["*", "标准", "紧凶", "松凶", "岩石", "受气包", "跟注站", "娱乐玩家", "过度诈唬型", "下注不足型"];
  const stacks = ["*", "20bb", "50bb", "100bb", "200bb"];
  const d = document.createElement("div");
  d.id = "lockDrawer";
  d.className = "lock-drawer";
  d.innerHTML = `
    <div class="ld-head">
      <b>派生新版本 · ${esc(POS_CN[pos] || pos)}${esc(pos)}</b>
      <button class="ld-x" onclick="closeLockEditor()">✕</button>
    </div>
    <div class="ld-tabs">
      <button class="ld-tab on" data-lt="type">对手画像</button>
      <button class="ld-tab" data-lt="range">范围</button>
      <button class="ld-tab" data-lt="strat">策略</button>
    </div>
    <div class="ld-body">
      <div class="ld-pane" data-lp="type">
        <label>对手形象</label>
        <select id="ldType">${types.map((t) => `<option value="${t}"${(cur.player_type||"*")===t?" selected":""}>${t === "*" ? "不锁定（用默认）" : t}</option>`).join("")}</select>
        <label>筹码深度</label>
        <select id="ldStack">${stacks.map((t) => `<option value="${t}"${(cur.stack||"*")===t?" selected":""}>${t === "*" ? "不锁定（同全局）" : t}</option>`).join("")}</select>
        <div class="ld-note">选了形象后，这个位置的翻前范围会按该形象调整。</div>
      </div>
      <div class="ld-pane hidden" data-lp="range">
        <label>自定义范围（13×13 上选，或直接写文本）</label>
        <textarea id="ldRange" rows="4" placeholder="如：QQ+, AKs, AKo, A5s">${esc(cur.payload || "")}</textarea>
        <div class="ld-note">留空 = 不锁定范围，用该位置的默认范围。</div>
      </div>
      <div class="ld-pane hidden" data-lp="strat">
        <label>策略锁定（高级）</label>
        <div class="ld-note">把该节点某个动作固定成指定频率。当前版本先开放「强制动作」。</div>
        <select id="ldForce">
          <option value="">不锁定</option>
          <option value="bet">强制下注</option>
          <option value="check">强制过牌</option>
          <option value="fold">强制弃牌</option>
        </select>
      </div>
    </div>
    <div class="ld-foot">
      <span id="ldCost">将创建 v${(window.__locks||[]).length ? "2" : "2"}（从 v1 派生）· 本机即时生效</span>
      <button class="pbtn primary" id="ldApply">应用</button>
      <button class="pbtn muted" id="ldRemove">移除这条锁定</button>
    </div>`;
  document.body.appendChild(d);
  d.querySelectorAll(".ld-tab").forEach((b) => {
    b.onclick = () => {
      d.querySelectorAll(".ld-tab").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      d.querySelectorAll(".ld-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.lp !== b.dataset.lt));
    };
  });
  document.getElementById("ldApply").onclick = async () => {
    const type = document.getElementById("ldType").value;
    const stack = document.getElementById("ldStack").value;
    const range = (document.getElementById("ldRange").value || "").trim();
    await setLock({ pos, ctype: "range", payload: range, player_type: type, stack,
                    note: [type !== "*" ? type : "", range ? "自定义范围" : ""].filter(Boolean).join(" · ") });
    closeLockEditor();
  };
  document.getElementById("ldRemove").onclick = async () => {
    await setLock({ action: "remove", pos });
    closeLockEditor();
  };
}

function closeLockEditor() {
  const d = document.getElementById("lockDrawer");
  if (d) d.remove();
  lockEditPos = null;
}

async function refreshLocks() {
  try {
    const d = await fetch("/api/locks").then((x) => x.json());
    window.__locks = d.constraints || [];
    const box = document.getElementById("lockList");
    if (box) {
      box.innerHTML = window.__locks.length
        ? `<div class="lk-head">锁定清单 <button class="mini-btn" onclick="clearAllLocks()">全部移除</button></div>`
          + window.__locks.map((c) => `<div class="lk-item"><b>${esc(c.pos)}</b>
              ${c.player_type && c.player_type !== "*" ? `<span>${esc(c.player_type)}</span>` : ""}
              ${c.stack && c.stack !== "*" ? `<span>${esc(c.stack)}</span>` : ""}
              <button class="mini-btn" data-unlock="${esc(c.pos)}">移除</button></div>`).join("")
        : `<div class="lk-empty">没有锁定</div>`;
      box.querySelectorAll("[data-unlock]").forEach((b) => {
        b.onclick = () => setLock({ action: "remove", pos: b.dataset.unlock });
      });
    }
    renderVersionBar();
  } catch (e) { console.warn("locks:", e); }
}

async function setLock(body) {
  try {
    await fetch("/api/locks", { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body) }).then((x) => x.json());
    await refreshLocks();
    if (typeof loadTree === "function") loadTree();
  } catch (e) { console.warn("setLock:", e); }
}

async function clearAllLocks() {
  await fetch("/api/locks", { method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ action: "clear" }) }).then((x) => x.json());
  await refreshLocks();
  if (typeof loadTree === "function") loadTree();
}

function bindMainCta() {
  const btn = document.getElementById("mainCta");
  const hint = document.getElementById("ctaHint");
  if (!btn) return;
  const sync = () => {
    const pre = ($("#treeStreet") || {}).value === "翻前";
    btn.textContent = pre ? "打完翻前 · 进翻后" : "分析这个局面";
    if (hint) hint.textContent = pre
      ? "带着翻前范围进入翻后，参数自动带过去"
      : "结果自动刷新；点这里把当前配置设为基线，方便对比";
  };
  btn.onclick = () => {
    const pre = ($("#treeStreet") || {}).value === "翻前";
    if (pre) { goPostflop(); return; }
    takeBaseline();
    toast("已把当前局面设为基线");
  };
  const st = document.getElementById("treeStreet");
  if (st) st.addEventListener("change", sync);
  sync();
}

function openDiagnostics() {
  const d = window.__diagnostics || {};
  const old = document.getElementById("diagDrawer");
  if (old) { old.remove(); return; }
  const box = document.createElement("div");
  box.id = "diagDrawer";
  box.className = "diag-drawer";
  box.innerHTML = `<div class="ld-head"><b>⚙ 诊断（内部信息）</b>
      <button class="ld-x" onclick="openDiagnostics()">✕</button></div>
    <div class="diag-body">`
    + Object.entries(d).map(([k, val]) =>
        `<div class="diag-row"><span>${esc(k)}</span><b>${esc(String(val == null ? "—" : val))}</b></div>`).join("")
    + `</div><div class="diag-foot">这些是数据库 ID 和内部状态，出问题时截图给开发者用。</div>`;
  document.body.appendChild(box);
}

function renderVersionBar() {
  const bar = document.getElementById("versionBar");
  if (!bar) return;
  const n = (window.__locks || []).length;
  bar.innerHTML = `<span class="v-label">版本</span>
    <span class="v-chip ${!n ? "on" : ""}">v1 基线</span>
    ${n ? `<span class="v-chip on">v2 锁定 ${n}</span>` : ""}
    <button class="v-btn" onclick="takeBaseline()">设为基线</button>
    <button class="v-btn" onclick="compareWithBaseline()">对比</button>
    <span class="spacer"></span>
    <span class="v-hint">${n ? "当前结果已锁定，注意对比基线" : "纯规则结果"}</span>`;
}

// ── 混合策略展示：聚合频率 + 边界手牌（不报每手牌精确百分比）──
// ── 锁定生效面板：把「基线 → 现在」的变化显示出来 ───────────
function renderLockedPanel(d) {
  const el = document.getElementById("lockedPanel");
  if (!el) return;
  const lk = d.locked;
  if (!lk || !lk.ok) { el.innerHTML = ""; return; }
  const b = lk.baseline || {};
  const arrow = (a, c, unit = "%") => {
    if (a == null || c == null) return esc(String(c));
    const diff = c - a;
    const col = diff > 0 ? "#3ba55d" : diff < 0 ? "#e06c75" : "#8a929c";
    const sign = diff > 0 ? "+" : "";
    return `<b>${esc(String(a))}${unit}</b> <span style="color:${col}">→ ${esc(String(c))}${unit} (${sign}${Math.round(diff * 10) / 10})</span>`;
  };
  el.innerHTML = `<div class="lkp-head">⚖ 锁定生效
      <span class="lkp-type">对手：${esc(lk.opp_type || "*")}</span></div>
    <div class="lkp-row"><span>下注尺度</span>${arrow(b.sizing, lk.br_sizing)}</div>
    <div class="lkp-row"><span>下注频率</span>${arrow(b.freq, lk.freq)}</div>
    <div class="lkp-row"><span>我方胜率</span><b>${(lk.equity * 100).toFixed(1)}%</b>
      <i class="lkp-adv">（范围优势 ${(lk.adv * 100).toFixed(1)}%）</i></div>
    <div class="lkp-why">${esc(lk.freq_why || lk.why || "")}</div>
    <div class="lkp-note">这是按你锁定的对手形象推的启发式结果，不是 solver 真值</div>`;
}

function bluffDetailHtml(combo) {
  const p = window.__bluffPlan;
  if (!p || !p.ok || !p.ranked || !p.ranked.length) return "";
  const rows = p.ranked.filter((x) => x.combo === combo);
  if (!rows.length) return "";
  const sel = rows.filter((x) => x.selected).length;
  const chips = rows.map((x) => `
    <span class="bl-chip ${x.selected ? "on" : ""}" title="挡强牌 ${(x.block_strong * 100).toFixed(0)}% · 挡弱牌 ${(x.block_weak * 100).toFixed(0)}% · 修正后弃牌率 ${(x.f * 100).toFixed(0)}%">
      <b>#${x.rank}</b><span class="bl-cards">${esc(x.cards)}</span>
      <em>${x.surplus >= 0 ? "+" : ""}${x.surplus.toFixed(3)}</em>
      <i>${x.selected ? "诈唬" : "过牌"}</i>
    </span>`).join("");
  return `<div class="bl-wrap">
    <div class="bl-head">诈唬排序 · 按 EV surplus 从高到低
      <span class="bl-sub">配额 ${p.target.toFixed(1)} 组合 · 选中 ${sel}/${rows.length} 手</span></div>
    <div class="bl-chips">${chips}</div>
    <div class="bl-note">挡掉对手 30% 强牌 → 他更难跟 → 弃牌率升 → 更该诈唬；挡掉他本来会弃的弱牌 → 反而不该诈唬。</div>
  </div>`;
}

function renderFreqBar(d, title) {
  const el = document.getElementById("freqBar");
  if (!el) return;
  const f = d.freq;
  if (!f || !f.actions || !f.actions.length) { el.innerHTML = ""; return; }
  const segs = f.actions.map((a) =>
    `<i style="width:${a.pct}%;background:${a.color}" title="${esc(a.label)} ${a.pct}%（${a.combos} 组合）"></i>`).join("");
  const chips = f.actions.map((a) =>
    `<span class="fr-chip"><i style="background:${a.color}"></i>${esc(a.label)}
      <b>${a.pct}%</b><em>${a.combos} 组合</em></span>`).join("");
  const pf = d.preflop || {};
  const pfTxt = (pf.ok && (pf.hero_pct != null || pf.villain_pct != null))
    ? `<div class="fr-pre">翻前：${esc(pf.label || "")}
        <span class="fr-pre-r">我方 ${pf.hero_pct ?? "—"}% · 对手 ${pf.villain_pct ?? "—"}% 组合</span>
        <span class="fr-pre-note">范围已带进翻后（${esc(pf.hero_label || "我方")}${pf.villain_label ? " / " + esc(pf.villain_label) : ""}）</span></div>`
    : "";
  const b = d.bluff || null;
  const bluffTxt = (b && b.ok)
    ? `<div class="fr-bluff">诈唬构成：${b.size_pct}% 池按 alpha 配额 ${b.quota.toFixed(1)} 组合，
        桶表空气 ${b.air_available.toFixed(1)} → 按 EV surplus 排序只留 <b>${b.selected}</b> 组合</div>`
    : (b && b.why ? `<div class="fr-bluff muted">诈唬构成：${esc(b.why)}</div>` : "");
  el.innerHTML = `<div class="fr-head">${esc(title || "节点频率")}
      <span class="fr-sub">按组合加权 · 共 ${f.total_combos} 个组合 · 有动作 ${f.bet_combos} 个</span></div>
    <div class="fr-bar">${segs}</div>
    <div class="fr-chips">${chips}</div>
    ${pfTxt}${bluffTxt}`;
}

function renderMixSummary(d) {
  const el = document.getElementById("mixSummary");
  if (!el) return;
  const m = d.mix_display;
  const multiOn = (() => { const c = document.getElementById("treeMulti"); return c && c.checked; })();
  if (!multiOn || !m) { el.innerHTML = ""; return; }
  const bd = (m.boundary || []).slice(0, 6)
    .map((x) => `<span class="bd-chip" title="${esc(x.hand)} ${esc(x.cat || "")}｜临界">${esc(x.hand)}</span>`).join("");
  const betPct = (d.freq && d.freq.bet_pct != null) ? d.freq.bet_pct : m.aggregate_freq;
  el.innerHTML = `<div class="mix-head">混合策略（${(d.strategy_mode || {}).n_sizing || "?"} 个尺度）</div>
    <div class="mix-row"><span>整体出牌频率</span><b class="mix-agg">${betPct}%</b>
      <span class="mix-note">按组合加权</span></div>
    <div class="mix-row"><span>可动作手牌</span><b>${m.acted_count} 类</b></div>
    <div class="mix-row" style="align-items:flex-start"><span>边界手牌</span>
      <div class="bd-list">${bd || "无"}<div class="bd-tip">这些牌「可打可过」，记住边界比背百分比有用</div></div></div>
    <div class="mix-warn">⚠ ${esc(m.note || "")}</div>`;
}

function goPostflop() {
  // 带着翻前的范围/位置/底池进入翻后
  // 注意：必须先改 Spot 的状态。derivePreflopUI() 会用 Spot.apply()
  // 把 treeStreet 写回去，只改 DOM 会在下一步被覆盖回「翻前」。
  try { Spot.setStreet("翻牌"); } catch (e) {}
  const st = document.getElementById("treeStreet");
  if (st) st.value = "翻牌";
  syncTableType();
  derivePreflopUI();
  // 进翻后第一件事：确定谁先说话。
  // 不重置的话 treeAction 还停在翻前的「开池」，翻后节点会查不到规则。
  try {
    const d = Spot.derive();
    const role = roleFrom(d.hero, d.villain, d.opener, d.pot);
    const oop = role.startsWith("OOP") || role === "BvB-BB";
    const act = document.getElementById("treeAction");
    if (act) act.value = oop ? "无" : "对手过牌";
  } catch (e) {}
  const bh = document.getElementById("boardHint");
  if (bh) bh.style.display = "";
  playReset();
  if (typeof loadTree === "function") loadTree();
}

function renderActions() {
  const box = document.getElementById("playActions");
  if (!box) return;
  // 翻前 5bet = 全下，没有翻后
  if (typeof isAllInPre === "function" && isAllInPre()) {
    box.innerHTML = `<div class="pa-row">
      <b style="color:#ffd479">翻前 5bet 全下 · 没有翻后行动</b>
      <span class="hint">这手牌在翻前结束（或直接进全下摊牌）</span>
    </div>`;
    const g = document.getElementById("treeGrid");
    if (g) g.innerHTML = "";
    return;
  }
  const v = window.__treeState || {};
  const heroActs = window.__nodeActions || [];
  const vilActs = window.__villainActions || [];

  if (!game) gameInit();
  const info = flowInfoHtml();
  if ((window.__treeState || {}).street === "翻前") {
    pfSeqRender();
    return;
  }
  if (playPhase === 0) {
    box.innerHTML = info + `<div class="pa-row"><span class="pa-who me">我</span>` +
      heroActs.map((a) => `<button class="pbtn ${a.kind === "allin" ? "danger" : a.kind === "check" ? "" : a.kind === "fold" ? "muted" : "primary"}"
        data-pa="${esc(a.label)}" data-kind="${esc(a.kind)}">${esc(a.label)}</button>`).join("") +
      `</div>`;
    box.querySelectorAll("[data-pa]").forEach((b) => {
      b.onclick = () => {
        const label = b.dataset.pa, kind = b.dataset.kind;
        playHeroAct = { label, kind };
        playPhase = 1;
        renderActions();
        if (kind === "check") {
          // 我过牌 → 对手可以过牌或下注
          showVillain(0);
        } else if (kind === "fold") {
          box.innerHTML = `<div class="pa-row"><span class="pa-who me">我</span><b style="color:#c96">弃牌，这手结束</b>
            <button class="pbtn" onclick="playReset();renderActions();">重来</button></div>`;
        } else {
          // 我下注/加注 → 记底池，对手面对下注
          const pct = parseFloat((label.match(/(\d+)/) || [])[1] || 0);
          if (!game) gameInit();
          if (pct) { const amt = betAmount(pct); potAfter(amt);
            game.history.push({street: streetName(), who:"我", act: label, amt}); }
          else { potAfter(game.pot); game.history.push({street:streetName(), who:"我", act:label}); }
          showVillain(1);
        }
      };
    });
  }
}

function showVillain(mode) {
  const box = document.getElementById("playActions");
  const vilActs = window.__villainActions || [];
  let opts = wilActsFor(mode);
  // 切到对手行动 → 矩阵换成对手范围
  switchRangeTo("opponent");
  box.innerHTML = flowInfoHtml() + `<div class="pa-row"><span class="pa-who me">我</span><span class="pa-act">${esc(playHeroAct.label)}</span></div>` +
    `<div class="pa-row"><span class="pa-who op">对手</span>` +
    opts.map((a) => `<button class="pbtn ${a.kind === "allin" ? "danger" : a.kind === "check" ? "" : a.kind === "fold" ? "muted" : "primary"}"
      data-va="${esc(a.label)}" data-kind="${esc(a.kind)}" data-node="${esc(a.node || "")}" data-pct="${a.pct || ""}">${esc(a.label)}</button>`).join("") +
    `</div>`;
  box.querySelectorAll("[data-va]").forEach((b) => {
    b.onclick = () => onVillainAct(b.dataset.va, b.dataset.kind, b.dataset.node, b.dataset.pct);
  });
}

// ── 翻前剧情 → 自动推导「我是谁 / 对手是谁 / 底池类型」────────────
const POS6 = ["UTG", "HJ", "CO", "BTN", "SB", "BB"];
const POS8 = ["UTG", "UTG1", "UTG2", "HJ", "CO", "BTN", "SB", "BB"];

function syncPositionsToTable() {
  const list = posList();
  const fix = (id) => {
    const e = document.getElementById(id);
    if (!e) return;
    if (!list.includes(e.value)) e.value = list.includes("BTN") ? "BTN" : list[0];
  };
  fix("treeHero"); fix("treeVillain"); fix("pfMe"); fix("pfOpp");
}

function posList() {
  // 权威是 Spot，下拉只是它的一个视图；下拉里还没有值时才回退看它
  if (typeof Spot !== "undefined") return Spot.positions();
  const sel = document.getElementById("treeTableType");
  return sel && String(sel.value).startsWith("8") ? POS8 : POS6;
}
function defaultStack() {
  const sel = document.getElementById("treeTableType");
  return sel && sel.value.startsWith("8") ? "200bb" : "100bb";
}
// 强抓：1 抓 = 1 等效 bb，强抓把盲注翻倍 → 等效筹码减半
function stackEquivText(stackVal, tableType) {
  const s = String(stackVal || "*");
  if (s === "*") return "任意";
  const head = parseFloat(s);
  if (Number.isNaN(head)) return "任意";
  const straddle = String(tableType || "").includes("强抓");
  const ante = String(tableType || "").includes("前注");
  let txt = `${head}bb`;
  if (straddle) txt += ` ＝ ${Math.round(head / 2)} 等效bb（1 抓 = 1 等效bb）`;
  if (ante) txt += " · 含 0.5bb 前注";
  return txt;
}

function fillPosSelects() {
  const list = posList();
  for (const id of ["pfOpener", "pfCaller", "pfThreeBet", "pfFourBet", "pfFiveBet", "pfExtraCaller"]) {
    const sel = document.getElementById(id);
    if (!sel) continue;
    const cur = sel.value;
    const optional = ["pfThreeBet", "pfFourBet", "pfFiveBet", "pfExtraCaller"].includes(id);
    const blank = {pfFourBet:"无（3bet 底池）", pfFiveBet:"无", pfExtraCaller:"无（两人单挑）"}[id] || "无（单加注底池）";
    sel.innerHTML = (optional ? `<option value="">${blank}</option>` : "") +
      list.map((p) => `<option${p === cur ? " selected" : ""}>${p}</option>`).join("");
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
  }
}

// ── 更深的翻前：4bet / 5bet / 全下 / 多人池 ──────────────────
function derivePreflopDeep() {
  const g = (id) => (document.getElementById(id) || {}).value || "";
  const opener = g("pfOpener") || "BTN";
  const caller = g("pfCaller") || "BB";
  const three = g("pfThreeBet");
  const four = g("pfFourBet");
  const five = g("pfFiveBet");
  const extra = g("pfExtraCaller");
  const meOpener = g("pfMeIsOpener") !== "0";

  // 参与人数 → 池型
  const players = 2 + (extra ? 1 : 0);
  let hero, villain, openerField, pot;

  // 最后加注者是谁，决定我在加注方还是跟注方
  const lastRaiser = five || four || three || "";

  if (lastRaiser) {
    const iRaisedLast = (five === opener) || (four === opener) || (three === opener);
    hero = meOpener ? opener : caller;
    villain = lastRaiser === hero ? (meOpener ? caller : opener) : lastRaiser;
    openerField = (lastRaiser === hero) ? "hero" : "villain";
    pot = five ? "4BP" : (four ? "4BP" : "3BP");
  } else {
    hero = meOpener ? opener : caller;
    villain = meOpener ? caller : opener;
    openerField = meOpener ? "hero" : "villain";
    pot = "SRP";
  }

  // 多人池覆盖（3 人及以上看翻牌）
  if (players >= 3) {
    pot = lastRaiser ? (three ? "3BP多人" : "多人池") : "3人池";
  }

  const set = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  set("treeHero", hero);
  set("treeVillain", villain);
  set("treeOpener", openerField);
  set("treePot", pot);
  const pe = document.getElementById("potAuto");
  if (pe) pe.textContent = `${pot} · 我 ${hero} vs ${villain}${extra ? "（" + players + " 人池）" : ""}`;
  return { hero, villain, pot, players };
}

// 全下标记：5bet 选了人就是 allin 底池
function isAllInPre() {
  return !!(document.getElementById("pfFiveBet") || {}).value;
}

// ── 翻前：只选位置，剧情自动推导 ─────────────────────────────
const PF_LINES = [
  { id: "hero_open_v_call",  me: "open",  opp: "call", pot: "SRP",  text: "我开池，{o} 跟注" },
  { id: "opp_open_v_call",   me: "call",  opp: "open", pot: "SRP",  text: "对手开池，我跟注" },
  { id: "hero_open_v_3b",    me: "open",  opp: "3bet", pot: "3BP",  text: "我开池，{o} 3bet，我跟注" },
  { id: "opp_open_v_3b",     me: "3bet",  opp: "open", pot: "3BP",  text: "对手开池，我 3bet，对手跟注" },
  { id: "hero_3b_v_4b",      me: "3bet",  opp: "4bet", pot: "4BP",  text: "我 3bet，{o} 4bet，我跟注" },
  { id: "opp_3b_v_4b",       me: "4bet",  opp: "3bet", pot: "4BP",  text: "对手 3bet，我 4bet，对手跟注" },
  { id: "hero_open_v_call2", me: "open",  opp: "call", pot: "3人池", text: "我开池，{o} 跟注，还有一家跟注" },
];

function pfPositions() { return posList(); }

function fillPfSelects() {
  const list = pfPositions();
  const me = document.getElementById("pfMe"), opp = document.getElementById("pfOpp");
  if (!me || !opp) return;
  const curMe = me.value, curOpp = opp.value;
  me.innerHTML = list.map((p) => `<option${p === curMe ? " selected" : ""}>${p}</option>`).join("");
  opp.innerHTML = list.map((p) => `<option${p === curOpp ? " selected" : ""}>${p}</option>`).join("");
  if (!curMe) me.value = "BTN";
  if (!curOpp || curOpp === me.value) opp.value = list.filter((p) => p !== me.value).pop();
}

function fillPfLines() {
  const sel = document.getElementById("pfLine");
  if (!sel) return;
  const opp = (document.getElementById("pfOpp") || {}).value || "BB";
  const cur = sel.value;
  sel.innerHTML = PF_LINES.map((l) =>
    `<option value="${l.id}">${l.text.replace("{o}", opp)} → ${l.pot}</option>`).join("");
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

function derivePreflopUI() {
  // 只从 Spot 推导，不读任何独立存储
  const d = Spot.apply();
  const se = document.getElementById("stackEquiv");
  if (se) se.textContent = stackEquivText(
    (document.getElementById("treeHeroStack") || {}).value || d.heroStack,
    (document.getElementById("treeTableType") || {}).value || d.tableType);
  return d;
}

function initPreflopUI() {
  fillPfSelects();
  fillPfLines();
  for (const id of ["pfMe","pfOpp","pfLine","treeVsType","treeVsType2","treeHeroStack","treeVillainStack"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => {
      if (id === "pfOpp") fillPfLines();
      derivePreflopUI();
      loadTree();
    });
  }
  // 桌型切换 → 位置列表 + 默认筹码 + 重新查
  const tt = document.getElementById("treeTableType");
  if (tt) tt.addEventListener("change", () => {
    const hs = document.getElementById("treeHeroStack");
    if (hs) hs.value = tt.value.startsWith("8") ? "200bb" : "100bb";
    fillPfSelects();
    fillPfLines();
    derivePreflopUI();
    syncPositionsToTable();
    loadTree();
  });
  const st = document.getElementById("treeStreet");
  if (st) st.addEventListener("change", () => loadTree());
  derivePreflopUI();
  syncPositionsToTable();
}

function switchRangeTo(who) {
  const box = document.getElementById("treeGrid");
  const meta = document.getElementById("treeMeta");
  const vr = window.__villainRange;
  const freq = window.__opponentFreq;
  if (!box) return;
  if (who !== "opponent") {
    if (typeof loadTree === "function") loadTree();
    return;
  }
  const st = window.__treeState || {};
  const pos = st.villain || "对手";
  if (!vr) return;

  const fm = {};
  (freq || []).forEach((x) => { fm[x.combo] = x; });
  let n3b = 0, ncall = 0;
  box.className = "treegrid";
  box.innerHTML = "";
  vr.forEach((c) => {
    const d = document.createElement("div");
    d.className = "treecell";
    const f = fm[c.combo];
    const kind = c.kind || (c.bucket ? "call" : "fold");
    if (kind === "threebet") {
      n3b++;
      d.style.background = "#b03a48"; d.style.color = "#fff";
      d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">3b</span>`;
      d.title = `${c.combo}｜3bet（不在跟注范围）`;
    } else if (kind === "call") {
      ncall++;
      if (f) {
        const r = f.raise, ca = Math.max(0, 100 - r - f.fold), fo = f.fold;
        d.style.background = `linear-gradient(to right, #ffc857 0% ${r}%, #3b82f6 ${r}% ${r + ca}%, #4b5563 ${r + ca}% 100%)`;
        d.style.color = "#fff"; d.style.textShadow = "0 1px 3px rgba(0,0,0,.9)";
        d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${r}</span>`;
        d.title = `${c.combo} ${f.cat || ""}｜加注 ${r}% 跟注 ${ca}% 弃/过 ${fo}%`;
      } else {
        d.style.background = "#2f6fb5"; d.style.color = "#fff";
        d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">跟</span>`;
      }
    } else {
      d.style.background = "#131313"; d.style.color = "#454545"; d.style.opacity = "0.55";
      d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">弃</span>`;
    }
    box.appendChild(d);
  });
  const vsRaw = st.vs_type;
  const vs = (!vsRaw || vsRaw === "*") ? "标准" : vsRaw;
  if (meta) meta.innerHTML = `👤 <b>${esc(pos)} 的完整范围</b> · 对手类型「${esc(vs)}」`
    + ` · <span style="color:#e06c75">3bet ${n3b} 类</span>`
    + ` / <span style="color:#6aa9ff">跟注 ${ncall} 类</span>`
    + ` / <span style="color:#6b7280">弃 ${169 - n3b - ncall} 类</span>`;
  const det = document.getElementById("treeDetail");
  if (det) det.innerHTML = `红色 = 他会 <b>3bet</b>（所以不在跟注范围里）；蓝色系 = 会跟注，`
    + `格内数字是<b>加注频率</b>，底色按加注/跟注/弃牌渐变；灰色 = 会弃。悬停看完整频率。`;
}

function wilActsFor(mode) {
  // mode 0 = 我过牌后（对手可过牌/下注）
  // mode 1 = 我下注后（对手可弃牌/跟注/过牌加注/全下）
  if (mode === 1) {
    const out = [{ label: "弃牌", kind: "fold" }, { label: "跟注", kind: "call" }];
    // 过牌加注：OOP 最关键的武器
    for (const [pct, node] of [[66, "对手小注（XR）"], [100, "对手小注（XR）"],
                               [150, "对手过牌加注"], [200, "对手过牌加注"]]) {
      out.push({ label: `过牌加注 ${pct}%`, kind: "xraise", pct, node });
    }
    out.push({ label: "全下", kind: "allin", node: "对手过牌加注" });
    return out;
  }
  const out = [{ label: "过牌", kind: "check" }];
  for (const [pct, node] of [[25, "对手小注"], [33, "对手小注"], [50, "对手中注"],
                             [75, "对手大注"], [100, "对手大注"]]) {
    out.push({ label: `下注 ${pct}%`, kind: "bet", pct, node });
  }
  out.push({ label: "全下", kind: "allin", node: "对手大注" });
  return out;
}

function onVillainAct(label, kind, node, pct) {
  const box = document.getElementById("playActions");
  if (kind === "fold") {
    box.innerHTML = `<div class="pa-row"><span class="pa-who me">我</span><span class="pa-act">${esc(playHeroAct.label)}</span>
      <span class="pa-who op">对手</span><b style="color:#3ba55d">弃牌 → 我赢下底池</b>
      <button class="pbtn" onclick="playReset();renderActions();">重来</button></div>`;
    return;
  }
  if (kind === "check" || kind === "call") {
    if (!game) gameInit();
    if (kind === "call") {
      // 跟注：把对手的下注额补进底池
      const lastBet = [...game.history].reverse().find((x) => x.who === "对手" && x.amt);
      if (lastBet) potAfter(lastBet.amt);
      game.history.push({street: streetName(), who:"我", act:"跟注"});
    }
    const isRiver = game.streetIdx >= GAME_STREETS.length - 1;
    box.innerHTML = `<div class="pa-row"><span class="pa-who me">我</span><span class="pa-act">${esc(playHeroAct.label)}</span>
      <span class="pa-who op">对手</span><span class="pa-act">${esc(label)}</span>
      <b style="color:#7ddc9f">底池 ${fmtPot()}</b>
      <button class="pbtn primary" onclick="nextStreet()">${isRiver ? "河牌结束 · 结算" : "进入下一街"}</button></div>`;
    return;
  }
  // 对手下注/加注 → 我有反应，重新查树
  if (node) {
    const sel = document.getElementById("treeAction");
    if (sel) sel.value = node;
    playPhase = 0;
    playHeroAct = null;
    if (typeof loadTree === "function") loadTree();
  }
}

function advanceStreet() {
  const order = ["翻牌", "转牌", "河牌"];
  const sel = document.getElementById("treeStreet");
  if (!sel) return;
  const i = order.indexOf(sel.value);
  if (i >= 0 && i < order.length - 1) sel.value = order[i + 1];
  playReset();
  if (typeof loadTree === "function") loadTree();
}
function treeSentence(v) {
  const pos = `${POS_CN[v.hero] || v.hero} 对 ${POS_CN[v.villain] || v.villain}`;
  const who = v.opener === "hero" ? "我开池" : v.opener === "villain" ? "对手开池" : "盲位战";
  const potCN = v.pot === "SRP" ? "单加注底池" : v.pot === "3BP" ? "3bet 底池"
    : v.pot === "4BP" ? "4bet 底池" : v.pot === "3BP多人" ? "3bet 底池(多人)"
    : v.pot === "3人池" ? "3人底池" : v.pot === "多人池" ? "多人底池" : "翻前";
  // 筹码：分开选时显示「我 / 他」，并标出有效筹码
  const num = (x) => { const m = String(x || "").match(/[0-9.]+/); return m ? parseFloat(m[0]) : null; };
  const hs = num(v.heroStack), vs = num(v.villainStack);
  let stackTxt = v.stack && v.stack !== "*" ? v.stack : "";
  if (hs != null || vs != null) {
    const eff = Math.min(hs ?? Infinity, vs ?? Infinity);
    stackTxt = `我 ${v.heroStack === "*" ? "—" : v.heroStack} / 他 ${v.villainStack === "*" ? "—" : v.villainStack}`;
    if (Number.isFinite(eff)) stackTxt += `（有效 ${eff}bb）`;
  } else if (!stackTxt) stackTxt = "—";
  const board = v.street === "翻前" ? "（无公共牌）" : `<b>${esc(v.board)}</b>`;
  return `<b>${stackTxt}</b> ｜ <b>${pos}</b> ｜ ${who} ｜ ${potCN} ｜ ${board} ｜ <b>${v.street}</b> ｜ <b>${v.action}</b>`;
}


// ── 自检：确认策略树依赖的控件都在 ─────────────────────────────
// 背景：改界面时替换文本没生效会静默失败，API 测试查不出来（只有 UI 缺这块）。
// 这里在加载时逐项核对，缺了就在页面和控制台同时报出来。
const TREE_REQUIRED = [
  ["treeHeroStack", "① 我的筹码", true],
  ["treeHero", "② 我在哪", true],
  ["treeVillain", "③ 对手在哪", true],
  ["treeOpener", "④ 谁先加注", true],
  ["treePot", "⑤ 底池类型", true],
  ["treeBoard", "⑥ 牌面", true],
  ["treeStreet", "⑦ 街道", true],
  ["treeAction", "⑩ 对手动作", true],
  ["treeLine", "⑧ 我是怎么走到这的", false],
  ["treeRunout", "⑨ 转牌/河牌变化", false],
  ["treeCapped", "⑪ 对手范围", false],
  ["treeVsType", "⑫ 对手类型", false],
];

function domIdSelfCheck() {
  const seen = new Set(), dup = [];
  document.querySelectorAll("[id]").forEach((el) => {
    if (seen.has(el.id)) dup.push(el.id);
    seen.add(el.id);
  });
  if (dup.length) console.error("[DOM 自检] 重复 id：", dup.join("、"), "—— 不同页签共用容器会互相覆盖内容");
  return dup;
}

function treeSelfCheck() {
  const missing = TREE_REQUIRED.filter(([id]) => !document.getElementById(id));
  if (!missing.length) return true;
  const msg = "策略树缺少控件：" + missing.map(([id, label]) => `${label}(#${id})`).join("、");
  console.error("[策略树自检]", msg);
  const box = document.getElementById("treeDetail");
  if (box) {
    box.innerHTML = `<div style="color:#ff7b72;font-weight:600">⚠ 界面自检失败</div>
      <div style="color:#d8dee6;margin-top:6px">${msg}</div>
      <div style="color:#8a929c;margin-top:6px;font-size:13px">
        多半是改 index.html 时的文本替换没命中，或者浏览器缓存了旧文件。强制刷新（Cmd+Shift+R）试试。</div>`;
  }
  return false;
}


// ── 跨街接力：这条线打完，下一街怎么接 ──────────────────────────
const STREETS = ["翻牌", "转牌", "河牌"];
function renderNextStreet(curStreet) {
  const box = document.getElementById("treeNext");
  if (!box) return;
  const i = STREETS.indexOf(curStreet);
  if (i < 0 || i >= STREETS.length - 1) { box.innerHTML = ""; return; }
  const nxt = STREETS[i + 1];
  box.innerHTML = `<button id="btnNextStreet" style="cursor:pointer;padding:6px 14px;border-radius:8px;
      border:1px solid #3a7bd5;background:#1b2b45;color:#fff;font-size:14px">→ 打到${nxt}</button>
    <span style="color:#8a929c;font-size:13px;margin-left:10px">接续当前这条行动线；记得把${nxt}那张牌补进牌面</span>`;
  const btn = document.getElementById("btnNextStreet");
  if (btn) btn.onclick = () => {
    document.getElementById("treeStreet").value = nxt;
    const pip = document.getElementById("treePath");
    if (pip) {
      const L = { "转牌": "T", "河牌": "R" }[nxt] || "";
      const cur = (pip.value || "").trim().toUpperCase();
      if (L && !cur.split("|").some((x) => x.startsWith(L))) {
        pip.value = (cur ? cur + "|" : "") + L + ":";
      }
    }
    const v = {
      hero: document.getElementById("treeHero").value,
      villain: document.getElementById("treeVillain").value,
      opener: document.getElementById("treeOpener").value,
      pot: document.getElementById("treePot").value,
    };
    const role = roleFrom(v.hero, v.villain, v.opener, v.pot);
    // 不利位置的人先行动 → 「无」；有位置的人等到对手动作 → 「对手过牌」
    const oop = role.startsWith("OOP") || role === "BvB-BB";
    document.getElementById("treeAction").value = oop ? "无" : "对手过牌";
    loadTree();
  };
}


// ── 行动路径：F/T/R + X/B/C/R ────────────────────────────────
const PATH_LINES = {
  "F:XX": "翻牌过牌→延迟",
  "F:BC": "翻牌下注→持续",
  "F:XBRC": "我XR后被跟注",
  "F:BXRC": "被过牌加注后",
  "F:XX|T:XX": "转牌双方过牌",
  "F:BC|T:BC": "二枪",
};
const PATH_STREET = { F: "翻牌", T: "转牌", R: "河牌" };

function applyPath(raw) {
  const p = (raw || "").trim().toUpperCase();
  if (!p) return null;
  const segs = p.split("|");
  const lastSeg = (segs[segs.length - 1] || "").trim();
  // 只有「街道:」这种以冒号结尾的段，才表示「决策点在这一街」
  if (/:$/.test(lastSeg)) {
    const tag = lastSeg.replace(":", "").match(/[FTR]/);
    const sel = document.getElementById("treeStreet");
    if (tag && PATH_STREET[tag[0]] && sel) sel.value = PATH_STREET[tag[0]];
  }
  let best = "";
  for (const k of Object.keys(PATH_LINES)) {
    if (p.startsWith(k) && k.length > best.length) best = k;
  }
  if (best) {
    const ln = document.getElementById("treeLine");
    if (ln) ln.value = PATH_LINES[best];
  }
  return best || null;
}


// ── 对手类型 → 范围 → 牌面构成 → 调整 ──────────────────────
async function loadVsType(v) {
  const box = document.getElementById("vsTypeBox");
  if (!box) return;
  if (!v.vs_type || v.vs_type === "*") { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  box.innerHTML = '<div class="muted">正在按这个对手类型算他的范围…</div>';
  try {
    const d = await api("/api/vs-type?" + new URLSearchParams({
      board: v.board, type: v.vs_type, hero: v.hero, opp: v.villain, pot: v.pot,
    }).toString());
    if (d.error) { box.innerHTML = `<div class="verdict neg">${esc(d.error)}</div>`; return; }
    const nd = d.nut_density == null ? 2 : d.nut_density;
    const tone = nd >= 1.15 ? "#3ba55d" : nd >= 0.85 ? "#e0a526" : "#c96";
    box.innerHTML = `
      <h2 style="margin-bottom:6px">对手类型：${esc(d.type)} <span class="badge">VPIP ${esc(d.vpip_range)}</span></h2>
      <div style="background:#141b24;border-left:3px solid #3a7bd5;padding:8px 12px;border-radius:4px;margin-bottom:10px">
        <div style="font-size:13.5px;line-height:1.6">${esc(d.desc || "")}</div>
        <div class="muted" style="font-size:12.5px;margin-top:8px;line-height:1.7">
          <b style="color:#9aa7b8">一眼识别</b>
          <span style="margin-left:6px">${esc((d.identify && d.identify[0]) || "")}</span>
          ${d.identify && d.identify[1] ? `<br><b style="color:#9aa7b8;visibility:hidden">一眼识别</b><span style="margin-left:6px;opacity:.85">${esc(d.identify[1])}</span>` : ""}
        </div>
        <div class="muted" style="font-size:12.5px;margin-top:4px"><b style="color:#9aa7b8">怎么打</b><span style="margin-left:6px">${esc(d.adjust_text || d.tendency || "")}</span></div>
      </div>
      <div class="muted" style="font-size:12.5px;margin-bottom:8px">他的翻前范围：${esc(d.their_range)}</div>
      <div class="row" style="gap:22px;margin:6px 0">
        <div><div class="big" style="color:${tone}">${d.nut_density_text || (d.nut_density == null ? "∞" : d.nut_density.toFixed(2))}</div>
          <div class="muted">坚果密度（我 ÷ 他）</div></div>
        <div style="flex:1;min-width:260px">
          <div style="font-size:13px"><b>他的坚果</b> ${d.their_cats.nut} 组 / 共 ${d.their_cats.total}</div>
          <div style="font-size:13px"><b>我的坚果</b> ${d.our_cats.nut} 组 / 共 ${d.our_cats.total}</div>
          <div class="muted" style="font-size:12px">${esc(d.nut_def)}</div>
        </div>
      </div>
      <div class="verdict ${nd >= 1.15 ? "pos" : "warn"}" style="margin-top:6px">
        <b>尺度</b> ${esc(d.sizing_advice)}
      </div>
      <div class="row" style="gap:18px;margin-top:8px;font-size:13px">
        <div><b>翻前宽度</b> ×${d.preflop_width_factor.toFixed(2)} <span class="muted">${esc(d.preflop_width_txt)}</span>
          <div class="muted" style="font-size:12px">${esc(d.preflop_width_why)}</div></div>
        ${d.tendency_adjust ? `<div><b>翻后频率</b><div class="muted" style="font-size:12px">
          抓诈 ${d.tendency_adjust.bluff_catch > 0 ? "+" : ""}${d.tendency_adjust.bluff_catch.toFixed(2)} ·
          薄价值 ${d.tendency_adjust.value_thin > 0 ? "+" : ""}${d.tendency_adjust.value_thin.toFixed(2)} ·
          诈唬 ${d.tendency_adjust.bluff > 0 ? "+" : ""}${d.tendency_adjust.bluff.toFixed(2)}
          <br>${esc(d.tendency_adjust.note)}</div></div>` : ""}
      </div>
      <div style="margin-top:10px;font-size:12.5px"><b>三种场景对照</b>（他用的范围完全不同）
        <table style="width:100%;border-collapse:collapse;margin-top:4px">
          ${Object.entries(d.scenarios || {}).map(([k, v]) => {
            const cur = (k === "SRP" && d.pot_type === "SRP")
              || (k === "3BP_IPFR" && d.pot_type === "3BP" && d.range_used === "跟注范围")
              || (k === "3BP_ICALL" && d.pot_type === "3BP" && d.range_used === "3bet 范围");
            return `<tr style="${cur ? "background:#16233a" : ""}">
              <td style="padding:3px 6px;white-space:nowrap">${cur ? "▶ " : ""}${esc(v.label.split("｜")[0])}</td>
              <td style="padding:3px 6px;color:#8a929c">${esc(v.label.split("｜")[1] || "")}</td>
              <td style="padding:3px 6px;text-align:right">${v.their_n} 组</td>
              <td style="padding:3px 6px;text-align:right;font-weight:600;color:${v.density == null ? "#3ba55d" : v.density >= 1.15 ? "#3ba55d" : v.density >= 0.85 ? "#e0a526" : "#c96"}">
                ${v.density == null ? "∞" : v.density.toFixed(2)}</td>
            </tr>`;
          }).join("")}
        </table>
      </div>
      <div class="muted" style="margin-top:6px;font-size:12.5px"><b>倾向</b> ${esc(d.tendency)}</div>
      ${d.is_baseline ? '<div class="muted" style="margin-top:4px;font-size:12px">这一行是参照点：其他类型的偏离都相对它算。</div>' : ""}`;
  } catch (e) {
    box.innerHTML = `<div class="verdict neg">${esc(e.message)}</div>`;
  }
}

// Donk 只有翻前跟注方才有意义：先加注的人不存在「领打」
function syncDonkOption() {
  // 对手动作已经改成隐藏字段（由行动流程驱动），这里只保留兜底兼容
  const act = document.getElementById("treeAction");
  if (!act || !act.options) return;
  const opt = Array.from(act.options).find((o) => o.value === "我方领打");
  if (!opt) return;
  const opener = document.getElementById("treeOpener");
  const allowed = !opener || opener.value !== "hero";
  opt.disabled = !allowed;
  opt.hidden = !allowed;
  if (!allowed && act.value === "我方领打") act.value = "对手过牌";
}

// 强抓：2BB 抓注等于盲注翻倍 → 有效筹码按一半算
function straddleAdj(stackVal, v) {
  const sel = document.getElementById("treeTableType");
  if (!sel || !sel.value.includes("强抓")) return stackVal;
  const n = parseFloat(String(stackVal));
  if (Number.isNaN(n)) return stackVal;
  const half = Math.max(5, Math.round(n / 2));
  return half + "bb";
}

function syncTableType() {
  const sel = document.getElementById("treeTableType");
  const hero = document.getElementById("treeHero");
  const vil = document.getElementById("treeVillain");
  if (!sel || !hero || !vil) return;
  const is8 = sel.value !== "6-max";
  // 切到「8-max + 强抓」时，默认筹码设成 200bb（200bb 带抓 ≈ 6 人桌 100bb）
  if (sel.value.includes("强抓")) {
    const hst = document.getElementById("treeHeroStack");
    if (hst && hst.value === "*") hst.value = "200bb";
    // 对手保持「同我」（*），别把它改成固定 200bb：
    // 否则英雄 100bb→50bb、对手 200bb→100bb，同一张桌子两个有效筹码。
  }
  POS_ORDER = is8 ? { ...POS_ORDER_8 } : { ...POS_ORDER_6 };
  const list = is8 ? POS_8 : POS_6;
  [hero, vil].forEach((el) => {
    const keep = el.value;
    el.innerHTML = list.map((p) => `<option>${p}</option>`).join("");
    el.value = list.includes(keep) ? keep : list[list.length - 1];
  });
  // 强抓：有效筹码减半（2BB 抓 = 盲注翻倍）
  const straddle = sel.value.includes("强抓");
  const tip = document.getElementById("treeStraddleTip");
  if (tip) tip.style.display = straddle ? "" : "none";
  const hs = document.getElementById("treeHeroStack");
  if (hs && straddle && hs.value !== "*") {
    const n = parseFloat(String(hs.value));
    if (!Number.isNaN(n)) {
      const half = Math.max(5, Math.round(n / 2));
      const el = document.getElementById("treeVillainStack");
      if (el && el.value === "*") el.value = "*";
      if (tip) {
        tip.style.display = "";
        tip.textContent = `强抓 2BB：盲注翻倍 → 有效筹码按一半算（${hs.value} → ${half}bb）。这是推导，不是实测数据。`;
      }
    }
  }
}

function syncThirdPlayer() {
  const el = document.getElementById("treeVillain2");
  const pot = document.getElementById("treePot");
  if (el && pot) el.style.display = pot.value === "3人池" ? "" : "none";
}

async function loadTree() {
  if (!bpCards.length) bpInit($("#treeBoard").value || "As7h2c");
  try { bindSpotInputs(); } catch (e) {}
  if (!window.__ctaInit) { window.__ctaInit = 1; try { bindMainCta(); } catch (e) {} }
  if (!window.__lockInit) { window.__lockInit = 1; try { refreshLocks(); } catch (e) {} }
  if (!window.__pfInited) { window.__pfInited = 1; try { initPreflopUI(); } catch (e) { console.warn("pf:", e); } }
  syncTableType();
  // 翻前没有公共牌：隐藏「强抓折算」和「牌面写法」两段提示；翻后恢复
  {
    const isPre = ($("#treeStreet") || {}).value === "翻前";
    const bh = document.getElementById("boardHint");
    if (bh) bh.style.display = isPre ? "none" : "";
    const tip = document.getElementById("treeStraddleTip");
    if (tip && isPre) tip.style.display = "none";
  }
  syncThirdPlayer();
  syncDonkOption();
  if (!treeSelfCheck()) return;
  const _isPre = $("#treeStreet").value === "翻前";
  const _roleField = $("#treeRole");
  const _potField = $("#treePot");
  const v = {
    heroStack: ($("#treeHeroStack") && $("#treeHeroStack").value) || "*",
    villainStack: ($("#treeVillainStack") && $("#treeVillainStack").value) || "*",
    hero: $("#treeHero").value,
    villain: $("#treeVillain").value,
    villain2: ($("#treeVillain2") && $("#treeVillain2").value) || "*",
    opener: $("#treeOpener").value,
    pot: _isPre ? "翻前" : (_potField ? _potField.value : "SRP"),
    role: _isPre ? "*" : ((_roleField && _roleField.value) || roleFrom($("#treeHero").value, $("#treeVillain").value, ($("#treeOpener")||{}).value, (_potField||{}).value)),
    board: ($("#treeBoard").value || "").trim() || "A72r",
    street: $("#treeStreet").value,
    // 翻前节点没有「对手过牌」，动作是「开池」
    action: ($("#treeStreet").value === "翻前") ? "开池" : $("#treeAction").value,
    hero_stack: ($("#treeStreet").value === "翻前") ? "*" : (($("#treeHeroStack") && $("#treeHeroStack").value) || "*"),
    villain_stack: ($("#treeStreet").value === "翻前") ? "*" : (($("#treeVillainStack") && $("#treeVillainStack").value) || "*"),
    runout: ($("#treeRunout") && $("#treeRunout").value) || "*",
    line: ($("#treeLine") && $("#treeLine").value) || "*",
    vs_type: ($("#treeVsType") && $("#treeVsType").value) || "*",
    capped: ($("#treeCapped") && $("#treeCapped").value) || "*",
    path: ($("#treePath") && ($("#treePath").value || "").trim().toUpperCase()) || "",
  };
  // 前注：8 人桌每人 0.5bb，翻前底池多 4bb → 开池收益变高，范围放宽（推导）
  {
    const sel = document.getElementById("treeTableType");
    v.ante = !!(sel && sel.value.includes("前注"));
    if (v.ante) {
      // 前注版有独立的开池表（简单GTO 实测），用专门的 stack 键
      v.stack = "200bb·前注";
      const tip = document.getElementById("treeStraddleTip");
      if (tip) {
        tip.style.display = "";
        tip.textContent = "前注 0.5bb（8 人桌 = 底池多 4bb）：偷盲收益变高，开池范围应放宽约 10–15%。"
          + "这是推导值，没有实测数据。";
      }
    }
  }
  // 强抓：2BB 抓注等于盲注翻倍，有效筹码按一半算（并标注）
  {
    const sel = document.getElementById("treeTableType");
    const straddle = sel && sel.value.includes("强抓");
    v.straddle = !!straddle;
    if (straddle) {
      const half = (x) => {
        const n = parseFloat(String(x));
        return Number.isNaN(n) ? x : Math.max(5, Math.round(n / 2)) + "bb";
      };
      v.heroStackRaw = v.heroStack;
      v.villainStackRaw = v.villainStack;
      v.heroStack = half(v.heroStack);
      v.villainStack = half(v.villainStack);
    }
  }
  // 翻前 + 已有序列：下面要显示「序列最后一步是什么」，而不是按位置
  // 去查一条「开池」规则 —— 否则 CO 3bet 之后会显示成 CO 的开池范围。
  if (v.street === "翻前" && typeof Spot !== "undefined" && Spot.line()) {
    const seq = Spot.state.seq.filter((x) => x.act !== "弃牌");
    const last = seq[seq.length - 1];
    if (last) {
      const RAISE = ["开池", "3bet", "4bet", "5bet 全下"];
      let kind = "open";
      if (last.act === "3bet") kind = "3bet";
      else if (last.act === "4bet") kind = "4bet";
      else if (last.act === "5bet 全下") kind = "5bet";
      else if (last.act === "跟注") {
        const nR = seq.filter((x) => RAISE.includes(x.act)).length;
        kind = nR >= 3 ? "call4bet" : nR >= 2 ? "call3bet" : "call_open";
      }
      const raisers = seq.filter((x) => RAISE.includes(x.act));
      const prev = raisers.length >= 2 ? raisers[raisers.length - 2] : null;
      const oppPos = prev ? prev.pos
        : ((seq.find((x) => x.pos !== last.pos) || {}).pos || v.villain);
      await pfShowRange(last.pos, kind, oppPos);
      return;
    }
  }
  // 有效筹码：用两个下拉框算，不要读不存在的 #treeStack（以前永远 "*"，
  // 所以「筹码 / 对手筹码」两个控件对策略完全没有影响）。
  {
    const num = (x) => {
      const n = parseFloat(String(x));
      return Number.isNaN(n) ? null : n;
    };
    const hs = num(v.heroStack);
    const vs = num(v.villainStack);
    let eff = null;
    if (hs != null && vs != null) eff = Math.min(hs, vs);
    else if (hs != null) eff = hs;
    else if (vs != null) eff = vs;
    v.stack = eff != null ? `${eff}bb` : "*";
  }
  const isPre = v.street === "翻前";
  const bEl = $("#treeBoard");
  if (bEl) { const lb = bEl.closest(".step"); if (lb) lb.style.display = isPre ? "none" : ""; }
  const needRun = (v.street === "转牌" || v.street === "河牌");
  const rw = $("#stepRunout"), lw = $("#stepLine");
  if (rw) rw.style.display = needRun ? "" : "none";
  if (lw) lw.style.display = needRun ? "" : "none";
  if (!needRun) { v.runout = "*"; v.line = "*"; }
  else {
    const lw2 = $("#treeLine"), rw2 = $("#treeRunout");
    // 有路径时，line 由路径推导，不要硬塞默认值
    if (lw2 && lw2.value === "*" && v.path) {
      applyPath(v.path);
      v.line = lw2.value;
    }
    if (lw2 && lw2.value === "*") { lw2.value = "翻牌下注→持续"; v.line = lw2.value; }
    if (rw2 && rw2.value === "*") { rw2.value = "空白"; v.runout = rw2.value; }
  }
  if ($("#treeSent")) $("#treeSent").innerHTML = treeSentence(v);
  loadVsType(v);

  const role = roleFrom(v.hero, v.villain, v.opener, v.pot);
  const qs = new URLSearchParams({
    pot: v.pot, role,
    board: isPre ? "A72r" : v.board,
    street: v.street, action: v.action,
    hero_pos: v.hero, opp_pos: (v.pot === "3人池" && v.villain2 && v.villain2 !== "*") ? (v.villain + "+" + v.villain2) : v.villain, stack: v.stack, villain_stack: (document.getElementById("treeVillainStack")||{}).value || "*", runout: v.runout, line: v.line, vs_type: v.vs_type, capped: v.capped, path: v.path,
    hero_stack: v.heroStack, villain_stack: v.villainStack,
    // 勾上「混合策略」= 保留多尺度；不勾 = 简化（默认）
    multi: (() => {
      const cb = document.getElementById("treeMulti");
      return (cb && cb.checked) ? "1" : "0";
    })(),
    simplify: (() => {
      const cb = document.getElementById("treeMulti");
      if (cb && cb.checked) return "0";   // 勾了混合 → 不简化
      return "1";
    })(),
    // 翻前序列 → 翻后范围（谁开池/谁跟注/谁 3bet，决定手里还剩哪些牌）
    pf: (!isPre && typeof Spot !== "undefined") ? Spot.line() : "",
  });
  const box = $("#treeGrid");
  const meta = $("#treeMeta");
  try {
    const r = await fetch("/api/tree?" + qs.toString()).then((x) => x.json());
    if (r.error) {
      meta.textContent = "✗ " + r.error;
      box.innerHTML = "";
      $("#treeDetail").innerHTML = `<b style="color:#ff6b35">接口报错：${r.error}</b>　（多半是服务没重启，关掉复盘台重开一次）`;
      return;
    }
    if (!r.ok) {
      meta.textContent = `${r.board_class} · ${r.reason}`;
      box.innerHTML = "";
      $("#treeDetail").innerHTML = `<b>这条线还没录入</b>（识别为「${r.board_class}」）`;
      renderNextStreet($("#treeStreet").value);
      return;
    }
    const rule = r.rule;
    const unit = (r.table && r.table.unit) || "下注率";
    window.__nodeActions = r.node_actions || [];
  window.__villainActions = r.villain_actions || [];
  window.__villainRange = r.villain_range || null;
  window.__opponentFreq = r.opponent_freq || null;
  window.__treeState = v;
    window.__rangeBetPct = r.range_bet_pct;
  window.__treeCells = r.cells || [];
  window.__bluffPlan = r.bluff || null;
  window.__preflopLine = r.preflop || null;
  window.__ruleInfo = { sizing: rule.sizing, freq: rule.freq, table: r.table.id };
  window.__mixTh = (r.strategy_mode || {}).threshold;
    try { renderPokerTable(v, {}); } catch (e) { console.warn("table:", e); }
  try { renderGuarantee(r.guarantee); } catch (e) { console.warn("guar:", e); }
  try { renderFreqBar(r); } catch (e) { console.warn("freq:", e); }
  try { renderMixSummary(r); } catch (e) { console.warn("mix:", e); }
  try { renderLockedPanel(r); } catch (e) { console.warn("locked:", e); }
  try { renderVersionBar(); } catch (e) { console.warn("ver:", e); }
  try { playReset(); renderActions(); } catch (e) { console.warn("actions:", e); }
    const tag = unit === "下注率" ? "下注" : unit === "跟注率" ? "跟注" : unit;
    const warn = (r.table.basis || "").startsWith("反推") ? ` ⚠ ${r.table.basis}` : "";
    const head = rule.street === "翻前" ? "" : `${r.board_class} · `;
    renderNextStreet(rule.street);
    const posCN = { UTG:"枪口", UTG1:"枪口+1", UTG2:"枪口+2", HJ:"高劫持",
                    CO:"关煞", BTN:"庄位", SB:"小盲", BB:"大盲" };
    // ── 顶部只留一句人话；内部 ID 进 ⚙ 诊断抽屉 ──
    const humanParts = [
      `${posCN[v.hero] || v.hero || ""} vs ${posCN[v.villain] || v.villain || ""}`,
      v.pot || "",
      (v.stack && v.stack !== "*") ? v.stack : "",
      rule.street === "翻前" ? "" : (r.board_class || ""),
    ].filter(Boolean);
    meta.textContent = humanParts.join(" · ");
    window.__diagnostics = {
      规则: rule.rule_id, 尺度: rule.sizing, 频率: rule.freq, 桶表: r.table.id,
      模式: (r.strategy_mode || {}).mode, 量化误差: (r.strategy_mode || {}).avg_err,
      阈值: (r.strategy_mode || {}).threshold,
      并存: (r.conflicts || []).join("/") || "无",
      近似: r.approx || "无", 来源: rule.source, 置信: rule.conf,
    };
    const multiOn = (() => {
      const cb = document.getElementById("treeMulti");
      if (cb && cb.checked) return true;
      try { return new URLSearchParams(location.search).get("multi") === "1"; } catch (e) { return false; }
    })();
    if (multiOn && r.multi_rules && r.multi_rules.length > 1) {
      const mr = r.multi_rules.map((x, i) =>
        `<span class="badge" style="margin-left:6px;${i===0?'background:#2d6a4f;color:#fff':''}">${esc(x.sizing || '—')} · ${esc(x.source)}/${esc(x.conf)}</span>`).join("");
      meta.innerHTML = meta.textContent + ` · <b>并存尺度</b> ${mr}`;
    }
    if (r.strategy_mode) {
      const sm = r.strategy_mode;
      const color = sm.mode === "简化" ? "#3ba55d" : "#c96";
      meta.innerHTML = (meta.innerHTML || meta.textContent) +
        ` · <span style="color:${color};font-weight:600">${sm.mode}</span>` +
        (sm.avg_err ? `（量化误差 ${sm.avg_err}）` : "") +
        `<span style="opacity:.55"> 阈值 ${window.__mixTh ?? "?"}</span>`;
    }
    if (r.approx) {
      meta.textContent += ` · ⚠ ${r.approx}`;
    }
    const _tnote = r.tendency_note || r.adjust;
    if (_tnote) {
      meta.textContent += ` · 已按「${v.vs_type}」调整数值：${_tnote}`;
    }
    if (r.conflicts && r.conflicts.length) {
      meta.textContent += r.hold ? ` · 并存（已裁决）${r.conflicts.join("/")}` : ` · ⚠ 并存 ${r.conflicts.join("/")}`;
    }

    // 翻前也走 13×13 矩阵（下面统一渲染），这里只补一个位置说明
    if (rule.street === "翻前") {
      const pos = (v.hero || "*");
      const opp = (v.villain || "*");
      const nm = { UTG: "枪口", UTG1: "枪口+1", UTG2: "枪口+2", HJ: "高劫持",
                   CO: "关煞", BTN: "庄位", SB: "小盲", BB: "大盲" };
      $("#treeDetail").innerHTML =
        `<b style="color:#ffd479">${esc(nm[pos] || pos)}${esc(pos)}</b> 的翻前开池范围 ｜`
        + ` 对手 ${esc(nm[opp] || opp)}${esc(opp)} ｜ 格内数字＝开池频率`;
    }

    box.className = "treegrid";
    box.innerHTML = "";
    const passTxt = v.street === "翻前" ? "弃" : "过";
    r.cells.forEach((c) => {
      const d = document.createElement("div");
      d.className = "treecell";
      const folded = !!c.folded;
      const mix = c.mix || [];
      if (folded) {
        // 翻前不在范围 = 弃牌；翻后不下注 = 过牌（不是弃牌，别写错）
        d.style.background = "#131313";
        d.style.color = "#454545";
        d.style.opacity = "0.5";
        d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${passTxt}</span>`;
      } else if (mix.length) {
        // solver 风格：整格按动作占比做横向渐变
        let acc = 0;
        const stops = mix.map((m) => {
          const a = acc, b = acc + m.freq;
          acc = b;
          return `${m.color} ${a}% ${b}%`;
        });
        d.style.background = `linear-gradient(to right, ${stops.join(",")})`;
        d.style.color = "#fff";
        d.style.textShadow = "0 1px 3px rgba(0,0,0,.9)";
        const top = mix.slice().sort((x, y) => y.freq - x.freq)[0];
        d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">${top.freq}%</span>`;
      } else {
        d.style.background = "#1a1a1a";
        d.style.color = "#6b6b6b";
        d.innerHTML = `<span class="cb">${c.combo}</span><span class="pct">–</span>`;
      }
      const bl = c.bluff;
      const blNote = bl ? `｜surplus 最好 #${bl.best_rank}（本类 ${bl.of} 手，选中 ${bl.selected}）` : "";
      d.title = folded
        ? (v.street === "翻前" ? `${c.combo}｜翻前不在开池范围，已弃牌`
                               : `${c.combo}｜这个节点不下注（过牌）${blNote}`)
        : `${c.combo}｜${c.cat}｜${c.bucket === null ? "未收录" : tag + " " + c.bucket + "%"}${blNote}`;
      d.onclick = () => {
        const head = folded
          ? (v.street === "翻前"
              ? `<b>${c.combo}</b> → <b style="color:#c96">翻前就该弃</b>（不在 ${v.hero} 的开池范围里），不存在翻后${tag}频率`
              : `<b>${c.combo}</b>｜${c.cat} → <b style="color:#c96">这个节点不下注（过牌）</b>${bl ? `｜surplus 最好 #${bl.best_rank}（本类 ${bl.of} 手，选中 ${bl.selected}）` : ""}`)
          : (c.mix && c.mix.length
              ? `<b>${c.combo}</b>｜${c.cat}｜` + c.mix.map((m) =>
                  `<span style="display:inline-block;width:10px;height:10px;background:${m.color};border-radius:2px;margin-left:8px;vertical-align:middle"></span> <b>${esc(m.action)}</b> ${m.freq}%`).join("")
              : `<b>${c.combo}</b> → 类别 <b>${c.cat}</b> → ${tag}频率 <b>未收录</b>`);
        // 单牌细分：同花牌按具体花色拆开
        const vars = folded ? [] : comboVariants(c, v.board);
        const split = vars.length ? `
          <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
            ${vars.map((x) => {
              if (x.dead) {
                return `<div style="background:#14181c;border:1px dashed #3a444d;border-radius:6px;padding:5px 10px;text-align:center;opacity:.55">
                  <div style="font-size:13px;color:#5d6d7e;text-decoration:line-through">${x.label}</div>
                  <div style="font-weight:700;color:#5d6d7e">不可能</div>
                  <div style="font-size:11px;color:#4a545e">牌在公共牌上</div>
                </div>`;
              }
              const isBlock = x.adj > 0;
              return `<div style="background:${isBlock ? "#1d3a2a" : "#1a1f26"};border:1px solid ${isBlock ? "#3d8b66" : "#2b333c"};border-radius:6px;padding:5px 10px;text-align:center">
                <div style="font-size:13px;color:${x.suit === "h" || x.suit === "d" ? "#e06c5a" : "#cfd8e3"}">${x.label}</div>
                <div style="font-weight:700;color:#fff">${x.bucket === null ? "—" : x.bucket + "%"}</div>
                ${x.adj ? `<div style="font-size:11px;color:#7ddc9f">${x.adj > 0 ? "+" : ""}${x.adj} 阻断</div>` : `<div style="font-size:11px;color:#5d6d7e">基准</div>`}
              </div>`;
            }).join("")}
          </div>
          <div class="muted" style="font-size:11.5px;margin-top:4px">
            牌面同花：${Object.entries(boardSuitCount(v.board)).filter(([, n]) => n).map(([k, n]) => SUIT_SYM[k] + n).join(" ") || "无"}　
            存活组合 <b>${vars.filter((x) => !x.dead).length}</b>/${vars.length}　
            持同花色的牌阻断对手的坚果同花，所以频率上调
          </div>` : "";
        $("#treeDetail").innerHTML = head + split + bluffDetailHtml(c.combo) +
          (rule.note ? `　<span style="color:#6b6b6b">${rule.note}</span>` : "") +
          `　<span style="color:#6b6b6b">（${rule.source} · 置信 ${rule.conf}）</span>`;
      };
      box.appendChild(d);
    });
    $("#treeDetail").innerHTML =
      (() => {
        // 图例从实际出现的动作里生成（solver 风格）
        const seen = new Map();
        r.cells.forEach((c) => (c.mix || []).forEach((m) => seen.set(m.kind, m.color)));
        const chips = [...seen.entries()].map(([k, col]) =>
          `<span style="display:inline-block;padding:1px 8px;margin-right:6px;border-radius:3px;background:${col};color:#fff;font-size:11.5px">${esc(k)}</span>`).join("");
        const passTip = v.street === "翻前" ? "深灰＝翻前已弃" : "深灰＝这个节点过牌";
        return `<span style="opacity:.75">图例</span> ${chips}
          <span style="opacity:.75">｜每格按动作占比左右分割，格内数字＝占比最大的动作</span>
          <span style="opacity:.75">｜${passTip}｜点格子看完整混合与诈唬排序</span>`;
      })();
    // 深链：URL 带 ?combo=A5s 时自动点开那手牌（要放在图例之后，否则会被覆盖）
    try {
      const wantCombo = new URLSearchParams(location.search).get("combo");
      if (wantCombo) {
        const el = [...box.querySelectorAll(".treecell")].find((x) => x.textContent.trim().startsWith(wantCombo));
        if (el) setTimeout(() => el.click(), 0);
      }
    } catch (e) {}
  } catch (e) {
    meta.textContent = "请求失败：" + e.message;
    $("#treeDetail").innerHTML = `<b style="color:#ff6b35">请求失败：${e.message}</b>　先关掉复盘台重开一次。`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  domIdSelfCheck();
  treeSelfCheck();
  ["treeMulti","treeTableType","treeHeroStack","treeVillainStack","treeHero","treeVillain","treeOpener","treePot","treeStreet","treeAction","treeRunout","treeLine","treeVsType","treeCapped"].forEach((id) => {
    const e = $("#" + id);
    if (e) e.onchange = loadTree;
  });
  const tb = $("#treeBoard");
  if (tb) tb.onkeydown = (e) => { if (e.key === "Enter") loadTree(); };
  const sg = $("#libSearchGo");
  if (sg) sg.onclick = libDoSearch;
  const ls = $("#libSearch");
  if (ls) ls.onkeydown = (e) => { if (e.key === "Enter") libDoSearch(); };
  const go = $("#treeGo");
  if (go) go.onclick = loadTree;
  const board = $("#treeBoard");
  if (board) board.onkeydown = (e) => { if (e.key === "Enter") loadTree(); };
});

if (params.get("tree")) {
  const setv = (id, v) => { const e = $(id); if (e && v) e.value = v; };
  setv("#treePot", params.get("pot"));
  setv("#treeTableType", params.get("table"));
  {
    const mb = document.getElementById("treeMulti");
    if (mb) mb.checked = params.get("multi") === "1";
  }
  setv("#treeHero", params.get("hero_pos"));
  setv("#treeVillain", params.get("opp_pos"));
  setv("#treeBoard", params.get("board"));
  setv("#treeStreet", params.get("street"));
  setv("#treeAction", params.get("action"));
  setv("#treeHeroStack", params.get("hero_stack") || params.get("stack"));
  setv("#treeVillainStack", params.get("villain_stack") || params.get("stack"));
  setv("#treeOpener", params.get("opener"));
  setv("#treeCapped", params.get("capped"));
  setv("#treeVsType", params.get("vs_type"));
  setv("#treePath", params.get("path"));
  const pip = document.getElementById("treePath");
  if (pip) pip.addEventListener("change", () => { applyPath(pip.value); loadTree(); });
  setv("#treeLine", params.get("line"));
  setv("#treeRunout", params.get("runout"));
  // 分享链接带 ?pf=BTN:open>BB:call：还原整条翻前序列，翻后范围随之带过去
  if (params.get("pf")) {
    try {
      Spot.loadLine(params.get("pf"));
      if (params.get("street")) Spot.setStreet(params.get("street"));
      Spot.apply();
    } catch (e) { console.warn("pf:", e); }
  }
  activateTab("tree", false);
  try { pfSeqRender(); loadTree(); } catch (e) {}
}

