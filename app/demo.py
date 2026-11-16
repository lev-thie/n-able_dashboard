"""Beispieldaten für den Demo-Modus (ohne API-Zugangsdaten).

Liefert dasselbe JSON-Format wie das echte Backend, damit Oberfläche und Kiosk-Setup
ohne Zugangsdaten getestet werden können. Alle Kundennamen sind erfunden.
"""
from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta, timezone


def _ago(minutes: float) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


SERVERS = [
    # name, rolle, kunde, cpu, ram, disk, laufzeit (tage), extras
    ("LIN-SQL01", "SQL Server", "Autohaus Lindner", 34, 62, 71, 41, {"svc": ["MSSQLSERVER", "SQLSERVERAGENT"], "svcCrit": True}),
    ("VOS-FS01", "Dateiserver", "Kanzlei Voss & Partner", 22, 95, 64, 112, {}),
    ("OTT-APP02", "ERP-Applikation", "Maschinenbau Ottens", 94, 81, 55, 18, {}),
    ("SEE-DC01", "Domain Controller", "Hotel Seeblick", None, None, None, None, {"offline": 42}),
    ("BRA-BKP01", "Backup-Server", "Logistik Brandt GmbH", 18, 48, 86, 63, {}),
    ("REI-TS01", "Terminalserver", "Praxis Dr. Reimers", 41, 82, 58, 9, {"svc": ["Spooler"]}),
    ("KRA-DC01", "Domain Controller", "Steuerbüro Kranz", 12, 44, 39, 36, {"reboot": True}),
    ("HOL-EX01", "Exchange", "Bäckerei Hollmann", 78, 70, 66, 22, {}),
    ("OTT-DC01", "Domain Controller", "Maschinenbau Ottens", 9, 38, 42, 18, {}),
    ("FAB-RDS01", "Terminalserver", "Immobilien Faber", 46, 64, 51, 5, {}),
    ("WEI-FS01", "Dateiserver", "Architekturbüro Weide", 15, 52, 68, 77, {}),
    ("SON-DC01", "Domain Controller", "Pflegedienst Sonnenhof", 7, 35, 33, 29, {}),
    ("ALB-DC01", "Domain Controller", "Schreinerei Albers", 11, 41, 47, 54, {}),
    ("WEI-DC01", "Domain Controller", "Architekturbüro Weide", 8, 39, 36, 77, {}),
    ("FAB-DC01", "Domain Controller", "Immobilien Faber", 10, 42, 40, 5, {}),
    ("HOL-DC01", "Domain Controller", "Bäckerei Hollmann", 6, 37, 45, 22, {}),
    ("BRA-DC01", "Domain Controller", "Logistik Brandt GmbH", 9, 40, 38, 63, {}),
    ("LIN-DC01", "Domain Controller", "Autohaus Lindner", 7, 36, 41, 41, {}),
]

SITES = [
    ("Hotel Seeblick", "UDM Pro", 0, 23, 0, "off", 0),
    ("Schreinerei Albers", "UCG Max", 6, 6, 19, "degraded", 93),
    ("Logistik Brandt GmbH", "UDM SE", 30, 31, 142, "ok", 100),
    ("Autohaus Lindner", "UDM Pro", 18, 18, 87, "ok", 100),
    ("Maschinenbau Ottens", "UDM Pro Max", 42, 42, 216, "ok", 100),
    ("Kanzlei Voss & Partner", "UDM SE", 9, 9, 34, "ok", 100),
    ("Praxis Dr. Reimers", "UCG Ultra", 5, 5, 22, "ok", 100),
    ("Steuerbüro Kranz", "UCG Ultra", 4, 4, 16, "ok", 100),
    ("Bäckerei Hollmann", "UDM Pro", 12, 12, 41, "ok", 100),
    ("Immobilien Faber", "UCG Max", 7, 7, 28, "ok", 100),
    ("Architekturbüro Weide", "UCG Ultra", 6, 6, 25, "ok", 100),
    ("Pflegedienst Sonnenhof", "UDM SE", 15, 15, 63, "ok", 99),
]


class Simulator:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.lock = threading.Lock()
        self.history = {"t": [], "cpu": [], "ram": []}
        self.offsets = {s[0]: 0.0 for s in SERVERS}
        cpu0, ram0 = self._avgs(jitter=False)
        for i in range(60):
            self.history["t"].append(_ago(60 - i))
            self.history["cpu"].append(round(cpu0 + random.uniform(-3, 3)))
            self.history["ram"].append(round(ram0 + random.uniform(-1, 1)))
        self.last = datetime.min.replace(tzinfo=timezone.utc)

    def _avgs(self, jitter=True):
        vals = [(s[3], s[4]) for s in SERVERS if s[3] is not None]
        return (sum(v[0] for v in vals) / len(vals), sum(v[1] for v in vals) / len(vals))

    def status(self) -> dict:
        with self.lock:
            now = datetime.now(timezone.utc)
            step = (now - self.last).total_seconds() >= 10
            if step:
                self.last = now
            servers = []
            for name, role, cust, cpu, ram, disk, days, ex in SERVERS:
                if cpu is not None and step:
                    self.offsets[name] = max(-6, min(6, self.offsets[name] * 0.6 + random.uniform(-3, 3)))
                c = None if cpu is None else max(1, min(99, round(cpu + self.offsets[name])))
                r = None if ram is None else max(1, min(99, round(ram + self.offsets[name] / 4)))
                online = "offline" not in ex
                s = {
                    "id": name, "name": name, "role": role, "customer": cust, "online": online,
                    "offlineSince": _ago(ex["offline"]) if not online else None,
                    "cpu": c, "ram": r, "disk": disk, "diskDrive": "D:" if name == "BRA-BKP01" else "C:",
                    "uptimeSec": days * 86400 if days else None,
                    "rebootRequired": bool(ex.get("reboot")),
                    "stoppedServices": ex.get("svc", []), "stoppedCritical": bool(ex.get("svcCrit")),
                }
                if not online:
                    s["state"] = "off"
                elif (c or 0) >= 90 or (r or 0) >= 90 or s["stoppedCritical"]:
                    s["state"] = "crit"
                elif (c or 0) >= 75 or (r or 0) >= 80 or (disk or 0) >= 85 or s["stoppedServices"] or s["rebootRequired"]:
                    s["state"] = "warn"
                else:
                    s["state"] = "ok"
                servers.append(s)
            order = {"off": 0, "crit": 0, "warn": 1, "ok": 2}
            servers.sort(key=lambda s: (order[s["state"]], -max(s["cpu"] or 0, s["ram"] or 0)))

            sites = [{"id": n, "name": n, "gateway": g, "devicesOnline": on, "devicesTotal": tot, "clients": cl,
                      "wan": wan, "wanUptime": up, "isp": "", "criticalNotifications": 0}
                     for n, g, on, tot, cl, wan, up in SITES]

            issues = [
                {"key": "d1", "sev": "crit", "title": "Dienst gestoppt: MSSQLSERVER", "where": "LIN-SQL01 · Autohaus Lindner", "source": "N-central", "since": _ago(12), "service": True},
                {"key": "d2", "sev": "crit", "title": "Dienst gestoppt: SQLSERVERAGENT", "where": "LIN-SQL01 · Autohaus Lindner", "source": "N-central", "since": _ago(12), "service": True},
                {"key": "d3", "sev": "crit", "title": "CPU-Auslastung über 90 %", "where": "OTT-APP02 · Maschinenbau Ottens", "source": "N-able", "since": _ago(16)},
                {"key": "d4", "sev": "crit", "title": "RAM-Auslastung 95 %", "where": "VOS-FS01 · Kanzlei Voss & Partner", "source": "N-able", "since": _ago(28)},
                {"key": "d5", "sev": "crit", "title": "Standort offline (Gateway)", "where": "UDM Pro · Hotel Seeblick", "source": "UniFi", "since": _ago(42)},
                {"key": "d6", "sev": "crit", "title": "Agent offline", "where": "SEE-DC01 · Hotel Seeblick", "source": "N-able", "since": _ago(42)},
                {"key": "d7", "sev": "warn", "title": "WAN-Störung (93 % Uptime)", "where": "UCG Max · Schreinerei Albers", "source": "UniFi", "since": _ago(35)},
                {"key": "d8", "sev": "warn", "title": "Dienst gestoppt: Spooler", "where": "REI-TS01 · Praxis Dr. Reimers", "source": "N-central", "since": _ago(64), "service": True},
                {"key": "d9", "sev": "warn", "title": "Datenträger D: 86 % belegt", "where": "BRA-BKP01 · Logistik Brandt GmbH", "source": "N-able", "since": _ago(190)},
                {"key": "d10", "sev": "warn", "title": "Neustart ausstehend", "where": "KRA-DC01 · Steuerbüro Kranz", "source": "N-able", "since": _ago(2900)},
                {"key": "d11", "sev": "warn", "title": "1 Gerät offline", "where": "Logistik Brandt GmbH", "source": "UniFi", "since": _ago(75)},
            ]

            live = [s for s in servers if s["online"]]
            cpu = round(sum(s["cpu"] for s in live) / len(live))
            ram = round(sum(s["ram"] for s in live) / len(live))
            if step:
                h = self.history
                h["t"].append(now.isoformat(timespec="seconds").replace("+00:00", "Z"))
                h["cpu"].append(cpu); h["ram"].append(ram)
                for k in h:
                    del h[k][:-120]
            at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
            src = {"enabled": True, "ok": True, "at": at, "error": None}
            return {
                "generatedAt": at, "demo": True, "deviceFilter": self.cfg.nc_filter,
                "display": {"start": self.cfg.display_start, "end": self.cfg.display_end,
                            "days": self.cfg.display_days, "timezone": str(self.cfg.tz),
                            "scale": self.cfg.ui_scale},
                "sources": {"nable": src, "ncentral": src, "unifi": src},
                "servers": servers, "sites": sites, "issues": issues,
                "summary": {"serversTotal": len(servers), "serversOnline": len(live), "cpuAvg": cpu, "ramAvg": ram,
                            "stoppedServices": sum(len(s["stoppedServices"]) for s in servers),
                            "serversWithStoppedServices": sum(1 for s in servers if s["stoppedServices"]),
                            "sitesTotal": len(sites), "sitesOnline": sum(1 for s in sites if s["wan"] != "off"),
                            "clients": sum(s["clients"] for s in sites)},
                "history": self.history, "lastAlarm": None,
            }
