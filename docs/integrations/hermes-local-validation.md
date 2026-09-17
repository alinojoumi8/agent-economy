# Local native Hermes validation

This is local integration evidence, not public-HTTPS connector certification.
The regular `agenteconomy` profile and messaging gateway stay separate from the
disposable profiles used by this rehearsal.

## Repeat the bounded rehearsal

With `DEEPSEEK_API_KEY` already supplied in the environment:

```powershell
.\.venv\Scripts\python.exe scripts/native_hermes_rehearsal.py --hermes-python <installed-hermes-python> --output .tmp/native-hermes-fresh --approve-live-inference
```

The command requires a fresh ignored directory and explicit live approval.
It creates two local test Passports using synthetic consent, uses the installed
Hermes executable and real DeepSeek calls for three rounds each, and verifies
canonical submissions, execution and balanced accounting. Native sessions are
bounded to ten turns and 120 seconds each (150-second subprocess timeout).
These bounds are not a dollar-denominated provider cap. The app's other agents
are scripted. Credential expiry is injected only into the disposable world and
token cache; refresh and rotation occur over the ordinary HTTP OAuth protocol.
The final offline tick checks Semantics 14 attendance. This does not modify or
upgrade the earlier Semantics 11 recording.

`receipt.json` is the review artifact. The neighboring profiles, databases,
prompts and logs are private and must not be uploaded as a bundle. Setup uses
synthetic local consent; the separate Chromium test proves real browser approval
and denial. Neither test impersonates independent hosted certification.

## Installed-client expiry repair

The installed Hermes revision was `a84a2223f82c3d9906fd4a9d778a188774e7a08e`.
An expired persisted token is rebased to `expires_in=0`. The SDK computes its
deadline as the current time and accepts `now <= deadline`. On a coarse clock,
the first request can therefore send an expired token, receive a 401 and enter
browser authorization instead of attempting refresh.

The [preserved patch](hermes-expired-cache.patch) makes the existing Hermes
provider mark a nonpositive lifetime strictly in the past. It includes a
regression with a fixed clock that requires the first request to target the
refresh endpoint. It changes no Agent Economy token lifetime or authorization
policy. The installed source was patched locally; an update may replace it.
Review applicability before reapplying to a different Hermes version. Do not
patch the SDK under `site-packages` or disable OAuth to work around this failure.

The focused installed-client checks passed:

```text
python -m pytest -q tests/tools/test_mcp_expired_cache.py tests/tools/test_mcp_oauth_manager.py
17 passed
```

The first rehearsal retained its failure after round one: no second-round
submission was recorded for citizen zero after forced expiry. That failed
attempt is not counted as a completed rehearsal.

## Completed September 17 rehearsal

The third isolated attempt passed: two citizens (actors 45 and 46), three native
Hermes sessions each, six accepted and successfully executed actions, five
committed world ticks and a balanced ledger. Four purchases cost 257/244 cents
per unit on their respective days; two deliberate no-ops counted as submitted.
Both absent citizens recorded `missed / offline / safe_do_nothing_v1` at tick 5.
Native refresh succeeded after injected access expiry and reuse of the rotated
refresh token was rejected. No replacement authorization browser was required.

Hermes session records show 31 model API calls and $0.013314354 estimated cost
for the successful attempt. Actual billed cost was unavailable; auxiliary calls
may be outside session accounting. Across all three attempts, session estimates
totaled $0.028862556. The app world itself used no paid native-provider route.
The second attempt proved refresh but stopped because the harness counted a
rejected submission toward its exactly-one-accepted assertion; that assertion
was corrected without deleting the failure or rejection evidence.

The five-tick recording also replays exactly after fixing an arrival-order bug:
replay previously copied a first-day missed attendance row before NIGHT created
its actor, violating the actor foreign key. Pre-NIGHT replay now restores inputs
only; MORNING restores attendance after arrival, matching live execution.
Replay `replay-native-hermes-rehearsal-ef91ab88ce` has no canonical differences
and makes no provider calls. Submitted and missed new-arrival regressions cover
this order without altering stored source runs or historical semantics.
