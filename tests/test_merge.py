"""Deterministic window arithmetic. No web and no model."""

import pytest

from tests.conftest import END, INCIDENT_END, INCIDENT_START, START, iso


def _item(severity, start, end=None, quote="Actions degraded"):
    return {
        "severity": severity,
        "start": start,
        "end": 0 if end is None else end,
        "has_end": end is not None,
        "quote": quote,
    }


def _obs(ok, severity, start=0, end=0, has_end=False, quote=""):
    return {"ok": ok, "severity": severity, "start": start, "end": end, "has_end": has_end, "quote": quote}


def test_overlap_respects_the_skew_bound(mod):
    assert mod.overlaps(START + 10, INCIDENT_END, True, START, END, 300)
    assert not mod.overlaps(END + 301, END + 900, True, START, END, 300)
    assert not mod.overlaps(START - 5000, START - 301, True, START, END, 300)
    assert mod.overlaps(START - 100, 0, False, START, END, 300)


def test_parse_timestamp_requires_a_zone(mod):
    assert mod.parse_ts(iso(INCIDENT_START)) == INCIDENT_START
    assert mod.parse_ts("2026-11-15T22:05:00.000Z") == mod.parse_ts("2026-11-15T22:05:00Z")
    assert mod.parse_ts("2026-11-15T22:05:00") is None
    assert mod.parse_ts("not-a-time") is None


def test_unanimous_outage_and_operational(mod):
    outage = _obs(True, "outage", INCIDENT_START, INCIDENT_END, True, "Actions degraded")
    agreed = mod.merge([outage, dict(outage)], 2, 2, 300, False)
    assert agreed["verdict"] == "attested"
    assert agreed["severity"] == "outage"
    assert agreed["incident_start"] == INCIDENT_START

    healthy = mod.merge([_obs(True, "operational"), _obs(True, "operational")], 2, 2, 300, False)
    assert healthy["verdict"] == "attested"
    assert healthy["severity"] == "operational"
    assert healthy["incident_start"] == 0


def test_dissent_and_incomplete_and_clock_skew(mod):
    outage = _obs(True, "outage", INCIDENT_START, INCIDENT_END, True, "Actions degraded")
    healthy = _obs(True, "operational")
    clash = mod.merge([outage, healthy], 2, 2, 300, False)
    assert clash["verdict"] == "abstain" and clash["reason"] == "conflict"

    missing = mod.merge([outage, _obs(False, "unknown")], 2, 2, 300, False)
    assert missing["reason"] == "incomplete"

    late = _obs(True, "outage", INCIDENT_START + 400, INCIDENT_END, True, "Actions degraded")
    skewed = mod.merge([outage, late], 2, 2, 300, False)
    assert skewed["reason"] == "conflict-time"

    near = _obs(True, "outage", INCIDENT_START + 120, INCIDENT_END, True, "Actions degraded")
    close = mod.merge([outage, near], 2, 2, 300, False)
    assert close["verdict"] == "attested"
    assert close["incident_start"] == INCIDENT_START + 60


def test_strict_correction_requires_every_source(mod):
    outage = _obs(True, "outage", INCIDENT_START, INCIDENT_END, True, "Actions degraded")
    down = _obs(False, "unknown")
    ordinary = mod.merge([outage, outage, down], 2, 3, 300, False)
    assert ordinary["verdict"] == "attested"
    strict = mod.merge([outage, outage, down], 2, 3, 300, True)
    assert strict["reason"] == "not-unanimous"


def test_statuspage_empty_is_operational_and_garbage_is_not(mod):
    quiet = mod.parse_statuspage('{"incidents": []}', START, END, 300)
    assert quiet["ok"] is True and quiet["severity"] == "operational"
    body = (
        '{"incidents":[{"name":"Actions degraded","impact":"major",'
        f'"started_at":"{iso(INCIDENT_START)}","resolved_at":"{iso(INCIDENT_END)}"}}]}}'
    )
    hit = mod.parse_statuspage(body, START, END, 300)
    assert hit["severity"] == "outage"
    assert hit["quote"] == "Actions degraded"
    assert mod.parse_statuspage("<html>major outage</html>", START, END, 300)["ok"] is False
    assert mod.parse_statuspage('{"nope": 1}', START, END, 300)["ok"] is False


def test_incident_outside_the_window_does_not_count(mod):
    body = (
        '{"incidents":[{"name":"Old maintenance window","impact":"maintenance",'
        f'"started_at":"{iso(START - 10000)}","resolved_at":"{iso(START - 8000)}"}}]}}'
    )
    got = mod.parse_statuspage(body, START, END, 300)
    assert got["severity"] == "operational"


def test_page_silence_is_not_operational(mod):
    assert mod.ground_page("all systems operational", {"incidents": []}, START, END, 300)["ok"] is False
    page = f"Major outage started at {iso(INCIDENT_START)} and recovered at {iso(INCIDENT_END)}."
    grounded = mod.ground_page(page, {
        "incidents": [{
            "severity": "outage",
            "started_at": iso(INCIDENT_START),
            "resolved_at": iso(INCIDENT_END),
            "quote": f"Major outage started at {iso(INCIDENT_START)}",
        }]
    }, START, END, 300)
    assert grounded["ok"] is True and grounded["severity"] == "outage"
    invented = mod.ground_page(page, {
        "incidents": [{
            "severity": "outage",
            "started_at": iso(INCIDENT_START),
            "resolved_at": None,
            "quote": "This sentence was not on the page.",
        }]
    }, START, END, 300)
    assert invented["ok"] is False


def test_same_site_mirrors_are_rejected(mod):
    with pytest.raises(Exception, match="registrable"):
        mod._parse_sources([
            {"url": "https://www.githubstatus.com/api/v2/incidents.json", "kind": "statuspage"},
            {"url": "https://api.githubstatus.com/api/v2/incidents.json", "kind": "statuspage"},
        ])
    with pytest.raises(Exception, match="ip literals"):
        mod.check_url("https://10.0.0.8/status")


def test_maintenance_mixed_with_outage_on_one_page_is_unknown(mod):
    got = mod.classify_incidents([
        _item("maintenance", INCIDENT_START, INCIDENT_END, "Database maintenance"),
        _item("outage", INCIDENT_START, INCIDENT_END, "Actions degraded"),
    ], 300)
    assert got["ok"] is False
