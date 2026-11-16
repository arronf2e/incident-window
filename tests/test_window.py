"""Window lifecycle against mocked status sources."""

import json

import pytest

from tests.conftest import (
    CONTRACT,
    END,
    GITHUB,
    INCIDENT_END,
    INCIDENT_START,
    NOW,
    PAGE,
    START,
    empty_status,
    iso,
    statuspage,
    warp,
)


def _mock_pair(vm, left, right, left_status=200, right_status=200):
    vm.mock_web(r".*githubstatus\.com.*", {"status": left_status, "body": left})
    vm.mock_web(r".*cloudflarestatus\.com.*", {"status": right_status, "body": right})


def _outage():
    return statuspage("Actions degraded", "major", INCIDENT_START, INCIDENT_END)


def test_unanimous_outage_finalizes(window, direct_vm):
    _mock_pair(direct_vm, _outage(), _outage())
    got = window.observe("github-actions", START, END)
    assert got["verdict"] == "attested"
    assert got["severity"] == "outage"
    assert got["status"] == "final"
    assert got["has_end"] is True
    assert "githubstatus.com" in got["evidence"][0]
    stored = window.get_window("github-actions", START, END)
    assert stored["correction_open"] is True
    with direct_vm.expect_revert("not retryable"):
        window.observe("github-actions", START, END)


def test_conflict_finalizes_and_incomplete_retries(window, direct_vm):
    _mock_pair(direct_vm, _outage(), empty_status())
    clash = window.observe("github-actions", START, END)
    assert clash["verdict"] == "abstain"
    assert clash["reason"] == "conflict"
    assert clash["status"] == "final"

    direct_vm.clear_mocks()
    _mock_pair(direct_vm, _outage(), "", left_status=200, right_status=503)
    # A second window, so the finalized one above is left untouched.
    missing = window.observe("github-actions", START - 7200, END - 7200)
    assert missing["reason"] == "incomplete"
    assert missing["status"] == "retryable"
    direct_vm.clear_mocks()
    _mock_pair(direct_vm, _outage(), _outage())
    resolved = window.observe("github-actions", START - 7200, END - 7200)
    assert resolved["verdict"] == "attested"
    assert resolved["attempts"] == 2


def test_incomplete_becomes_final_at_the_attempt_cap(window, direct_vm):
    _mock_pair(direct_vm, "", "", 503, 503)
    for expected in (1, 2):
        got = window.observe("github-actions", START, END)
        assert got["status"] == "retryable"
        assert got["attempts"] == expected
    last = window.observe("github-actions", START, END)
    assert last["status"] == "final"
    assert last["verdict"] == "abstain"
    assert last["attempts"] == 3


def test_operational_when_both_feeds_are_quiet(window, direct_vm):
    _mock_pair(direct_vm, empty_status(), empty_status())
    got = window.observe("github-actions", START, END)
    assert got["severity"] == "operational"
    assert got["verdict"] == "attested"


def test_page_silence_does_not_second_an_operational_vote(window, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    window.create_watch(
        "mixed",
        "GitHub Actions, page plus feed",
        2,
        300,
        [
            {"url": GITHUB, "kind": "statuspage"},
            {"url": PAGE, "kind": "page"},
        ],
    )
    direct_vm.mock_web(r".*githubstatus\.com.*", {"status": 200, "body": empty_status()})
    direct_vm.mock_web(r".*status\.example\.net.*", {"status": 200, "body": "All systems operational today."})
    direct_vm.mock_llm(r".*INCIDENT_WINDOW_EXTRACT.*", json.dumps({"incidents": []}))
    got = window.observe("mixed", START, END)
    assert got["reason"] == "incomplete"


def test_grounded_page_can_agree_with_the_feed(window, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    window.create_watch(
        "mixed",
        "GitHub Actions, page plus feed",
        2,
        300,
        [
            {"url": GITHUB, "kind": "statuspage"},
            {"url": PAGE, "kind": "page"},
        ],
    )
    page = f"Major outage started at {iso(INCIDENT_START)} for Actions."
    direct_vm.mock_web(
        r".*githubstatus\.com.*",
        {"status": 200, "body": statuspage("Actions degraded", "major", INCIDENT_START, None)},
    )
    direct_vm.mock_web(r".*status\.example\.net.*", {"status": 200, "body": page})
    direct_vm.mock_llm(r".*INCIDENT_WINDOW_EXTRACT.*", json.dumps({
        "incidents": [{
            "severity": "outage",
            "started_at": iso(INCIDENT_START),
            "resolved_at": None,
            "quote": f"Major outage started at {iso(INCIDENT_START)}",
        }]
    }))
    got = window.observe("mixed", START, END)
    assert got["verdict"] == "attested"
    assert got["severity"] == "outage"
    assert got["ongoing"] is True


def test_correction_replaces_the_head_and_keeps_the_original(window, direct_vm, direct_alice, direct_bob):
    _mock_pair(direct_vm, _outage(), _outage())
    first = window.observe("github-actions", START, END)
    finalized = first["finalized_ts"]
    warp(direct_vm, "2026-11-16T01:00:00Z")
    direct_vm.clear_mocks()
    _mock_pair(direct_vm, empty_status(), empty_status())
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("not the watch admin"):
            window.correct("github-actions", START, END)
    direct_vm.sender = direct_alice
    corrected = window.correct("github-actions", START, END)
    assert corrected["verdict"] == "attested"
    assert corrected["severity"] == "operational"
    assert corrected["corrected"] is True
    assert corrected["finalized_ts"] == finalized
    stored = window.get_window("github-actions", START, END)
    assert stored["original_verdict"] == "attested"
    assert stored["original_severity"] == "outage"
    with direct_vm.expect_revert("not open for correction"):
        window.correct("github-actions", START, END)


def test_correction_rejects_a_partial_reread(window, direct_vm):
    _mock_pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    direct_vm.clear_mocks()
    _mock_pair(direct_vm, empty_status(), "", right_status=503)
    with direct_vm.expect_revert("not unanimous"):
        window.correct("github-actions", START, END)
    assert window.get_window("github-actions", START, END)["severity"] == "outage"


def test_seal_after_the_correction_deadline(window, direct_vm):
    _mock_pair(direct_vm, _outage(), _outage())
    window.observe("github-actions", START, END)
    with direct_vm.expect_revert("still open"):
        window.seal("github-actions", START, END)
    warp(direct_vm, "2026-11-17T00:00:01Z")
    with direct_vm.expect_revert("closed"):
        window.correct("github-actions", START, END)
    window.seal("github-actions", START, END)
    assert window.get_window("github-actions", START, END)["status"] == "sealed"
    assert window.get_window("github-actions", START, END)["correction_open"] is False


def test_bounds_and_source_rules(window, direct_vm):
    with direct_vm.expect_revert("still open"):
        window.observe("github-actions", NOW - 100, NOW + 3600)
    with direct_vm.expect_revert("lookback"):
        window.observe("github-actions", NOW - 2000000, NOW - 1996400)
    with pytest.raises(Exception, match="registrable"):
        window.create_watch(
            "mirrors",
            "same site twice",
            2,
            60,
            [
                {"url": GITHUB, "kind": "statuspage"},
                {"url": "https://api.githubstatus.com/api/v2/incidents.json", "kind": "statuspage"},
            ],
        )
    window.set_watch_paused("github-actions", True)
    with direct_vm.expect_revert("watch is paused"):
        window.observe("github-actions", START, END)


def test_constructor_rejects_a_short_window(direct_deploy):
    with pytest.raises(Exception, match="max_window_secs"):
        direct_deploy(CONTRACT, 10, 1209600, 3, 86400)
