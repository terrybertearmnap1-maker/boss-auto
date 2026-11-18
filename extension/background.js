/* 后台 Service Worker
 * 负责：初始化默认配置、处理 CSV 下载、显示今日计数徽标。
 * 设计原则：顶层绝不能抛异常——任何一条 chrome API 不可用都只降级，不能让 SW 注册失败。
 */

'use strict';

const K_CFG = 'boss_auto_cfg';
const K_DAILY = 'boss_auto_daily';

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

/** 安全执行：任何异常只记录，不向上抛 */
function guard(label, fn) {
  try {
    return fn();
  } catch (e) {
    try { console.warn('[boss-auto]', label, e && e.message); } catch (_) { /* ignore */ }
  }
}

/** 安全注册监听器：事件对象不存在时跳过 */
function listen(event, handler) {
  guard('listen', () => {
    if (event && typeof event.addListener === 'function') event.addListener(handler);
  });
}

async function ensureDefaults() {
  const got = await chrome.storage.local.get(K_CFG);
  if (!got || !got[K_CFG]) {
    await chrome.storage.local.set({ [K_CFG]: DEFAULTS });
  }
}

async function updateBadge() {
  if (!chrome.action || typeof chrome.action.setBadgeText !== 'function') return;
  const got = await chrome.storage.local.get(K_DAILY);
  const d = (got && got[K_DAILY]) || { date: '', count: 0 };
  const today = new Date().toISOString().slice(0, 10);
  const count = d.date === today ? d.count : 0;
  await chrome.action.setBadgeText({ text: count ? String(count) : '' });
  guard('badgeColor', () => chrome.action.setBadgeBackgroundColor({ color: '#00bebd' }));
}

// ---- 事件注册（全部包裹，避免单点失败）----
listen(chrome.runtime && chrome.runtime.onInstalled, () => {
  ensureDefaults().catch(() => {});
  updateBadge().catch(() => {});
});

listen(chrome.runtime && chrome.runtime.onStartup, () => {
  ensureDefaults().catch(() => {});
  updateBadge().catch(() => {});
});

listen(chrome.action && chrome.action.onClicked, () => {
  guard('openOptions', () => chrome.runtime.openOptionsPage());
});

listen(chrome.storage && chrome.storage.onChanged, (changes, area) => {
  if (area === 'local' && changes && changes[K_DAILY]) {
    updateBadge().catch(() => {});
  }
});

listen(chrome.runtime && chrome.runtime.onMessage, (msg, sender, sendResponse) => {
  if (!msg || msg.type !== 'download') return false;
  guard('download', () => {
    chrome.downloads.download(
      {
        url: msg.url,
        filename: msg.filename || 'boss-auto/export.csv',
        saveAs: !!msg.saveAs,
        conflictAction: 'uniquify',
      },
      (id) => {
        const err = chrome.runtime.lastError;
        guard('downloadResponse', () => sendResponse({ ok: !err, id, error: err && err.message }));
      }
    );
  });
  return true; // 异步响应
});

// ---- 启动初始化：异步执行，失败也不影响 SW 注册 ----
ensureDefaults().catch(() => {});
updateBadge().catch(() => {});


