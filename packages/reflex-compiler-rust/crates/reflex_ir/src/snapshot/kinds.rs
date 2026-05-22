//! `NodeKind` discriminant for `NodeSnapshot`.
//!
//! Mirrors the tree-IR `Component` variants (Element..Expr) and adds
//! `MemoizeWrapper`, the synthetic node Stage 6 inserts when a subtree
//! becomes a memoized child. Stage 0 only emits `Element`, `Text`,
//! `Foreach`, `Cond`, `Match`, `Memoize`, `Fragment`, `Expr` — the
//! `MemoizeWrapper` slot exists so subsequent stages can extend without
//! renumbering.

/// Kind discriminator on every `NodeSnapshot`.
#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default)]
pub enum NodeKind {
    #[default]
    Element = 0,
    Text = 1,
    Foreach = 2,
    Cond = 3,
    Match = 4,
    Memoize = 5,
    Fragment = 6,
    Expr = 7,
    MemoizeWrapper = 8,
}

impl NodeKind {
    /// True for nodes whose JSX shape is "tag(props, children)" — drives
    /// whether the freeze pass needs to walk children.
    #[inline]
    pub fn has_children(self) -> bool {
        matches!(
            self,
            NodeKind::Element
                | NodeKind::Fragment
                | NodeKind::Foreach
                | NodeKind::Cond
                | NodeKind::Match
                | NodeKind::Memoize
                | NodeKind::MemoizeWrapper
        )
    }
}
