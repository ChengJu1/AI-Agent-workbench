"""Read-only form structure: field names, sections, control types, required marks and current values.

The script only reads the page. It never clicks, types, opens dropdowns or leaves markers in the DOM;
the result is used to build a copy-ready kit the user fills in by hand.
"""

EXTRACT = r'''
const vis = e => {
  if (!e) return false;
  // checkVisibility (Chrome 105+) covers hidden ancestors without a style recalculation per element.
  if (e.checkVisibility) return e.checkVisibility({opacityProperty: true, visibilityProperty: true}) && !!e.getClientRects().length;
  const s = getComputedStyle(e); return !!e.getClientRects().length && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
};
const text = e => ((e && (e.innerText || e.textContent)) || '').replace(/\s+/g, ' ').trim();
const cls = e => (e && typeof e.className === 'string' ? e.className : (e && e.getAttribute && e.getAttribute('class')) || '').toLowerCase();
const CONTAINERS = '.el-form-item,.ant-form-item,.ivu-form-item,.arco-form-item,.n-form-item,[class*="form-item"],[class*="FormItem"],[class*="form-row"],[class*="field-item"]';
const CONTROL = 'input:not([type=hidden]),textarea,select,[role=combobox],[role=radiogroup],[role=radio],[class*=select],[class*=cascader],[class*=picker],[class*=date-editor],[class*=upload],[class*=radio],[class*=checkbox]';
const POPUP = '[class*=dropdown],[class*=popper],[class*=popover],[class*=picker-panel],[class*=cascader-menus],[class*=cascader-dropdown],[class*=select-dropdown],[role=listbox],[role=tree]';
const GENERIC = /^(请(输入|选择|填写|上传)|选择|输入|please|select)/i;
const PLACE = /^请选择/;
const isLeaf = e => !!text(e) && ![...e.children].some(ch => text(ch));
const choices = new Set(), kinds = new Map(), names = new Map();
const isChoice = c => choices.has(c) || [...choices].some(h => c.contains(h));

function nearLabel(c) {
  for (let node = c, depth = 0; node && node !== document.body && depth < 4; node = node.parentElement, depth++) {
    let sib = node.previousElementSibling;
    for (let n = 0; sib && n < 3; sib = sib.previousElementSibling, n++) {
      if (sib.querySelector('input,textarea,select') || isChoice(sib)) break;
      const t = vis(sib) ? text(sib) : '';
      if (t && t.length <= 24) return t;
      if (t) break;
    }
  }
  return '';
}
function kind(c) {
  const all = [c, ...c.querySelectorAll('*')];
  const has = re => all.some(e => re.test(cls(e)));
  if (c.querySelector('input[type=file]') || has(/upload/)) return 'file';
  if (c.querySelector('select')) return 'select';
  if (has(/cascader/)) return 'cascader';
  if (c.querySelector('input[type=date],input[type=month]') || has(/date-editor|date-picker|picker-input|datepicker|ant-picker|month-picker/)) return 'date';
  if (c.querySelector('input[type=radio],[role=radio]') || has(/radio/)) return 'radio';
  if (c.querySelector('input[type=checkbox],[role=checkbox]') || has(/checkbox/)) return 'checkbox';
  if (c.querySelector('[role=combobox],[aria-haspopup=listbox]') || has(/(^|[\s_-])select($|[\s_-])|select__|select-selector|selection/)) return 'custom_select';
  // Without known class names: a readonly input or a box that only says "请选择" is a dropdown.
  const editable = c.querySelector('input:not([type=hidden]):not([type=file]):not([readonly]),textarea');
  if (isChoice(c) && !editable) return 'custom_select';
  const ro = c.querySelector('input[readonly]:not([type=hidden]):not([type=file])');
  if (ro && !editable) return /日期|时间|年月|date|month|year/i.test((ro.placeholder || '') + text(c)) ? 'date' : 'custom_select';
  if (c.querySelector('textarea')) return 'textarea';
  if (c.querySelector('input')) return 'text';
  return '';
}
function control(c, k) {
  if (k === 'select') return c.querySelector('select');
  if (k === 'textarea') return c.querySelector('textarea');
  if (k === 'file') return c.matches('input[type=file]') ? c : c.querySelector('input[type=file]');
  return c.querySelector('input:not([type=hidden]):not([type=file])');
}
function labelOf(c, ctl) {
  const l = c.querySelector('label,[class*=label],[class*=title]');
  let raw = l && !l.contains(ctl) ? text(l) : '';
  if (!raw && ctl && ctl.id) raw = text(document.querySelector('label[for="' + CSS.escape(ctl.id) + '"]'));
  if (!raw && ctl) raw = ctl.getAttribute('aria-label') || '';
  // A placeholder ("请输入") is not a name: prefer the text placed next to the field.
  if (!raw || GENERIC.test(raw.replace(/^\s*[*＊]\s*/, ''))) raw = nearLabel(c) || raw || (ctl && ctl.getAttribute('placeholder')) || '';
  return raw;
}
function sectionOf(c, label) {
  for (let node = c; node && node !== document.body; node = node.parentElement) {
    for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
      const h = sib.matches('h1,h2,h3,h4,h5,[class*=title],[class*=header],legend') ? sib : sib.querySelector('h1,h2,h3,h4,h5,legend');
      const t = text(h);
      if (t && t.length <= 30 && t.replace(/^\s*[*＊]\s*/, '').replace(/[：:]\s*$/, '') !== label) return t;
    }
  }
  return '';
}
function valueOf(c, k, ctl) {
  if (k === 'select') { const o = ctl.options[ctl.selectedIndex]; return o && ctl.value ? o.label : ''; }
  if (k === 'radio') { const r = c.querySelector('input[type=radio]:checked'); const box = r && (r.closest('label,[class*=radio]') || r.parentElement); return box ? text(box) : text(c.querySelector('[class*=is-checked],[class*=radio-checked],[aria-checked=true]')); }
  if (k === 'checkbox') return [...c.querySelectorAll('input[type=checkbox]:checked')].map(i => text(i.closest('label') || i.parentElement)).join('、');
  if (k === 'file') { const f = control(c, k); const picked = f && f.files ? [...f.files].map(x => x.name) : []; return picked.join(',') || text(c.querySelector('[class*=file-name],[class*=upload-list],[class*=filename]')); }
  if (k === 'custom_select' || k === 'cascader') {
    const i = c.querySelector('input:not([type=hidden]):not([type=file])');
    let v = (i && i.value) || text(c.querySelector('[class*=selected-item],[class*=selection-item],[class*=select__selected],[class*=tags]'));
    if (!v) { const h = [...choices].find(h => c === h || c.contains(h)); v = h ? text(h) : ''; }
    return PLACE.test(v) ? '' : v;
  }
  return ctl ? ctl.value || '' : '';
}

// Walk text nodes, not elements: reading innerText of every container is quadratic on large forms.
const open = [...document.querySelectorAll(POPUP)].filter(e => vis(e) && ['absolute', 'fixed'].includes(getComputedStyle(e).position));
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
for (let node = walker.nextNode(); node; node = walker.nextNode()) {
  const e = node.parentElement;
  if (!e || !PLACE.test(node.nodeValue.trim()) || !isLeaf(e) || !vis(e) || e.closest('select,[role=listbox],[role=option]') || open.some(p => p.contains(e))) continue;
  let host = e;
  while (host.parentElement && host.parentElement !== document.body && text(host.parentElement).length <= text(e).length + 2
         && !host.parentElement.querySelector('input:not([type=hidden]):not([readonly]),textarea')) host = host.parentElement;
  choices.add(host);
}
let rows = [...document.querySelectorAll(CONTAINERS)].filter(vis).filter(c => c.querySelector(CONTROL) || isChoice(c));
for (const h of choices) if (!rows.some(r => r.contains(h))) rows.push(h);
for (const f of document.querySelectorAll('input[type=file]')) {
  if (rows.some(r => r.contains(f))) continue;
  // Hidden file inputs outside every form row: the nearest visible wrapper with text is the upload area.
  let host = f.parentElement;
  for (let n = 0; host && host !== document.body && !(vis(host) && text(host)) && n < 5; n++) host = host.parentElement;
  if (!host || host === document.body) continue;
  const own = [...host.querySelectorAll('*')].find(e => vis(e) && isLeaf(e) && text(e).length <= 20);
  kinds.set(host, 'file');
  names.set(host, (own && text(own)) || nearLabel(host) || '附件');
  rows.push(host);
}
rows = rows.filter(c => !rows.some(d => d !== c && c.contains(d)));
for (const l of document.querySelectorAll('label[for]')) {
  const ctl = document.getElementById(l.htmlFor);
  if (ctl && vis(ctl) && !rows.some(r => r.contains(ctl))) {
    const row = ctl.parentElement && ctl.parentElement.contains(l) && ctl.parentElement !== document.body && ctl.parentElement.tagName !== 'FORM' ? ctl.parentElement : ctl;
    names.set(row, text(l));
    rows.push(row);
  }
}
rows.sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);  // Page order, as the user sees it.
const fields = [];
for (const c of rows) {
  const native = c.matches('input,textarea,select');
  const k = kinds.get(c) || (native ? ({SELECT: 'select', TEXTAREA: 'textarea'}[c.tagName] || (c.type === 'file' ? 'file' : ['date', 'month'].includes(c.type) ? 'date' : c.type === 'checkbox' ? 'checkbox' : 'text')) : kind(c));
  if (!k) continue;
  const ctl = native ? c : control(c, k);
  const raw = names.get(c) || labelOf(c, ctl);
  const label = raw.replace(/^\s*[*＊]\s*/, '').replace(/[：:]\s*$/, '').trim();
  if (!label) continue;
  const field = {key: 'f' + fields.length, label, section: sectionOf(c, label), type: k,
    required: /^\s*[*＊]/.test(raw) || [c, c.parentElement].some(e => /(^|[\s_-])(is-)?required/.test(cls(e))) || !!(ctl && (ctl.required || ctl.getAttribute('aria-required') === 'true')),
    value: valueOf(c, k, ctl), placeholder: ctl ? (ctl.getAttribute('placeholder') || '') : '', disabled: !!(ctl && ctl.disabled)};
  if (k === 'select') field.options = [...ctl.options].filter(o => o.value !== '').map(o => o.label).slice(0, 200);
  if (k === 'radio' || k === 'checkbox') field.options = [...c.querySelectorAll('label,[class*=radio__label],[class*=checkbox__label],[role=radio]')].map(text).filter(v => v && v.replace(/^[*＊]\s*/, '') !== label).filter((v, j, a) => a.indexOf(v) === j).slice(0, 50);
  if (k === 'date') field.format = ctl && ctl.type === 'month' ? 'YYYY-MM' : ctl && ctl.type === 'date' ? 'YYYY-MM-DD' : /日|day|dd/i.test(field.placeholder) ? 'YYYY-MM-DD' : /月|month|mm/i.test(field.placeholder) ? 'YYYY-MM' : '';
  fields.push(field);
}
return fields;
'''


class FormEngine:
    """Provider-agnostic reader. `driver` only needs evaluate(fn)."""

    def __init__(self, driver):
        self.driver = driver

    async def extract(self):
        return await self.driver.evaluate('() => {\n' + EXTRACT + '\n}')


class PlaywrightDriver:
    """Driver over a Playwright page (built-in browser provider)."""

    def __init__(self, page):
        self.page = page

    async def evaluate(self, fn):
        return await self.page.evaluate(fn)


class McpDriver:
    """Driver over the official Playwright MCP (native Chrome provider)."""

    def __init__(self, client, result_json):
        self.client, self.result_json = client, result_json

    async def evaluate(self, fn):
        return self.result_json(await self.client.call('browser_evaluate', {'function': fn}))
