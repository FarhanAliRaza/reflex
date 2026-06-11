# Parity Oracle — design, guarantees, and known gaps

Modeled on React Compiler's Rust-port testing docs
(`facebook/react#36173`, `compiler/docs/rust-port/rust-port-0003-testing-infrastructure.md`):
state exactly what is compared, why each normalization is sound, and what is
deliberately NOT covered — so a green check is never mistaken for a stronger
guarantee than it actually is.

**Current status (2026-06-10):** 27 cases, all green. Golden lives in-repo.
Determinism verified empirically (same-seed and cross-seed byte-identical).
One real emit bug found and fixed during this validation (see §7).

---

## 1. Goal

Every perf change to the Rust compile pipeline (freeze / memoize / emit /
Component construction) must reproduce the compiled output **byte-for-byte**.
The oracle is a *regression* oracle: it compares the tree after a change
against a golden captured before it — not against the legacy Python compiler
(that cross-implementation comparison was done once at the arena cutover and
the legacy path is no longer the reference).

```
fixture build()  ──► CompilerSession.compile_page_from_component_arena
                          │
                          ├── page_js            (exact bytes)
                          ├── memo_bodies        (exact bytes, sorted by name)
                          ├── imports            (canonicalized, see §3)
                          └── snapshot_stats     (arena intermediate state, §4)
root artifacts   ──► compile_{document_root,theme,app_root}_arena
                          └── emitted file bytes (exact)
```

## 2. What is captured

| Case group | Count | What it exercises |
|---|---|---|
| `corpus:01–18` | 18 | text/box nesting, cond/foreach/match, state + computed vars, events, custom_attrs, key/id props, flat style dict |
| `corpus:19–21` | 3 | **style transforms**: breakpoint lists → `@media` maps, pseudo-selectors (`_hover`, nested `_before`, `:focus`), pseudo-key-holding-media-map, Var values (`rx.color`) — the exact `format_as_emotion` surface the Rust style port must reproduce |
| `bench:complicated`, `bench:stateful` | 2 | the heavy benchmark pages: deep nesting, foreach/match, state, events end-to-end |
| `page:kwargs` | 1 | the optional compile kwargs (`title`, `meta_tags`, `custom_code`, `hooks_body`) — template splices otherwise never covered |
| `root:document`, `root:theme`, `root:app` | 3 | `_document.js`, `theme.js`, `root.jsx` — these freeze Component trees through the **same `freeze.rs`** as pages; a freeze refactor can break them while every page case stays green |

Not captured (deliberately): `context.js`, `styles.css`,
`stateful_pages.json` — pure string templates with no Component input; a
freeze/emit change cannot affect them.

## 3. Canonicalization rules — and why each one is sound

The contract is: **normalize only what is provably not part of the output
contract.** Every rule must carry a justification; if you can't write one,
don't normalize — fail instead.

1. **`memo_bodies` sorted by name.** Body modules are emitted as independent
   files; their relative order in the return tuple is a HashMap-iteration
   artifact. Names embed the subtree hash, so sorting is stable and
   collision-free.
2. **Import entries serialized by field tuple, not `repr`.** The native
   `RustImportVar` falls back to an address-bearing default repr; fields
   (`tag, alias, is_default, install, render, package_path`) are the
   identity.
3. **Import multiplicity deduped per module.** The harvest accumulates one
   entry per contributing node; duplicate counts depend on walk internals
   (e.g. VarData object identity), not output semantics. Every consumer
   dedups: the page's emitted import lines are covered byte-exactly by
   `page_js`, and `_get_frontend_packages` dedups before install. (Added
   2026-06-09 when sparse `__init__` changed multiplicity by one with
   byte-identical `page_js`.)

## 4. Intermediate-state check

React's port diffs the compiler IR **after every pass**, not just final
output. Our cheap analog: each component case also records
`snapshot_stats` (arena `node_count`, `var_data_len`, `vars_used_total`,
`unique_var_ids`) from a fresh `build()`. This catches freeze drift that
happens to emit identical bytes (e.g. a node silently dropped from the
arena whose output was redundant). A full arena debug-print diff (the real
per-pass equivalent) is planned for the style-port work, where localizing
drift to a pass will matter most.

## 5. Determinism

Verified empirically (2026-06-10): two same-seed captures are
byte-identical (no flakiness) and `PYTHONHASHSEED=0` vs `=12345` captures
are byte-identical (no hash-order dependence in any captured byte — like
React's IndexMap-everywhere discipline, ours comes from insertion-ordered
dicts and explicit sorts). The `PYTHONHASHSEED=0` prefix in older notes is
unnecessary; plain `uv run python scripts/parity_oracle.py check` is the
gate. Caveat: verified on the 27-case corpus, not proven for all inputs.

One known environment sensitivity, **not** gated: memo names embed a
subtree hash that differs between a pytest process and a plain script
process (`Box_memo_2d915d…` vs `Box_memo_6a459e…`). Within one process
type it is stable, so the oracle (always a script) never sees it. Root
cause not yet chased — worth a look if memo naming ever feeds caching.

## 6. Usage and discipline

```
uv run python scripts/parity_oracle.py capture   # BEFORE a change (baseline)
uv run python scripts/parity_oracle.py check     # AFTER every step — must be zero drift
```

- Golden: `tests/codegen_corpus/parity_golden.json` — **in-repo**. It lived
  in `/tmp` until 2026-06-10, when a tmpfs wipe destroyed the baseline
  mid-program (recovery relied on the prior session having ended green).
  React commits its 1,725 `.expect.md` fixtures for the same reason.
- An *intentional* output change (new feature, bug fix) recaptures the
  golden in the same commit, with the diff reviewed — recapture is an
  explicit, justified act, never a reflex to make `check` pass.
- The corpus substring tests (`pytest tests/codegen_corpus`) are the
  human-readable companion: they assert against the page module **plus all
  memo bodies** (the memoize pass promotes subtrees out of `page_js`; until
  2026-06-10 the runner only searched `page_js` and 10 fixtures were
  silently asserting against the wrong artifact).

## 7. What this validation found (2026-06-10)

Auditing the oracle against React's setup surfaced one process failure and
one real product bug:

1. **Process:** the golden was in `/tmp` (lost), root artifacts and compile
   kwargs were uncovered, style coverage was one flat dict, and corpus
   expectations didn't search memo bodies. All fixed (§2, §6).
2. **Product bug — invalid JS shipped while the oracle was green.** Any
   component with an `id` prop made the page/memo emitters write a
   hardcoded `const ref_root = useRef(null); …` line *in addition to* the
   node's own harvested ref hook. With `id="root"` the two collided — a
   duplicate `const` declaration in one scope, a **SyntaxError** — and with
   any other id the page declared a dangling unused `ref_root`. The
   page-level line was a porting stopgap (`page.rs` comment: "Single shared
   ref for now") from before per-node hooks were harvested; legacy Python
   has no page-level ref concept at all. Fixed by deleting the page/memo
   `ref_root` emission (4 sites) and the per-node `getattr("id")`
   `needs_ref` harvest that fed it (one fewer PyO3 crossing per node).
   Lesson, straight from React's playbook: **byte-parity ratifies whatever
   the baseline does — it cannot see semantically broken bytes.** Their
   answer is fixture e2e runs on top of snapshot parity; ours (gap, below)
   is at minimum a JS syntax check over emitted modules.

Known residual wart (valid JS, deliberately not chased now): the page
module renders hooks for nodes that were promoted into memo bodies, so a
ref hook can appear in both the page and the memo body scopes. Harmless at
runtime (separate scopes; the memo body's registration wins), but hook
emission should eventually partition by memo-boundary.

## 8. Known gaps (ranked)

1. **No semantic validation of emitted JS.** A syntax pass (e.g. running
   the emitted modules through a parser in CI, or one Playwright smoke per
   corpus app) would have caught §7.2 years earlier than a human reading
   goldens. Highest-value next hardening step.
2. **No error-case parity.** React's fixtures compare diagnostics; we only
   capture success paths. Acceptable while perf refactors don't touch
   error handling.
3. **No full `compile_pages` end-to-end golden** (multi-page app, all
   written files hashed). Partially covered: the cache tests assert
   byte-identical hit output and the parallelism harness asserted
   pool-vs-sequential byte equality.
4. **Per-pass arena debug dump** (§4) — build when the style port starts.
