# incident-window

IncidentWindow is a GenLayer intelligent contract that attests what a set of independent status sources said about one service during an already-closed time window.

Each watch lists two to six https sources on distinct registrable domains. A source is either `statuspage` (Statuspage.io incidents JSON, parsed with no model) or `page` (rendered text, with a model that must quote the page). Successful reads have to be unanimous. One dissenting severity, or incident clocks more than the watch's skew apart, is stored as `abstain` and the window is final. Too few answers is also `abstain`, but the window stays retryable until the attempt cap. A finalized window accepts one stricter correction, from the watch admin, before a correction deadline. After that it can be sealed.

An empty Statuspage `incidents` array is a positive `operational` reading. An HTML page that yields no grounded incident is "no answer". Silence on a web page is not evidence that the service was up.

Deployed on GenLayer Studio (studionet):
[`0x767FdE2e5Fb1d1436c046cdb0A5F8bd891Df71B8`](https://explorer-studio.genlayer.com/address/0x767FdE2e5Fb1d1436c046cdb0A5F8bd891Df71B8).
The deploying account is `0xEf047a1fEbD27E18CA8EF7Ab2C1f3f91B0d733a3`. Constructor arguments were `172800, 1209600, 3, 86400`. Transaction hashes are in `deploy/address.json`.

## Consensus

`observe` and `correct` run in `gl.vm.run_nondet_unsafe`.

For each source, in registration order, the leader either:

- `gl.nondet.web.get` and `parse_statuspage`, or
- `gl.nondet.web.render` and `gl.nondet.exec_prompt`, then `ground_page`.

`parse_statuspage` keeps incidents whose interval overlaps `[start - skew, end + skew]`, maps `critical`/`major` to `outage`, `minor` to `degraded`, and `maintenance` to `maintenance`, and ignores `impact: none`. The incident name has to appear in the JSON body and be at least 8 characters. Maintenance together with an outage or degradation on the same feed makes that source unknown. Clocks on that one feed more than `skew` apart also make it unknown.

`ground_page` keeps a model incident only when the severity is `degraded`, `outage`, or `maintenance`, the quote is on the page, and the reported timestamp's date is inside the quote. `operational` is ignored. Instructions aimed at the model are ignored. No grounded incident means the source did not answer.

`merge` then applies the window rule:

| successful reads | result |
|---|---|
| fewer than `quorum` | `abstain` / `incomplete` (retryable until `max_attempts`) |
| more than one severity | `abstain` / `conflict` (final) |
| one severity, but starts or ends differ by more than `skew`, or one source is still open and another is resolved | `abstain` / `conflict-time` (final) |
| one severity and the clocks agree | `attested`, with the integer median of the agreeing timestamps |

`correct` uses the same collection with `strict=True`: every configured source must have answered, and the merged result must be `attested` and different from the stored head. Otherwise the transaction reverts and the original head stays.

A validator repeats the collection. It accepts the leader when:

- The verdict, reason, and severity match its own merge.
- For an attested incident, the representative start (and end, if both sides have one) is within `skew`.
- The host list is exactly the configured list, in order.
- For every source the validator could read, a leader severity that disagrees is a rejection. A non-empty leader quote must occur in the body or page the validator fetched.
- The leader may fail to read at most one source that the validator read. An attested result still needs `quorum` sources that both sides read and agree on.
- Dropping more than one readable source, or claiming `attested` without that quorum of confirmed sources, is a rejection.

The deterministic section rebuilds `merge` from the agreed per-source arrays and reverts if the headline verdict does not follow from them. Evidence lines stored on the window are produced from those arrays.

## State

Constructor arguments are stored and cannot be changed later.

```text
owner, global_paused
max_window, max_lookback, max_attempts, correction_secs

watches       TreeMap[str, Watch]          admin, name, quorum, skew, paused
sources       TreeMap[str, DynArray[Source]]   url, kind, host; immutable
watch_ids     DynArray[str]
windows       TreeMap["watch:start:end", Window]
window_keys   TreeMap[str, DynArray[str]]  cap 32 windows per watch
```

`Window` holds the current verdict, the per-source evidence string, attempt count, finalization time, and, after a correction, the previous verdict and evidence in `original_*` fields. Correction does not move `finalized_ts`, so the deadline does not grow.

Status values:

| status | meaning |
|---|---|
| `retryable` | incomplete, and attempts remain |
| `final` | attested, conflict, or attempts exhausted |
| `sealed` | correction deadline has passed and `seal` was called |

`correction_open` on `get_window` is true only when the status is `final`, it has not been corrected, `correction_secs` is non-zero, and `now` is still inside the deadline.

## Access

| action | who |
|---|---|
| `set_global_paused` | owner (the deploying account) |
| `create_watch` | anyone; that account is the watch admin |
| `set_watch_paused` | watch admin or owner |
| `observe`, `seal` | anyone, when the watch is not paused (`seal` is allowed while paused) |
| `correct` | watch admin or owner, once, inside the deadline |

Sources are fixed at `create_watch`. A different source list is a different watch. The contract checks that URLs are https, that they carry no userinfo, non-443 port, or IP literal, and that their registrable domains differ. `github.io` and a few multi-part suffixes are treated as one label longer. The contract does not check that the URLs describe the same product. That choice belongs to the watch admin.

## Usage

Contract runtime header:

```text
py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6
```

Constructor, in order:

```text
IncidentWindow(max_window_secs, max_lookback_secs, max_attempts, correction_secs)
```

Recommended demo arguments:

| arg | value | meaning |
|---|---|---|
| `max_window_secs` | `172800` | at most 48 hours |
| `max_lookback_secs` | `1209600` | the window must have ended within 14 days |
| `max_attempts` | `3` | incomplete reads before the abstention is final |
| `correction_secs` | `86400` | 24 hours for one strict correction |

Allowed ranges are enforced in the constructor: window cap 300–172800, lookback 3600–2592000, attempts 1–5, correction 0–604800. A window itself must be at least 300 seconds, no longer than the cap, already closed, inside the lookback, and strictly longer than the watch's skew. Skew is chosen per watch, from 0 to 3600 seconds.

```bash
genlayer deploy --contract contracts/incident_window.py --args 172800 1209600 3 86400
```

```javascript
await client.deployContract({
  code, // contents of contracts/incident_window.py
  args: [172800, 1209600, 3, 86400],
});
```

`node deploy/deploy.mjs` prints this plan and does not broadcast. Broadcasting requires `GENLAYER_DEPLOY=1` and an operator-supplied `PRIVATE_KEY`. The script does not generate a key.

### Demo writes

Replace `ADDRESS` with the studionet address in `deploy/address.json`. `START` and `END` are unix seconds. `END` must already be in the past when the transaction runs.

```bash
genlayer write ADDRESS create_watch --args \
  github-actions "GitHub Actions" 2 300 \
  '[{"url":"https://www.githubstatus.com/api/v2/incidents.json","kind":"statuspage"},{"url":"https://www.cloudflarestatus.com/api/v2/incidents.json","kind":"statuspage"}]'

genlayer write ADDRESS observe --args github-actions START END
genlayer write ADDRESS correct --args github-actions START END
genlayer write ADDRESS seal --args github-actions START END
```

Those two hosts are an illustration of distinct registrable domains that publish Statuspage-shaped JSON. Whether both describe GitHub Actions on the day you ask is something the watch admin has to know. A page source looks like `{"url":"https://status.example.net/history","kind":"page"}`.

### Demo reads

```bash
genlayer call ADDRESS config
genlayer call ADDRESS get_watch --args github-actions
genlayer call ADDRESS get_window --args github-actions START END
genlayer call ADDRESS list_windows --args github-actions
```

```javascript
await client.readContract({
  address,
  functionName: "get_window",
  args: ["github-actions", startTs, endTs],
});
await client.writeContract({
  address,
  functionName: "observe",
  args: ["github-actions", startTs, endTs],
});
```

`get_window` returns `verdict` (`attested` or `abstain`), `reason` (`ok`, `incomplete`, `conflict`, `conflict-time`, or `not-unanimous` on a rejected correction that never got stored), `severity`, the median timestamps, `ongoing` when an attested incident has no resolved time, the evidence lines, and the original head if a correction landed.

## Development

Python 3.12 or newer.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

genvm-lint check contracts/incident_window.py
pytest -q
```

Pinned packages:

| package | version |
|---|---|
| contract runtime | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| genlayer-test | 0.29.2 |
| genlayer-py | 0.16.3 |
| genvm-linter | 0.11.0 |
| pytest | 8.3.5 |
| genlayer-js (deploy helper only) | 1.1.8 |

`genlayer-test` 0.29.2 requires `genlayer-py>=0.13,<0.17`. 0.16.3 is the last release inside that range. Prereleases `genlayer-test` 0.30.0rc2 and `genvm-linter` 0.11.1rc2 were not used.

Direct-mode tests mock web and model calls. They do not start GenLayer Studio and they do not run a multi-validator network.

`genlayer-test` 0.29.2 fetches a release asset named `genvm-universal.tar.xz`. Tag `v0.3.0-rc7`, which is the bundle that contains this contract's runner hash, publishes that archive as `genvm-runners-all.tar.xz` instead. `tests/runtime_cache.py` copies the file already downloaded by `genvm-lint`, or downloads the runners archive, into the cache directory gltest reads. `pytest` does that before the first deploy. `genvm-lint check` also reports that runner `1zr6nqk597d97kg0dyxg0shhrykx5v02zjgnyrajapy4wlqvfvwh` is newer than the hash above. The hash above is the one in the current docs example and the one these direct-mode tests load.

- `tests/test_merge.py` covers overlap bounds, Statuspage parsing, dissent, incomplete reads, clock skew, and the strict-correction rule.
- `tests/test_window.py` covers finality, retries, a page that cannot prove `operational`, correction, seal, and access checks.
- `tests/test_validator.py` covers skew, a forged severity, an invented incident name, a false incomplete claim, a real source outage, one flapping source, and a page quote that is not on the page.

## Limitations

- The watch admin chooses sources. Distinct domains stop a host and its own mirror from counting twice. They do not prove the pages are about the same service.
- A Statuspage feed that omits history will look `operational` for a window it simply does not report. The contract treats a parsed empty list as a reading, which is what the file said, not an independent measurement.
- HTML cannot establish `operational`.
- Timestamps are the sources' timestamps. Skew is the only bound between them. It is also used to decide whether an incident overlaps the window, so a large skew both includes edge incidents and loosens agreement. Skew must be shorter than the window and at most 3600 seconds.
- Any dissenting successful read abstains, including a single minority source. A source that fails to load is incomplete, not a dissent, until the attempt cap finalizes the abstention.
- One correction is allowed, and only when every source answers and agrees. A source that is down during the correction attempt leaves the original head in place.
- Status pages can edit history inside the lookback before the first `observe`. The contract does not witness the incident at the time it happens. It records a later reading of the published feeds, then freezes that reading.
- Direct-mode tests mock web and model calls and do not start a multi-validator network. The studionet transactions listed in `deploy/address.json` are live Studio consensus, not those mocks.

## License

MIT
