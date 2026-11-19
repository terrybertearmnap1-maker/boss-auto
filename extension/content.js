/* BOSS 自动投递助手 — content script
 * 在 BOSS直聘 职位列表页 / 职位详情页 / 聊天页 运行，做三件事：
 *   1. 列表页：按配置筛选岗位，生成待投递队列
 *   2. 详情页：点「立即沟通」，发送打招呼语
 *   3. 记录结果、控制每日上限、遵守时间窗口、检测风控
 * 运行状态全部存在 chrome.storage.local，跨页面跳转不丢。
 */
(() => {
  'use strict';

  const K_CFG = 'boss_auto_cfg';
  const K_RUN = 'boss_auto_run';
  const K_DAILY = 'boss_auto_daily';
  const K_GREETED = 'boss_auto_greeted';
  const K_LOG = 'boss_auto_log';

  const DEFAULTS = {
    enabled: true,              // 总开关：关掉后即使打开页面也不自动跑
    dryRun: true,               // 演练模式：只筛选和记录，不发消息
    keywords: ['Agent', '智能体', '大模型', 'AI应用'],
    city: '广州',
    salaryMin: 4,
    salaryMax: 10,
    salaryMode: 'min',
    experienceMust: ['应届', '经验不限', '1年以内', '实习', '在校'],
    degreeMust: ['本科', '硕士', '学历不限'],
    greeting: '',               // 空 = 用 BOSS 默认打招呼语（直接回车发送）
    maxPerDay: 20,
    maxPerRun: 20,
    minDelaySec: 25,
    maxDelaySec: 75,
    windows: [['10:00', '11:30'], ['14:00', '16:00']],
    weekdaysOnly: true,
    experienceFilter: 'off',
    excludeKeywords: [],
    coreSkills: ['Python', 'Agent|智能体', 'LLM|大模型', 'RAG|检索增强|知识库', 'LangChain|LangGraph', 'Prompt|提示词'],
    bonusSkills: ['FastAPI', 'Docker', 'SQL', '向量数据库|向量检索', '工具调用|Function Calling', 'MCP', '微调|Fine-tune', '多模态'],
    minScore: 60,
    reportUrl: '',
    autoExecute: false,
    useBackendGreeting: true,
    safetyStopOnCaptcha: true,
  };

  // ---------------- 基础工具 ----------------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const clampText = (s, n = 40) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);

  /**
   * BOSS 用私有区字符（U+E031 起）混淆数字：U+E031→0 … U+E03A→9。
   * 页面上看到的是「260-300元/天」，DOM 里是「\uE033\uE037\uE031-\uE034\uE031\uE031元/天」。
   * 不还原的话薪资永远是空字符串，所有岗位都会被薪资过滤掉。
   */
  function decodePua(s) {
    if (!s) return '';
    return String(s).replace(/[\uE030-\uE03F]/g, (ch) => {
      const code = ch.charCodeAt(0);
      if (code >= 0xE031 && code <= 0xE03A) return String.fromCharCode(0x30 + (code - 0xE031));
      return ch;
    });
  }

  async function storeGet(key, fallback) {
    try {
      const o = await chrome.storage.local.get(key);
      return o[key] === undefined ? fallback : o[key];
    } catch (e) {
      return fallback;
    }
  }
  async function storeSet(key, value) {
    try {
      await chrome.storage.local.set({ [key]: value });
    } catch (e) { /* ignore */ }
  }

  async function getCfg() {
    const cfg = await storeGet(K_CFG, {});
    return { ...DEFAULTS, ...cfg };
  }

  async function waitFor(fn, timeout = 10000, step = 250) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      try {
        const v = fn();
        if (v) return v;
      } catch (e) { /* ignore */ }
      await sleep(step);
    }
    return null;
  }

  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };

  // ---------------- 页面判定 ----------------
  const isJobsPage = () => /zhipin\.com\/web\/geek\/jobs/i.test(location.href);
  const isDetailPage = () => /zhipin\.com\/job_detail\//i.test(location.href);
  const isChatPage = () => /zhipin\.com\/web\/geek\/chat/i.test(location.href);

  const jobId = (url) => {
    const m = String(url || '').match(/job_detail\/([^.?#/]+)\.html/);
    return m ? m[1] : '';
  };

  // BOSS 城市编码
  const CITY_CODES = {
    全国: '100010000', 北京: '101010100', 上海: '101020100', 广州: '101280100',
    深圳: '101280600', 杭州: '101210100', 成都: '101270100', 武汉: '101200100',
    南京: '101190100', 西安: '101110100', 苏州: '101190400', 长沙: '101250100',
    重庆: '101040100', 天津: '101030100',
  };

  /** 城市字段支持逗号分隔的多城市 */
  const splitCities = (city) =>
    String(city || '').split(/[,，、;；\s]+/).map((s) => s.trim()).filter(Boolean);

  /** 生成搜索页链接：BOSS 搜索框只认单个关键词，多关键词靠轮询页面实现 */
  const searchUrl = (keyword, city) => {
    const p = new URLSearchParams();
    p.set('query', keyword || '');
    const code = CITY_CODES[String(city || '').trim()];
    if (code) p.set('city', code);
    p.set('bossauto', '1');
    return `https://www.zhipin.com/web/geek/jobs?${p.toString()}`;
  };

  // ---------------- 时间窗口 ----------------
  function hhmmToMin(s) {
    const [h, m] = String(s).split(':').map(Number);
    return h * 60 + (m || 0);
  }
  function inWindow(cfg, d = new Date()) {
    const day = d.getDay();
    if (cfg.weekdaysOnly && (day === 0 || day === 6)) return false;
    const now = d.getHours() * 60 + d.getMinutes();
    return (cfg.windows || []).some(([a, b]) => now >= hhmmToMin(a) && now <= hhmmToMin(b));
  }

  // ---------------- 职位筛选 ----------------
  function parseSalary(text) {
    const t = String(text || '').replace(/\s/g, '');
    const range = t.match(/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)[Kk千]/);
    if (range) return [Number(range[1]), Number(range[2])];
    const single = t.match(/(\d+(?:\.\d+)?)[Kk]/);
    if (single) return [Number(single[1]), Number(single[1])];
    return null; // 日结/面议等解析不了
  }

  /** 从整张卡片文本里抽出薪资串：15-30K·14薪 / 260-300元/天 / 20K以上 / 面议 */
  function extractSalaryText(text) {
    const t = String(text || '').replace(/\n/g, ' ');
    const m = t.match(
      /(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk](?:\s*·\s*\d+薪)?|\d+\s*-\s*\d+\s*元\s*\/\s*[天时月周]|\d+(?:\.\d+)?\s*[Kk]\s*以上|面议)/
    );
    return m ? m[0] : '';
  }

  function salaryMatch(text, cfg) {
    let r = parseSalary(text);
    if (!r) {
      // 日结/时薪：折算成月薪再比（按 22 天 / 8 小时粗估）
      const t = String(text || '').replace(/\s/g, '');
      const day = t.match(/(\d+)-(\d+)元\/天/);
      if (day) r = [Number(day[1]) * 22 / 1000, Number(day[2]) * 22 / 1000];
      const hour = t.match(/(\d+)-(\d+)元\/[时小]时/);
      if (!r && hour) r = [Number(hour[1]) * 176 / 1000, Number(hour[2]) * 176 / 1000];
    }
    if (!r) return false;
    if (cfg.salaryMode === 'range' && Number(cfg.salaryMax) > 0) {
      // 区间模式：岗位区间与期望区间必须有交集
      return r[1] >= cfg.salaryMin && r[0] <= cfg.salaryMax;
    }
    // 只卡下限：岗位薪资上限 ≥ 期望下限即通过（不封顶）
    return r[1] >= Number(cfg.salaryMin || 0);
  }

  function anyIncludes(list, words) {
    if (!words || !words.length) return true;
    return list.some((t) => words.some((w) => String(t).includes(w)));
  }

  function keywordMatch(title, cfg) {
    const t = String(title || '');
    if (!cfg.keywords || !cfg.keywords.length) return true;
    return cfg.keywords.some((k) => t.includes(k));
  }

  // ---------------- 打招呼按钮 / 输入框 ----------------
  const CHAT_BTN_TEXTS = ['立即沟通', '继续沟通', '打招呼', '立即聊聊'];

  function findChatButton() {
    const sels = [
      '.btn-startchat', '.op-btn-chat', '.job-detail-box .btn-startchat',
      'a[class*="startchat"]', 'button[class*="startchat"]',
      '.job-banner .btn', '.job-op .btn',
    ];
    for (const sel of sels) {
      for (const el of document.querySelectorAll(sel)) {
        if (isVisible(el)) return el;
      }
    }
    // 文本兜底
    for (const el of document.querySelectorAll('a,button,div,span')) {
      const t = (el.innerText || '').trim();
      if (!t || t.length > 10) continue;
      if (CHAT_BTN_TEXTS.some((x) => t === x || t.includes(x))) {
        if (isVisible(el)) return el;
      }
    }
    return null;
  }

  function findChatInput() {
    const sels = [
      '#chat-input', '.chat-input', '.chat-editor',
      'div[contenteditable="true"]', 'textarea[class*="input"]', 'textarea',
    ];
    for (const sel of sels) {
      for (const el of document.querySelectorAll(sel)) {
        if (isVisible(el) && el.getAttribute('contenteditable') !== 'false') return el;
      }
    }
    return null;
  }

  function typeInto(el, text) {
    el.focus();
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
      const setterInput = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
      const isArea = el.tagName === 'TEXTAREA';
      (isArea ? setter : setterInput)?.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    // contenteditable
    try {
      el.innerHTML = '';
      document.execCommand('insertText', false, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    } catch (e) {
      el.textContent = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }
  }

  function pressEnter(el) {
    for (const type of ['keydown', 'keypress', 'keyup']) {
      el.dispatchEvent(new KeyboardEvent(type, {
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, charCode: 13,
        bubbles: true, cancelable: true, composed: true,
      }));
    }
  }

  /** 真·点击：补全 pointer/mouse 事件序列，很多前端只监听 mousedown/pointerdown */
  function realClick(el) {
    const mk = (type, Ctor) => {
      try {
        return new Ctor(type, { bubbles: true, cancelable: true, composed: true, view: window });
      } catch (e) {
        return new MouseEvent(type, { bubbles: true, cancelable: true });
      }
    };
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(mk(t, t.startsWith('pointer') ? PointerEvent : MouseEvent));
    }
  }

  function findSendButton() {
    // 优先找真正的 button，再退化到任意可点元素；取最后一个可见的（聊天框右下角那个）
    const cands = [];
    for (const el of document.querySelectorAll('button, [class*="send"], a, div, span')) {
      const t = (el.innerText || '').trim();
      if (t === '发送' && isVisible(el)) cands.push(el);
    }
    return cands.length ? cands[cands.length - 1] : null;
  }

  /** 输入框里是否还残留着这段文字（用来判断消息到底发出去没有） */
  function stillInInput(input, text) {
    if (!input) return false;
    const cur = (input.innerText || input.value || '').trim();
    if (!cur) return false;
    if (!text) return cur.length > 0;
    return cur.includes(text.slice(0, 6)) || cur.slice(0, 6) === text.slice(0, 6);
  }

  /**
   * 发送消息并验证：点发送按钮 → 复查 → 回车 → 复查。
   * 返回 { ok, via }。ok=false 时调用方必须当成失败，不能记 sent。
   */
  async function sendGreeting(cfg, text) {
    const input = await waitFor(findChatInput, 8000);
    if (!input) return { ok: false, reason: 'no-chat-input' };
    if (!text) return { ok: true, via: 'auto' }; // 留空 = 用 BOSS 自动发出的默认打招呼语
    typeInto(input, text);
    await sleep(500);

    for (let i = 0; i < 3 && stillInInput(input, text); i++) {
      const btn = findSendButton();
      if (btn) realClick(btn);
      await sleep(700);
    }
    for (let i = 0; i < 2 && stillInInput(input, text); i++) {
      pressEnter(input);
      await sleep(600);
    }
    const left = stillInInput(input, text);
    return { ok: !left, via: left ? '' : 'sent', reason: left ? 'send-blocked' : '' };
  }

  // ---------------- JD 抓取与匹配打分 ----------------
  /** 从详情页抽出 JD 正文（不依赖单一类名，取最长的候选块兜底） */
  function extractJdText() {
    const sels = [
      '.job-sec-text', '.job-detail-section', '.job-detail', '[class*="job-detail"]',
      '.job-desc', '[class*="job-desc"]', '.detail-content', '.job-banner-box',
    ];
    let best = '';
    for (const sel of sels) {
      for (const el of document.querySelectorAll(sel)) {
        const t = (el.innerText || '').trim();
        if (t.length > best.length) best = t;
      }
    }
    if (best.length < 80) {
      const body = document.body.innerText || '';
      const i = body.indexOf('职位描述');
      if (i >= 0) best = body.slice(i, i + 4000);
    }
    // 去掉详情页里的按钮文字与杂项，只留正文
    const cleaned = decodePua(best)
      .replace(/微信扫码分享|举报|收藏|立即沟通|感兴趣|继续沟通/g, ' ')
      .replace(/^\s*职位描述\s*/, '')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
    return cleaned.slice(0, 4000);
  }

  /**
   * 取这次要发的话术：优先问后端（按 JD 用 LLM 生成），
   * 后端不可用 / 未配置 / 校验不通过时回退到本地占位符模板。
   */
  async function pickGreeting(cfg, item, jdText, sc) {
    const local = renderGreeting(cfg.greeting, item, sc);
    if (!cfg.useBackendGreeting) return local;
    const base = String(cfg.reportUrl || '').trim();
    if (!base) return local;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 15000);
      const res = await fetch(base.replace(/\/+$/, '') + '/greeting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: item.title || '',
          company: item.company || '',
          jd: String(jdText || '').slice(0, 2000),
          matched: (sc && sc.hits) || [],
        }),
        signal: ctl.signal,
      });
      clearTimeout(timer);
      if (!res.ok) return local;
      const data = await res.json();
      return (data && data.greeting) || local;
    } catch (e) {
      return local;   // 后端不在也不影响投递
    }
  }

  /**
   * 按岗位渲染话术，让每个岗位说的不一样。
   *   {岗位} / {title}    岗位名
   *   {公司} / {company}  公司名
   *   {技能} / {skills}   这份 JD 命中的技能（最多 3 个）
   *   {城市} / {city}     城市
   * 没有占位符就原样返回——绝不擅自改动你写的话。
   */
  function renderGreeting(tpl, item, sc) {
    const hit = (sc && sc.hits ? sc.hits : []).slice(0, 3).join('、');
    return String(tpl || '')
      .replace(/\{岗位\}|\{title\}/g, (item && item.title) || '')
      .replace(/\{公司\}|\{company\}/g, (item && item.company) || '')
      .replace(/\{技能\}|\{skills\}/g, hit)
      .replace(/\{城市\}|\{city\}/g, (item && item.city) || '');
  }

  /**
   * 匹配打分：我的技能画像被这份 JD 覆盖的比例（0-100）。
   * 核心技能权重 3，加分技能权重 1。
   *
   * 排除词只匹配**岗位标题**，不扫 JD 正文——
   * 「AI Agent 开发工程师」的正文里常提到"后端/服务端"，扫全文会把好岗位全判死。
   */
  function scoreJd(jdText, cfg, title) {
    const text = jdText || '';
    const head = String(title || '');
    const banned = (cfg.excludeKeywords || []).find((w) => w && head.includes(w));
    if (banned) return { score: 0, hits: [], miss: [], banned };
    const core = (cfg.coreSkills || []).filter(Boolean);
    const bonus = (cfg.bonusSkills || []).filter(Boolean);
    const items = [
      ...core.map((w) => ({ w, weight: 3 })),
      ...bonus.map((w) => ({ w, weight: 1 })),
    ];
    if (!items.length) return { score: 0, hits: [], miss: [], reason: 'no-profile' };
    const total = items.reduce((s, i) => s + i.weight, 0) || 1;
    let got = 0;
    const hits = [];
    const miss = [];
    for (const it of items) {
      const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      // 支持同义词组：'LLM|大模型' 任一命中即算
      const parts = String(it.w).split('|').map((s) => s.trim()).filter(Boolean);
      const hit = parts.some((p) => new RegExp(esc(p), 'i').test(text));
      if (hit) { got += it.weight; hits.push(it.w.split('|')[0]); } else miss.push(it.w.split('|')[0]);
    }
    return { score: Math.round((got / total) * 100), hits, miss };
  }

  // ---------------- 风控检测 ----------------
  function captchaVisible() {
    if (/[?&]_security_check=/.test(location.href)) return true;
    const sels = ['#captcha', '.geetest_panel', '.nc-container', '.captcha', '[class*="verify"]'];
    return sels.some((s) => [...document.querySelectorAll(s)].some(isVisible));
  }

  // ---------------- 运行状态 ----------------
  async function getRun() { return storeGet(K_RUN, null); }
  async function setRun(run) { await storeSet(K_RUN, run); }

  async function bumpDaily() {
    const today = new Date().toISOString().slice(0, 10);
    const d = await storeGet(K_DAILY, { date: today, count: 0 });
    if (d.date !== today) return { date: today, count: 0 };
    return d;
  }

  async function todayCount() {
    const d = await bumpDaily();
    return d.count;
  }

  async function incDaily() {
    const today = new Date().toISOString().slice(0, 10);
    const d = await storeGet(K_DAILY, { date: today, count: 0 });
    const next = d.date === today ? { date: today, count: d.count + 1 } : { date: today, count: 1 };
    await storeSet(K_DAILY, next);
    return next.count;
  }

  async function logEntry(entry) {
    const log = await storeGet(K_LOG, []);
    log.push({ ts: new Date().toISOString(), ...entry });
    await storeSet(K_LOG, log.slice(-500));
    // 可选：上报到本地 JobPilot 后端（失败静默，绝不影响投递流程）
    reportToBackend(entry).catch(() => {});
    rememberVisited(entry);
  }

  // ---------------- 批量上报（供多 Agent 流水线复用） ----------------
  // 注意：必须存 chrome.storage 而不是内存数组——
  // 流程每跳一个岗位详情页都是一次整页加载，content script 会重跑，内存变量直接清空。
  const K_VISITED = 'boss_auto_visited';

  async function rememberVisited(entry) {
    if (!entry || !entry.url || !entry.jd) return;
    const jid = entry.jobId || jobId(entry.url);
    if (!jid) return;
    const list = await storeGet(K_VISITED, []);
    if (list.some((v) => v.job_id === jid)) return;
    list.push({
      job_id: jid,
      title: entry.title || '',
      company: entry.company || '',
      salary: entry.salary || '',
      url: entry.url,
      jd: String(entry.jd).slice(0, 2000),
    });
    await storeSet(K_VISITED, list.slice(-80));
  }

  async function flushVisited(cfg) {
    const base = String((cfg && cfg.reportUrl) || '').trim();
    if (!base) return 0;
    const batch = await storeGet(K_VISITED, []);
    if (!batch.length) return 0;
    await storeSet(K_VISITED, []);
    try {
      await fetch(base.replace(/\/+$/, '') + '/search-results', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keywords: (cfg && cfg.keywords) || [],
          city: (cfg && cfg.city) || '',
          source: 'extension',
          jobs: batch,
        }),
      });
      return batch.length;
    } catch (e) {
      return 0; // 上报失败不影响投递
    }
  }

  // 上报失败计数：后端没起 / 端口被占时扩展不会报错，数据会静默丢失，
  // 把失败次数显示在面板上，否则用户根本不知道丢了数据。
  const K_FAIL = 'boss_auto_report_fail';

  async function bumpFail(n = 1) {
    const cur = (await storeGet(K_FAIL, 0)) || 0;
    await storeSet(K_FAIL, cur + n);
  }

  async function reportFailCount() {
    return (await storeGet(K_FAIL, 0)) || 0;
  }

  /** 把岗位结果推给 JobPilot（数据库 / 向量去重 / 看板都靠它） */
  async function reportToBackend(entry) {
    const cfg = await getCfg();
    const base = String(cfg.reportUrl || '').trim();
    if (!base || !entry.url) return;
    const jid = entry.jobId || jobId(entry.url);
    if (!jid) return;
    let res = null;
    try {
      res = await fetch(base.replace(/\/+$/, '') + '/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jid,
          title: entry.title || '',
          company: entry.company || '',
          salary: entry.salary || '',
          url: entry.url || '',
          source: 'zhipin',
          jd: entry.jd || '',
        }),
      });
    } catch (e) {
      await bumpFail();
      return;
    }
    if (!res || !res.ok) await bumpFail();
  }

  async function markGreeted(id) {
    const g = await storeGet(K_GREETED, {});
    g[id] = Date.now();
    // 只保留 60 天
    const cutoff = Date.now() - 60 * 864e5;
    for (const k of Object.keys(g)) if (g[k] < cutoff) delete g[k];
    await storeSet(K_GREETED, g);
  }

  // ---------------- 面板 UI ----------------
  let panel = null;
  let panelStatus = '';
  let panelTimer = null;

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = document.createElement('div');
    panel.id = 'boss-auto-panel';
    panel.innerHTML = `
      <div class="ba-head">
        <span class="ba-title">BOSS 自动投递 <em style="font-style:normal;opacity:.75;font-size:11px">v3.8</em></span>
        <span class="ba-badge" id="ba-badge">待机</span>
      </div>
      <div class="ba-body">
        <div class="ba-row"><span>今日已投</span><b id="ba-count">0</b></div>
        <div class="ba-row"><span>本轮进度</span><b id="ba-progress">-</b></div>
        <div id="ba-fail" style="display:none;color:#ffb020;font-size:11px;margin-top:2px"></div>
        <div class="ba-status" id="ba-status">等待</div>
        <div class="ba-actions">
          <button id="ba-start">开始</button>
          <button id="ba-stop">停止</button>
          <button id="ba-csv">导出</button><button id="ba-dump">诊断</button>
        </div>
        <div class="ba-tip" id="ba-tip"></div>
      </div>`;
    document.body.appendChild(panel);

    panel.querySelector('#ba-start').addEventListener('click', async () => {
      await startRun(true);
    });
    panel.querySelector('#ba-stop').addEventListener('click', async () => {
      const run = await getRun();
      if (run && run.status === 'running') {
        run.status = 'stopped';
        run.stoppedAt = Date.now();
        await setRun(run);
        await logEntry({
          status: 'stop',
          reason: `done=${run.done.length} cursor=${run.cursor}/${run.queue.length}`,
        });
        await exportCsv(true); // 手动停止也要落盘，否则记录只留在浏览器里
        await flushVisited(await getCfg());
        setStatus(`已停止，已导出记录（${run.cursor}/${run.queue.length}）`);
        return;
      }
      setStatus('当前没有运行中的任务');
    });
    panel.querySelector('#ba-csv').addEventListener('click', () => exportCsv(true));
    panel.querySelector('#ba-dump').addEventListener('click', () => dumpDiagnostics());
    return panel;
  }

  function setStatus(text, tip) {
    panelStatus = text;
    const el = document.getElementById('ba-status');
    if (el) el.textContent = text;
    if (tip !== undefined) {
      const t = document.getElementById('ba-tip');
      if (t) t.textContent = tip;
    }
  }

  async function refreshPanel() {
    const panelEl = ensurePanel();
    const cfg = await getCfg();
    const run = await getRun();
    const count = await todayCount();
    panelEl.querySelector('#ba-count').textContent = String(count);
    const fails = await reportFailCount();
    const failEl = panelEl.querySelector('#ba-fail');
    if (failEl) {
      failEl.textContent = fails ? `⚠ 上报失败 ${fails} 条（后端没收到，检查服务是否在跑）` : '';
      failEl.style.display = fails ? 'block' : 'none';
    }
    const badge = panelEl.querySelector('#ba-badge');
    if (!run || run.status !== 'running') {
      badge.textContent = run && run.status === 'finished' ? '已完成' : '待机';
      badge.className = 'ba-badge idle';
      if (run && run.status === 'finished') {
        setStatus(`本轮完成：成功 ${run.done?.length || 0}，跳过 ${run.skipped?.length || 0}`,
          `演练模式：${cfg.dryRun ? '开（不发消息）' : '关（会真实发送）'}`);
      }
    } else {
      badge.textContent = cfg.dryRun ? '演练中' : '运行中';
      badge.className = 'ba-badge running';
      panelEl.querySelector('#ba-progress').textContent =
        `${Math.min(run.cursor + 1, run.queue.length)} / ${run.queue.length}`;
      setStatus(panelStatus || '正在处理…');
    }
    return panelEl;
  }

  // ---------------- CSV 导出 ----------------
  /** 把前 5 张职位卡片的原始 HTML / 文本 / 解析结果导出，用于排查选择器 */
  async function dumpDiagnostics() {
    const anchors = [...document.querySelectorAll('a[href*="/job_detail/"]')];
    const cards = anchors.slice(0, 5).map((a) => {
      const card = a.closest('li') || a.closest('.job-card-wrapper') || a.parentElement;
      return {
        href: a.href,
        cardClass: card ? String(card.className) : '',
        cardText: card ? card.innerText : '',
        parsedTitle: card ? (card.querySelector('.job-name')?.innerText || '') : '',
        parsedSalary: card ? (card.querySelector('.salary')?.innerText || '') : '',
        innerHTML: card ? card.outerHTML.slice(0, 6000) : '',
      };
    });
    const payload = {
      url: location.href,
      time: new Date().toISOString(),
      anchorCount: anchors.length,
      cards,
    };
    const data = 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(payload, null, 2));
    try {
      await chrome.runtime.sendMessage({
        type: 'download',
        url: data,
        filename: `boss-auto/diag-${Date.now()}.json`,
        saveAs: false,
      });
      setStatus('诊断已导出到 下载/boss-auto/');
    } catch (e) {
      setStatus('诊断导出失败：' + (e && e.message));
    }
  }

  async function exportCsv(auto = false) {
    const log = await storeGet(K_LOG, []);
    const rows = [['时间', '状态', '职位', '薪资', '公司', '匹配分', '命中技能', '链接', '说明', 'JD摘要']];
    for (const e of log) {
      rows.push([
        e.ts, e.status, e.title || '', e.salary || '', e.company || '',
        e.score === undefined ? '' : e.score, e.hits || '', e.url || '', e.reason || '',
        (e.jd || '').replace(/\s+/g, ' ').slice(0, 300),
      ]);
    }
    const csv = '\ufeff' + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    try {
      // content script 不能直接调 downloads，转交 background
      await chrome.runtime.sendMessage({
        type: 'download',
        url: 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv),
        filename: `boss-auto/boss-auto-${stamp}.csv`,
        saveAs: !auto,
      });
    } catch (e) {
      console.warn('[boss-auto] 导出失败', e);
    }
  }

  // ---------------- 列表页 ----------------
  async function collectJobs(cfg, greeted) {
    const stats = { links: 0, cards: 0, excluded: 0, keyword: 0, salary: 0, exp: 0, degree: 0, matched: 0 };
    const samples = [];
    await waitFor(() => document.querySelectorAll('a[href*="/job_detail/"]').length > 0, 20000);
    // 触发懒加载：滚到底再回顶
    for (let i = 0; i < 3; i++) {
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(1200);
    }
    window.scrollTo(0, 0);
    await sleep(600);

    const seen = new Set();
    const out = [];
    for (const a of document.querySelectorAll('a[href*="/job_detail/"]')) {
      stats.links += 1;
      if (out.length >= cfg.maxPerRun) break;
      const href = a.href;
      const id = jobId(href);
      if (!id || seen.has(id) || greeted[id]) continue;
      const card = a.closest('li') || a.closest('.job-card-wrapper') || a.parentElement;
      if (!card) continue;
      stats.cards += 1;
      // 不依赖单一类名：先取整张卡片的文本（并还原私有区数字），再从中抽标题/薪资/标签
      const cardText = decodePua(card.innerText || '').trim();
      const titleEl = card.querySelector('.job-name, .job-title, [class*="job-name"], [class*="job-title"]');
      const title = clampText(decodePua(titleEl ? titleEl.innerText : (cardText.split('\n')[0] || '')), 40);
      const salaryEl = card.querySelector('.job-salary, .salary, [class*="salary"]');
      const salary = clampText(
        decodePua(salaryEl ? salaryEl.innerText : '') || extractSalaryText(cardText), 24);
      const company = clampText(
        decodePua(card.querySelector('.boss-name, .company-name, [class*="company-name"]')?.innerText || ''), 30);
      const tags = [...card.querySelectorAll('.tag-list li, [class*="tag-list"] li, [class*="tag"] li')]
        .map((x) => clampText(x.innerText, 12))
        .filter(Boolean);
      if (samples.length < 6) samples.push(`${title}|${salary}|${tags.join('/')}`);

      // 排除词优先：命中就跳过（比如 java / 后端 / 销售）
      const exHit = (cfg.excludeKeywords || []).find((w) => w && `${title} ${cardText}`.includes(w));
      if (exHit) { stats.excluded += 1; continue; }
      if (!keywordMatch(`${title} ${cardText}`, cfg)) continue;
      stats.keyword += 1;
      if (!salaryMatch(salary, cfg)) continue;
      stats.salary += 1;
      // 实习/在校岗位的经验标签是「5天/周 6个月」这类，单独放行
      const isIntern = /实习|在校/.test(cardText) || tags.some((t) => /天\s*\/\s*周|个月/.test(t));
      // 经验：默认不卡（BOSS 上多数岗位标 1-3 年也收应届），可切回严格匹配
      if (cfg.experienceFilter === 'strict' && !isIntern && !anyIncludes(tags, cfg.experienceMust)) continue;
      stats.exp += 1;
      if (!anyIncludes(tags, cfg.degreeMust)) continue;
      stats.degree += 1;

      seen.add(id);
      out.push({ url: href, id, title, salary, company, tags });
    }
    stats.matched = out.length;
    window.__bossAutoStats = { stats, samples };
    console.log('[boss-auto] 筛选统计', stats, samples);
    return { queue: out, stats, samples };
  }

  async function startRun(manual = false, windowed = false) {
    const cfg = await getCfg();
    if (!manual) {
      if (!cfg.enabled) return null;
      if (!inWindow(cfg)) return null;
    }
    const greeted = await storeGet(K_GREETED, {});
    await storeSet(K_VISITED, []); // 新一轮开始，清掉上一轮残留的访问缓冲
    await storeSet(K_FAIL, 0);     // 上报失败计数按轮统计
    setStatus('正在筛选岗位…');
    const { queue, stats, samples } = await collectJobs(cfg, greeted);
    if (!queue.length) {
      const line = `链接${stats.links}/卡片${stats.cards}/排除${stats.excluded}/关键词${stats.keyword}/薪资${stats.salary}/学历${stats.degree}`;
      const sampleTip = samples && samples.length
        ? '识别样例：' + samples.slice(0, 2).join(' ／ ')
        : '没抓到任何卡片，检查页面是否加载完';
      setStatus(`0 命中 · ${line}`, sampleTip);
      await logEntry({ status: 'empty', reason: line });
      return null;
    }
    // 关键词 × 城市 的笛卡尔积：每个组合打开一次搜索页收集岗位
    const kwList = (cfg.keywords || []).filter(Boolean);
    const cityList = splitCities(cfg.city);
    const searches = [];
    for (const kw of (kwList.length ? kwList : [''])) {
      for (const c of (cityList.length ? cityList : [''])) searches.push({ kw, city: c });
    }
    const run = {
      status: 'running',
      dryRun: cfg.dryRun,
      windowed,
      startedAt: Date.now(),
      queue,
      cursor: 0,
      done: [],
      skipped: [],
      searches,
      keywords: kwList.slice(),
      phase: 0,
      cfgSnapshot: { keywords: cfg.keywords, salary: [cfg.salaryMin, cfg.salaryMax], city: cfg.city },
    };
    await setRun(run);
    await logEntry({
      status: 'start',
      reason: `queue=${queue.length} links=${stats.links} cards=${stats.cards} ex=${stats.excluded} kw=${stats.keyword} sal=${stats.salary} deg=${stats.degree} city=${cfg.city} keywords=${kwList.join('|')} searches=${searches.length} exclude=${(cfg.excludeKeywords || []).join('|')}`,
    });
    setStatus(`已筛选 ${queue.length} 个岗位，开始投递`);
    await sleep(1500);
    location.href = queue[0].url;
    return run;
  }

  async function initJobsPage() {
    await refreshPanel();
    const cfg = await getCfg();
    const run = await getRun();
    const params = new URLSearchParams(location.search);
    const auto = params.get('bossauto') === '1';
    const isSearchPage = params.has('query');

    // 上一轮跑到一半被打断 → 继续
    if (run && run.status === 'running' && run.cursor < run.queue.length) {
      const next = run.queue[run.cursor];
      setStatus('继续上一轮，跳转到下一个岗位…');
      await sleep(1200);
      location.href = next.url;
      return;
    }
    // 多搜索轮询（关键词 × 城市）：上一个组合的岗位跑完了，切到下一个搜索页继续采集
    if (run && run.status === 'collecting') {
      const cur = (run.searches || [])[run.phase] || {};
      const kw = cur.kw || (run.keywords || [])[run.phase] || '';
      const cityLabel = cur.city || '';
      setStatus(`采集「${kw}」${cityLabel ? ' · ' + cityLabel : ''}…`);
      await sleep(2500);
      const greeted = await storeGet(K_GREETED, {});
      const { queue: more } = await collectJobs(cfg, greeted);
      const have = new Set(run.queue.map((x) => x.id));
      // 关键：总队列不能超过「单轮上限」，多关键词累计时要卡住
      const room = Math.max(0, Number(cfg.maxPerRun || 20) - run.queue.length);
      const added = more.filter((x) => !have.has(x.id)).slice(0, room);
      run.queue = run.queue.concat(added);
      run.status = 'running';
      await setRun(run);
      setStatus(`「${kw}」追加 ${added.length} 个岗位`);
      await sleep(1200);
      const next = run.queue[run.cursor];
      if (next) {
        location.href = next.url;
        return;
      }
      // 这个搜索词一个都没补进来 → 继续推进（切下一个搜索词或收工），
      // 否则流程会停在这一步，既不投递也不结束（v3.2 及之前的问题）
      await nextJob(run);
      return;
    }
    // 只带 bossauto=1 的裸链接：按当前配置自动跳到对应搜索页（定时任务用这个，换方向不用改任务）
    if (auto && !isSearchPage) {
      const kw0 = (cfg.keywords || [])[0] || '';
      const city0 = splitCities(cfg.city)[0] || '';
      setStatus(`按当前配置打开搜索：${kw0}${city0 ? ' · ' + city0 : ''}`);
      await sleep(800);
      location.href = searchUrl(kw0, city0);
      return;
    }
    // 「推荐」等非搜索页不自动启动，避免把推荐流当成搜索结果
    if (!auto && !isSearchPage) {
      setStatus('当前是推荐页，不自动运行', '请打开带 query 参数的搜索页，或点设置页的「打开投递页」');
      return;
    }
    if (!cfg.enabled && !auto) { setStatus('总开关已关闭'); return; }
    if (!auto && !inWindow(cfg)) {
      setStatus('不在投递时段（周一至周五 10:00-11:30 / 14:00-16:00）');
      return;
    }
    if ((await todayCount()) >= cfg.maxPerDay) { setStatus('今日已达上限'); return; }

    if (auto) {
      // 去掉 bossauto 参数，避免刷新重复触发
      const u = new URL(location.href);
      u.searchParams.delete('bossauto');
      history.replaceState(null, '', u.toString());
    }
    await sleep(1500);
    // 走到这里说明已通过 enabled / 时间窗口 / 上限检查（auto 参数视为显式触发）
    await startRun(true, true);
  }

  // ---------------- 详情页 ----------------
  async function nextJob(run, reason) {
    if (reason) run.skipped.push(reason);
    run.cursor += 1;
    await setRun(run);
    if (run.cursor >= run.queue.length) {
      const all = run.searches || [];
      if ((run.phase || 0) + 1 < all.length) {
        run.phase = (run.phase || 0) + 1;
        run.status = 'collecting';
        await setRun(run);
        const nx = all[run.phase];
        setStatus(`切换搜索「${nx.kw}」${nx.city ? ' · ' + nx.city : ''}，继续筛选…`);
        await sleep(rnd(2500, 5000));
        location.href = searchUrl(nx.kw, nx.city);
        return;
      }
      await finishRun(run);
      return;
    }
    const cfg = await getCfg();
    // 定时触发的一轮：过了投递时段就收工，不拖到窗口外
    if (run.windowed && !inWindow(cfg)) {
      setStatus('已到投递时段结束，提前收工');
      await finishRun(run);
      return;
    }
    const lo = Math.max(5, Number(cfg.minDelaySec) || 25);
    const hi = Math.max(lo + 1, Number(cfg.maxDelaySec) || 75);
    const delay = rnd(lo * 1000, hi * 1000);
    setStatus(`下一个岗位，${Math.round(delay / 1000)} 秒后跳转…`);
    await sleep(delay);
    location.href = run.queue[run.cursor].url;
  }

  async function finishRun(run) {
    run.status = 'finished';
    run.finishedAt = Date.now();
    await setRun(run);
    await logEntry({ status: 'finish', reason: `done=${run.done.length} skipped=${run.skipped.length}` });
    // 把本轮访问过、带 JD 的岗位批量推给 JobPilot，供多 Agent 流水线复用
    const pushed = await flushVisited(await getCfg());
    setStatus(
      `本轮完成：成功 ${run.done.length}，跳过 ${run.skipped.length}`,
      pushed ? `已上报 ${pushed} 条岗位给 JobPilot` : ''
    );
    await exportCsv(true);
    await refreshPanel();
  }

  async function initDetailPage() {
    await refreshPanel();

    // P6：如果是后端下发的投递指令，优先执行它（执行完就停，不续跑队列）
    const cmd = await storeGet(K_CMD, null);
    if (cmd && cmd.job && jobId(location.href) === cmd.job.job_id) {
      await runCommand(cmd, await getCfg());
      return;
    }

    const run = await getRun();
    if (!run || run.status !== 'running') { setStatus('未运行，忽略此页'); return; }
    const id = jobId(location.href);
    const item = run.queue[run.cursor] || {};
    if (id && item.id && id !== item.id) {
      // 不是队列中的岗位（比如用户手动点开）→ 直接回队列
      await nextJob(run, 'not-in-queue');
      return;
    }

    // 每日上限：跑到一半超了也要立刻收工
    const cfgNow = await getCfg();
    if ((await todayCount()) >= Number(cfgNow.maxPerDay || 20)) {
      setStatus('已达每日上限，收工', `今日已投 ${await todayCount()} 个`);
      await finishRun(run);
      return;
    }

    if (captchaVisible()) {
      setStatus('检测到验证码/安全校验，已停止', '请在浏览器里完成验证后手动点「开始」');
      run.status = 'stopped';
      run.stoppedAt = Date.now();
      run.stopReason = 'captcha';
      await setRun(run);
      await logEntry({ status: 'captcha', title: item.title, url: location.href });
      return;
    }

    const greeted = await storeGet(K_GREETED, {});
    if (id && greeted[id]) { await nextJob(run, 'already-greeted'); return; }

    setStatus(`打开岗位：${item.title || id}`);
    const btn = await waitFor(findChatButton, 12000);
    if (!btn) {
      await logEntry({ status: 'skip', reason: 'no-chat-button', title: item.title, url: location.href });
      await nextJob(run, 'no-chat-button');
      return;
    }

    const btnText = (btn.innerText || '').trim();
    if (/继续沟通/.test(btnText)) {
      await logEntry({ status: 'skip', reason: 'already-chatted', title: item.title, url: location.href });
      await markGreeted(id);
      await nextJob(run);
      return;
    }

    // 抓 JD 并打分（演练模式也打，方便先看分数分布）
    const jdText = extractJdText();
    const cfgNow2 = await getCfg();
    const sc = scoreJd(jdText, cfgNow2, item.title);
    item.score = sc.score;
    run.queue[run.cursor] = item;
    await setRun(run);
    setStatus(`匹配分 ${sc.score} · ${item.title}`);
    const minScore = Number(cfgNow2.minScore || 0);
    if (jdText.length < 20) {
      // 抓不到 JD 时不能按 0 分处理，否则会把整轮岗位全刷掉
      await logEntry({
        status: 'warn', reason: 'jd-empty', title: item.title, url: location.href,
      });
      setStatus('JD 抓取为空，本轮跳过打分', '可能是详情页结构变了，点「诊断」导出给我');
    } else if (sc.banned) {
      await logEntry({
        status: 'skip', reason: `banned:${sc.banned}`, score: 0,
        title: item.title, salary: item.salary, company: item.company, url: location.href,
        jd: jdText.slice(0, 200),
      });
      await nextJob(run, 'banned');
      return;
    }
    if (sc.score < minScore) {
      await logEntry({
        status: 'skip', reason: `low-score<${minScore}`, score: sc.score,
        title: item.title, salary: item.salary, company: item.company, url: location.href,
        jd: jdText.slice(0, 2000),
      });
      setStatus(`分数不足（${sc.score} < ${minScore}），跳过：${item.title}`);
      await nextJob(run, 'low-score');
      return;
    }

    // 演练模式：只确认「立即沟通」按钮存在，绝不点击
    // （BOSS 点这个按钮会自动发默认打招呼语，演练时点它就等于真发了）
    if (run.dryRun) {
      run.done.push({ id, title: item.title, mode: 'dry-run', score: sc.score });
      await logEntry({
        status: 'dry-run', score: sc.score, hits: sc.hits.join('/'),
        title: item.title, salary: item.salary, company: item.company, url: location.href,
        jd: jdText.slice(0, 2000),
      });
      setStatus(`演练命中：${item.title}`);
      await nextJob(run);
      return;
    }

    // 已关闭 BOSS 自动打招呼语的情况下，扩展没配话术就会点出"空对话"——直接拦下
    const cfgPre = await getCfg();
    if (!String(cfgPre.greeting || '').trim()) {
      run.status = 'stopped';
      run.stoppedAt = Date.now();
      run.stopReason = 'no-greeting';
      await setRun(run);
      await logEntry({ status: 'stopped', reason: 'no-greeting', title: item.title, url: location.href });
      setStatus('未配置打招呼语，已停止', '去设置页填一段话术再运行，否则会创建空对话');
      return;
    }

    btn.click();
    await sleep(rnd(1500, 2500));

    const cfg = await getCfg();
    setStatus('正在发送打招呼语…');
    const res = await sendGreeting(cfg, await pickGreeting(cfg, item, jdText, sc));
    if (!res.ok) {
      // 没发出去就不能算成功，也不能标记为已沟通，下一轮还能重试
      await logEntry({
        status: 'fail', reason: res.reason || 'send-failed',
        title: item.title, salary: item.salary, company: item.company, url: location.href,
      });
      setStatus(`发送失败，跳过：${item.title}`, '输入框里还留着文字，说明没点动发送按钮');
      await nextJob(run, res.reason || 'send-failed');
      return;
    }

    await sleep(rnd(1000, 1600));
    await markGreeted(id);
    await incDaily();
    run.done.push({ id, title: item.title, via: res.via });
    await logEntry({
      status: 'sent', score: sc.score, hits: sc.hits.join('/'), via: res.via,
      title: item.title, salary: item.salary, company: item.company, url: location.href,
      jd: jdText.slice(0, 2000),
    });
    setStatus(`已打招呼：${item.title}`);
    await nextJob(run);
  }

  // ---------------- P6：后端下发的投递指令 ----------------
  const K_CMD = 'boss_auto_cmd';

  /** 执行一条指令：进页面 → 点立即沟通 → 发后端算好的话术 → ack 回报 */
  async function runCommand(cmd, cfg) {
    const job = cmd.job || {};
    setStatus(`执行指令：${job.title || ''}`);
    const btn = await waitFor(findChatButton, 12000);
    if (!btn) {
      await ackCommand(cmd.id, false, 'no-chat-button');
      await storeSet(K_CMD, null);
      setStatus('指令失败：找不到「立即沟通」');
      return;
    }
    btn.click();
    await sleep(rnd(1500, 2500));
    const res = await sendGreeting(cfg, job.greeting || cfg.greeting || '');
    await ackCommand(cmd.id, res.ok, res.reason || '');
    await storeSet(K_CMD, null);
    await logEntry({
      status: res.ok ? 'cmd-sent' : 'cmd-failed',
      title: job.title, company: job.company, url: job.url,
      reason: res.reason || '',
    });
    setStatus(res.ok ? `指令完成：${job.title}` : `指令失败：${res.reason || '发送失败'}`);
  }

  async function ackCommand(id, ok, reason) {
    try {
      const cfg = await getCfg();
      const base = String(cfg.reportUrl || '').trim();
      if (!base || !id) return;
      await fetch(base.replace(/\/+$/, '') + '/commands/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, ok, reason: String(reason || '').slice(0, 200) }),
      });
    } catch (e) { /* 静默 */ }
  }

  /** 轮询后端指令队列；只在没有正常流程进行时工作 */
  let pollTimer = null;
  function startCommandPoller() {
    if (pollTimer) return;
    setStatus('指令轮询已启动（每 6 秒问一次后端）');
    pollTimer = setInterval(async () => {
      try {
        const cfg = await getCfg();
        if (!cfg.autoExecute) return;
        const base = String(cfg.reportUrl || '').trim();
        if (!base) return;
        const run = await getRun();
        if (run && run.status === 'running') return;   // 正常投递进行中，不抢
        if (await storeGet(K_CMD, null)) return;       // 已有指令待执行

        // 限速：两条指令之间至少间隔 25-45 秒，模拟人看岗位的时间
        const last = (await storeGet('boss_auto_last_exec', 0)) || 0;
        if (Date.now() - last < rnd(25000, 45000)) return;
        const res = await fetch(base.replace(/\/+$/, '') + '/commands?limit=1');
        if (!res.ok) return;
        const data = await res.json();
        const cmd = (data.items || [])[0];
        if (!cmd || !cmd.job || !cmd.job.url) return;
        await storeSet(K_CMD, cmd);
        await storeSet('boss_auto_last_exec', Date.now());
        location.href = cmd.job.url;
      } catch (e) { /* 网络问题忽略，下一轮再试 */ }
    }, 6000);
  }

  // 设置页刚勾上「自动执行后端下发的投递指令」时，立即生效，不用刷新页面
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes[K_CFG]) return;
      const next = changes[K_CFG].newValue || {};
      if (next.autoExecute) startCommandPoller();
    });
  } catch (e) { /* 某些上下文没有 storage.onChanged，忽略 */ }

  // ---------------- 聊天页（立即沟通跳转到这里时兜底处理） ----------------
  async function initChatPage() {
    const run = await getRun();
    if (!run || run.status !== 'running') return;
    await refreshPanel();
    const item = run.queue[run.cursor] || {};
    setStatus(`聊天页：${item.title || ''}`);
    const cfg = await getCfg();
    const input = await waitFor(findChatInput, 8000);
    if (!input) { await nextJob(run, 'chat-no-input'); return; }
    if (!run.dryRun) {
      const res = await sendGreeting(cfg, renderGreeting(cfg.greeting, item, null));
      if (!res.ok) {
        await logEntry({ status: 'fail', reason: res.reason || 'send-failed', title: item.title, url: location.href });
        await nextJob(run, res.reason || 'send-failed');
        return;
      }
      await sleep(1500);
      if (item.id) await markGreeted(item.id);
      await incDaily();
      run.done.push({ id: item.id, title: item.title, via: res.via });
      await logEntry({ status: 'sent', via: res.via, title: item.title, url: location.href });
    }
    await sleep(rnd(2000, 4000));
    // 发完这一条，直接进入队列中的下一个岗位
    await nextJob(run);
  }

  // ---------------- 入口 ----------------
  async function main() {
    // 只在 zhipin 域下工作
    if (!/zhipin\.com/.test(location.hostname)) return;
    try {
      if (isJobsPage()) await initJobsPage();
      else if (isDetailPage()) await initDetailPage();
      else if (isChatPage()) await initChatPage();

      // P6：开启「自动执行后端指令」后，任何 BOSS 页面都会轮询指令队列
      const cfg = await getCfg();
      if (cfg.autoExecute) startCommandPoller();
    } catch (e) {
      console.warn('[boss-auto] error', e);
      setStatus('出错：' + (e && e.message ? e.message : 'unknown'));
    }
    panelTimer = setInterval(refreshPanel, 5000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', main);
  } else {
    main();
  }
})();

