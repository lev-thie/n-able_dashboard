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
  var display = { start: '07:30', end: '17:00', days: [1, 2, 3, 4, 5, 6, 7], timezone: 'Europe/Berlin', scale: 1 };
  var narrow = window.matchMedia('(max-aspect-ratio: 4/3)');

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

  /* ---------- Seitenwechsel: so viele Zeilen wie gut lesbar in den Bereich passen ---------- */
  function fit(bodyId, headPx) {
    if (narrow.matches) return { n: 1e6, h: 'auto' };
    var el = $(bodyId), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    var minRow = 3.4 * rem, avail = el.clientHeight - (headPx || 0);
    var n = Math.max(1, Math.floor(avail / minRow));
    return { n: n, h: (avail / n) + 'px' };
  }
  function headH(listId) {
    var h = $(listId).querySelector('.head');
    return h ? h.getBoundingClientRect().height : 0;
  }
  function page(list, n) {
    var pages = Math.max(1, Math.ceil(list.length / n)), p = pageTick % pages;
    return { items: list.slice(p * n, p * n + n), p: p + 1, pages: pages };
  }
  function pagerText(pg) { return pg.pages > 1 ? ' · Seite <b>' + pg.p + '/' + pg.pages + '</b>' : ''; }

  function meter(v, w, c) {
    if (v == null) return '<div class="meter"><div class="bar"></div><div class="num">–</div></div>';
    return '<div class="meter ' + lvl(v, w, c) + '"><div class="bar"><i style="width:' + v + '%"></i></div><div class="num">' + v + ' %</div></div>';
  }

  /* ---------- Rendern ---------- */
  function renderServers(d) {
    var head = '<div class="srv-head head"><span></span><span>Server · Kunde</span><span>CPU</span><span>RAM</span><span>Datenträger</span></div>';
    if (!d.servers.length) {
      $('servers').innerHTML = head + '<div class="empty">' + (d.sources.nable.enabled ? 'Noch keine Serverdaten von N-able.' : 'N-able ist nicht konfiguriert.') + '</div>';
      $('srv-src').textContent = '';
      return;
    }
    $('servers').innerHTML = head;
    var f = fit('servers-body', headH('servers')), pg = page(d.servers, f.n);
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
        '<div style="min-width:0"><div class="name">' + esc(s.name) + tags + '</div><div class="subl">' + esc(s.customer || s.role) + '</div></div>' +
        (s.online
          ? meter(s.cpu, 75, 90) + meter(s.ram, 80, 90) + meter(s.disk, 85, 95)
          : '<div class="offline-note">Agent offline' + (s.offlineSince ? ' seit ' + sinceText(s.offlineSince) : '') + '</div>') +
        '</div>';
    }).join('');
    $('srv-src').innerHTML = d.servers.length + ' Server' + pagerText(pg);
  }

  function renderIssues(d) {
    var crit = d.issues.filter(function (i) { return i.sev === 'crit'; }).length;
    if (!d.issues.length) {
      $('issues').innerHTML = '<div class="empty"><strong>Keine aktiven Probleme</strong>Alle Systeme melden Normalbetrieb.</div>';
      $('iss-src').textContent = '';
      return;
    }
    var f = fit('issues-body', 0), pg = page(d.issues, f.n);
    $('issues').style.setProperty('--rowh', f.h);
    $('issues').innerHTML = pg.items.map(function (i) {
      return '<div class="issue ' + i.sev + '"><span class="stripe"></span>' +
        '<div style="min-width:0"><div class="name">' + esc(i.title) + '</div><div class="subl">' + esc(i.where) + '</div></div>' +
        '<div class="since">' + (i.since ? sinceText(i.since) : '') + '</div></div>';
    }).join('');
    $('iss-src').innerHTML = '<b>' + crit + '</b> kritisch · <b>' + (d.issues.length - crit) + '</b> Warnungen' + pagerText(pg);
  }

  function renderSites(d) {
    var head = '<div class="site-head head"><span></span><span>Kunde</span><span class="r">Geräte</span><span class="r">WAN</span></div>';
    if (!d.sites.length) {
      $('sites').innerHTML = head + '<div class="empty">' + (d.sources.unifi.enabled ? 'Noch keine Standortdaten von UniFi.' : 'UniFi ist nicht konfiguriert.') + '</div>';
      $('site-src').textContent = '';
      return;
    }
    $('sites').innerHTML = head;
    var f = fit('sites-body', headH('sites')), pg = page(d.sites, f.n);
    $('sites').style.setProperty('--rowh', f.h);
    $('sites').innerHTML = head + pg.items.map(function (s) {
      var st = s.wan === 'off' ? 'crit' : (s.wan === 'degraded' || s.devicesOnline < s.devicesTotal) ? 'warn' : 'ok';
      var wan = s.wan === 'off' ? 'offline' : (s.wanUptime != null ? s.wanUptime + ' %' : 'ok');
      var devCls = s.devicesOnline < s.devicesTotal ? (s.devicesOnline === 0 ? 'crit' : 'warn') : '';
      return '<div class="site ' + (st === 'crit' ? 'crit' : '') + '"><span class="dot ' + st + '"></span>' +
        '<div style="min-width:0"><div class="name">' + esc(s.name) + '</div><div class="subl">' + esc([s.gateway, s.clients + ' Clients'].filter(Boolean).join(' · ')) + '</div></div>' +
        '<div class="r ' + devCls + '">' + s.devicesOnline + '/' + s.devicesTotal + '</div>' +
        '<div class="r ' + (s.wan === 'off' ? 'crit' : s.wan === 'degraded' ? 'warn' : '') + '">' + wan + '</div></div>';
    }).join('');
    $('site-src').innerHTML = d.sites.length + ' Standorte' + pagerText(pg);
  }

  function renderKpis(d) {
    var s = d.summary;
    var crit = d.issues.filter(function (i) { return i.sev === 'crit'; }).length;
    var warn = d.issues.length - crit;
    var off = s.serversTotal - s.serversOnline;
    var k = [
      { c: crit ? 'crit' : 'ok', l: 'Kritisch', v: crit, n: crit ? 'sofort handeln' : 'keine' },
      { c: warn ? 'warn' : 'ok', l: 'Warnungen', v: warn, n: warn ? 'beobachten' : 'keine' },
      { c: s.stoppedServices ? 'crit' : 'ok', l: 'Dienste gestoppt', v: s.stoppedServices,
        n: s.stoppedServices ? 'auf ' + s.serversWithStoppedServices + ' Server' + (s.serversWithStoppedServices > 1 ? 'n' : '') : (d.sources.ncentral.enabled || d.demo ? 'alle laufen' : 'N-central fehlt') },
      { c: off ? 'warn' : 'ok', l: 'Server online', v: s.serversOnline + '<small>/' + s.serversTotal + '</small>', n: off ? off + ' ohne Verbindung' : 'alle verbunden' },
      { c: '', l: 'Ø CPU · RAM', v: (s.cpuAvg == null ? '–' : s.cpuAvg) + '<small>%</small> ' + (s.ramAvg == null ? '–' : s.ramAvg) + '<small>%</small>', n: 'alle Server' },
      { c: s.sitesOnline < s.sitesTotal ? 'warn' : 'ok', l: 'Standorte online', v: s.sitesOnline + '<small>/' + s.sitesTotal + '</small>', n: s.clients + ' Clients' }
    ];
    $('kpis').innerHTML = k.map(function (x) {
      return '<div class="kpi ' + x.c + '"><div class="l">' + x.l + '</div><div class="v">' + x.v + '</div><div class="n">' + x.n + '</div></div>';
    }).join('');
  }

  function renderFeeds(d) {
    var names = { nable: 'N-able', ncentral: 'N-central', unifi: 'UniFi' };
    $('feeds').innerHTML = Object.keys(names).filter(function (k) { return d.sources[k].enabled; }).map(function (k) {
      var s = d.sources[k];
      var age = s.at ? (Date.now() - Date.parse(s.at)) / 1000 : null;
      var good = s.ok && !(age != null && age > 600);
      return '<div class="feed' + (good ? '' : ' err') + '" title="' + esc(s.error || '') + '"><span class="dot ' + (good ? 'ok' : 'crit') + '"></span>' + names[k] + (good ? '' : ' Fehler') + '</div>';
    }).join('');
  }

  function render() {
    if (!state || !$('clock').hidden) return;
    $('demo-badge').hidden = !state.demo;
    renderKpis(state); renderServers(state); renderIssues(state); renderSites(state); renderFeeds(state);
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
      if (d.display) {
        display = d.display;
        document.documentElement.style.setProperty('--scale', display.scale || 1);
      }
      render();
    }).catch(function () { /* letzter Stand bleibt sichtbar, Hinweis nach STALE_MS */ });
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
  }

  document.querySelectorAll('#switch button').forEach(function (b) {
    b.addEventListener('click', function () {
      mode = b.dataset.mode;
      document.querySelectorAll('#switch button').forEach(function (o) { o.setAttribute('aria-pressed', String(o === b)); });
      tick();
    });
  });
  window.addEventListener('resize', render);
  if (narrow.addEventListener) narrow.addEventListener('change', render);

  poll(); tick();
  setInterval(poll, POLL_MS);
  setInterval(tick, 1000);
  setInterval(function () { pageTick++; render(); }, PAGE_MS);
  setInterval(function () { location.reload(); }, 6 * 3600 * 1000);   // Speicher frisch halten im Dauerbetrieb
})();
