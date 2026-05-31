st. what are we missing here?                                                                                                          

● What you're missing — and it's load-bearing:

  The bridge architecture is the third option that breaks the binary

  You're framing "Python wins" vs "Rust wins" as a dichotomy. The bridge I just landed is neither — it's "Python walks Component PyObjects once and produces msgpack bytes; Rust walks bytes."
  Several of your "Rust-architecture wins" don't need the snapshot rewrite at all. They need an enriched IR, which is a bounded extension to bridge.py + reflex_ir, not weeks of arena-rewriting
   work.

  Concretely, of your "~12 ms of Rust wins":

  ┌───────────────────────────────────────┬────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                 Item                  │ Your claim │                                                     Reality after bridge lands                         │
  ├───────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ collect_all_imports_into → snapshot,  │ needs Rust │ Bridge already harvests (module, name) per page via _get_imports(). Drop the separate PyO3 walk and union from bridge harvest.     │
  │ -3.6 ms                               │  walks     │ Pure deletion. No snapshot needed.                                     │
  ├───────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Memoize IR variant kills              │ needs      │ Add Component::MemoCall { name, children } to the existing tree-IR; bridge emits it when it hits a candidate (so Python never      │
  │ Component.create() allocations, -5.8  │ snapshot   │ builds a wrapper Component). Rust emits jsx(<Name>, {}, ...) at the call site + a separate memo body module. The worktree's memo:  │
  │ ms                                    │            │ add Component::MemoCall variant + JSX emit commit (1a16c7a4) is exactly this. No snapshot.                        │
  ├───────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Memo body emit finish, -2.5 ms        │ needs      │ Already pure-Rust in the current bridge path (compile_memo_from_bytes = 33 µs). The 1.65 ms is the Python bridge walk per body —   │
  │                                       │ snapshot   │ batch them in one PyO3 call and it drops further. No snapshot.                                                                     │
  ├───────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Misc walk speedups, -1-2 ms           │ needs      │ Same: enrich the bridge harvest. No snapshot.                       │
  │                                       │ snapshot   │                                                                                                                                    │
  └───────────────────────────────────────┴────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  So your "Rust-architecture wins" actually split into bridge-IR wins (~11 ms, can land incrementally on what I just shipped) and snapshot wins (~1-2 ms + qualitative hot-reload caching). The
  snapshot rewrite is for one thing only: Salsa-style cross-page incremental caching keyed on content hash. That's the qualitative reload-experience win, not a per-page steady-state win.

  Other things in your accounting I'd push back on

  1. _get_all_custom_code 6.4 → 0.4 ms via "cache closure at class def" — likely unsound. The markdown closure captures component_map, which is instance-level state: rx.markdown(text, 
  component_map={...}) accepts different maps per instance. Cache at the class is wrong; cache as @cached_property on the instance is right but framework-side (yourrule §0a #1). Also the
  docs-page hot value is the closure code text, not the closure object — and that's already cheap to build. The real cost may be in _render not the closure construction. Worth re-profiling
  before scoping.
  2. Var._get_all_var_data() cache — "pure Python win" — this is reflex_base.vars.base, which is a framework primitive (plan §0a rule 1). It's a separate PR againstthe framework, not the
  compile pipeline. The plan explicitly disallows touching it from the rewrite. So scope it correctly — it's a framework optimization that happens to benefit compile, not part of the
  compile-pipeline budget.
  3. The 2.6 ms compile_unevaluated_page floor is misleading — that's cold compile per page. Under hot reload with content-hash caching (which the bridge architecture enables — msgpack bytes
  are deterministic), unchanged pages are free. Floor becomes 2.6 ms × pages_that_actually_changed. For 50 pages with one edit, the steady-state floor is 2.6 ms, not 130 ms. This is the
  qualitative shift you mentioned but tied to bridge + cache, not snapshot.
  4. compile_unevaluated_page 2.6 ms also includes _add_style_recursive — Python tree walk that applies theme styles. Plan §0a #5 stage 5 has a Rust port (merge_app_styles_arena_pass). That's
  another ~0.5-1 ms recoverable on style-heavy pages. Lives in the "Rust wins" bucket but again via bridge IR, not snapshot.
  5. Parallelism unlock is bigger than you said — my compile_page_from_bytes already does py.allow_threads (GIL released for the parse+emit span). With bridge per-pa
  ├────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Memo body emit finish, -2.5 ms     │ needs      │ Already pure-Rust in the current bridge path (compile_memo_from_bytes = 33 µs). The 1.65 ms is the Python  │
  │                                    │ snapshot   │ bridge walk per body — batch them in one PyO3 call and it drops further. No snapshot.                      │
  ├────────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Misc walk speedups, -1-2 ms        │ needs      │ Same: enrich the bridge harvest. No snapshot.                                                              │
  │                                    │ snapshot   │                                                                                                            │
  └────────────────────────────────────┴────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  So your "Rust-architecture wins" actually split into bridge-IR wins (~11 ms, can land incrementally on what I just shipped) and snapshot wins (~1-2 ms +
  qualitative hot-reload caching). The snapshot rewrite is for one thing only: Salsa-style cross-page incremental caching keyed on content hash. That's the
  qualitative reload-experience win, not a per-page steady-state win.

  Other things in your accounting I'd push back on

  1. _get_all_custom_code 6.4 → 0.4 ms via "cache closure at class def" — likely unsound. The markdown closure captures component_map, which is instance-level state:
   rx.markdown(text, component_map={...}) accepts different maps per instance. Cache at the class is wrong; cache as @cached_property on the instance is right but
  framework-side (your rule §0a #1). Also the docs-page hot value is the closure code text, not the closure object — and that's already cheap to build. The real cost
   may be in _render not the closure construction. Worth re-profiling before scoping.
  2. Var._get_all_var_data() cache — "pure Python win" — this is reflex_base.vars.base, which is a framework primitive (plan §0a rule 1). It's a separate PR against
  the framework, not the compile pipeline. The plan explicitly disallows touching it from the rewrite. So scope it correctly — it's a framework optimization that
  happens to benefit compile, not part of the compile-pipeline budget.
  3. The 2.6 ms compile_unevaluated_page floor is misleading — that's cold compile per page. Under hot reload with content-hash caching (which the bridge
  architecture enables — msgpack bytes are deterministic), unchanged pages are free. Floor becomes 2.6 ms × pages_that_actually_changed. For 50 pages with one edit,
  the steady-state floor is 2.6 ms, not 130 ms. This is the qualitative shift you mentioned but tied to bridge + cache, not snapshot.
  4. compile_unevaluated_page 2.6 ms also includes _add_style_recursive — Python tree walk that applies theme styles. Plan §0a #5 stage 5 has a Rust port
  (merge_app_styles_arena_pass). That's another ~0.5-1 ms recoverable on style-heavy pages. Lives in the "Rust wins" bucket but again via bridge IR, not snapshot.
  5. Parallelism unlock is bigger than you said — my compile_page_from_bytes already does py.allow_threads (GIL released for the parse+emit span). With bridge
  per-page taking 0.3 ms and Rust emit 0.03 ms, you can pipeline: Python bridges page B while Rust emits page A in a worker thread. For 50 pages this isn't 50 × 0.33
   ms sequential, it's max(50 × 0.27, 50 × 0.035) ≈ 13 ms if you push it through rayon. Pure Python can't do this (GIL). The bridge architecture already buys this;
  you don't need snapshot.
  6. The "33 ms/page → ~5-6 ms" ceiling math doesn't separate dev iterations from CI cold builds — they have completely different distributions. Hot reload value
  comes from not paying the 2.6 ms × N user-code re-evaluation on every reload; that's a 10× win on dev experience that has nothing to do with the per-page Rust emit
   being 35 µs vs 5 ms.

  Sequencing recommendation

  You're directionally right on "Python first, then Rust." But the cut is:

  1. Bridge architecture (✓ landed today). Pure-Rust emit, GIL released, IR bytes architecture. Foundation for everything else.
  2. Pure-Python deletions that fall out of the bridge: drop redundant collect_all_imports_into (2.4 ms), drop the app-root second-walk (3.6 ms), hoist plugin
  resolve (3 ms amortized). ~9 ms. Days of work. Zero IR changes.
  3. Bridge-IR enrichment: Memoize variant (5-6 ms), fold install-imports into bridge (2 ms), batch memo-body bridging (1 ms). ~8-9 ms. ~1 week. Tree-IR additions
  only, no snapshot.
  4. Framework PRs (orthogonal): Var data cache, markdown closure cache. Reflex-base PRs, not compile-pipeline.
  5. Snapshot + Salsa caching, if and only if the cross-page hot-reload win is worth it after #1-4. This is the architectural lift. After 1-4 you should be at ~4-6
  ms/page cold, and the question is whether incremental hot-reload caching is worth the rewrite. My read: probably yes for 50+ page apps, no for small apps. Decide
  empirically after #1-4.

  The trap I think you're still in

  You wrote: "the snapshot work has to justify itself against the full 22 ms of headroom but it'll only deliver ~12 ms." That's the wrong frame because the bridge
  architecture already delivers ~9 ms of that 12 ms, which means the snapshot rewrite's marginal value is even smaller — maybe 1-3 ms per-page steady state, plus
  whatever hot-reload caching is worth. Frame the snapshot decision as "is incremental caching worth the rewrite?" not "is the rewrite worth 12 ms?"

  The bench numbers I'm citing are for 48 nodes. Docs pages run 200-500 nodes. Scale every per-page number ~5× and the ceiling math changes again — that's the next
  thing I'd want to re-measure before committing scope.

---

# Appendix: lower-level pitfalls (audit pass)

Findings from a separate sweep of bridge.py, parse.rs, page.rs, jsx.rs, session.rs, rust_pipeline.py, reflex_intern. These are the things the high-level "bridge vs snapshot" framing above doesn't touch — they're correctness/perf bugs already shipped that will silently bound any of the wins above.

## 0. The single biggest hidden cliff

**The interner is a single global `Mutex<Interner>` and every emit-side `resolve_unchecked` takes the lock.** (`packages/reflex-compiler-rust/crates/reflex_intern/src/lib.rs:74-77, 107-128`). The plan acknowledges this in the file header ("plan's R5/R8 target is per-thread sharded interners… deferred until profiling shows the lock matters"). It matters now: `compile_page_from_bytes` already releases the GIL (`session.rs:530`), so the "pages compile concurrently from different threads" claim in the docstring (line 514-516) is literally false the moment more than one thread enters emit — they serialize on this mutex. Every prop name, tag, state binding, meta name, ImportVar tag in `parse.rs` calls `intern_str` (mutex lock); every byte of the page module emit calls `resolve_unchecked` (mutex lock). For a 200-node page that's thousands of lock acquisitions per page. **Until this is sharded (or replaced with `arc-swap` / `dashmap` / a pre-fill-then-read-only table), every parallelism win in the plan is dead on arrival.** Fix this before §3 of the sequencing recommendation, not after.

## 1. The "single-walk bridge" claim is false — the tree is walked 3-4× per page

The bridge architecture sells itself on "Python walks Component PyObjects once and produces msgpack bytes." In practice (`reflex/compiler/rust_pipeline.py:174-270`, per page):

1. `sess.collect_all_imports_into(all_imports, component)` (line 203) — Rust callback that walks the tree to harvest imports.
2. `pre_memo_imports = component._get_all_imports()` (line 235) — Python tree walk.
3. `_get_all_imports()` on the post-memoize tree (line 244) — Python tree walk.
4. `page_to_ir(component, ...)` (the actual bridge walk) — Python tree walk.

That's four walks producing overlapping data, plus the bridge's harvest internally already populates `harvest.component_imports`. The whole reason the bridge exists is to make exactly one of these passes — drop #1 and #3 (already redundant with bridge harvest), and audit whether #2 is needed at all given bridge already collects pre-walk via the `extra_imports=` parameter. **Estimated savings:** 3× walks × 200 nodes × ~3µs/node ≈ 1.8 ms/page = ~90 ms across 50 pages.

## 2. The CLI loop holds the GIL — `allow_threads` is wasted

`reflex/compiler/rust_pipeline.py:174` is a plain `for route, unev in app._unevaluated_pages.items():` with the Rust call inside. `compile_page_from_bytes` releases the GIL (`session.rs:530`) — but the surrounding loop runs sequentially, so the GIL-released span only ever executes on one thread. The python-side preludes (compile_unevaluated_page eval, walk_and_memoize, page_to_ir, …) are 99% of per-page wall time; the actual Rust call is ~30 µs. A `ThreadPoolExecutor` over the iter — interleaving the bridge walk for page B with Rust emit for page A — would buy real concurrency. (Combined with #0, the interner mutex would immediately cap how many threads can actually progress.)

## 3. bridge.py hot-path waste

All cite `reflex/compiler/ir/bridge.py`.

- **L301-308 `_decode_js_string`** does `import json` *inside the function*. Called once per Bare node. Cached after first call, but the global lookup is still per-call. Move to module top.
- **L306 `json.loads`** is being used to unescape a `"…"` JS string. `LiteralVar.create(str)` produces a known shape (JSON-encoded `"…"`); a hand-rolled `\"` / `\\` / `\n` decoder is ~10× faster and avoids spinning a fresh `JSONDecoder` per call.
- **L65-94 `_find_state_idents`** is a pure-Python char-by-char scanner. Called for every Var `_js_expr` via `harvest.scan_expr`. Replace with a compiled regex `re.compile(rf"(?<!\w){re.escape(_STATE_PREFIX)}\w*{re.escape(_STATE_SUFFIX)}(?!\w)")` — the re module dispatches in C.
- **L145-149 VarData fallback** does `hasattr(var, "_get_all_var_data")` (exception-based attr probe) then `getattr(var, "_var_data", None)`. Every `Var` defines `_get_all_var_data`; the hasattr is dead defensiveness paying per call. Direct call.
- **L195-217 `_value_to_ir`** uses `isinstance` for `bool/int/float/str`. None of these have user-defined subclasses on the compile path. Use `type(value) is bool` etc. — measurably faster and clearer. Also: put the `value is None` check before the bool isinstance (None is *much* more common than bool in Reflex props).
- **L164-181, 252-269, 360-388, 468-484** — pervasive `getattr(c, "name", default)` for attributes that are always present on the class (`tag`, `library`, `alias`, `children`, `event_triggers`, `custom_attrs`, `_is_tag_in_global_scope`). Each call walks the MRO + dict for the fallback. Add class-level defaults on Component / ImportVar so direct attribute access works.
- **L20-22 schema attribute lookups** — `_schema.VALUE_JS_EXPR`, `_schema.LITERAL_NULL`, etc., are module-level lookups inside the hottest path (`_value_to_ir`, `_bare_to_ir`, every component constructor). Bind to local module-level names: `_VAL_JS_EXPR = _schema.VALUE_JS_EXPR` etc. Local-bind cuts ~3-5× off attribute lookup overhead.
- **L406-418 dispatch via `type(c).__name__`** — string-keyed dispatch. Two problems: (a) subclassing `Foreach` etc. silently falls through to `_element_to_ir` (correctness footgun); (b) `__name__` is a descriptor lookup. Use `type(c)` as the dict key. (Or attach `_ir_kind = "foreach"` as a class attribute.)
- **L185 `_schema_EMPTY_VAR_DATA`** is a **mutable** module-level list returned by reference. If any downstream consumer mutates it (msgpack doesn't, but bridge IR is later passed to other code), the shared state is a latent footgun. Make it a tuple, or return a fresh `[[], [], None, [], None, []]` each call (allocation cost negligible for the empty case).
- **L323-326 `_cond_to_ir`** materializes `list(c.children or ())` to index `[0]` and `[1]`. Just access `c.children[0]` and `c.children[1]` directly (or `next(it)` twice).
- **L312-314 `_children_to_ir`** allocates a list comprehension per element — fine, but pre-allocating with `[None] * len(children)` then assigning in a loop avoids list-grow.
- **L472-473 `_merge_imports_into_harvest`** uses `tag.split(".", 1)[0]` — builds a 2-element list. Use `tag.partition(".")[0]` (one tuple alloc, no list).
- **L169, 483** — `f"{tag} as {alias}"` is computed twice (once in `_var_data_to_ir`, once in `_merge_imports_into_harvest`) for the same ImportVar appearing in both VarData walk and `_get_all_imports`. Cache on the ImportVar instance or hoist into a helper.

## 4. page.rs has O(n²) dedup + per-page interning of static constants

All cite `packages/reflex-compiler-rust/crates/reflex_codegen/src/page.rs`.

- **L240-258 `emit_combined_imports`** — `runtime_react`, `runtime_rest` `.collect()` into two heap Vecs *per page emit*, then call `intern()` on each of the 8 constant strings *per page emit*. Each `intern()` takes the global mutex (#0). Pre-intern the eight runtime symbols once via `OnceLock<[(Symbol, Symbol); 8]>` at startup. Saves ~16 mutex acquisitions per page.
- **L271-276 module-dedup `if !modules.contains(m)`** — O(n) inside O(n) → O(n²) over imports. For a 50-import page that's 2500 compares. Use `HashSet<Symbol>` (Symbol is `u32`, hashes free).
- **L278-288 alias-dedup `if emitted.contains(alias)`** — same O(n²) per module. Same fix.
- **L281 inner loop** re-scans **all** imports for every outer module. Pre-bucket once into `HashMap<Symbol, Vec<Symbol>>`; one pass to build, then iterate per module. Combined with the two fixes above, import emit drops from O(modules × imports + Σ aliases²) to O(imports).

## 5. jsx.rs walks each prop name three times

`packages/reflex-compiler-rust/crates/reflex_codegen/src/jsx.rs:220-265` (`emit_prop_name`, `write_camel_case`):

- `resolve_unchecked(sym)` (mutex), then `name.contains('_')`, then *inside* that branch `is_js_identifier(name)` (re-scan), then fall-through to `write_camel_case` (third scan). For names without `_`, `is_js_identifier` may also run depending on branch structure — audit the control flow.
- `write_camel_case` (L243-265) uses `ch.to_uppercase()` + `[0;4]` UTF-8 buffer for every char including ASCII. Prop names are >99% ASCII; fast-path `b.to_ascii_uppercase()` + `buf.write_byte`.
- Pre-computing "is-valid-ident" and "camel-cased form" *at intern time* and storing in a side table keyed by Symbol turns the whole per-prop path into a single Vec index. Closed-vocabulary prop names make this trivial.

## 6. parse.rs allocator and validation waste

All cite `packages/reflex-compiler-rust/crates/reflex_ir/src/parse.rs`.

- **L101 `std::str::from_utf8(head)?`** validates UTF-8 for every msgpack str. msgpack `str` is spec-guaranteed UTF-8 and Python's `msgpack.packb(use_bin_type=True)` produces valid UTF-8. `from_utf8_unchecked` (gated behind `cfg(not(debug_assertions))`) saves a full-input walk.
- **L122-125 `read_u64`** decodes via `i128` intermediate. Use `decode::read_int::<u64, _>` directly.
- **L174-183 `read_u8_or_nil`** and **L398-399 `read_hook`** decode via `u16`/`u32`. Use `read_u8(buf)?` directly (consistent with the in-file helper).
- **L344, 379, 396, 429, 502** — `arena.alloc_str(read_str_borrowed(buf)?)` copies bytes that already live in the input buffer. The caller in `session.rs:528` holds `buf: Vec<u8>` on the stack across the whole `allow_threads` block — Page lifetime is bounded by buf lifetime. Change Page's lifetime to `'bytes` (or unify `'bytes: 'arena`) and let Text values, JsExpr strings, Hook code, Meta content all borrow directly. For a docs page with hundreds of long expression strings this is a measurable copy budget.
- **L433-636 `read_component`** is recursive on the call stack. Pages with >1000-deep nesting blow the stack. The bridge produces these without complaint. Add a stack-depth check or convert to a work queue.
- **L447-481** — every Element allocates 4 separate bumpalo Vecs (props/children/events/hooks). For element-heavy pages that's 4N bump-alloc operations. Not blocking, but worth flagging if the arena grows beyond expectations.
- **L609** (`compile_page_with_sourcemap_inner`) — `Arena::with_capacity(page_bytes.len() * 4)`. The 4× heuristic is the *only* sized capacity in the pipeline; `session.rs:531, 570` use bare `Arena::new()`. Apply the same heuristic to `compile_page_from_bytes` and `compile_memo_from_bytes` — saves the first 3-4 bump-page realloc cycles per page.

## 7. session.rs per-page allocation churn

All cite `packages/reflex-compiler-rust/crates/reflex_py/src/session.rs`.

- **L526-528, 565-568** — three `String`/`Vec` allocations per page just to satisfy `allow_threads`'s `'static` requirement. `ir_bytes.as_bytes().to_vec()` copies the entire msgpack blob (could be 100 KB+). Investigate whether `Py<PyBytes>` + holding a `Bound` reference inside the closure is acceptable; if not, at minimum reuse a per-session `Vec<u8>` buffer with `clear()` + `extend_from_slice`.
- **L535-536** — `custom_code_owned.iter().map(String::as_str).collect()` rebuilds a `Vec<&str>` only to pass into `emit_page_with_extras`. Change the API to `IntoIterator<Item=&str>`.
- The `String::from_utf8(out.into_bytes())` round-trip at L539 returns a Python `String` that Python then writes to disk. The `compile_*_module` variants stream straight to disk via `BufWriter<File>` — add a `compile_page_to_file(path, ...)` variant that skips the Python string round-trip entirely.

## 8. rust_pipeline.py module-import churn

`reflex/compiler/rust_pipeline.py` does inline imports inside the per-page loop body — `from reflex.compiler.ir.bridge import page_to_ir`, `from reflex.state import all_base_state_classes`. They're cached after first call, but the lookup-in-sys.modules cost adds up over a 50-page loop. Hoist to top of `compile_pages`.

## 9. Correctness footguns worth flagging

- **bridge.py L185 `_schema_EMPTY_VAR_DATA`** — shared mutable list, addressed above. Worth a comment if not fixed: "DO NOT mutate; shared sentinel."
- **bridge.py L417 dispatch via `__name__`** — silent fall-through on subclassing (Foreach, Cond, Match all are user-subclassable in principle). At minimum, add a `__init_subclass__` warning if any subclass inherits and isn't registered.
- **parse.rs L433 recursion** — see #6 above. Real stack-overflow vector with no current guard.

## Top-of-the-list priorities, summarized

If you implement nothing else from this appendix, in order:

1. **Shard / lock-free the interner** (`reflex_intern/src/lib.rs:74`). Single biggest blocker. Pre-fill all `WELL_KNOWN` + harvested static strings, then move to read-mostly `arc-swap`/`dashmap` for novel interns. Until this lands, every other parallelism plan is theoretical.
2. **Drop the redundant tree walks** in `rust_pipeline.py` — `collect_all_imports_into` (L203) and the duplicate `_get_all_imports()` calls. Bridge already harvests this.
3. **Drop `import json` + `json.loads`** in `_decode_js_string` (bridge.py L301-308). Free win.
4. **Pre-intern `RUNTIME_IMPORTS`** in page.rs and replace O(n²) dedup with HashSet (page.rs L240-288). Free win.
5. **ThreadPoolExecutor over the per-page loop** (`rust_pipeline.py:174`) — only useful *after* #1 lands. Sequencing matters.
6. **Tighten parse.rs lifetimes** so msgpack `str` doesn't get copied into the arena when the input buf outlives the Page (parse.rs L344, 379, 396, 429, 502).

These six items would (a) make the parallelism story real, (b) cut ~3-5 ms/page of redundant Python walks, (c) cut another ~1-2 ms/page of bridge.py micro-overhead, and (d) shave fixed per-page allocation costs in Rust. Notably none of these require the snapshot architecture — they're all bug fixes against what already shipped.
