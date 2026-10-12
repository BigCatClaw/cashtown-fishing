// ==UserScript==
// @name         Cash Town → Fishing Log
// @namespace    https://bigcatclaw.github.io/cashtown-fishing/
// @version      1.0.0
// @description  Sends every fish you land in Cash Town to your fishing log (start.bat must be running).
// @match        https://cashfc-website.vercel.app/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      localhost
// @run-at       document-idle
// @downloadURL  https://bigcatclaw.github.io/cashtown-fishing/cashtown-autolog.user.js
// @updateURL    https://bigcatclaw.github.io/cashtown-fishing/cashtown-autolog.user.js
// ==/UserScript==

// How it reads the game: the fishing result popup looks like
//   <h2 id="town-fish-h">ตกปลา</h2><span>น้ำลึก</span> …
//   <div data-came="landed" data-what="catfish"><p>ได้ ปลาดุก ยาว 34.6 ซม.</p> …
// Each landed fish is sent once to http://localhost:8765/api/inbox; the open log page
// then saves it with the conditions currently set there.
(() => {
  'use strict';

  const LOG_URL = 'http://localhost:8765/api/inbox';
  const QUEUE_KEY = 'unsent';
  const sentRows = new WeakMap();         // popup row element -> what it showed when it was sent
  let lastBatch = {sig: '', at: 0};       // the last result sent, to spot the game redrawing it
  let queue = GM_getValue(QUEUE_KEY, []); // catches not delivered yet (survives closing the tab)
  let sending = false, retryTimer = 0, sentCount = 0;

  // ---------- reading the popup ----------

  // root: the document, or a popup that was just removed (closed before we read it).
  function readCatch(root) {
    const title = root.querySelector?.('#town-fish-h') || document.getElementById('town-fish-h');
    const rows = [...(root.querySelectorAll?.('[data-came][data-what]') || [])];
    if (root.matches?.('[data-came][data-what]')) rows.unshift(root);
    if (!rows.length) return null;
    const water = title?.nextElementSibling?.textContent.trim() || null;
    const fish = [];
    let notThai = false;
    for (const row of rows) {
      if (row.dataset.came !== 'landed') continue; // got away, not a catch
      const line = (row.querySelector('p')?.textContent || '').replace(/\s+/g, ' ').trim();
      const m = line.match(/(?:^|\s)ได้\s+(.+?)(?:\s+ยาว\s+([\d.]+)\s*ซม\.?)?$/);
      if (!m) { notThai = true; continue; } // e.g. the game is set to English
      const name = m[1].trim(), size = m[2] ? Number(m[2]) : null;
      fish.push({row, name, size, sig: `${row.dataset.what}|${name}|${size}`});
    }
    return {water, fish, notThai};
  }

  function handle(result) {
    if (!result) return;
    if (result.notThai) badge('warn', 'Switch the game to ไทย so fish names match your log');
    // A row still on screen showing what we already sent is skipped; a new cast either
    // brings new rows or changes the text of the old ones.
    const fresh = result.fish.filter(f => sentRows.get(f.row) !== f.sig);
    if (!fresh.length) return;
    for (const f of result.fish) sentRows.set(f.row, f.sig);
    // Exactly the same fish and lengths in brand-new elements a moment later: a redraw.
    const batchSig = result.fish.map(f => f.sig).join(';');
    const now = Date.now();
    if (batchSig === lastBatch.sig && now - lastBatch.at < 5000) return;
    lastBatch = {sig: batchSig, at: now};
    const items = fresh.map((f, i) => ({
      id: `game-${now.toString(36)}-${i}-${Math.random().toString(36).slice(2, 8)}`,
      t: now, fish: f.name, size: f.size, water: result.water,
    }));
    queue.push(...items);
    GM_setValue(QUEUE_KEY, queue);
    send();
  }

  let settleTimer = 0;
  new MutationObserver(records => {
    // A result popup closed straight away: read the fish from the removed nodes.
    for (const r of records) {
      for (const n of r.removedNodes) {
        if (n.nodeType === 1 && (n.matches('[data-came]') || n.querySelector('[data-came]'))) handle(readCatch(n));
      }
    }
    // Otherwise read once the popup has stopped changing.
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => handle(readCatch(document)), 200);
  }).observe(document.body, {childList: true, subtree: true, characterData: true});

  // ---------- sending to the log ----------

  function send() {
    if (sending || !queue.length) return;
    sending = true;
    const batch = queue.slice(0, 50);
    const done = ok => {
      sending = false;
      if (ok) {
        const ids = new Set(batch.map(c => c.id));
        queue = queue.filter(c => !ids.has(c.id));
        GM_setValue(QUEUE_KEY, queue);
        sentCount += batch.length;
        badge('ok', `Fishing log ✓ ${sentCount} sent`);
        if (queue.length) send();
      } else {
        badge('bad', `Fishing log not reachable: start.bat running? ${queue.length} waiting`);
        clearTimeout(retryTimer);
        retryTimer = setTimeout(send, 10000);
      }
    };
    GM_xmlhttpRequest({
      method: 'POST',
      url: LOG_URL,
      headers: {'Content-Type': 'application/json'},
      data: JSON.stringify({catches: batch}),
      timeout: 8000,
      onload: r => done(r.status === 200),
      onerror: () => done(false),
      ontimeout: () => done(false),
    });
  }

  // ---------- a small status label (bottom-left, never blocks clicks) ----------

  let label = null, fadeTimer = 0;
  function badge(kind, text) {
    if (!label) {
      label = document.createElement('div');
      label.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;pointer-events:none;'
        + 'font:600 12px system-ui,sans-serif;padding:4px 8px;border-radius:4px;color:#fff;transition:opacity .4s';
      document.body.append(label);
    }
    label.textContent = text;
    label.style.background = {ok: 'rgba(46,125,50,.85)', warn: 'rgba(176,120,0,.9)', bad: 'rgba(183,28,28,.9)'}[kind];
    label.style.opacity = '1';
    clearTimeout(fadeTimer);
    if (kind === 'ok') fadeTimer = setTimeout(() => { label.style.opacity = '0'; }, 4000);
  }

  if (queue.length) send(); // left over from last time
})();
