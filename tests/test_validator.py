"""Validator half of an incident observation."""

import json

from tests.conftest import (
    END,
    GITHUB,
    INCIDENT_END,
    INCIDENT_START,
    PAGE,
    START,
    empty_status,
    iso,
    statuspage,
)


def _pair(vm, left, right, left_status=200, right_status=200):
    vm.mock_web(r".*githubstatus\.com.*", {"status": left_status, "body": left})
    vm.mock_web(r".*cloudflarestatus\.com.*", {"status": right_status, "body": right})


def _outage(start=INCIDENT_START, end=INCIDENT_END):
    return statuspage("Actions degraded", "major", start, end)


def test_validator_agrees_inside_the_skew(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    direct_vm.clear_mocks()
    _pair(direct_vm, _outage(INCIDENT_START + 120), _outage(INCIDENT_START + 120))
    assert direct_vm.run_validator() is True


def test_validator_rejects_a_clock_outside_the_skew(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    direct_vm.clear_mocks()
    _pair(direct_vm, _outage(INCIDENT_START + 600), _outage(INCIDENT_START + 600))
    assert direct_vm.run_validator() is False


def test_validator_rejects_a_forged_severity(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    forged = {
        "verdict": "attested",
        "reason": "ok",
        "severity": "operational",
        "incident_start": 0,
        "incident_end": 0,
        "has_end": False,
        "hosts": ["www.githubstatus.com", "www.cloudflarestatus.com"],
        "ok": [True, True],
        "severities": ["operational", "operational"],
        "starts": [0, 0],
        "ends": [0, 0],
        "has_ends": [False, False],
        "quotes": ["", ""],
    }
    assert direct_vm.run_validator(leader_result=forged) is False


def test_validator_rejects_an_invented_incident_name(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    invented = {
        "verdict": "attested",
        "reason": "ok",
        "severity": "outage",
        "incident_start": INCIDENT_START,
        "incident_end": INCIDENT_END,
        "has_end": True,
        "hosts": ["www.githubstatus.com", "www.cloudflarestatus.com"],
        "ok": [True, True],
        "severities": ["outage", "outage"],
        "starts": [INCIDENT_START, INCIDENT_START],
        "ends": [INCIDENT_END, INCIDENT_END],
        "has_ends": [True, True],
        "quotes": ["Invented incident name", "Actions degraded"],
    }
    assert direct_vm.run_validator(leader_result=invented) is False


def test_validator_rejects_a_false_incomplete(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    claimed = {
        "verdict": "abstain",
        "reason": "incomplete",
        "severity": "none",
        "incident_start": 0,
        "incident_end": 0,
        "has_end": False,
        "hosts": ["www.githubstatus.com", "www.cloudflarestatus.com"],
        "ok": [False, False],
        "severities": ["unknown", "unknown"],
        "starts": [0, 0],
        "ends": [0, 0],
        "has_ends": [False, False],
        "quotes": ["", ""],
    }
    assert direct_vm.run_validator(leader_result=claimed) is False


def test_validator_confirms_a_real_outage_of_sources(window, direct_vm):
    _pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    direct_vm.clear_mocks()
    _pair(direct_vm, "", "", 503, 503)
    assert direct_vm.run_validator(leader_result={
        "verdict": "abstain",
        "reason": "incomplete",
        "severity": "none",
        "incident_start": 0,
        "incident_end": 0,
        "has_end": False,
        "hosts": ["www.githubstatus.com", "www.cloudflarestatus.com"],
        "ok": [False, False],
        "severities": ["unknown", "unknown"],
        "starts": [0, 0],
        "ends": [0, 0],
        "has_ends": [False, False],
        "quotes": ["", ""],
    }) is True


def test_validator_tolerates_one_flapping_source(window, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    window.create_watch(
        "three",
        "three feeds",
        2,
        300,
        [
            {"url": GITHUB, "kind": "statuspage"},
            {"url": "https://www.cloudflarestatus.com/api/v2/incidents.json", "kind": "statuspage"},
            {"url": "https://status.atlassian.com/api/v2/incidents.json", "kind": "statuspage"},
        ],
    )
    body = _outage()
    direct_vm.mock_web(r".*githubstatus\.com.*", {"status": 200, "body": body})
    direct_vm.mock_web(r".*cloudflarestatus\.com.*", {"status": 200, "body": body})
    direct_vm.mock_web(r".*atlassian\.com.*", {"status": 200, "body": body})
    window.observe("three", START, END)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*githubstatus\.com.*", {"status": 200, "body": body})
    direct_vm.mock_web(r".*cloudflarestatus\.com.*", {"status": 200, "body": body})
    direct_vm.mock_web(r".*atlassian\.com.*", {"status": 503, "body": ""})
    assert direct_vm.run_validator() is True


def test_validator_rejects_a_page_quote_that_is_not_there(window, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    window.create_watch(
        "mixed",
        "feed plus page",
        2,
        300,
        [
            {"url": GITHUB, "kind": "statuspage"},
            {"url": PAGE, "kind": "page"},
        ],
    )
    page = f"Major outage started at {iso(INCIDENT_START)} for Actions."
    answer = json.dumps({
        "incidents": [{
            "severity": "outage",
            "started_at": iso(INCIDENT_START),
            "resolved_at": None,
            "quote": f"Major outage started at {iso(INCIDENT_START)}",
        }]
    })
    direct_vm.mock_web(
        r".*githubstatus\.com.*",
        {"status": 200, "body": statuspage("Actions degraded", "major", INCIDENT_START, None)},
    )
    direct_vm.mock_web(r".*status\.example\.net.*", {"status": 200, "body": page})
    direct_vm.mock_llm(r".*INCIDENT_WINDOW_EXTRACT.*", answer)
    window.observe("mixed", START, END)
    forged = {
        "verdict": "attested",
        "reason": "ok",
        "severity": "outage",
        "incident_start": INCIDENT_START,
        "incident_end": 0,
        "has_end": False,
        "hosts": ["www.githubstatus.com", "status.example.net"],
        "ok": [True, True],
        "severities": ["outage", "outage"],
        "starts": [INCIDENT_START, INCIDENT_START],
        "ends": [INCIDENT_END, 0],
        "has_ends": [True, False],
        "quotes": ["Actions degraded", "A quote the page never contained"],
    }
    assert direct_vm.run_validator(leader_result=forged) is False
