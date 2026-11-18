// 用真实诊断数据回归筛选逻辑（不依赖浏览器）
const fs = require('fs');
const path = process.argv[2];
const data = JSON.parse(fs.readFileSync(path, 'utf8'));

const cfg = {
  keywords: ['Agent', '智能体', '大模型', 'AI应用'],
  salaryMin: 4, salaryMax: 10, salaryMode: 'min',
  experienceMust: ['应届', '经验不限', '1年以内', '实习', '在校'],
  degreeMust: ['本科', '硕士', '学历不限'],
};

function decodePua(s) {
  if (!s) return '';
  return String(s).replace(/[\uE030-\uE03F]/g, (ch) => {
    const code = ch.charCodeAt(0);
    if (code >= 0xE031 && code <= 0xE03A) return String.fromCharCode(0x30 + (code - 0xE031));
    return ch;
  });
}
function extractSalaryText(text) {
  const t = String(text || '').replace(/\n/g, ' ');
  const m = t.match(/(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk](?:\s*·\s*\d+薪)?|\d+\s*-\s*\d+\s*元\s*\/\s*[天时月周]|\d+(?:\.\d+)?\s*[Kk]\s*以上|面议)/);
  return m ? m[0] : '';
}
function parseSalary(text) {
  const t = String(text || '').replace(/\s/g, '');
  const range = t.match(/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)[Kk千]/);
  if (range) return [Number(range[1]), Number(range[2])];
  const single = t.match(/(\d+(?:\.\d+)?)[Kk]/);
  if (single) return [Number(single[1]), Number(single[1])];
  return null;
}
function salaryMatch(text, c) {
  let r = parseSalary(text);
  if (!r) {
    const t = String(text || '').replace(/\s/g, '');
    const day = t.match(/(\d+)-(\d+)元\/天/);
    if (day) r = [Number(day[1]) * 22 / 1000, Number(day[2]) * 22 / 1000];
  }
  if (!r) return false;
  if (c.salaryMode === 'range' && Number(c.salaryMax) > 0) return r[1] >= c.salaryMin && r[0] <= c.salaryMax;
  return r[1] >= Number(c.salaryMin || 0);
}
const anyIncludes = (list, words) => list.some((t) => words.some((w) => String(t).includes(w)));

console.log('卡片数：', data.cards.length);
data.cards.forEach((card, i) => {
  const text = decodePua(card.cardText || '');
  const title = decodePua(card.parsedTitle || text.split('\n')[0]);
  const salaryEl = (card.innerHTML.match(/<span[^>]*class="job-salary"[^>]*>(.*?)<\/span>/) || [])[1] || '';
  const salary = decodePua(salaryEl) || extractSalaryText(text);
  const tagMatch = card.innerHTML.match(/<ul[^>]*class="tag-list"[^>]*>([\s\S]*?)<\/ul>/);
  const tags = tagMatch ? [...tagMatch[1].matchAll(/<li[^>]*>(.*?)<\/li>/g)].map((m) => decodePua(m[1]).trim()) : [];

  const kwOk = cfg.keywords.some((k) => `${title} ${text}`.includes(k));
  const salOk = salaryMatch(salary, cfg);
  const isIntern = /实习|在校/.test(text) || tags.some((t) => /天\s*\/\s*周|个月/.test(t));
  const expOk = isIntern || anyIncludes(tags, cfg.experienceMust);
  const degOk = anyIncludes(tags, cfg.degreeMust);
  const pass = kwOk && salOk && expOk && degOk;
  console.log(
    `${i} ${pass ? 'PASS' : 'FAIL'} | ${title.slice(0, 24)} | ${salary} | tags=${tags.join(',')} | kw=${kwOk} sal=${salOk} exp=${expOk}(intern=${isIntern}) deg=${degOk}`
  );
});
