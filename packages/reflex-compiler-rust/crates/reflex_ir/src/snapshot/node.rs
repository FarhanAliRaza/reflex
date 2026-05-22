//! `NodeSnapshot` — a single node in the flat snapshot arena.
//!
//! Hot fields live inline. Sparse data (control-flow payloads, app-wrap
//! contributions, special props, …) lives in `Snapshot` side tables keyed
//! by `NodeIdx`. See `super::tables` for the side-table types.
//!
//! The whole struct is checked at compile time to fit within 256 bytes
//! (4 cache lines). If a future change blows the budget the build fails
//! on the `const _: () = assert!(...)` below — tune the SmallVec inline
//! arities or move a field to a side table instead.

use std::ops::Range;

use smallvec::SmallVec;

use reflex_intern::Symbol;

use super::flags::NodeFlags;
use super::kinds::NodeKind;

/// Snapshot-local index into `Snapshot.nodes`. `u32` rather than `usize`
/// to keep the struct size under control — Reflex apps don't approach
/// 2^32 nodes per page.
pub type NodeIdx = u32;

/// Reference into the `Snapshot.var_data` side table.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct VarDataRef(pub u32);

impl VarDataRef {
    pub const NONE: VarDataRef = VarDataRef(u32::MAX);

    #[inline]
    pub fn is_none(self) -> bool {
        self.0 == u32::MAX
    }
}

/// `(module, name)` pair for an import entry.
///
/// Both halves are interned. `module` is the JS module specifier after
/// `format_library_name` normalization; `name` is the imported binding
/// (the local alias used inside JSX).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct ImportEntry {
    pub module: Symbol,
    pub name: Symbol,
}

impl ImportEntry {
    #[inline]
    pub const fn new(module: Symbol, name: Symbol) -> Self {
        Self { module, name }
    }
}

/// Pre-rendered hook fragment + position bucket.
///
/// `code` is the interned JS source for the hook line. `position` is the
/// `Hooks.HookPosition` enum value (0 = INTERNAL, 1 = PRE_TRIGGER,
/// 2 = POST_TRIGGER) used to sort hooks at codegen time.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default)]
pub struct HookEntry {
    pub code: Symbol,
    pub position: u8,
    _pad: [u8; 3],
}

impl HookEntry {
    #[inline]
    pub const fn new(code: Symbol, position: u8) -> Self {
        Self {
            code,
            position,
            _pad: [0; 3],
        }
    }
}

/// One node in the flat snapshot arena.
///
/// `Symbol::EMPTY` is used as the "absent" marker for the `tag`,
/// `custom_code`, and `ref_name` slots — saves 12 bytes vs `Option<Symbol>`
/// on three fields, keeping the whole struct under the 256-byte budget.
/// Callers should treat `Symbol::EMPTY` as "not set".
#[derive(Clone, Debug)]
pub struct NodeSnapshot {
    pub kind: NodeKind,
    /// JSX tag name. `Symbol::EMPTY` ⇔ "no tag" (a Fragment / Bare /
    /// missing-library Element). When unset, callers should also set the
    /// `TAG_IS_NONE` bit in `flags` so downstream walks don't have to
    /// re-check the symbol.
    pub tag: Symbol,
    /// `type(self).__qualname__` of the originating Python `Component`.
    /// Drives the app-style merge in stage 5 — every node with the same
    /// `style_key` shares the same `App.style[cls]` entry.
    pub style_key: Symbol,
    /// Pre-rendered emotion-CSS JS object literal.
    pub style: Symbol,
    pub rendered_props: SmallVec<[(Symbol, Symbol); 4]>,
    pub event_callbacks: SmallVec<[(Symbol, Symbol); 2]>,
    pub imports: SmallVec<[ImportEntry; 4]>,
    pub hooks_internal: SmallVec<[HookEntry; 2]>,
    pub hooks_user: SmallVec<[HookEntry; 1]>,
    /// Pre-rendered custom-code block. `Symbol::EMPTY` ⇔ none.
    pub custom_code: Symbol,
    pub dynamic_imports: SmallVec<[Symbol; 1]>,
    /// Ref identifier name. `Symbol::EMPTY` ⇔ no ref.
    pub ref_name: Symbol,
    pub vars_used: SmallVec<[VarDataRef; 4]>,
    /// Indices into `Snapshot.nodes` for this node's direct children. Empty
    /// range for leaf nodes.
    pub children: Range<NodeIdx>,
    pub flags: NodeFlags,
    /// `xxh3_64` of the canonical bytes of this subtree. Filled by the
    /// freeze-close pass; the `MemoizeWrapper` rewrite in stage 6 reads
    /// this to dedupe identical memo bodies.
    pub subtree_hash: u64,
}

impl Default for NodeSnapshot {
    fn default() -> Self {
        Self {
            kind: NodeKind::default(),
            tag: Symbol::EMPTY,
            style_key: Symbol::EMPTY,
            style: Symbol::EMPTY,
            rendered_props: SmallVec::new(),
            event_callbacks: SmallVec::new(),
            imports: SmallVec::new(),
            hooks_internal: SmallVec::new(),
            hooks_user: SmallVec::new(),
            custom_code: Symbol::EMPTY,
            dynamic_imports: SmallVec::new(),
            ref_name: Symbol::EMPTY,
            vars_used: SmallVec::new(),
            children: 0..0,
            flags: NodeFlags::empty(),
            subtree_hash: 0,
        }
    }
}

/// Build fails if a future change pushes `NodeSnapshot` past 256 bytes.
/// Stage 0 measured ~232 bytes on x86_64 with the `union` SmallVec layout;
/// if you hit this assertion, tune a `SmallVec<[T; N]>` arity down or
/// move a rare field into a `Snapshot` side table.
const _: () = {
    assert!(std::mem::size_of::<NodeSnapshot>() <= 256);
};
