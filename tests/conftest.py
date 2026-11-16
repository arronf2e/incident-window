import json
import sys
from datetime import datetime, timezone

import pytest

from tests.runtime_cache import seed

seed()

CONTRACT = "contracts/incident_window.py"

NOW = int(datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc).timestamp())
START = NOW - 7200
END = NOW - 3600
INCIDENT_START = START + 300
INCIDENT_END = START + 2400

GITHUB = "https://www.githubstatus.com/api/v2/incidents.json"
CLOUDFLARE = "https://www.cloudflarestatus.com/api/v2/incidents.json"
ATLASSIAN = "https://status.atlassian.com/api/v2/incidents.json"
PAGE = "https://status.example.net/history"


def warp(vm, ts: str) -> None:
    """Keep gl.message_raw['datetime'] aligned with the direct-mode clock."""
    vm.warp(ts)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = ts


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def statuspage(name, impact, start, end):
    return json.dumps({
        "incidents": [{
            "name": name,
            "status": "resolved" if end else "investigating",
            "impact": impact,
            "started_at": iso(start) if start else None,
            "created_at": iso(start) if start else None,
            "resolved_at": iso(end) if end else None,
        }]
    })


def empty_status():
    return json.dumps({"incidents": []})


def load_module():
    for module in sys.modules.values():
        if getattr(module, "IncidentWindow", None) is not None and hasattr(module, "merge"):
            return module
    raise RuntimeError("contract module not found")


@pytest.fixture
def mod(direct_deploy):
    direct_deploy(CONTRACT, 172800, 1209600, 3, 86400)
    return load_module()


@pytest.fixture
def window(direct_vm, direct_deploy, direct_alice):
    direct_vm.check_pickling = True
    direct_vm.sender = direct_alice
    contract = direct_deploy(CONTRACT, 172800, 1209600, 3, 86400)
    warp(direct_vm, "2026-11-16T00:00:00Z")
    contract.create_watch(
        "github-actions",
        "GitHub Actions",
        2,
        300,
        [
            {"url": GITHUB, "kind": "statuspage"},
            {"url": CLOUDFLARE, "kind": "statuspage"},
        ],
    )
    return contract
