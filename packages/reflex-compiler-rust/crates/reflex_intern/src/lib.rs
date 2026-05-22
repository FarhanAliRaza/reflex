//! Symbol interning. See plan §3, R5.
//!
//! Every identifier and namespace string in the IR is a `Symbol(u32)`. Equality
//! and hashing of identifiers becomes `u32 == u32`; the string materializes
//! only at final byte-emit time.
//!
//! The interner uses `RwLock` so concurrent emit-time `resolve_unchecked`
//! reads don't serialize against each other. Interning a novel string is
//! the only operation that takes the write lock — and only after a
//! best-effort read-side check fails to find the string already there.
//!
//! Plan's longer-term target is per-thread sharded interners or a
//! `dashmap`/`arc-swap` lock-free design; this `RwLock` step is the
//! minimum required to unblock `py.allow_threads` parallelism in
//! `compile_page_from_bytes`. The public API (`Symbol`, `intern`,
//! `resolve`, `well_known`) is stable across any future change.

use std::collections::HashMap;
use std::sync::{OnceLock, RwLock};

/// Interned string identifier.
///
/// `Symbol(0)` is reserved for the empty string so `Symbol::default()` is a
/// valid no-op. Other symbols are assigned in insertion order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Symbol(pub u32);

impl Symbol {
    pub const EMPTY: Symbol = Symbol(0);

    #[inline]
    pub fn as_u32(self) -> u32 {
        self.0
    }
}

impl Default for Symbol {
    fn default() -> Self {
        Self::EMPTY
    }
}

struct Interner {
    /// Indexed by `Symbol.0 as usize`. Strings live forever (leaked into
    /// `'static` so callers don't pay a copy at resolve time).
    strings: Vec<&'static str>,
    lookup: HashMap<&'static str, Symbol>,
}

impl Interner {
    fn new() -> Self {
        // Generous initial capacity — well-known strings + a few hundred
        // novel ones per app. Avoids early rehashes that would force
        // hot-path writers to grab the writer lock for longer.
        let mut me = Self {
            strings: Vec::with_capacity(512),
            lookup: HashMap::with_capacity(512),
        };
        let s = me.intern_inner("");
        debug_assert_eq!(s, Symbol::EMPTY);
        for name in WELL_KNOWN {
            me.intern_inner(name);
        }
        me
    }

    fn intern_inner(&mut self, s: &str) -> Symbol {
        if let Some(&sym) = self.lookup.get(s) {
            return sym;
        }
        let leaked: &'static str = Box::leak(s.to_owned().into_boxed_str());
        let sym = Symbol(self.strings.len() as u32);
        self.strings.push(leaked);
        self.lookup.insert(leaked, sym);
        sym
    }

    #[inline]
    fn resolve(&self, sym: Symbol) -> Option<&'static str> {
        self.strings.get(sym.0 as usize).copied()
    }
}

fn interner() -> &'static RwLock<Interner> {
    static IT: OnceLock<RwLock<Interner>> = OnceLock::new();
    IT.get_or_init(|| RwLock::new(Interner::new()))
}

/// Common identifiers pre-interned at startup so they get low IDs and are
/// already in the table when the first compile starts.
const WELL_KNOWN: &[&str] = &[
    "rx.",
    "$/",
    "reflex___state____",
    "__reflex_",
    "react",
    "useState",
    "useEffect",
    "useCallback",
    "useMemo",
    "useRef",
    "useContext",
    "useReducer",
    "jsx",
    "Fragment",
    "children",
    "key",
    "ref",
    "className",
    "style",
    "onClick",
    "onChange",
    "onSubmit",
];

/// Intern a string, returning its `Symbol`.
///
/// Fast-path: takes the read lock first and returns the existing symbol
/// without ever blocking concurrent readers. Only escalates to the write
/// lock when the string is genuinely novel.
pub fn intern(s: &str) -> Symbol {
    let it = interner();
    if let Some(&sym) = it.read().unwrap().lookup.get(s) {
        return sym;
    }
    it.write().unwrap().intern_inner(s)
}

/// Resolve a `Symbol` back to its string. Returns `None` if the symbol was
/// created by a different interner instance (shouldn't happen in normal use).
#[inline]
pub fn resolve(sym: Symbol) -> Option<&'static str> {
    interner().read().unwrap().resolve(sym)
}

/// Resolve, panicking on unknown symbol. Use only when an unknown symbol is a
/// program bug, not a recoverable error.
#[inline]
pub fn resolve_unchecked(sym: Symbol) -> &'static str {
    resolve(sym).expect("symbol not in interner")
}

/// Look up the `Symbol` for a known-pre-interned string. Returns `None` if the
/// string was never interned. Useful for hot-path comparisons that want to
/// avoid `intern()`'s writer lock.
pub fn well_known(s: &str) -> Option<Symbol> {
    interner().read().unwrap().lookup.get(s).copied()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_is_symbol_zero() {
        assert_eq!(intern(""), Symbol::EMPTY);
    }

    #[test]
    fn same_string_same_symbol() {
        let a = intern("foo_bar");
        let b = intern("foo_bar");
        assert_eq!(a, b);
    }

    #[test]
    fn different_strings_different_symbols() {
        let a = intern("alpha");
        let b = intern("beta");
        assert_ne!(a, b);
    }

    #[test]
    fn resolve_round_trip() {
        let s = intern("hello_world");
        assert_eq!(resolve(s).unwrap(), "hello_world");
    }

    #[test]
    fn well_known_returns_some() {
        assert!(well_known("rx.").is_some());
        assert!(well_known("react").is_some());
    }
}
