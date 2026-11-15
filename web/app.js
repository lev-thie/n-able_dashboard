/* NOC-Wanddisplay – Oberfläche. Holt /api/status vom lokalen Backend und rendert. */
(function () {
  'use strict';

  var POLL_MS = 15000;          // Abfrage des lokalen Backends
  var PAGE_MS = 12000;          // Seitenwechsel bei langen Listen
  var STALE_MS = 90000;         // ab hier gilt die Anzeige als veraltet
  var params = new URLSearchParams(location.search);
  if (params.has('kiosk')) document.body.classList.add('kiosk');
  if (params.has('preview')) document.getElementById('switch').hidden = false;

  var state = null, lastOk = 0, lastAlarmSeen, mode = 'auto', pageTick = 0;
  var display = { start: '07:30', end: '17:00', days: [1, 2, 3, 4, 5, 6, 7], timezone: 'Europe/Berlin' };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function lvl(v, w, c) { return v == null ? '' : v >= c ? 'crit' : v >= w ? 'warn' : ''; }
  function sinceText(iso) {
    if (!iso) return '';
    var m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
    if (m < 60) return m + ' min';
    if (m < 48 * 60) return Math.round(m / 60) + ' h';
    return Math.round(m / 1440) + ' T';
  }
  function uptime(sec) {
    if (sec == null) return '–';
    if (sec < 86400) return Math.max(1, Math.round(sec / 3600)) + ' h';
    return Math.round(sec / 86400) + ' T';
  }

  /* ---------- Seitenwechsel: so viele Zeilen wie in den Bereich passen ---------- */
  function fit(bodyId, headPx) {
    var el = $(bodyId), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    var minRow = 3.0 * rem, avail = el.clientHeight - (headPx || 0);
    var n = Math.max(1, Math.floor(avail / minRow));
    return { n: n, h: (avail / n) + 'px' };
  }
  function page(list, n) {
    var pages = Math.max(1, Math.ceil(list.length / n)), p = pageTick % pages;
    return { items: list.slice(p * n, p * n + n), p: p + 1, pages: pages };
  }
  function pagerText(pg) { return pg.pages > 1 ? ' · Seite <b>' + pg.p + '/' + pg.pages + '</b>' : ''; }

  function meter(v, w, c, cls) {
    if (v == null) return '<div class="meter ' + (cls || '') + '"><div class="bar"></div><div class="num">–</div></div>';
    return '<div class="meter ' + lvl(v, w, c) + ' ' + (cls || '') + '"><div class="bar"><i style="width:' + v + '%"></i></div><div class="num">' + v + ' %</div></div>';
  }

  /* ---------- Rendern ---------- */
  function renderServers(d) {
    var head = '<div class="head"><span></span><span>Server</span><span class="h-cust">Kunde</span><span>CPU</span><span>RAM</span><span class="h-disk">Datenträger</span><span class="h-up" style="text-align:right">Laufzeit</span></div>';
    if (!d.servers.length) {
      $('servers').innerHTML = head + '<div class="empty">' + (d.sources.nable.enabled ? 'Noch keine Serverdaten von N-able.' : 'N-able ist nicht konfiguriert.') + '</div>';
      $('srv-src').textContent = 'N-able';
      return;
    }
    var f = fit('servers-body', 34);
    var pg = page(d.servers, f.n);
    $('servers').style.setProperty('--rowh', f.h);
    $('servers').innerHTML = head + pg.items.map(function (s) {
      var tags = '';
      if (s.stoppedServices.length) {
        tags += '<span class="tag' + (s.stoppedCritical ? '' : ' warn') + '">' + s.stoppedServices.length +
          (s.stoppedServices.length > 1 ? ' Dienste' : ' Dienst') + ' gestoppt</span>';
      }
      if (s.rebootRequired) tags += '<span class="tag warn">Neustart offen</span>';
      var dot = s.state === 'off' ? 'crit' : s.state;
      return '<div class="row ' + (s.state === 'crit' || s.state === 'off' ? 'crit' : '') + (s.state === 'off' ? ' off' : '') + '">' +
        '<span class="dot ' + dot + '"></span>' +
        '<div style="min-width:0"><div class="name">' + esc(s.name) + '</div><div class="role">' + esc(s.role) + tags + '</div></div>' +
        '<div class="cust">' + esc(s.customer) + '</div>' +
        (s.online
          ? meter(s.cpu, 75, 90) + meter(s.ram, 80, 90) + meter(s.disk, 85, 95, 'disk') + '<div class="up">' + uptime(s.uptimeSec) + '</div>'
          : '<div class="offline-note">Agent offline' + (s.offlineSince ? ' seit ' + sinceText(s.offlineSince) : '') + '</div>') +
        '</div>';
    }).join('');
    $('srv-src').innerHTML = 'N-able · ' + d.servers.length + ' Server' + pagerText(pg);
  }

  function renderIssues(d) {
    var crit = d.issues.filter(function (i) { return i.sev === 'crit'; }).length;
    if (!d.issues.length) {
      $('issues').innerHTML = '<div class="empty"><strong>Keine aktiven Probleme</strong>Alle überwachten Systeme melden Normalbetrieb.</div>';
      $('iss-src').textContent = 'alles in Ordnung';
      return;
    }
    var f = fit('issues-body', 0), pg = page(d.issues, f.n);
    $('issues').style.setProperty('--rowh', f.h);
    $('issues').innerHTML = pg.items.map(function (i) {
      return '<div class="issue ' + i.sev + '"><span class="stripe"></span>' +
        '<div style="min-width:0"><div class="ti">' + esc(i.title) + '</div><div class="wh">' + esc(i.where) + '</div></div>' +
        '<div class="since">' + (i.since ? 'seit ' + sinceText(i.since) : '') + '<span>' + esc(i.source) + '</span></div></div>';
    }).join('');
    $('iss-src').innerHTML = crit + ' kritisch · ' + (d.issues.length - crit) + ' Warnungen' + pagerText(pg);
  }

  function renderSites(d) {
    var head = '<div class="head"><span></span><span>Kunde</span><span class="r">Geräte</span><span class="r">Clients</span><span class="r">WAN</span></div>';
    if (!d.sites.length) {
      $('sites').innerHTML = head + '<div class="empty">' + (d.sources.unifi.enabled ? 'Noch keine Standortdaten von UniFi.' : 'UniFi ist nicht konfiguriert.') + '</div>';
      $('site-src').textContent = 'UniFi';
      return;
    }
    var f = fit('sites-body', 30), pg = page(d.sites, f.n);
    $('sites').style.setProperty('--rowh', f.h);
    $('sites').innerHTML = head + pg.items.map(function (s) {
      var st = s.wan === 'off' ? 'crit' : (s.wan === 'degraded' || s.devicesOnline < s.devicesTotal) ? 'warn' : 'ok';
      var wan = s.wan === 'off' ? 'offline' : (s.wanUptime != null ? s.wanUptime + ' %' : 'ok');
      var devCls = s.devicesOnline < s.devicesTotal ? (s.devicesOnline === 0 ? 'crit' : 'warn') : '';
      return '<div class="site ' + (st === 'crit' ? 'crit' : '') + '"><span class="dot ' + st + '"></span>' +
        '<div style="min-width:0"><div class="name">' + esc(s.name) + '</div><div class="role">' + esc([s.gateway, s.isp].filter(Boolean).join(' · ')) + '</div></div>' +
        '<div class="r ' + devCls + '">' + s.devicesOnline + '/' + s.devicesTotal + '</div>' +
        '<div class="r">' + s.clients + '</div>' +
        '<div class="r ' + (s.wan === 'off' ? 'crit' : s.wan === 'degraded' ? 'warn' : '') + '">' + wan + '</div></div>';
    }).join('');
    $('site-src').innerHTML = 'UniFi · ' + d.sites.length + ' Standorte' + pagerText(pg);
  }

  function renderKpis(d) {
    var s = d.summary;
    var crit = d.issues.filter(function (i) { return i.sev === 'crit'; }).length;
    var warn = d.issues.length - crit;
    var off = s.serversTotal - s.serversOnline;
    var k = [
      { c: crit ? 'crit' : 'ok', l: 'Kritische Probleme', v: crit, n: crit ? 'sofort handeln' : 'keine' },
      { c: warn ? 'warn' : 'ok', l: 'Warnungen', v: warn, n: warn ? 'beobachten' : 'keine' },
      { c: s.stoppedServices ? 'crit' : 'ok', l: 'Gestoppte Dienste', v: s.stoppedServices,
        n: s.stoppedServices ? 'auf ' + s.serversWithStoppedServices + ' Server' + (s.serversWithStoppedServices > 1 ? 'n' : '') : (d.sources.ncentral.enabled || d.demo ? 'alle Dienste laufen' : 'N-central nicht verbunden') },
      { c: off ? 'warn' : 'ok', l: 'Server online', v: s.serversOnline + '<small> / ' + s.serversTotal + '</small>', n: off + ' ohne Verbindung' },
      { c: '', l: 'Ø CPU · Ø RAM', v: (s.cpuAvg == null ? '–' : s.cpuAvg + '<small> %</small>') + ' · ' + (s.ramAvg == null ? '–' : s.ramAvg + '<small> %</small>'), n: 'alle Server, aktuell' },
      { c: s.sitesOnline < s.sitesTotal ? 'warn' : 'ok', l: 'UniFi-Standorte online', v: s.sitesOnline + '<small> / ' + s.sitesTotal + '</small>', n: s.clients + ' Clients verbunden' }
    ];
    $('kpis').innerHTML = k.map(function (x) {
      return '<div class="kpi ' + x.c + '"><div class="l">' + x.l + '</div><div class="v">' + x.v + '</div><div class="n">' + x.n + '</div></div>';
    }).join('');
  }

  function renderChart(d) {
    var h = d.history, n = h.cpu.length, el = $('chart');
    if (n < 2) { el.innerHTML = '<div class="empty">Verlauf wird aufgebaut …</div>'; return; }
    var W = Math.max(280, el.clientWidth - 12), H = Math.max(140, el.clientHeight - 10), L = 34, R = 84, T = 12, B = 26;
    var x = function (i) { return L + (W - L - R) * i / (n - 1); };
    var y = function (v) { return T + (H - T - B) * (1 - v / 100); };
    var t0 = Date.parse(h.t[0]), mins = Math.round((Date.now() - t0) / 60000);
    $('chart-src').textContent = 'Mittelwert in %, letzte ' + (mins >= 90 ? Math.round(mins / 60) + ' h' : mins + ' min');
    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Verlauf der mittleren CPU- und RAM-Auslastung">';
    [0, 25, 50, 75, 100].forEach(function (v) {
      svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="#303030" stroke-width="1"/>' +
        '<text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" text-anchor="end" font-size="11" fill="#787878">' + v + '</text>';
    });
    [[0, '−' + mins + ' min', 'start'], [n - 1, 'jetzt', 'end']].forEach(function (t) {
      svg += '<text x="' + x(t[0]) + '" y="' + (H - 6) + '" text-anchor="' + t[2] + '" font-size="11" fill="#787878">' + t[1] + '</text>';
    });
    [['ram', '#2ba5a0', 'RAM'], ['cpu', '#82acba', 'CPU']].forEach(function (s) {
      var vals = h[s[0]], pts = vals.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); }), last = vals[n - 1];
      svg += '<polygon points="' + x(0) + ',' + y(0) + ' ' + pts.join(' ') + ' ' + x(n - 1) + ',' + y(0) + '" fill="' + s[1] + '" fill-opacity="0.12"/>' +
        '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + s[1] + '" stroke-width="2" stroke-linejoin="round"/>' +
        '<circle cx="' + x(n - 1) + '" cy="' + y(last) + '" r="3.5" fill="' + s[1] + '"/>' +
        '<text x="' + (x(n - 1) + 9) + '" y="' + (y(last) + 4) + '" font-size="12" font-weight="700" fill="' + s[1] + '">' + s[2] + ' ' + last + ' %</text>';
    });
    el.innerHTML = svg + '</svg>';
  }

  function renderFeeds(d) {
    var names = { nable: 'N-able', ncentral: 'N-central', unifi: 'UniFi' };
    $('feeds').innerHTML = Object.keys(names).filter(function (k) { return d.sources[k].enabled; }).map(function (k) {
      var s = d.sources[k];
      var age = s.at ? Math.round((Date.now() - Date.parse(s.at)) / 1000) : null;
      var txt = s.ok ? (age == null ? '' : age < 90 ? 'vor ' + age + ' s' : 'vor ' + Math.round(age / 60) + ' min') : 'Fehler';
      return '<div class="feed' + (s.ok ? '' : ' err') + '" title="' + esc(s.error || '') + '"><span class="dot ' + (s.ok ? 'ok' : 'crit') + '"></span>' + names[k] + ' · ' + txt + '</div>';
    }).join('');
  }

  function render() {
    if (!state) return;
    $('demo-badge').hidden = !state.demo;
    renderKpis(state); renderServers(state); renderIssues(state); renderSites(state); renderChart(state); renderFeeds(state);
  }

  /* ---------- Daten holen ---------- */
  function poll() {
    fetch('api/status', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (d) {
      if (!d || !d.servers) return;
      if (lastAlarmSeen !== undefined && d.lastAlarm && d.lastAlarm !== lastAlarmSeen) showAlert();
      lastAlarmSeen = d.lastAlarm || null;
      state = d; lastOk = Date.now();
      if (d.display) display = d.display;
      $('sub').textContent = 'Gleich ITS GmbH · Anzeige ' + display.start + '–' + display.end + ' Uhr';
      render();
    }).catch(function () { /* Anzeige des letzten Stands bleibt, Hinweis via STALE_MS */ });
  }
  function showAlert() {
    var a = $('alert'); a.hidden = false;
    a.style.animation = 'none'; void a.offsetWidth; a.style.animation = '';
    clearTimeout(showAlert.t); showAlert.t = setTimeout(function () { a.hidden = true; }, 30000);
  }

  /* ---------- Uhr + Modus ---------- */
  function tick() {
    var fmtT = new Intl.DateTimeFormat('de-DE', { timeZone: display.timezone, hour: '2-digit', minute: '2-digit', second: '2-digit', weekday: 'short', hour12: false });
    var fmtD = new Intl.DateTimeFormat('de-DE', { timeZone: display.timezone, weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
    var now = new Date(), p = {};
    fmtT.formatToParts(now).forEach(function (x) { p[x.type] = x.value; });
    var hm = (p.hour === '24' ? '00' : p.hour) + ':' + p.minute, date = fmtD.format(now);
    var dow = ['Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.', 'So.'].indexOf(p.weekday) + 1;
    $('hdr-time').textContent = hm; $('hdr-date').textContent = date;
    $('clk-hm').textContent = hm; $('clk-s').textContent = p.second; $('clk-date').textContent = date;
    var active = display.days.indexOf(dow) >= 0 && hm >= display.start && hm < display.end;
    var showClock = mode === 'clock' || (mode === 'auto' && !active);
    var wasClock = !$('clock').hidden;
    $('clock').hidden = !showClock; $('dashboard').hidden = showClock;
    $('clk-hint').textContent = 'Dashboard aktiv ' + display.start + '–' + display.end + ' Uhr';
    if (wasClock && !showClock) render();          // Größen neu berechnen
    if (p.second === '00') {                        // Einbrennschutz: Uhr wandert leicht
      var dx = (Math.random() - 0.5) * 6, dy = (Math.random() - 0.5) * 4;
      $('clock-inner').style.transform = 'translate(' + dx.toFixed(1) + 'vw,' + dy.toFixed(1) + 'vh)';
    }
    $('backend-down').hidden = showClock || !lastOk || Date.now() - lastOk < STALE_MS;
    if (state && !showClock && now.getSeconds() % 5 === 0) renderFeeds(state);
  }

  document.querySelectorAll('#switch button').forEach(function (b) {
    b.addEventListener('click', function () {
      mode = b.dataset.mode;
      document.querySelectorAll('#switch button').forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
      tick();
    });
  });
  window.addEventListener('resize', render);

  poll(); tick();
  setInterval(poll, POLL_MS);
  setInterval(tick, 1000);
  setInterval(function () { pageTick++; render(); }, PAGE_MS);
  setInterval(function () { location.reload(); }, 6 * 3600 * 1000);   // Speicher frisch halten im Dauerbetrieb
})();
