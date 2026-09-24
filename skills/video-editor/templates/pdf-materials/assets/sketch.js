/* Shared components for summary.html / transcript.html (no dependencies).
   Sketch accents are hand-drawn-looking SVG strokes in coral, echoing the video chapter cards. */
(function () {
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const isPlaceholder = (s) => /\{[A-Z_]+\}/.test(String(s || ''));

  function accentTitle(title, accent) {
    const t = esc(title);
    if (!accent) return t;
    const a = esc(accent);
    const i = t.lastIndexOf(a);
    return i < 0 ? t : t.slice(0, i) + '<span class="accent">' + a + '</span>' + t.slice(i + a.length);
  }

  // two overlapping marker strokes, like the chapter card in the video
  function underline(opts = {}) {
    const { stroke = 5, color = 'var(--coral)', cls = '' } = opts;
    return `<svg class="marker ${cls}" viewBox="0 0 400 22" preserveAspectRatio="none" aria-hidden="true">
      <path d="M3 9 C 90 5, 190 7, 300 6 S 380 5, 397 6" style="stroke:${color};stroke-width:${stroke}"/>
      <path d="M92 16 C 170 13, 260 14, 330 13 S 372 13, 386 12" style="stroke:${color};stroke-width:${stroke * 0.85};opacity:.9"/>
    </svg>`;
  }

  // «>» spark rays that frame titles on the deck
  function rays(dir = 'right', color = 'var(--coral)') {
    const flip = dir === 'left' ? 'transform="scale(-1,1) translate(-24,0)"' : '';
    return `<svg class="rays" viewBox="0 0 24 32" width="7mm" height="9mm" aria-hidden="true"><g ${flip} style="stroke:${color}">
      <path d="M3 5 L17 11"/><path d="M2 16 L19 16"/><path d="M3 27 L17 21"/></g></svg>`;
  }

  function arrow(opts = {}) {
    const { color = 'var(--lavender)', w = '16mm', h = '14mm', flip = false } = opts;
    const tr = flip ? 'transform="scale(-1,1) translate(-80,0)"' : '';
    return `<svg class="doodle" viewBox="0 0 80 70" width="${w}" height="${h}" aria-hidden="true"><g ${tr} style="stroke:${color}">
      <path d="M8 64 C 4 36, 22 14, 62 10" style="stroke-width:2.6"/>
      <path d="M50 3 L64 10 L52 20" style="stroke-width:2.6"/></g></svg>`;
  }

  function circleMark(color = 'var(--coral)') {
    return `<svg class="doodle circle-mark" viewBox="0 0 100 70" preserveAspectRatio="none" aria-hidden="true">
      <path d="M58 6 C 22 2, 4 20, 7 38 C 10 58, 44 67, 72 60 C 96 53, 98 26, 80 13 C 70 6, 52 4, 38 8" style="stroke:${color};stroke-width:2.4"/></svg>`;
  }

  function starBurst(color = 'var(--coral)') {
    return `<svg class="doodle" viewBox="0 0 40 40" width="8mm" height="8mm" aria-hidden="true"><g style="stroke:${color};stroke-width:2.2">
      <path d="M20 3 L20 12"/><path d="M20 28 L20 37"/><path d="M3 20 L12 20"/><path d="M28 20 L37 20"/>
      <path d="M8 8 L13 13"/><path d="M27 27 L32 32"/><path d="M32 8 L27 13"/><path d="M13 27 L8 32"/></g></svg>`;
  }

  function link(url, label, cls = '') {
    if (!url) return esc(label || '');
    if (isPlaceholder(url)) return `<span class="placeholder ${cls}">${esc(url)}</span>`;
    const shown = label || url.replace(/^https?:\/\//, '');
    return `<a class="${cls}" href="${esc(url)}">${esc(shown)}</a>`;
  }

  function logo(onDark = true) {
    return `<img class="logo" src="assets/brand/${onDark ? 'logo-dark-bg' : 'logo-paper-bg'}.svg" alt="logo">`;
  }

  /* Full-bleed dark cover. doc = {eyebrow,title,title_accent,subtitle,kind,host,host_role,co,chips[]} */
  function cover(doc, opts = {}) {
    const chips = (doc.chips || []).map((c) => `<span class="cv-chip">${esc(c)}</span>`).join('');
    const co = (doc.co || []).map((c) => `<div class="cv-co">${esc(c)}</div>`).join('');
    return `<section class="page-full stage cover">
      <div class="cv-top">${logo(true)}<div class="eyebrow">${esc(doc.eyebrow)}</div></div>
      <div class="cv-kind"><span class="pill coral">${esc(doc.kind)}</span>${doc.provisional ? '<span class="provisional">Черновик · таймкоды предварительные</span>' : ''}</div>
      <h1 class="h-display cv-title">${accentTitle(doc.title, doc.title_accent)}</h1>
      <div class="cv-sub">${esc(doc.subtitle)}</div>
      <div class="cv-underline">${underline({ stroke: 6 })}</div>
      ${doc.lead ? `<p class="cv-lead">${esc(doc.lead)}</p>` : ''}
      <div class="cv-chips">${chips}</div>
      <img class="cv-art" src="assets/art/${esc(opts.art || 'hand-pills')}.png" alt="">
      ${opts.note ? `<div class="cv-note"><span class="hand">${esc(opts.note)}</span>${arrow({ color: 'var(--lavender)', w: '15mm', h: '13mm' })}</div>` : ''}
      <div class="cv-host"><div class="cv-bar"></div><div><div class="cv-name">${esc(doc.host)}</div><div class="cv-role">${esc(doc.host_role)}</div>${co}</div></div>
      <div class="cv-date mono">${esc(doc.date || '')}</div>
    </section>`;
  }

  /* Full-bleed dark «что дальше» page. s = shared.next */
  function ctaPage(s) {
    const n = s.next, L = s.links;
    // QR images: files prepare_assets.py wrote to assets/brand/ for job.json outro.links[] entries with "qr": true
    // (qr-<index in outro.links>-navy.png, or that entry's qr_file). shared.json next.intensive.qr / next.bot.qr pick
    // the file; defaults = outro.links[0] (contact) and [1] (bot); "" hides the tile.
    const qrOf = (o, def) => (o.qr === undefined ? def : o.qr);
    const qr = qrOf(n.intensive, 'qr-0-navy.png'), qrBot = qrOf(n.bot, 'qr-1-navy.png');
    const bullets = (n.intensive.bullets || []).map((b) => `<li>${esc(b)}</li>`).join('');
    const links = (L || []).filter((l) => l.url).map((l) => `<div class="ct-link"><span class="ct-l-label">${esc(l.label)}</span>${link(l.url, l.shown)}</div>`).join('');
    return `<section class="page-full stage cta">
      <div class="cv-top">${logo(true)}<div class="eyebrow">${esc(n.eyebrow || 'Что дальше')}</div></div>
      <h2 class="h-display ct-title">${accentTitle(n.title, n.title_accent)}</h2>
      <div class="ct-underline">${underline({ stroke: 5 })}</div>
      <div class="ct-grid">
        <div class="ct-main">
          <div class="eyebrow">${esc(n.intensive.eyebrow)}</div>
          <div class="ct-h">${esc(n.intensive.title)}</div>
          <p class="ct-p">${esc(n.intensive.text)}</p>
          <ul class="ct-list">${bullets}</ul>
          <div class="ct-action">
            ${qr ? `<div class="qr-tile"><img class="qr" src="assets/brand/${esc(qr)}" alt=""></div>` : ''}
            <div><div class="ct-do">${esc(n.intensive.cta)}</div>
              <div class="ct-url">${link(n.intensive.contact_url, n.intensive.contact_label)}</div>
              <div class="ct-promo"><span>промокод</span><b>${esc(n.intensive.promo)}</b><em>${esc(n.intensive.promo_note)}</em></div></div>
          </div>
        </div>
        <div class="ct-side">
          <div class="ct-card">
            <div class="eyebrow">${esc(n.saturday.eyebrow)}</div>
            <div class="ct-h2">${esc(n.saturday.title)}</div>
            <p>${esc(n.saturday.text)}</p>
            <div class="ct-when mono">${esc(n.saturday.when)}</div>
          </div>
          <div class="ct-card">
            <div class="eyebrow">${esc(n.bot.eyebrow)}</div>
            <div class="ct-h2">${esc(n.bot.title)}</div>
            <p>${esc(n.bot.text)}</p>
            <div class="ct-bot">${qrBot ? `<div class="qr-tile small"><img class="qr" src="assets/brand/${esc(qrBot)}" alt=""></div>` : ''}${link(n.bot.url, n.bot.label)}</div>
          </div>
        </div>
      </div>
      <div class="ct-links"><div class="eyebrow">Материалы эфира</div>${links}</div>
      <img class="ct-hand" src="assets/art/hand-final.png" alt="">
    </section>`;
  }

  window.VA = { esc, isPlaceholder, accentTitle, underline, rays, arrow, circleMark, starBurst, link, logo, cover, ctaPage };
})();
