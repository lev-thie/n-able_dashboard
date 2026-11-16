#!/usr/bin/env python3
"""NOC-Wanddisplay – Backend.

Sammelt Daten aus der N-able GraphQL-API (Server, CPU/RAM, Datenträger, Agent-Status),
optional aus der N-central REST-API (aktive Probleme, gestoppte Dienste) und aus der
UniFi Site Manager API (Kundenstandorte), stellt sie unter /api/status als JSON bereit,
liefert die Weboberfläche aus und spielt bei neuen kritischen Problemen eine WAV-Datei ab.

Nur Python-Standardbibliothek (läuft auf Raspberry Pi OS ohne pip).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import demo

log = logging.getLogger("noc")
BASE = Path(__file__).resolve().parent
WEB_DIR = BASE.parent / "web"


# --------------------------------------------------------------------------- Konfiguration
def load_env_file(path: Path) -> None:
    """Liest KEY=VALUE-Zeilen (wie systemd EnvironmentFile), ohne bestehende Variablen zu überschreiben."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    v = env(name, "")
    return default if v == "" else v.lower() in ("1", "true", "yes", "ja", "on")


class Config:
    def __init__(self) -> None:
        self.port = env_int("PORT", 8765)
        self.bind = env("BIND", "127.0.0.1")
        self.tz = ZoneInfo(env("TIMEZONE", "Europe/Berlin"))
        self.display_start = env("DISPLAY_START", "07:30")
        self.display_end = env("DISPLAY_END", "17:00")
        self.display_days = [int(d) for d in env("DISPLAY_DAYS", "1,2,3,4,5,6,7").split(",") if d.strip()]
        try:
            self.ui_scale = max(0.5, min(2.5, float(env("UI_SCALE", "1").replace(",", "."))))
        except ValueError:
            self.ui_scale = 1.0

        self.nable_url = env("NABLE_GRAPHQL_URL", "https://api.n-able.com/graphql")
        self.nable_token = env("NABLE_API_TOKEN")
        self.nable_orgs = [o for o in env("NABLE_ORGANIZATION_IDS").split(",") if o.strip()]
        self.nable_inventory_s = env_int("NABLE_INVENTORY_INTERVAL", 600)
        self.nable_metrics_s = env_int("NABLE_METRICS_INTERVAL", 60)

        self.nc_server = env("NCENTRAL_SERVER").rstrip("/")
        if self.nc_server and not self.nc_server.startswith("http"):
            self.nc_server = "https://" + self.nc_server
        self.nc_jwt = env("NCENTRAL_JWT")
        self.nc_interval_s = env_int("NCENTRAL_INTERVAL", 120)
        self.nc_crit_states = {s.strip() for s in env("NCENTRAL_CRITICAL_STATES", "5").split(",") if s.strip()}
        self.nc_service_re = re.compile(env("NCENTRAL_SERVICE_PATTERN", r"(?i)service|dienst"))

        self.unifi_key = env("UNIFI_API_KEY")
        self.unifi_url = env("UNIFI_API_URL", "https://api.ui.com").rstrip("/")
        self.unifi_interval_s = env_int("UNIFI_INTERVAL", 60)

        self.cpu_warn, self.cpu_crit = env_int("CPU_WARN", 75), env_int("CPU_CRIT", 90)
        self.ram_warn, self.ram_crit = env_int("RAM_WARN", 80), env_int("RAM_CRIT", 90)
        self.disk_warn, self.disk_crit = env_int("DISK_WARN", 85), env_int("DISK_CRIT", 95)

        self.sound_file = Path(env("ALARM_SOUND", "/opt/noc-dashboard/sounds/alarm.wav"))
        self.sound_device = env("ALARM_ALSA_DEVICE")
        self.sound_only_display = env_bool("ALARM_ONLY_DURING_DISPLAY", True)
        self.sound_cooldown_s = env_int("ALARM_COOLDOWN", 60)
        self.sound_repeat_min = env_int("ALARM_REPEAT_MINUTES", 0)

        self.demo = env_bool("DEMO_MODE", False) or not (self.nable_token or self.unifi_key or self.nc_jwt)

    def display_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(self.tz)
        if now.isoweekday() not in self.display_days:
            return False
        hm = now.strftime("%H:%M")
        return self.display_start <= hm < self.display_end


# --------------------------------------------------------------------------- HTTP-Helfer
def http_json(url: str, *, method: str = "GET", headers: dict | None = None, body: dict | None = None,
              timeout: int = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json", "User-Agent": "noc-dashboard/1.0"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} von {urllib.parse.urlsplit(url).netloc}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Keine Verbindung zu {urllib.parse.urlsplit(url).netloc}: {e.reason}") from None
    return json.loads(raw) if raw else {}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class SourceState:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.ok = False
        self.at: str | None = None
        self.error: str | None = None

    def success(self) -> None:
        self.ok, self.at, self.error = True, iso_now(), None

    def fail(self, err: Exception) -> None:
        self.ok, self.error = False, str(err)[:300]

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "ok": self.ok, "at": self.at, "error": self.error}


# --------------------------------------------------------------------------- N-able GraphQL
INVENTORY_QUERY = """
query Inventory($first: Int!, $after: String, $orgs: [ID!]) {
  assetSearch(first: $first, after: $after, inOrganizations: $orgs,
              orderBy: [{field: NAME, direction: ASC}]) {
    totalCount
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      description
      operatingSystemInfo { name role }
      customer { id name }
      site { id name }
      ncentralDevice { deviceId }
    }
  }
}"""

METRICS_QUERY = """
query Metrics($ids: [ID!]!, $input: AssetMetricInput!) {
  assets(ids: $ids) {
    id
    lastBootedAt
    agentConnection { status statusChangedAt }
    reboot { isRequired }
    logicalDrives { driveId totalSizeBytes freeSpaceBytes }
    metrics {
      cpu { percentage(input: $input) { timeSeries { dateTime value } } }
      memory { percentage(input: $input) { timeSeries { dateTime value } } }
    }
  }
}"""


class NableClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _gql(self, query: str, variables: dict) -> dict:
        res = http_json(self.cfg.nable_url, method="POST",
                        headers={"Authorization": f"Bearer {self.cfg.nable_token}"},
                        body={"query": query, "variables": variables}, timeout=60)
        if res.get("errors") and not res.get("data"):
            raise RuntimeError("N-able GraphQL: " + "; ".join(e.get("message", "?") for e in res["errors"])[:300])
        if res.get("errors"):
            log.warning("N-able GraphQL Teilfehler: %s", res["errors"][:3])
        return res.get("data") or {}

    def servers(self) -> list[dict]:
        out, after = [], None
        while True:
            d = self._gql(INVENTORY_QUERY, {"first": 100, "after": after, "orgs": self.cfg.nable_orgs or None})
            conn = d["assetSearch"]
            for a in conn["nodes"]:
                if ((a.get("operatingSystemInfo") or {}).get("role") or "") == "SERVER":
                    out.append(a)
            if not conn["pageInfo"]["hasNextPage"]:
                return out
            after = conn["pageInfo"]["endCursor"]

    def metrics(self, ids: list[str]) -> dict[str, dict]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        metric_input = {"timeSeries": {
            "dateTimeRange": {"relative": {"relativeTo": now, "dateTimePeriod": "PREVIOUS_MINUTES",
                                           "numberOfDateTimeUnits": 15}},
            "granularity": {"value": 5, "unit": "MINUTE"}}}
        out: dict[str, dict] = {}
        for i in range(0, len(ids), 50):
            d = self._gql(METRICS_QUERY, {"ids": ids[i:i + 50], "input": metric_input})
            for a in d.get("assets") or []:
                out[a["id"]] = a
        return out


def last_value(series: dict | None) -> float | None:
    pts = ((series or {}).get("percentage") or {}).get("timeSeries") or []
    pts = [p for p in pts if p.get("value") is not None]
    if not pts:
        return None
    pts.sort(key=lambda p: p.get("dateTime") or "")
    return round(float(pts[-1]["value"]))


# --------------------------------------------------------------------------- N-central REST
class NcentralClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.access: str | None = None
        self.access_until = 0.0
        self.states_seen: set[str] = set()

    def _token(self) -> str:
        if self.access and time.time() < self.access_until - 60:
            return self.access
        res = http_json(f"{self.cfg.nc_server}/api/auth/authenticate", method="POST",
                        headers={"Authorization": f"Bearer {self.cfg.nc_jwt}"})
        acc = res["tokens"]["access"]
        self.access = acc["token"]
        self.access_until = time.time() + int(acc.get("expirySeconds", 3600))
        return self.access

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.cfg.nc_server}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return http_json(url, headers={"Authorization": f"Bearer {self._token()}"})

    def _paged(self, path: str) -> list[dict]:
        items, page = [], 1
        while True:
            res = self._get(path, {"pageNumber": page, "pageSize": 500})
            items += res.get("data") or []
            total_pages = res.get("totalPages")
            if total_pages is None:
                total = res.get("totalItems") or 0
                total_pages = (total + 499) // 500
            if page >= (total_pages or 1):
                return items
            page += 1

    def active_issues(self) -> list[dict]:
        issues = []
        for c in self._paged("/api/customers"):
            cid = c.get("customerId") or c.get("orgUnitId")
            if cid is None:
                continue
            for it in self._paged(f"/api/org-units/{cid}/active-issues"):
                st = str(it.get("notificationState"))
                if st not in self.states_seen:
                    self.states_seen.add(st)
                    log.info("N-central notificationState gesehen: %s (z. B. %s)", st, it.get("serviceName"))
                extra = it.get("_extra") or {}
                tree = extra.get("customerTree") or []
                issues.append({
                    "deviceId": str(it.get("deviceId")),
                    "device": extra.get("deviceName") or str(it.get("deviceId")),
                    "customer": tree[-1] if tree else (c.get("customerName") or ""),
                    "service": it.get("serviceName") or "Unbekannter Dienst",
                    "state": st,
                    "taskId": it.get("taskId"),
                })
        return issues


# --------------------------------------------------------------------------- UniFi Site Manager
class UnifiClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _paged(self, path: str) -> list[dict]:
        items, token = [], None
        while True:
            params = {"pageSize": "200"}
            if token:
                params["nextToken"] = token
            res = http_json(f"{self.cfg.unifi_url}{path}?{urllib.parse.urlencode(params)}",
                            headers={"X-API-Key": self.cfg.unifi_key})
            items += res.get("data") or []
            token = res.get("nextToken")
            if not token:
                return items

    def sites(self) -> list[dict]:
        hosts = {}
        for h in self._paged("/v1/devices"):
            consoles = [d for d in h.get("devices") or [] if d.get("isConsole")]
            hosts[h.get("hostId")] = {"name": h.get("hostName") or "",
                                      "model": consoles[0].get("model") if consoles else ""}
        out = []
        for s in self._paged("/v1/sites"):
            meta, st = s.get("meta") or {}, s.get("statistics") or {}
            counts, host = st.get("counts") or {}, hosts.get(s.get("hostId"), {})
            desc = meta.get("desc") or ""
            name = desc if desc and desc.lower() != "default" else (host.get("name") or desc or meta.get("name") or "?")
            total = int(counts.get("totalDevice") or 0)
            offline = int(counts.get("offlineDevice") or 0)
            gw_off = int(counts.get("offlineGatewayDevice") or 0)
            clients = sum(int(counts.get(k) or 0) for k in ("wifiClient", "wiredClient", "guestClient"))
            wan_up = (st.get("percentages") or {}).get("wanUptime")
            issues = st.get("internetIssues") or []
            wan = "off" if gw_off else ("degraded" if issues or (wan_up is not None and wan_up < 99) else "ok")
            out.append({
                "id": s.get("siteId"), "name": name,
                "gateway": (st.get("gateway") or {}).get("shortname") or host.get("model") or "",
                "devicesOnline": max(total - offline, 0), "devicesTotal": total,
                "clients": clients, "wan": wan,
                "wanUptime": round(wan_up) if isinstance(wan_up, (int, float)) else None,
                "isp": (st.get("ispInfo") or {}).get("name") or "",
                "criticalNotifications": int(counts.get("criticalNotification") or 0),
            })
        return out


# --------------------------------------------------------------------------- Alarmton
class Alarm:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.last_play = 0.0
        self.known: set[str] | None = None
        self.last_reminder = time.time()
        self.lock = threading.Lock()

    def play(self, reason: str) -> bool:
        if not self.cfg.sound_file.is_file():
            log.warning("Alarmton fehlt: %s", self.cfg.sound_file)
            return False
        player = shutil.which("aplay")
        if not player:
            log.warning("aplay nicht gefunden (Paket alsa-utils)")
            return False
        cmd = [player, "-q"]
        if self.cfg.sound_device:
            cmd += ["-D", self.cfg.sound_device]
        cmd.append(str(self.cfg.sound_file))
        log.info("Alarmton: %s", reason)
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.last_play = time.time()
        return True

    def update(self, critical_keys: set[str]) -> str | None:
        """Gibt den Zeitpunkt zurück, wenn ein Ton ausgelöst wurde."""
        with self.lock:
            if self.known is None:          # erster Durchlauf: Bestand nicht melden
                self.known = set(critical_keys)
                return None
            new = critical_keys - self.known
            self.known = set(critical_keys)
            allowed = not self.cfg.sound_only_display or self.cfg.display_active()
            now = time.time()
            if new and allowed and now - self.last_play >= self.cfg.sound_cooldown_s:
                if self.play(f"{len(new)} neue(s) kritische(s) Problem(e)"):
                    self.last_reminder = now
                    return iso_now()
            if (self.cfg.sound_repeat_min and critical_keys and allowed
                    and now - self.last_reminder >= self.cfg.sound_repeat_min * 60):
                self.last_reminder = now
                if self.play("Erinnerung: kritische Probleme bestehen weiter"):
                    return iso_now()
            return None


# --------------------------------------------------------------------------- Zustand / Aggregation
class Hub:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lock = threading.Lock()
        self.src = {
            "nable": SourceState(bool(cfg.nable_token)),
            "ncentral": SourceState(bool(cfg.nc_server and cfg.nc_jwt)),
            "unifi": SourceState(bool(cfg.unifi_key)),
        }
        self.inventory: list[dict] = []
        self.inventory_at = 0.0
        self.metrics: dict[str, dict] = {}
        self.nc_issues: list[dict] = []
        self.sites: list[dict] = []
        self.first_seen: dict[str, str] = {}
        self.history: dict[str, list] = {"t": [], "cpu": [], "ram": []}
        self.alarm = Alarm(cfg)
        self.last_alarm: str | None = None
        self.snapshot: dict = {}

    # ---- Pollers
    def poll_nable(self, client: NableClient) -> None:
        if time.time() - self.inventory_at > self.cfg.nable_inventory_s or not self.inventory:
            inv = client.servers()
            with self.lock:
                self.inventory, self.inventory_at = inv, time.time()
            log.info("N-able: %d Server im Bestand", len(inv))
        m = client.metrics([a["id"] for a in self.inventory])
        with self.lock:
            self.metrics = m

    def poll_ncentral(self, client: NcentralClient) -> None:
        issues = client.active_issues()
        with self.lock:
            self.nc_issues = issues

    def poll_unifi(self, client: UnifiClient) -> None:
        sites = client.sites()
        with self.lock:
            self.sites = sites

    # ---- Aufbereitung
    def _servers(self) -> list[dict]:
        cfg, now = self.cfg, datetime.now(timezone.utc)
        svc_by_dev: dict[str, list[dict]] = {}
        for it in self.nc_issues:
            if cfg.nc_service_re.search(it["service"]):
                svc_by_dev.setdefault(it["deviceId"], []).append(it)
        out = []
        for a in self.inventory:
            m = self.metrics.get(a["id"]) or {}
            conn = m.get("agentConnection") or {}
            online = conn.get("status") != "DISCONNECTED"
            drives = [d for d in m.get("logicalDrives") or [] if (d.get("totalSizeBytes") or 0) > 2**30]
            disk = max((round(100 * (1 - int(d.get("freeSpaceBytes") or 0) / int(d["totalSizeBytes"])))
                        for d in drives), default=None)
            disk_drive = max(drives, key=lambda d: 1 - int(d.get("freeSpaceBytes") or 0) / int(d["totalSizeBytes"]),
                             default={}).get("driveId")
            boot = parse_dt(m.get("lastBootedAt"))
            dev_id = str((a.get("ncentralDevice") or {}).get("deviceId") or "")
            out.append({
                "id": a["id"], "name": a.get("name") or "?",
                "role": a.get("description") or (a.get("operatingSystemInfo") or {}).get("name") or "",
                "customer": (a.get("customer") or {}).get("name") or (a.get("site") or {}).get("name") or "",
                "online": online, "offlineSince": conn.get("statusChangedAt") if not online else None,
                "cpu": last_value((m.get("metrics") or {}).get("cpu")),
                "ram": last_value((m.get("metrics") or {}).get("memory")),
                "disk": disk, "diskDrive": disk_drive,
                "uptimeSec": int((now - boot).total_seconds()) if boot else None,
                "rebootRequired": bool((m.get("reboot") or {}).get("isRequired")),
                "stoppedServices": [i["service"] for i in svc_by_dev.get(dev_id, [])],
                "stoppedCritical": any(i["state"] in cfg.nc_crit_states for i in svc_by_dev.get(dev_id, [])),
            })
        return out

    def _server_state(self, s: dict) -> str:
        c = self.cfg
        if not s["online"]:
            return "off"
        if ((s["cpu"] or 0) >= c.cpu_crit or (s["ram"] or 0) >= c.ram_crit or (s["disk"] or 0) >= c.disk_crit
                or s["stoppedCritical"]):
            return "crit"
        if ((s["cpu"] or 0) >= c.cpu_warn or (s["ram"] or 0) >= c.ram_warn or (s["disk"] or 0) >= c.disk_warn
                or s["stoppedServices"] or s["rebootRequired"]):
            return "warn"
        return "ok"

    def _issues(self, servers: list[dict], sites: list[dict]) -> list[dict]:
        c, out = self.cfg, []

        def add(key, sev, title, where, source, since=None, service=False):
            out.append({"key": key, "sev": sev, "title": title, "where": where, "source": source,
                        "since": since, "service": service})

        for s in servers:
            w = f'{s["name"]} · {s["customer"]}'.strip(" ·")
            if not s["online"]:
                add(f'agent:{s["id"]}', "crit", "Agent offline", w, "N-able", s["offlineSince"])
                continue
            for key, label, wv, cv in (("cpu", "CPU", c.cpu_warn, c.cpu_crit), ("ram", "RAM", c.ram_warn, c.ram_crit)):
                v = s[key]
                if v is not None and v >= wv:
                    add(f'{key}:{s["id"]}', "crit" if v >= cv else "warn", f"{label}-Auslastung {v} %", w, "N-able")
            if s["disk"] is not None and s["disk"] >= c.disk_warn:
                add(f'disk:{s["id"]}', "crit" if s["disk"] >= c.disk_crit else "warn",
                    f'Datenträger {s["diskDrive"] or ""} {s["disk"]} % belegt'.replace("  ", " "), w, "N-able")
            if s["rebootRequired"]:
                add(f'reboot:{s["id"]}', "warn", "Neustart ausstehend", w, "N-able")

        for it in self.nc_issues:
            svc = bool(c.nc_service_re.search(it["service"]))
            sev = "crit" if it["state"] in c.nc_crit_states else "warn"
            title = ("Dienst gestoppt: " if svc else "") + it["service"]
            add(f'nc:{it["deviceId"]}:{it["taskId"] or it["service"]}', sev, title,
                f'{it["device"]} · {it["customer"]}'.strip(" ·"), "N-central", service=svc)

        for st in sites:
            if st["wan"] == "off":
                add(f'site:{st["id"]}', "crit", "Standort offline (Gateway)", f'{st["gateway"]} · {st["name"]}', "UniFi")
            elif st["wan"] == "degraded":
                add(f'wan:{st["id"]}', "warn", f'WAN-Störung ({st["wanUptime"]} % Uptime)',
                    f'{st["gateway"]} · {st["name"]}', "UniFi")
            off = st["devicesTotal"] - st["devicesOnline"]
            if off > 0 and st["wan"] != "off":
                add(f'dev:{st["id"]}', "warn", f'{off} Gerät{"e" if off > 1 else ""} offline', st["name"], "UniFi")

        # Zeitpunkt „seit“: API-Wert oder erste Beobachtung durch das Backend
        now, keys = iso_now(), set()
        for i in out:
            keys.add(i["key"])
            self.first_seen.setdefault(i["key"], i["since"] or now)
            i["since"] = i["since"] or self.first_seen[i["key"]]
        for k in list(self.first_seen):
            if k not in keys:
                del self.first_seen[k]
        out.sort(key=lambda i: (0 if i["sev"] == "crit" else 1, i["since"] or ""))
        return out

    def rebuild(self) -> None:
        with self.lock:
            servers = self._servers()
            for s in servers:
                s["state"] = self._server_state(s)
            order = {"crit": 0, "off": 0, "warn": 1, "ok": 2}
            servers.sort(key=lambda s: (order[s["state"]], -(max(s["cpu"] or 0, s["ram"] or 0)), s["name"]))
            sites = sorted(self.sites, key=lambda s: ({"off": 0, "degraded": 1}.get(s["wan"], 2 if s["devicesOnline"] == s["devicesTotal"] else 1), s["name"]))
            issues = self._issues(servers, sites)

            live = [s for s in servers if s["online"]]
            def avg(k):
                vals = [s[k] for s in live if s[k] is not None]
                return round(sum(vals) / len(vals)) if vals else None
            cpu, ram = avg("cpu"), avg("ram")
            if cpu is not None:
                h = self.history
                h["t"].append(iso_now()); h["cpu"].append(cpu); h["ram"].append(ram)
                for k in h:
                    del h[k][:-120]

            # Alarm erst scharf schalten, wenn jede aktive Quelle einmal geantwortet hat –
            # so lösen bereits bestehende Probleme nach einem Neustart keinen Ton aus.
            if all(v.at or v.error for v in self.src.values() if v.enabled):
                crit_keys = {i["key"] for i in issues if i["sev"] == "crit"}
                played = self.alarm.update(crit_keys)
                if played:
                    self.last_alarm = played

            self.snapshot = {
                "generatedAt": iso_now(), "demo": False,
                "display": {"start": self.cfg.display_start, "end": self.cfg.display_end,
                            "days": self.cfg.display_days, "timezone": str(self.cfg.tz),
                            "scale": self.cfg.ui_scale},
                "sources": {k: v.as_dict() for k, v in self.src.items()},
                "servers": servers, "sites": sites, "issues": issues,
                "summary": {"serversTotal": len(servers), "serversOnline": len(live),
                            "cpuAvg": cpu, "ramAvg": ram,
                            "stoppedServices": sum(len(s["stoppedServices"]) for s in servers),
                            "serversWithStoppedServices": sum(1 for s in servers if s["stoppedServices"]),
                            "sitesTotal": len(sites), "sitesOnline": sum(1 for s in sites if s["wan"] != "off"),
                            "clients": sum(s["clients"] for s in sites)},
                "history": self.history, "lastAlarm": self.last_alarm,
            }


def run_loop(name: str, interval: int, fn, hub: Hub) -> None:
    state = hub.src[name]
    while True:
        try:
            fn()
            state.success()
        except Exception as e:  # noqa: BLE001 – Quelle darf das Gesamtsystem nicht stoppen
            state.fail(e)
            log.error("%s: %s", name, e)
        hub.rebuild()
        time.sleep(interval if state.ok else min(interval, 60))


# --------------------------------------------------------------------------- Webserver
def make_handler(get_status):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB_DIR), **kw)

        def log_message(self, fmt, *args):  # ruhig halten
            log.debug("http %s", fmt % args)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/status":
                body = json.dumps(get_status(), ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            super().do_GET()
    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="NOC-Wanddisplay Backend")
    ap.add_argument("--config", default="/etc/noc-dashboard/config.env")
    ap.add_argument("--test-sound", action="store_true", help="Alarmton einmal abspielen und beenden")
    ap.add_argument("--demo", action="store_true", help="Beispieldaten statt echter APIs")
    args = ap.parse_args()

    load_env_file(Path(args.config))
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()
    if args.demo:
        cfg.demo = True

    if args.test_sound:
        ok = Alarm(cfg).play("Test")
        time.sleep(0.2)
        raise SystemExit(0 if ok else 1)

    if cfg.demo:
        log.warning("Demo-Modus: keine API-Zugangsdaten konfiguriert, es werden Beispieldaten angezeigt.")
        sim = demo.Simulator(cfg)
        get_status = sim.status
    else:
        hub = Hub(cfg)
        loops = []
        if hub.src["nable"].enabled:
            loops.append(("nable", cfg.nable_metrics_s, lambda c=NableClient(cfg): hub.poll_nable(c)))
        if hub.src["ncentral"].enabled:
            loops.append(("ncentral", cfg.nc_interval_s, lambda c=NcentralClient(cfg): hub.poll_ncentral(c)))
        if hub.src["unifi"].enabled:
            loops.append(("unifi", cfg.unifi_interval_s, lambda c=UnifiClient(cfg): hub.poll_unifi(c)))
        hub.rebuild()
        for name, interval, fn in loops:
            threading.Thread(target=run_loop, args=(name, interval, fn, hub), daemon=True, name=name).start()
        get_status = lambda: hub.snapshot  # noqa: E731

    srv = ThreadingHTTPServer((cfg.bind, cfg.port), make_handler(get_status))
    log.info("Dashboard läuft auf http://%s:%d/", cfg.bind, cfg.port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
