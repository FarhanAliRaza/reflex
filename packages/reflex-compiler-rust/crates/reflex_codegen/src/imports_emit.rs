//! Stage 2 imports emitter. Mirrors
//! `reflex.compiler.utils.compile_imports` reduced to the JSX-block shape:
//! one `import { … } from "<module>";` per module, names deduped and
//! sorted alphabetically.
//!
//! `Symbol::EMPTY` modules and binding strings are skipped. Modules that
//! match `ALIAS_PREFIXES` get the `$` rewrite (matching
//! `reflex_pyread::imports::apply_alias_prefix`) so Vite's `$` alias
//! resolves them to `.web/<prefix>/...`.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use reflex_intern::resolve_unchecked;
use reflex_ir::ImportEntry;

const ALIAS_PREFIXES: &[&str] = &["/utils/", "/components/", "/styles/", "/public/"];

/// Format a sequence of `(module, name)` pairs into the rendered JSX
/// import block. Pairs may arrive in any order; the output is
/// deterministic: modules sorted alphabetically with the `$/` prefix
/// applied, and within each module the bindings sorted alphabetically
/// and deduped.
pub fn emit_imports_block(entries: &[ImportEntry]) -> String {
    let mut groups: BTreeMap<String, BTreeSet<&'static str>> = BTreeMap::new();
    for entry in entries {
        let module = resolve_unchecked(entry.module);
        if module.is_empty() {
            continue;
        }
        let binding = resolve_unchecked(entry.name);
        if binding.is_empty() {
            continue;
        }
        let module_aliased = apply_alias_prefix(module);
        groups.entry(module_aliased).or_default().insert(binding);
    }
    let mut out = String::with_capacity(groups.len() * 64);
    for (module, names) in groups {
        if !out.is_empty() {
            out.push('\n');
        }
        out.push_str("import { ");
        for (i, name) in names.iter().enumerate() {
            if i > 0 {
                out.push_str(", ");
            }
            out.push_str(name);
        }
        out.push_str(" } from \"");
        out.push_str(&module);
        out.push_str("\";");
    }
    out
}

fn apply_alias_prefix(module: &str) -> String {
    if ALIAS_PREFIXES.iter().any(|p| module.starts_with(p)) {
        let mut out = String::with_capacity(module.len() + 1);
        out.push('$');
        out.push_str(module);
        out
    } else {
        module.to_owned()
    }
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::ImportEntry;

    use super::*;

    fn ie(module: &str, name: &str) -> ImportEntry {
        ImportEntry::new(intern(module), intern(name))
    }

    #[test]
    fn sorts_and_dedupes_within_module() {
        let entries = vec![
            ie("react", "useState"),
            ie("react", "useEffect"),
            ie("react", "useState"),
        ];
        let out = emit_imports_block(&entries);
        assert_eq!(out, "import { useEffect, useState } from \"react\";");
    }

    #[test]
    fn modules_sorted_alphabetically() {
        let entries = vec![ie("zebra", "Z"), ie("apple", "A"), ie("react", "useState")];
        let out = emit_imports_block(&entries);
        let lines: Vec<&str> = out.lines().collect();
        assert_eq!(lines[0], "import { A } from \"apple\";");
        assert_eq!(lines[1], "import { useState } from \"react\";");
        assert_eq!(lines[2], "import { Z } from \"zebra\";");
    }

    #[test]
    fn alias_prefix_rewrites_dollar() {
        let entries = vec![ie("/utils/state", "refs")];
        let out = emit_imports_block(&entries);
        assert!(out.contains("from \"$/utils/state\""));
    }

    #[test]
    fn empty_inputs_produce_empty_output() {
        use reflex_intern::Symbol;

        assert!(emit_imports_block(&[]).is_empty());
        // Empty module / name entries are skipped.
        let s = ImportEntry::new(Symbol::EMPTY, intern("X"));
        assert!(emit_imports_block(&[s]).is_empty());
    }
}
