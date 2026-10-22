"""Read DOM affordances, including framework div/span buttons, without changing the page."""
HELPERS = r'''
const native = 'a,button,input:not([type=hidden]),textarea,select,summary';
function label(e) {
    const ids = (e.getAttribute('aria-labelledby') || '').trim().split(/\s+/).filter(Boolean);
    const root = e.getRootNode();
    const named = ids.map(id => root.getElementById?.(id)?.textContent || '').join(' ').trim();
    return (e.getAttribute('aria-label') || named || (e.labels && e.labels[0]?.innerText) || e.innerText || e.getAttribute('title') || e.placeholder || e.name || '').trim();
}
function visible(e) {
    const s = getComputedStyle(e);
    return !!e.getClientRects().length && s.visibility !== 'hidden' && s.visibility !== 'collapse' && s.display !== 'none';
}
function clickable(e) {
    const tag = e.tagName.toLowerCase(), role = (e.getAttribute('role') || '').toLowerCase();
    if (['a','button','summary'].includes(tag) || (tag === 'input' && ['button','submit','reset','image'].includes(e.type))) return true;
    if (['button','link'].includes(role)) return true;
    const text = label(e);
    if (!text || text.length > 250) return false;
    if (typeof e.onclick === 'function' || e.hasAttribute('onclick')) return true;
    if (!['DIV','SPAN','LI'].includes(e.tagName) || getComputedStyle(e).cursor !== 'pointer') return false;
    // Inherited cursor on a child must not turn every nested label into another button.
    const parent = e.parentElement;
    if (parent && getComputedStyle(parent).cursor === 'pointer' && label(parent).length <= 250) return false;
    return !e.querySelector('a,button,input,select,textarea,[role=button],[role=link]');
}
function info(e) {
    const style = getComputedStyle(e);
    return {tag:e.tagName.toLowerCase(),type:e.type || '',role:e.getAttribute('role') || '',label:label(e).slice(0,250),
        clickable:clickable(e),disabled:!!e.disabled || e.matches(':disabled') || e.getAttribute('aria-disabled') === 'true' || !!e.closest('[inert]') || style.pointerEvents === 'none',
        href:e.tagName === 'A' ? e.href : undefined,value:e.type === 'password' || e.type === 'file' ? '' : e.value,
        options:e.tagName === 'SELECT' ? Array.from(e.options).slice(0,80).map(o=>({label:o.label,value:o.value})) : undefined,
        checked:['checkbox','radio'].includes(e.type) ? !!e.checked : undefined,
        selected_label:e.tagName === 'SELECT' && e.selectedIndex >= 0 ? e.options[e.selectedIndex].label : undefined,
        file_names:e.type === 'file' ? Array.from(e.files || []).map(f=>f.name).slice(0,20) : undefined,
        form_action:e.form ? e.form.action : ''};
}
function collect() {
    const found = [], roots = [document];
    for (let index = 0; index < roots.length; index++) {
        for (const e of roots[index].querySelectorAll('*')) {
            if (e.shadowRoot) roots.push(e.shadowRoot);
            if (visible(e) && (e.matches(native) || clickable(e))) found.push(e);
        }
    }
    return found;
}
'''
CANDIDATES_JS = '() => {' + HELPERS + 'return collect().slice(0,251);}'
ELEMENT_INFO_JS = 'e => {' + HELPERS + 'return info(e);}'
FINGERPRINT_JS = '() => {' + HELPERS + 'return {url:location.href,fields:collect().map(e=>[e.id,e.name,e.className,info(e)])};}'
