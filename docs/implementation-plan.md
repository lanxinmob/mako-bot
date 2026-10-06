# Mako group participation implementation

> 2026-09-08: PAUSED by the user's newer instruction. Complete developer-approved
> structural refactoring first; see `refactor/plan.md` and `../AGENTS.md`.
> Existing implementation is unfinished draft work, not a verified baseline.
> User accepted 600-second / 60-event memory-only group context. Bird content
> may use relevant websites; journal features must prioritize factual, useful
> discovery/query results, not merely an entertainment draw. All three worker
> agents stopped due to workspace credits; independent review has not occurred.

Scope: implement the September 8 request against the live repository. No deployment, public messages, commits, or private configuration changes are implied.

## Requirements and evidence

| Requirement | Implementation / evidence | Status |
| --- | --- | --- |
| Observe group context before participation, speaker/time/reply/mentions, bounded TTL | group_conversation service + ingress | in progress |
| Distinguish invocation, third-person mention, closure, follow-up and other people's conversations | participation decisions + replay cases | in progress |
| Real ignore/wait/reply and optional semantic classification | decision service + main integration | in progress |
| One disposable candidate, bounded batching, recheck before sending | group candidate lifecycle + dispatcher guard | in progress |
| Explicit tools and due reminders do not disappear with disposable chat | command routing + delivery results | in progress |
| Shared group output limits, separate categories, coalesced errors | outbound service + all send paths | in progress |
| Natural concise expression, no forced quote/name pings, speaker-aware history | prompt/policy/engine/delivery | in progress |
| Bird source/photo/fact/distribution/collection | discoveries registry and catalog | in progress |
| Historical backdrop + fictional encounter + continuation | discoveries registry and catalog | in progress |
| Journal entertainment draw with sourced fields/year, no invented ranking | discoveries registry and catalog | in progress |
| Extensible validated catalogs, configuration, setup/help, migration docs | feature interfaces + docs | in progress |
| Three parallel workers then independent reviewer and synthesis | agent reports and review record | in progress |
| Focused verification and full requirement audit | selective regression + replay/import/package checks | pending |
| Real QQ behavior / deployment cost | requires actual deployment and permitted group trial; do not claim from unit tests | pending external evidence |

## Pending user preferences

- Requested preferred bird/history/journal sources; use small verifiable starter data if none supplied.
- Proposed group context default: 600 seconds / 60 events, memory-only, separate from durable memory.

## Ownership

- Kant: framework-independent group conversation state and candidate decisions.
- Bernoulli: shared outbound scheduling and delivery adapters.
- Sagan: discoveries features and sourced catalogs.
- Main: ingress/generation integration, settings, documentation and final corrections.
- Independent reviewer: to review combined live implementation after workers finish.

## Validation policy

Run meaningful checks once per coherent integration. Add adversarial cases for interleaved speakers, stale completion, waiting starvation, rejected targets, task delivery and source failures. Do not use a green unit suite as proof of human-like behavior or live QQ reliability.
