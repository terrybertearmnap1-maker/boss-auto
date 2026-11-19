/* 设置页逻辑 */

const K_CFG = 'boss_auto_cfg';
const K_DAILY = 'boss_auto_daily';
const K_LOG = 'boss_auto_log';

// BOSS 城市编码（常用）
const CITY_CODES = {
  全国: '100010000',
  北京: '101010100',
  上海: '101020100',
  广州: '101280100',
  深圳: '101280600',
  杭州: '101210100',
  成都: '101270100',
  武汉: '101200100',
  南京: '101190100',
  西安: '101110100',
  苏州: '101190400',
  长沙: '101250100',
  重庆: '101040100',
  天津: '101030100',
};

const DEFAULTS = {
  enabled: true,
  dryRun: true,
  keywords: ['Agent', '智能体', '大模型', 'AI应用'],
  city: '广州',
  salaryMin: 4,
  salaryMax: 10,
  salaryMode: 'min',
  experienceMust: ['应届', '经验不限', '1年以内', '实习', '在校'],
  degreeMust: ['本科', '硕士', '学历不限'],
  greeting: '',
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
  safetyStopOnCaptcha: true,
};

const $ = (id) => document.getElementById(id);
const splitList = (s) => String(s || '').split(/[,，、]/).map((x) => x.trim()).filter(Boolean);

function fill(cfg) {
  $('keywords').value = (cfg.keywords || []).join(',');
  $('excludeKeywords').value = (cfg.excludeKeywords || []).join(',');
  $('coreSkills').value = (cfg.coreSkills || []).join(',');
  $('bonusSkills').value = (cfg.bonusSkills || []).join(',');
  $('minScore').value = cfg.minScore === undefined ? 60 : cfg.minScore;
  $('reportUrl').value = cfg.reportUrl || '';
  $('city').value = cfg.city || '';
  $('salaryMin').value = cfg.salaryMin;
  $('salaryMode').value = cfg.salaryMode || 'min';
  $('salaryMax').value = cfg.salaryMax;
  $('experienceMust').value = (cfg.experienceMust || []).join(',');
  $('experienceFilter').value = cfg.experienceFilter || 'off';
  $('degreeMust').value = (cfg.degreeMust || []).join(',');
  $('greeting').value = cfg.greeting || '';
  $('maxPerDay').value = cfg.maxPerDay;
  $('maxPerRun').value = cfg.maxPerRun;
  $('minDelay').value = cfg.minDelaySec;
  $('maxDelay').value = cfg.maxDelaySec;
  const w = cfg.windows || [['10:00', '11:30'], ['14:00', '16:00']];
  $('w1s').value = w[0]?.[0] || '10:00';
  $('w1e').value = w[0]?.[1] || '11:30';
  $('w2s').value = w[1]?.[0] || '14:00';
  $('w2e').value = w[1]?.[1] || '16:00';
  $('dryRun').checked = !!cfg.dryRun;
  $('autoExecute').checked = !!cfg.autoExecute;
  $('useBackendGreeting').checked = cfg.useBackendGreeting !== false;
  $('enabled').checked = !!cfg.enabled;
  renderUrl(cfg);
}

function read() {
  return {
    enabled: $('enabled').checked,
    dryRun: $('dryRun').checked,
    autoExecute: $('autoExecute').checked,
    useBackendGreeting: $('useBackendGreeting').checked,
    keywords: splitList($('keywords').value),
    excludeKeywords: splitList($('excludeKeywords').value),
    coreSkills: splitList($('coreSkills').value),
    bonusSkills: splitList($('bonusSkills').value),
    minScore: Number($('minScore').value) || 0,
    reportUrl: $('reportUrl').value.trim(),
    city: $('city').value.trim(),
    salaryMin: Number($('salaryMin').value) || 0,
    salaryMax: Number($('salaryMax').value) || 0,
    salaryMode: $('salaryMode').value || 'min',
    experienceMust: splitList($('experienceMust').value),
    degreeMust: splitList($('degreeMust').value),
    greeting: $('greeting').value.trim(),
    maxPerDay: Number($('maxPerDay').value) || 20,
    maxPerRun: Number($('maxPerRun').value) || 20,
    minDelaySec: Number($('minDelay').value) || 25,
    maxDelaySec: Number($('maxDelay').value) || 75,
    windows: [
      [$('w1s').value || '10:00', $('w1e').value || '11:30'],
      [$('w2s').value || '14:00', $('w2e').value || '16:00'],
    ],
    weekdaysOnly: true,
    experienceFilter: $('experienceFilter').value || 'off',
    safetyStopOnCaptcha: true,
  };
}

function buildSearchUrl(cfg, forceAuto = false) {
  const kw = (cfg.keywords || [])[0] || '';
  const cityFirst = String(cfg.city || '').split(/[,，、;；\s]+/).filter(Boolean)[0] || '';
  const code = CITY_CODES[cityFirst] || '';
  const p = new URLSearchParams();
  p.set('query', kw);
  if (code) p.set('city', code);
  if (forceAuto) p.set('bossauto', '1');
  return `https://www.zhipin.com/web/geek/jobs?${p.toString()}`;
}

function renderUrl(cfg) {
  $('searchUrl').textContent = buildSearchUrl(cfg, true);
}

async function save() {
  const cfg = read();
  await chrome.storage.local.set({ [K_CFG]: cfg });
  renderUrl(cfg);
  $('status').textContent = '已保存 ' + new Date().toLocaleTimeString();
  setTimeout(() => { $('status').textContent = ''; }, 2500);
}

$('save').addEventListener('click', save);

$('openSearch').addEventListener('click', async () => {
  const cfg = read();
  await chrome.storage.local.set({ [K_CFG]: cfg });
  renderUrl(cfg);
  await chrome.tabs.create({ url: buildSearchUrl(cfg, true) });
});

$('exportCsv').addEventListener('click', async () => {
  const { [K_LOG]: log = [] } = await chrome.storage.local.get(K_LOG);
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
  chrome.downloads.download({
    url: 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv),
    filename: `boss-auto/boss-auto-${stamp}.csv`,
    saveAs: true,
  });
});

$('resetDaily').addEventListener('click', async () => {
  await chrome.storage.local.remove(K_DAILY);
  $('status').textContent = '今日计数已清零';
  setTimeout(() => { $('status').textContent = ''; }, 2500);
});

(async () => {
  const { [K_CFG]: cfg } = await chrome.storage.local.get(K_CFG);
  fill({ ...DEFAULTS, ...(cfg || {}) });
  await renderPresets();
})();

/* ---------------- 方向预设 ---------------- */
const K_PRESETS = 'boss_auto_presets';

async function getPresets() {
  const { [K_PRESETS]: p } = await chrome.storage.local.get(K_PRESETS);
  return p || [];
}

async function setPresets(list) {
  await chrome.storage.local.set({ [K_PRESETS]: list });
}

async function renderPresets(selectedName) {
  const list = await getPresets();
  const sel = $('presetSel');
  sel.innerHTML = '';
  if (!list.length) {
    const o = document.createElement('option');
    o.value = '';
    o.textContent = '（还没有保存的方向）';
    sel.appendChild(o);
    return;
  }
  for (const p of list) {
    const o = document.createElement('option');
    o.value = p.name;
    o.textContent = `${p.name} · ${(p.cfg.keywords || []).join('/')} · ${p.cfg.city || ''}`;
    sel.appendChild(o);
  }
  if (selectedName) sel.value = selectedName;
}

$('presetSave').addEventListener('click', async () => {
  const name = $('presetName').value.trim();
  if (!name) { $('status').textContent = '先给这个方向起个名字'; return; }
  const cfg = read();
  const list = await getPresets();
  const i = list.findIndex((p) => p.name === name);
  const item = { name, cfg, savedAt: Date.now() };
  if (i >= 0) list[i] = item; else list.push(item);
  await setPresets(list);
  await renderPresets(name);
  $('presetName').value = '';
  $('status').textContent = `已保存方向「${name}」`;
  setTimeout(() => { $('status').textContent = ''; }, 2500);
});

$('presetApply').addEventListener('click', async () => {
  const name = $('presetSel').value;
  if (!name) return;
  const list = await getPresets();
  const p = list.find((x) => x.name === name);
  if (!p) return;
  fill({ ...DEFAULTS, ...p.cfg });
  await chrome.storage.local.set({ [K_CFG]: { ...DEFAULTS, ...p.cfg } });
  $('status').textContent = `已切换到「${name}」`;
  setTimeout(() => { $('status').textContent = ''; }, 2500);
});

$('presetDelete').addEventListener('click', async () => {
  const name = $('presetSel').value;
  if (!name) return;
  const list = (await getPresets()).filter((p) => p.name !== name);
  await setPresets(list);
  await renderPresets();
  $('status').textContent = `已删除「${name}」`;
  setTimeout(() => { $('status').textContent = ''; }, 2500);
});



$('resetGreeted').addEventListener('click', async () => {
  await chrome.storage.local.remove('boss_auto_greeted');
  $('status').textContent = '已清空"已沟通"记录，这些岗位下一轮会重新进入队列';
  setTimeout(() => { $('status').textContent = ''; }, 3500);
});
/* ---------------- 从 JobPilot 同步简历画像 ---------------- */
$('syncResume').addEventListener('click', async () => {
  const base = $('reportUrl').value.trim().replace(/\/+$/, '');
  const status = $('syncStatus');
  if (!base) { status.textContent = '先填上报地址'; return; }
  status.textContent = '拉取中…';
  try {
    const res = await fetch(`${base}/resume/current`);
    const data = await res.json();
    if (!data.profile) { status.textContent = 'JobPilot 里还没有简历，先去后台上传'; return; }
    const p = data.profile;
    if (p.keywords && p.keywords.length) $('keywords').value = p.keywords.join(',');
    if (p.city) $('city').value = (p.cityList || [p.city]).join(',');
    if (p.salary_min) $('salaryMin').value = p.salary_min;
    if (p.directions && p.directions.length) $('presetName').value ||= (p.directions[0] + ' · ' + (p.city || ''));
    await save();
    status.textContent = `已同步：${p.skills?.length || 0} 项技能 / ${p.city || ''} / ${p.salary_min}K 起`;
  } catch (e) {
    status.textContent = '拉取失败：' + (e.message || e);
  }
});