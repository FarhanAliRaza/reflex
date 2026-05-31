//! Flat-arena snapshot IR. See `rust_port_plan.md` §"IR schema".
//!
//! Stage 0 introduces this module alongside the existing tree IR. The
//! `freeze` pass in `reflex_pyread` is the only producer; stages 1–6
//! progressively cut over consumers from the tree IR to read here. Once
//! every consumer has migrated (stage 7), the tree IR is deleted.

use std::collections::HashMap;
use std::ops::Range;

use smallvec::SmallVec;

use reflex_intern::Symbol;

use crate::SourceLoc;

pub mod builder;
pub mod flags;
pub mod kinds;
pub mod node;
pub mod tables;

pub use builder::{close_snapshot, SnapshotBuilder};
pub use flags::{MemoizationDisposition, NodeFlags};
pub use kinds::NodeKind;
pub use node::{HookEntry, ImportEntry, NodeIdx, NodeSnapshot, VarDataRef};
pub use tables::{AppWrap, ControlFlowExtras, MemoizeBody, PageMeta, VarDataEntry};

/// The flat-arena snapshot a `freeze_component` call produces. One per
/// frozen Component tree.
///
/// `nodes` is the primary arena, indexed by `NodeIdx`. Nodes are pushed in
/// parent-before-children order so any child's `NodeIdx` is strictly
/// greater than its parent's — this lets the freeze-close pass walk
/// backward to compute `subtree_hash` and `propagates_hooks` without
/// recursion.
#[derive(Default)]
pub struct Snapshot {
    /// Primary node arena.
    pub nodes: Vec<NodeSnapshot>,
    /// Memoized subtree bodies; populated by stage 6.
    pub memo_bodies: Vec<MemoizeBody>,
    /// `subtree_hash` → `memo_bodies` index. Stage 6 uses this to dedupe
    /// identical memo bodies across pages.
    pub memo_dedup: HashMap<u64, u32>,
    /// Deduped `VarData` entries. Each `VarDataRef` is a `u32` index here.
    pub var_data: Vec<VarDataEntry>,
    /// Dense backing for `VarDataEntry.hooks` ranges.
    pub var_hooks: Vec<Symbol>,
    /// Dense backing for `VarDataEntry.imports` ranges.
    pub var_imports: Vec<(Symbol, Symbol)>,
    /// Dense backing for `VarDataEntry.deps` ranges.
    pub var_deps: Vec<Symbol>,
    /// Dense backing for `VarDataEntry.components` ranges.
    pub var_components: Vec<Symbol>,
    /// Sparse per-node control-flow payloads.
    pub control_flow: ControlFlowExtras,
    /// Stage 6 wrapper-substitution table. Maps `node_idx → wrapper_idx`
    /// where `wrapper_idx` points at a synthetic `MemoizeWrapper` node
    /// appended to the arena. Emitters consult this on every visited
    /// node so a candidate node renders as its wrapper at the page call
    /// site (and renders its full content inside a separate memo body
    /// module). Empty when no candidates were identified.
    pub wrap_redirects: HashMap<NodeIdx, NodeIdx>,
    /// Per-node source locations. Off by default; populated only when
    /// the freeze caller asks for source maps (a later stage feature).
    pub source_locs: Vec<SourceLoc>,
    /// Deduped app-wrap contributions. Stage 5 fills this from
    /// `_get_app_wrap_components()`.
    pub app_wraps: Vec<AppWrap>,
    /// Extra custom-code blocks attached to specific nodes (rare; the
    /// common case carries one block per node in
    /// `NodeSnapshot.custom_code`).
    pub add_custom_code_extra: HashMap<NodeIdx, SmallVec<[Symbol; 2]>>,
    /// Special props (vars rendered as `{...x}`) per node.
    pub special_props: HashMap<NodeIdx, SmallVec<[Symbol; 1]>>,
    /// Rename-prop map (e.g. `class_name` → `className`) per node. Stage 4
    /// populates this when freeze observes a prop the legacy renderer
    /// would have renamed.
    pub rename_props: HashMap<NodeIdx, SmallVec<[(Symbol, Symbol); 1]>>,
    /// Emit-time override for `event_callbacks` JSX values, keyed by
    /// `(node_idx, trigger_symbol)`. Populated by the memo-body emit
    /// path (where every event needs to be `useCallback`-hoisted to a
    /// stable identifier) just before walking the JSX. The page-emit
    /// path leaves this empty. `write_props_and_events` consults the
    /// map and, when an override is present, emits `<trigger>:
    /// <override_name>` instead of the raw chain expression. Never
    /// mutates `event_callbacks` itself — the original chain stays
    /// observable for tooling, hash stability, and the matching
    /// `const <override> = useCallback(<chain>, ...)` declaration the
    /// memo-body emit splices into the hooks block.
    pub event_callback_overrides: HashMap<(NodeIdx, Symbol), Symbol>,
    /// `App.style` map keyed by component qualname. Stage 5 reads this
    /// to apply theme/app styles in the arena.
    pub app_style_map: HashMap<Symbol, Symbol>,
    /// Per-node `id(component)` captured during the PyO3 freeze walk.
    /// Used so callers (e.g. memoize-decision precomputation) can map
    /// snapshot node indices back to the original Python `Component`
    /// instances without a second PyO3 walk. Empty when the freeze pass
    /// is driven by something other than `freeze_component` (e.g. test
    /// fixtures building snapshots directly).
    pub node_pyids: Vec<usize>,
    /// Index of the page root in `nodes`. Set by the freeze pass.
    pub root: NodeIdx,
    /// Page-level metadata captured at freeze time.
    pub page_meta: PageMeta,
}

impl Snapshot {
    /// Total node count. Equivalent to `nodes.len()`.
    #[inline]
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    /// Empty snapshot (no root, no nodes). Equivalent to `Snapshot::default()`.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Access a node by index. Panics if out of bounds.
    #[inline]
    pub fn node(&self, idx: NodeIdx) -> &NodeSnapshot {
        &self.nodes[idx as usize]
    }

    /// Indices of `node`'s direct children. Cheap — returns a `Range`
    /// copy; iterating it costs one cache miss per child.
    #[inline]
    pub fn children_of(&self, idx: NodeIdx) -> Range<NodeIdx> {
        self.nodes[idx as usize].children.clone()
    }
}
