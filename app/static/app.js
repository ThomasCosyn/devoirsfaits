(() => {
'use strict';
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h) e.innerHTML = h; return e; };

/* ---- Contexte : window.EXO_CONTEXT ou paramètres d'URL (?exercice_id=&titre=&enonce=&eleve=&classe=) ---- */
const CTX = Object.assign(
  { api: '/api/chat', exercice_id: '', titre: 'Exercice', enonce: '', eleve: '', classe: '' },
  Object.fromEntries(new URLSearchParams(location.search)),
  window.EXO_CONTEXT || {}
);
const state = { msgs: [], hint: 0, step: null, busy: false, image: null };
const CHECK = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-9"/></svg>';

/* ---- Maths + markdown (HTML du LLM échappé, formules rendues par KaTeX) ---- */
const tex = (s, d) => { try { return katex.renderToString(s, { displayMode: !!d, throwOnError: false }); } catch { return s.replace(/</g, '&lt;'); } };
function md(src) {
  const store = [];
  const keep = d => (m, s) => `@@M${store.push(tex(s, d)) - 1}@@`;
  src = src.replace(/\$\$([\s\S]+?)\$\$/g, keep(true)).replace(/\\\[([\s\S]+?)\\\]/g, keep(true))
           .replace(/\\\(([\s\S]+?)\\\)/g, keep(false)).replace(/\$([^$\n]+?)\$/g, keep(false));
  src = src.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return marked.parse(src, { breaks: true }).replace(/@@M(\d+)@@/g, (m, i) => store[i]);
}

/* ---- Série (localStorage, date locale) ---- */
const day = d => d.toLocaleDateString('sv');
const readStreak = () => { try { return JSON.parse(localStorage.getItem('exo.streak')) || { count: 0, last: '' }; } catch { return { count: 0, last: '' }; } };
function showStreak(n) { $('#streak').textContent = n; $('#streakPill').hidden = !n; $('#streakPill').setAttribute('aria-label', `Série de ${n} jour${n > 1 ? 's' : ''}`); }
function touchStreak() {
  const s = readStreak(), t = day(new Date()), y = day(new Date(Date.now() - 864e5));
  if (s.last !== t) { s.count = s.last === y ? s.count + 1 : 1; s.last = t; try { localStorage.setItem('exo.streak', JSON.stringify(s)); } catch {} }
  showStreak(s.count);
}
(() => { const s = readStreak(), y = day(new Date(Date.now() - 864e5)); showStreak(s.last === day(new Date()) || s.last === y ? s.count : 0); })();

/* ---- Étapes : le LLM émet <etape n="2" total="4"/>, le front le lit et le masque ---- */
function renderStep() {
  const st = state.step, who = [CTX.eleve, CTX.classe].filter(Boolean).join(' · ');
  $('#sub').textContent = [st && `Étape ${st.n} sur ${st.total}`, who].filter(Boolean).join(' · ');
  const seg = $('#seg'); seg.hidden = !st; if (!st) return;
  seg.setAttribute('aria-label', `Progression : étape ${st.n} sur ${st.total}`);
  seg.innerHTML = Array.from({ length: st.total }, (_, i) => `<i class="${i + 1 < st.n ? 'on' : i + 1 === st.n ? 'cur' : ''}"></i>`).join('');
}

/* ---- Brouillon : blocs ```brouillon {json} ``` ; cases = [[id]] dans les chaînes LaTeX ---- */
function slots(s) {
  const f = document.createDocumentFragment();
  s.split(/\[\[(\w*)\]\]/).forEach((seg, i) => {
    if (i % 2 === 0) { if (seg) { const sp = el('span', '', tex(seg)); sp.dataset.t = seg; f.append(sp); } }
    else { const inp = el('input', 'slot'); inp.autocomplete = 'off'; inp.placeholder = '?'; inp.setAttribute('aria-label', 'Case à compléter'); f.append(inp); }
  });
  return f;
}
const cellText = n => [...n.querySelectorAll('[data-t],input')].map(x => x.tagName === 'INPUT' ? (x.value.trim() || '?') : x.dataset.t).join('');
function brouillon(json) {
  let d; try { d = JSON.parse(json); } catch { return null; }
  const pad = el('div', 'pad'); pad.append(el('h4', '', 'TON BROUILLON'));
  const rows = [];
  if (d.type === 'tableau') {
    const g = el('div', 'tb'); g.style.setProperty('--n', d.entetes.length);
    const hr = el('div', 'tr'); d.entetes.forEach(h => hr.append(el('div', 'c hd', tex(h)))); g.append(hr);
    d.lignes.forEach(l => { const r = el('div', 'tr' + (l.etat === 'verrouille' ? ' lock' : '')); l.cellules.forEach(c => { const x = el('div', 'c'); x.append(slots(c)); r.append(x); }); g.append(r); rows.push(r); });
    pad.append(g);
  } else {
    (d.lignes || []).forEach(l => {
      const r = el('div', 'ln' + (l.etat === 'verrouille' ? ' lock' : ''));
      r.append(el('span', l.etat === 'fait' ? 'ok' : 'sp', l.etat === 'fait' ? CHECK : '')); r.append(slots(l.tex)); pad.append(r); rows.push(r);
    });
  }
  if (pad.querySelector('input')) {
    const go = el('button', 'go', 'Vérifier'); go.type = 'button';
    go.onclick = () => {
      const parts = rows.filter(r => !r.classList.contains('lock') && r.querySelector('input')).map(r =>
        r.classList.contains('tr') ? [...r.children].map(cellText).join(' | ') : '$' + cellText(r) + '$');
      pad.querySelectorAll('input').forEach(i => i.disabled = true); go.disabled = true;
      send('Mon brouillon :\n' + parts.join('\n'));
    };
    pad.append(go);
  }
  return pad;
}

/* ---- Rendu d'un message du bot (appelé à chaque chunk de stream) ---- */
function paint(box, raw, live) {
  let text = raw.replace(/<etape\s+n="(\d+)"\s+total="(\d+)"\s*\/?>/g, (m, n, t) => { state.step = { n: +n, total: +t }; return ''; }).replace(/<etape[^>]*$/, '');
  box.textContent = '';
  const add = n => n && box.append(n);
  const re = /```brouillon\s*\n([\s\S]*?)```/g; let i = 0, m, waiting = false;
  const md1 = v => v.trim() && add(el('div', '', md(v)));
  while ((m = re.exec(text))) { md1(text.slice(i, m.index)); add(brouillon(m[1])); i = re.lastIndex; }
  let rest = text.slice(i); const open = rest.indexOf('```brouillon');
  if (open >= 0) { md1(rest.slice(0, open)); waiting = true; } else md1(rest);
  if (waiting || (!box.childNodes.length && live)) box.append(el('div', 'dots', '<i></i><i></i><i></i>'));
  else if (live) (box.lastElementChild || box).insertAdjacentHTML('beforeend', '<span class="cur" aria-hidden="true"></span>');
  renderStep(); toBottom();
}

/* ---- Messages ---- */
const msgs = $('#msgs');
const nearBottom = () => msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 140;
const toBottom = (force) => { if (force || nearBottom()) msgs.scrollTop = msgs.scrollHeight; };
function addUser(text, img) { const u = el('div', 'user'); if (img) { const im = el('img'); im.src = img; im.alt = 'Photo envoyée'; u.append(im); } u.append(document.createTextNode(text)); msgs.append(u); toBottom(true); }
function addBot() { const b = el('div', 'bot'), body = el('div'); b.append(body); msgs.append(b); return body; }

async function send(text) {
  text = (text || '').trim();
  if ((!text && !state.image) || state.busy) return;
  state.busy = true; setBusy(true); touchStreak();
  const img = state.image; clearImage();
  text = text || 'Voici ma photo.';
  addUser(text, img); state.msgs.push({ role: 'user', content: text });
  const body = addBot(); paint(body, '', true);
  try {
    const r = await fetch(CTX.api, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: state.msgs, image: img, context: { exercice_id: CTX.exercice_id, niveau_indice: state.hint, eleve: CTX.eleve, classe: CTX.classe } })
    });
    if (!r.ok || !r.body) throw new Error(r.status);
    const rd = r.body.getReader(), dec = new TextDecoder(); let raw = '', queued = false;
    for (;;) {
      const { done, value } = await rd.read(); if (done) break;
      raw += dec.decode(value, { stream: true });
      if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; paint(body, raw, true); }); }
    }
    paint(body, raw, false); state.msgs.push({ role: 'assistant', content: raw });
  } catch {
    body.innerHTML = '<p class="err">Connexion impossible. Vérifie ta connexion et réessaie.</p>'; state.msgs.pop();
  }
  state.busy = false; setBusy(false); $('#input').focus({ preventScroll: true });
}
function setBusy(b) { document.querySelectorAll('#send,.qr').forEach(x => x.disabled = b); }

/* ---- Composer ---- */
const input = $('#input');
const grow = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px'; };
input.addEventListener('input', grow);
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
function submit() { const t = input.value; input.value = ''; grow(); send(t); }
$('#send').onclick = submit;
$('#hint').onclick = () => { state.hint = Math.min(3, state.hint + 1); send("Donne-moi un indice, sans me donner la réponse."); };
document.querySelectorAll('[data-say]').forEach(b => b.onclick = () => send(b.dataset.say));

/* ---- Photo ---- */
function clearImage() { state.image = null; $('#att').hidden = true; $('#file').value = ''; }
$('#photo').onclick = () => $('#file').click();
$('#attX').onclick = clearImage;
$('#file').onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { state.image = rd.result; $('#attImg').src = rd.result; $('#att').hidden = false; };
  rd.readAsDataURL(f);
};

/* ---- Énoncé, titre, sortie ---- */
$('#title').textContent = CTX.titre;
if (CTX.enonce) { $('#stmt').hidden = false; $('#stmtText').innerHTML = md(CTX.enonce); }
$('#stmtToggle').onclick = e => { const o = $('#stmt').classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', o); };
$('#quit').onclick = () => { document.dispatchEvent(new CustomEvent('exo:quitter')); if (history.length > 1) history.back(); else location.href = '/logout'; };
renderStep();
const hello = addBot(); hello.innerHTML = '<p>Salut ! Dis-moi ce que tu as déjà essayé, ou à quel endroit tu bloques.</p>';
})();
