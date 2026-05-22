 Phase 1 — IR schema design and crate layout (2 weeks)                                                                                                                        
The IR design is the project. Spend real time here; everything else is mechanical once it's right.                                                                                   
Crate structure (separate crates so the IR is testable without Python):                                                                                                              
crates/                                                                                                                                                                              
  reflex-ir/           # Pure Rust types, zero PyO3 deps                                                                                                                             
  reflex-snapshot/     # Arena, interner, traversal primitives                                                                                                                       
  reflex-walks/        # Walk implementations (import collect, memoize, etc.)                                                                                                        
  reflex-bindings/     # The ONLY crate with PyO3 — thin wrappers                                                                                                                    
The reflex-ir crate has no pyo3 in Cargo.toml. This is enforced. It means all walks can be unit-tested in pure Rust, and the Python boundary is a single concentrated surface.       
IR schema decisions you need to make explicit in code review:                                                                                                                        
                                                                                                                                                                                     
Arena representation: Vec<NodeSnapshot> flat, with children: Range<u32> for child indices. No Box/Rc trees.                                                                          
String interning: StringInterner (use the string-interner crate or roll your own) built per-compile. Every string field in the snapshot is a Symbol (u32). Final emit phase resolves 
 back to strings.                                                                                                                                                                    
NodeSnapshot fields: enumerate every one. From my earlier analysis:                                                                                                                  
                                                                                                                                                                                     
kind: NodeKind (Tag, Bare, Cond, Match, Foreach, MemoizeWrapper, ...)                                                                                                                
tag: Option<Symbol>                                                                                                                                                                  
imports: SmallVec<[ImportEntry; 4]>                                                                                                                                                  
custom_code: Option<Symbol>                                                                                                                                                          
hooks_internal: SmallVec<[HookEntry; 2]>                                                                                                                                             
hooks_user: SmallVec<[Symbol; 1]>                                                                                                                                                    
dynamic_imports: SmallVec<[Symbol; 1]>                                                                                                                                               
vars_used: SmallVec<[VarDataRef; 4]>                                                                                                                                                 
event_callbacks: SmallVec<[(Symbol, Symbol); 2]> (trigger name → rendered callback string)                                                                                           
rendered_props: SmallVec<[(Symbol, Symbol); 4]> (prop name → rendered JS expression)                                                                                                 
style: SmallMap<Symbol, Symbol>                                                                                                                                                      
ref_name: Option<Symbol>                                                                                                                                                             
app_wrap_components: SmallVec<[u32; 0]> (indices into arena)                                                                                                                         
children: Range<u32>                                                                                                                                                                 
flags: NodeFlags (bit-packed: has_state_or_hooks, has_event_triggers, is_bare, is_snapshot_boundary, propagates_hooks, memoization_disposition encoded in 2 bits, etc.)              
subtree_hash: u64 (computed bottom-up at freeze time, used for cross-page caching)                                                                                                   
                                                                                                                                                                                     
                                                                                                                                                                                     
Mutability model: walks produce new arenas (immutable snapshot) OR modify in place via a &mut Arena handle (allows in-place style merge, trigger rewriting). Pick one. I'd recommend 
 in-place for mutations, returning derived data for collections (imports, hooks).                                                                                                    
Serialization: how does Python hand the snapshot to Rust? Options:                                                                                                                   
                                                                                                                                                                                     
(a) Build snapshot in Python as nested dicts/lists, extract into Rust. Easy but slow (many PyObject reads).                                                                          
(b) Serialize Python-side to bytes (bincode, rkyv, msgpack), Rust deserializes once. Single boundary crossing.                                                                       
(c) Build snapshot directly via PyO3 helpers — Python calls Rust constructors that append nodes to the arena. No serialization, but multiple boundary crossings (one per node).      
                                                                                                                                                                                     
I'd recommend (c) for snapshot construction (the freeze pass appends node-by-node to a Rust-owned arena via PyO3) and zero serialization afterwards because the arena lives in Rust  
for the rest of the compile.                                                                                                                                                         
                                                                                                                                                                                     
Validation: the IR crate compiles standalone, has unit tests for arena operations, interner round-trips, flag encoding. No Python involvement yet.                                   
Phase 2 — Freeze pass scaffolding (2 weeks)                                                                                                                                          
The Python code that produces the snapshot. This IS Python work, but it's not optimization — it's required infrastructure. There's no Rust-first version that skips this; Component  
instances exist in Python and someone has to extract their state.                                                                                                                    
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
reflex/compiler/freeze.py — single-pass walker. Takes a Component tree, calls each per-node method (_get_imports, _get_custom_code, _get_hooks_internal, etc.), packs results into a 
 Rust-owned arena via PyO3 bindings.                                                                                                                                                 
Field extraction helpers: one helper per IR field, with explicit handling for the awkward cases (Var rendering, event chain serialization, style merging).                           
Side effect phase discipline: document and enforce that freeze is observation-only. Add assertions (when REFLEX_DEBUG_FREEZE=1) that detect mutations during freeze and fail loudly. 
Parallel execution path: freeze runs alongside the existing pipeline. Both produce output. Outputs are diffed. No code paths are removed yet.                                        
                                                                                                                                                                                     
Validation: every page in the benchmark suite produces a snapshot that round-trips through Python→Rust→Python with byte-identical Component dunder method outputs. No optimizations  
measured here; correctness only.                                                                                                                                                     
Phase 3 — First Rust walk: import collection (2 weeks)                                                                                                                               
Pick one walk to migrate first. Imports is right because: well-bounded, clear input/output, ~4 ms of payoff, validates the whole pipeline.                                           
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
reflex-walks::collect_imports(arena: &Arena) -> ImportMap in pure Rust.                                                                                                              
PyO3 binding that takes the arena handle from Phase 2 and returns the merged imports as a Python-side structure (or symbol-resolved strings).                                        
Replace the call site in reflex/compiler/utils.py to invoke the Rust path behind a feature flag (REFLEX_RUST_IMPORTS=1).                                                             
Both Python and Rust implementations remain. The Python one is the source of truth; the Rust one is validated against it.                                                            
                                                                                                                                                                                     
Validation:                                                                                                                                                                          
                                                                                                                                                                                     
Output equivalence: import maps from Python and Rust paths byte-identical across the entire benchmark suite.                                                                         
Performance: Rust path is at least 3x faster on the same input (~3.9 ms → <1.3 ms). If not, debug before continuing.                                                                 
Memory: arena allocation patterns sane (no per-node mallocs in the inner loop).                                                                                                      
                                                                                                                                                                                     
This is the gate. If Phase 3 doesn't deliver the expected wins, the rest of the plan is wrong and needs rethinking before continuing.                                                
Phase 4 — Memoize walk in Rust + IR variant (3 weeks)                                                                                                                                
The biggest structural win and the most architecturally risky step. Today walk_and_memoize allocates Python Component wrappers; in the new design, it inserts                        
NodeKind::MemoizeWrapper markers into the arena with associated memo body definitions stored separately.                                                                             
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
IR additions: MemoizeBody table (separate from main arena) holding signature, body subtree reference, hash. NodeKind::MemoizeWrapper variant pointing into this table.               
reflex-walks::memoize(arena: &mut Arena) -> MemoizeDecisions that walks the arena, decides per node based on flags (memoization_disposition, has_state_or_hooks, subtree reactive    
walk over precomputed bools), inserts wrapper nodes or restructures the arena.                                                                                                       
Memo body emit: takes MemoizeBody entries, produces JSX modules via the existing Rust emit path.                                                                                     
Python integration: the legacy walk_and_memoize path stays under feature flag; the Rust path replaces it.                                                                            
                                                                                                                                                                                     
Validation:                                                                                                                                                                          
                                                                                                                                                                                     
Emitted memo JSX byte-identical to current pipeline output (this is where bugs hide — tiny formatting differences cause cache misses on hot reload).                                 
Performance: 6.73 ms → <1 ms on benchmark pages.                                                                                                                                     
All existing memo tests pass.                                                                                                                                                        
                                                                                                                                                                                     
Phase 5 — Remaining walks in Rust (2 weeks)                                                                                                                                          
Once the pattern is established, these are mechanical:                                                                                                                               
                                                                                                                                                                                     
_get_all_custom_code aggregation                                                                                                                                                     
_get_all_hooks collection (with position-aware ordering)                                                                                                                             
_get_all_dynamic_imports                                                                                                                                                             
_get_all_app_wrap_components                                                                                                                                                         
Var data fingerprinting                                                                                                                                                              
                                                                                                                                                                                     
Each: pure Rust walk over arena, feature-flagged, output-equivalence-validated, perf-measured.                                                                                       
Validation: cumulative profile shows phase-by-phase reduction matching the predictions.                                                                                              
Phase 6 — Mutations in Rust (2 weeks)                                                                                                                                                
Move the mutation passes (style merge, event trigger rewriting, plugin transform outputs) to operate on the arena.                                                                   
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
reflex-walks::apply_app_style(arena: &mut Arena, app_style: &Style) — replaces _add_style_recursive.                                                                                 
reflex-walks::rewrite_event_triggers_for_memo(arena: &mut Arena, decisions: &MemoizeDecisions) — replaces fix_event_triggers_for_memo.                                               
Plugin output capture: plugins still run in Python at the transform phase, but their outputs (added imports, contributed components) are funneled into the arena rather than         
mutating Components directly.                                                                                                                                                        
                                                                                                                                                                                     
Validation: post-mutation arenas produce same output as today's post-mutation Component trees.                                                                                       
Phase 7 — Integration with existing Rust emit (1 week)                                                                                                                               
The existing compile_page_from_component (rust_pipeline) already consumes IR. Reconcile schemas so the new arena IS what the emit phase reads, eliminating intermediate translation. 
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
Schema unification: existing IR and new arena converge on one type (probably new arena absorbs existing IR shape).                                                                   
Emit phase reads arena directly, no intermediate dict-of-dicts conversion.                                                                                                           
                                                                                                                                                                                     
Validation: no redundant transformations in the pipeline; full compile passes regression tests.                                                                                      
Phase 8 — Hot reload caching (3 weeks)                                                                                                                                               
The actual long-term payoff. Per-subtree identity hashing makes incremental compilation possible.                                                                                    
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
Subtree hash computation at freeze time (already in IR schema from Phase 1).                                                                                                         
Snapshot cache: HashMap<u64, ArenaSubtree> keyed by subtree hash, persisted across compiles.                                                                                         
Module-change detection: on hot reload, only re-freeze modules whose source changed; reuse cached subtrees for unchanged modules.                                                    
Cache invalidation: app-level config changes (style, plugins) invalidate caches; module-level changes invalidate only affected subtrees.                                             
                                                                                                                                                                                     
Validation: hot reload of a single-component change in a 50-page app touches <1% of nodes. Total reload time is dominated by user code execution, not compile overhead.              
This is the phase that justifies the whole project. The 12 ms/page savings is meaningful; the qualitative change in hot reload latency from "linear in app size" to "linear in       
change size" is what actually matters.                                                                                                                                               
Phase 9 — Parallelism (2 weeks)                                                                                                                                                      
Once walks are pure Rust and arenas are immutable post-freeze, walks parallelize trivially.                                                                                          
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
Rayon-based parallel walk traversal for independent passes (import collection, hook collection — anything that doesn't write back to arena).                                         
Per-page parallelism: arena per page, walks across pages run on different threads.                                                                                                   
Configurable thread pool size.                                                                                                                                                       
                                                                                                                                                                                     
Validation: on a 50-page app, compile time scales sublinearly with page count up to thread count.                                                                                    
Phase 10 — Cleanup and removal (1 week)                                                                                                                                              
Remove the Python implementations of migrated walks. Feature flags become permanent enables. The legacy paths existed only for validation; now they're dead code.                    
Deliverables:                                                                                                                                                                        
                                                                                                                                                                                     
Delete legacy walkers from reflex/compiler/.                                                                                                                                         
Delete feature flags.                                                                                                                                                                
Update docs.                                                                                                                                                                         
                                                                                                                                                                                     
Validation: full test suite passes without legacy paths. Benchmark shows final numbers.                                                                                              
Cross-cutting concerns                                                                                                                                                               
Side effect discipline. Already mentioned: freeze must be observation-only, mutations happen in explicit transform phase, Rust walks never call back into Python. The freeze-pass    
debug assertion (REFLEX_DEBUG_FREEZE=1) catches violations.                                                                                                                          
PyO3 boundary patterns. Snapshot construction uses per-node PyO3 calls (one per Component during freeze). Walks use zero PyO3 calls — they operate on Rust-owned data. Emit uses one 
 PyO3 call to hand finalized strings back to Python.                                                                                                                                 
Memory ownership. Arena is owned by a Rust-side struct exposed via #[pyclass] to Python as an opaque handle. Python passes the handle to walk functions, doesn't read into it. The   
arena's lifetime spans one compile invocation. For hot reload caching, arenas (or subtree fragments) persist in a Rust-side cache map keyed by hash.                                 
Plugin compatibility. Plugins stay in Python, run at transform phase. Their API contract: contribute components/imports/custom-code via well-defined hooks at app init or compile    
start. No plugin runs during walks. This may require API changes to existing plugins — audit them in Phase 0 and document migration.                                                 
Testing strategy. Three levels:                                                                                                                                                      
                                                                                                                                                                                     
Rust unit tests for walks (in reflex-walks crate, no Python).                                                                                                                        
Python integration tests calling Rust through PyO3 bindings.                                                                                                                         
End-to-end output equivalence: full compile of benchmark apps, byte-diff against golden output.                                                                                      
                                                                                                                                                                                     
Existing rust_pipeline. Reflex already has Rust code in rust_pipeline/. The new crates should live alongside it and eventually subsume it (Phase 7). Audit rust_pipeline's IR shape  
in Phase 1 — your arena design should be a strict superset.                                                                                                                          
What the first PR looks like                                                                                                                                                         
If you're going Rust-first, your first PR is Phase 0 only: the benchmark harness, the timing instrumentation, and the output-diff infrastructure. No Rust code yet. This PR sets up  
the gauntlet every subsequent PR has to pass through.                                                                                                                                
The second PR is Phase 1: crate skeleton, IR type definitions, arena implementation, interner, unit tests. Still no Python integration. The deliverable is "a Rust crate that can    
construct arenas and pass unit tests." Reviewable in isolation.                                                                                                                      
The third PR is Phase 2: freeze pass producing arenas, side-by-side with existing compile. Output diffs prove equivalence. No performance change yet (you're doing 2x the work —     
freeze AND existing walks).                                                                                                                                                          
The fourth PR is Phase 3: first Rust walk. This is where the first performance number lands. If it's not 3x faster on imports, you stop and figure out why before continuing.        
Each PR is independently reviewable, mergeable behind feature flags, and reversible. Phases 4-10 follow the same pattern.