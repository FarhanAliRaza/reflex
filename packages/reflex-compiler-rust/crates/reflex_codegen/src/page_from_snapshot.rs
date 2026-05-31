//! Stage 4 JSX emitter that walks `reflex_ir::Snapshot` instead of the
//! tree IR. Mirrors the shape `jsx.rs::emit_component` produces so
//! diff-harness comparisons against the legacy emit stay byte-comparable
//! on the subset of components Stage 4 covers.
//!
//! Only the structural kinds (`Element`, `Text`, `Fragment`, `Expr`) are
//! fully covered. `Foreach`, `Cond`, `Match`, `Memoize` need
//! `ControlFlowExtras` populated during freeze (a Stage 5+ task); they
//! emit `null` placeholders until that lands. Production runs still use
//! `read_page` + `emit_page` for those node kinds.

use reflex_intern::{intern, resolve_unchecked, Symbol};
use reflex_ir::{NodeIdx, NodeKind, NodeSnapshot, Snapshot};

use crate::buffer::CodeBuffer;
use crate::harvest::{collect_custom_code, collect_imports, page_needs_ref};
use crate::hooks_emit::{render_hooks, render_hooks_for_subtree};

/// Baseline runtime aliases that every page module needs. Mirrors
/// `page::RUNTIME_IMPORTS` so the legacy and arena paths emit the same
/// header block.
const PAGE_RUNTIME_IMPORTS: &[(&str, &str)] = &[
    ("react", "Fragment"),
    ("react", "useCallback"),
    ("react", "useContext"),
    ("react", "useRef"),
    ("$/utils/context", "EventLoopContext"),
    ("$/utils/context", "StateContexts"),
    ("$/utils/state", "refs"),
    ("$/utils/state", "ReflexEvent"),
    ("@emotion/react", "jsx"),
];

/// Module-import prefix rewrite — `apply_alias_prefix` in
/// `reflex_pyread::imports`. Modules starting with `/utils/`,
/// `/components/`, `/styles/`, `/public/` get a leading `$` so Vite
/// resolves them via the `$` alias.
const ALIAS_PREFIXES: &[&str] = &["/utils/", "/components/", "/styles/", "/public/"];

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

/// PR4: emit a full page module from a `Snapshot` — the cutover entry
/// point that replaces `walk_and_memoize` → `page_to_ir` →
/// `compile_page_from_bytes`. Mirrors `page::emit_page_inner` output
/// shape so the diff harness can compare byte-for-byte against the
/// legacy emit.
///
/// Inputs:
///
/// * `snapshot` — the post-`memoize_arena_pass` arena. `wrap_redirects`
///   is consulted by `emit_node` so memoize candidates render as their
///   synthetic `MemoizeWrapper` at the page call site.
/// * `route_ident` — JS identifier for `__reflex_route_ident`.
/// * `route` — URL path for `__reflex_route`.
/// * `title` / `meta` — page-document metadata; when non-empty the root
///   JSX gets wrapped in `jsx(Fragment, {}, <root>, jsx("title", …),
///   jsx("meta", …), …)`.
/// * `custom_code_extra` — additional custom-code blocks the Python
///   caller wants to splice (passed through verbatim).
/// * `hooks_body_extra` — additional pre-rendered hooks the Python
///   caller wants to splice between the state-context lines and the
///   `return`. Empty string skips.
pub fn emit_page_module_from_snapshot(
    buf: &mut CodeBuffer,
    snapshot: &Snapshot,
    route_ident: &str,
    route: &str,
    title: Option<&str>,
    meta: &[(String, String)],
    custom_code_extra: &[&str],
    hooks_body_extra: &str,
) {
    emit_page_imports(buf, snapshot);

    // Per-node custom_code blocks first (markdown component maps,
    // JIT-built helpers); then Python-supplied extras. Matches the
    // legacy ordering (`page_template` splices `_get_all_custom_code()`
    // before the `export default function` line).
    for code in collect_custom_code(snapshot) {
        let block = resolve_unchecked(code);
        if block.is_empty() {
            continue;
        }
        buf.write_byte(b'\n');
        buf.write_str(block);
        if !block.ends_with('\n') {
            buf.write_byte(b'\n');
        }
    }
    for block in custom_code_extra {
        if block.is_empty() {
            continue;
        }
        buf.write_byte(b'\n');
        buf.write_str(block);
        if !block.ends_with('\n') {
            buf.write_byte(b'\n');
        }
    }

    buf.write_str("\nexport default function Component() {\n");
    if page_needs_ref(snapshot) {
        buf.write_str("  const ref_root = useRef(null); refs[\"ref_root\"] = ref_root;\n");
    }
    for binding in collect_state_bindings(snapshot) {
        buf.write_str("  const ");
        buf.write_str(&binding);
        buf.write_str(" = useContext(StateContexts.");
        buf.write_str(&binding);
        buf.write_str(");\n");
    }
    buf.write_str("  const [addEvents, connectErrors] = useContext(EventLoopContext);\n");

    // Hooks: per-node hooks_internal/hooks_user via `render_hooks`,
    // then Python's extras spliced verbatim. The latter preserves the
    // current `_render_hooks` output for hooks that aren't yet
    // captured in the arena (e.g. those produced by the markdown
    // ComponentMap render).
    let hooks_block = render_hooks(snapshot, &[]);
    let trimmed = hooks_block.trim();
    if !trimmed.is_empty() {
        buf.write_str(&hooks_block);
        if !hooks_block.ends_with('\n') {
            buf.write_byte(b'\n');
        }
    }
    if !hooks_body_extra.is_empty() {
        buf.write_str(hooks_body_extra);
        if !hooks_body_extra.ends_with('\n') {
            buf.write_byte(b'\n');
        }
    }

    let wrap_in_fragment = title.is_some() || !meta.is_empty();
    buf.write_str("  return ");
    if wrap_in_fragment {
        buf.write_str("jsx(Fragment, {}, ");
        emit_jsx_from_snapshot(buf, snapshot);
        if let Some(title_s) = title {
            buf.write_str(", jsx(\"title\", {}, ");
            buf.write_str("\"");
            write_js_string_escaped(buf, title_s);
            buf.write_str("\")");
        }
        for (name, content) in meta {
            buf.write_str(", jsx(\"meta\", {");
            let key = if name.starts_with("og:") || name.starts_with("twitter:") {
                "property"
            } else {
                "name"
            };
            buf.write_str(key);
            buf.write_str(": \"");
            write_js_string_escaped(buf, name);
            buf.write_str("\", content: \"");
            write_js_string_escaped(buf, content);
            buf.write_str("\"})");
        }
        buf.write_str(")");
    } else {
        emit_jsx_from_snapshot(buf, snapshot);
    }
    buf.write_str(";\n}\n");

    buf.write_str("\nexport const __reflex_route = \"");
    write_js_string_escaped(buf, route);
    buf.write_str("\";\n");
    buf.write_str("export const __reflex_route_ident = \"");
    write_js_string_escaped(buf, route_ident);
    buf.write_str("\";\n");
    if let Some(title_s) = title {
        buf.write_str("export const __reflex_title = \"");
        write_js_string_escaped(buf, title_s);
        buf.write_str("\";\n");
    }
}

/// PR4: emit a memo body module from a Snapshot — the wrapper module
/// the page module imports. Mirrors `memo::emit_memo_module` but reads
/// the body JSX from the snapshot's `MemoizeBody.root` and renders the
/// captured subtree via `emit_memo_body_jsx`.
pub fn emit_memo_module_from_snapshot(
    buf: &mut CodeBuffer,
    snapshot: &Snapshot,
    body_root: NodeIdx,
    name: &str,
    signature: &str,
    pre_hooks_extra: &str,
) {
    emit_memo_module_imports(buf, snapshot);
    buf.write_str("\nexport const ");
    buf.write_str(name);
    buf.write_str(" = memo(");
    buf.write_str(signature);
    buf.write_str(" => {\n");
    if page_needs_ref(snapshot) {
        buf.write_str("  const ref_root = useRef(null); refs[\"ref_root\"] = ref_root;\n");
    }
    for binding in collect_state_bindings(snapshot) {
        buf.write_str("  const ");
        buf.write_str(&binding);
        buf.write_str(" = useContext(StateContexts.");
        buf.write_str(&binding);
        buf.write_str(");\n");
    }
    buf.write_str("  const [addEvents, connectErrors] = useContext(EventLoopContext);\n");

    let hooks_block = render_hooks_for_subtree(snapshot, body_root, &[]);
    let trimmed = hooks_block.trim();
    if !trimmed.is_empty() {
        buf.write_str(&hooks_block);
        if !hooks_block.ends_with('\n') {
            buf.write_byte(b'\n');
        }
    }
    if !pre_hooks_extra.is_empty() {
        buf.write_str("  ");
        buf.write_str(pre_hooks_extra);
        if !pre_hooks_extra.ends_with('\n') {
            buf.write_str("\n");
        }
    }

    buf.write_str("  return ");
    emit_memo_body_jsx(buf, snapshot, body_root);
    buf.write_str(";\n});\n");
}

/// Memo runtime aliases (mirrors `memo::MEMO_RUNTIME_IMPORTS`).
const MEMO_RUNTIME_IMPORTS: &[(&str, &str)] = &[
    ("react", "memo"),
    ("react", "useCallback"),
    ("react", "useContext"),
    ("react", "useRef"),
    ("$/utils/context", "EventLoopContext"),
    ("$/utils/context", "StateContexts"),
    ("$/utils/state", "refs"),
    ("$/utils/state", "ReflexEvent"),
    ("@emotion/react", "jsx"),
];

fn emit_page_imports(buf: &mut CodeBuffer, snapshot: &Snapshot) {
    emit_combined_imports(buf, snapshot, PAGE_RUNTIME_IMPORTS);
}

fn emit_memo_module_imports(buf: &mut CodeBuffer, snapshot: &Snapshot) {
    emit_combined_imports(buf, snapshot, MEMO_RUNTIME_IMPORTS);
}

fn emit_combined_imports(buf: &mut CodeBuffer, snapshot: &Snapshot, runtime: &[(&str, &str)]) {
    // Combine runtime + harvested per-node imports, then group by
    // module preserving first-seen order — same shape as
    // `page::emit_imports_grouped_by_module`.
    let mut all: Vec<(String, String)> = Vec::with_capacity(runtime.len() + 16);
    let mut runtime_react: Vec<(String, String)> = runtime
        .iter()
        .filter(|(m, _)| *m == "react")
        .map(|(m, n)| (m.to_string(), n.to_string()))
        .collect();
    let runtime_rest: Vec<(String, String)> = runtime
        .iter()
        .filter(|(m, _)| *m != "react")
        .map(|(m, n)| (m.to_string(), n.to_string()))
        .collect();
    all.append(&mut runtime_react);
    for ie in collect_imports(snapshot) {
        let module = resolve_unchecked(ie.module);
        let name = resolve_unchecked(ie.name);
        if module.is_empty() || name.is_empty() {
            continue;
        }
        let aliased = apply_alias_prefix(module);
        all.push((aliased, name.to_owned()));
    }
    all.extend(runtime_rest);

    let mut modules: Vec<String> = Vec::new();
    for (m, _) in &all {
        if !modules.contains(m) {
            modules.push(m.clone());
        }
    }
    for module in &modules {
        let mut emitted: Vec<String> = Vec::new();
        buf.write_str("import { ");
        let mut first = true;
        for (m, name) in &all {
            if m != module {
                continue;
            }
            if emitted.iter().any(|n| n == name) {
                continue;
            }
            emitted.push(name.clone());
            if !first {
                buf.write_str(", ");
            }
            first = false;
            buf.write_str(name);
        }
        let module_aliased = apply_alias_prefix(module);
        buf.write_str(" } from \"");
        buf.write_str(&module_aliased);
        buf.write_str("\";\n");
    }
}

/// Scan every node's `rendered_props`, `event_callbacks`, and
/// `hooks_*` for `reflex___state__…` identifiers. Mirrors the Python
/// `bridge.collect_state_bindings` walk. Dedupes in observation order.
fn collect_state_bindings(snapshot: &Snapshot) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    for node in &snapshot.nodes {
        for (_k, v) in &node.rendered_props {
            scan_for_state_idents(resolve_unchecked(*v), &mut out, &mut seen);
        }
        for (_k, v) in &node.event_callbacks {
            scan_for_state_idents(resolve_unchecked(*v), &mut out, &mut seen);
        }
        for h in node.hooks_internal.iter().chain(node.hooks_user.iter()) {
            scan_for_state_idents(resolve_unchecked(h.code), &mut out, &mut seen);
        }
    }
    out
}

/// Mirror `reflex_pyread::pyo3_reader::find_state_idents` for use over
/// already-rendered JS expression strings. State identifiers match the
/// pattern `reflex___state____state__<name>_state`.
fn scan_for_state_idents(
    expr: &str,
    out: &mut Vec<String>,
    seen: &mut std::collections::HashSet<String>,
) {
    const PREFIX: &str = "reflex___state____state__";
    let bytes = expr.as_bytes();
    let mut i = 0;
    while i + PREFIX.len() <= bytes.len() {
        if &bytes[i..i + PREFIX.len()] == PREFIX.as_bytes() {
            let start = i;
            i += PREFIX.len();
            while i < bytes.len() {
                let c = bytes[i];
                if c.is_ascii_alphanumeric() || c == b'_' {
                    i += 1;
                } else {
                    break;
                }
            }
            let ident = &expr[start..i];
            // Must end with `_state` to count.
            if ident.ends_with("_state") {
                if seen.insert(ident.to_owned()) {
                    out.push(ident.to_owned());
                }
            }
        } else {
            i += 1;
        }
    }
}

/// Render the page's JSX expression rooted at `snapshot.root`.
/// Output shape matches `emit_component`: one nested `jsx(<tag>, {…}, …)`
/// expression per element, with text leaves as quoted JS strings.
pub fn emit_jsx_from_snapshot(buf: &mut CodeBuffer, snapshot: &Snapshot) {
    if snapshot.is_empty() {
        buf.write_str("null");
        return;
    }
    emit_node(buf, snapshot, snapshot.root);
}

/// Render a memo body's JSX rooted at `body_root`.
///
/// The body Component was built by `walk_and_memoize` /
/// `create_passthrough_component_memo` Python-side:
///
/// - **Passthrough bodies** (most common): `body.children` is a single
///   `Bare(Var(_js_expr="children"))` placeholder. The normal emit
///   walks that placeholder and renders the literal `children`
///   identifier — which is the JS function parameter the wrapper's
///   `memo(({ children }) => …)` introduces.
/// - **Snapshot bodies**: `body.children` is the original subtree
///   verbatim, with no `children` placeholder. The wrapper signature
///   is `()` (no `children` param), and the body renders its full
///   subtree inline.
///
/// In both cases the right behavior is to emit the body's tree via
/// the normal `emit_node` walk — the body's actual children (literal
/// or placeholder) drive the output. We do skip the `wrap_redirects`
/// check at the body root specifically: a candidate node can be the
/// body root, and we want to emit *its* tag/props, not the synthetic
/// wrapper redirect.
pub fn emit_memo_body_jsx(buf: &mut CodeBuffer, snapshot: &Snapshot, body_root: NodeIdx) {
    if snapshot.is_empty() {
        buf.write_str("null");
        return;
    }
    let node = snapshot.node(body_root);
    match node.kind {
        NodeKind::Element => emit_element(buf, snapshot, body_root, node),
        NodeKind::Text => emit_text(buf, snapshot, body_root),
        NodeKind::Expr => emit_expr(buf, snapshot, body_root),
        NodeKind::Fragment => emit_fragment(buf, snapshot, node),
        NodeKind::MemoizeWrapper => emit_memoize_wrapper(buf, snapshot, body_root, node),
        NodeKind::Foreach => emit_foreach(buf, snapshot, body_root, node),
        NodeKind::Cond => emit_cond(buf, snapshot, body_root, node),
        NodeKind::Match => emit_match(buf, snapshot, body_root, node),
        NodeKind::Memoize => emit_memoize(buf, snapshot, body_root, node),
    }
}

fn emit_node(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx) {
    // Stage 6: when a node is the source of a wrapper redirect, emit the
    // synthetic `MemoizeWrapper` in its place. The original node stays
    // in the arena (the body-emit pass reads from it) but at the page
    // call site only the wrapper appears.
    let emit_idx = snapshot.wrap_redirects.get(&idx).copied().unwrap_or(idx);
    let node = snapshot.node(emit_idx);
    match node.kind {
        NodeKind::Element => emit_element(buf, snapshot, emit_idx, node),
        NodeKind::Text => emit_text(buf, snapshot, emit_idx),
        NodeKind::Expr => emit_expr(buf, snapshot, emit_idx),
        NodeKind::Fragment => emit_fragment(buf, snapshot, node),
        NodeKind::MemoizeWrapper => emit_memoize_wrapper(buf, snapshot, emit_idx, node),
        NodeKind::Foreach => emit_foreach(buf, snapshot, emit_idx, node),
        NodeKind::Cond => emit_cond(buf, snapshot, emit_idx, node),
        NodeKind::Match => emit_match(buf, snapshot, emit_idx, node),
        NodeKind::Memoize => emit_memoize(buf, snapshot, emit_idx, node),
    }
}

fn emit_foreach(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let iter_expr = snapshot
        .control_flow
        .foreach_iter
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("[]");
    buf.write_str("(");
    buf.write_str(iter_expr);
    buf.write_str(").map((item, index) => ");
    if let Some(body) = node.children.clone().next() {
        emit_node(buf, snapshot, body);
    } else {
        buf.write_str("null");
    }
    buf.write_str(")");
}

fn emit_cond(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let test = snapshot
        .control_flow
        .cond_test
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("false");
    buf.write_str("((");
    buf.write_str(test);
    buf.write_str(") ? ");
    let mut iter = node.children.clone();
    if let Some(then_idx) = iter.next() {
        emit_node(buf, snapshot, then_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str(" : ");
    if let Some(else_idx) = iter.next() {
        emit_node(buf, snapshot, else_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str(")");
}

fn emit_match(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, _node: &NodeSnapshot) {
    let value = snapshot
        .control_flow
        .match_value
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("null");
    buf.write_str("match_template((");
    buf.write_str(value);
    buf.write_str("), [");
    if let Some(arms) = snapshot.control_flow.match_arms.get(&idx) {
        for (i, (case, body_idx)) in arms.iter().enumerate() {
            if i > 0 {
                buf.write_str(", ");
            }
            buf.write_str("[");
            buf.write_str(resolve_unchecked(*case));
            buf.write_str(", ");
            emit_node(buf, snapshot, *body_idx);
            buf.write_str("]");
        }
    }
    buf.write_str("], ");
    if let Some(default_idx) = snapshot.control_flow.match_default.get(&idx) {
        emit_node(buf, snapshot, *default_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str(")");
}

fn emit_memoize(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let key = snapshot
        .control_flow
        .memo_key
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .map(|s| s.to_owned())
        .unwrap_or_else(|| format!("\"{:016x}\"", node.subtree_hash));
    buf.write_str("jsx(MemoWrapper, {key: ");
    buf.write_str(&key);
    buf.write_str("}");
    for child_idx in node.children.clone() {
        buf.write_str(", ");
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

fn emit_element(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    buf.write_str("jsx(");
    if node.tag == reflex_intern::Symbol::EMPTY {
        buf.write_str("Fragment");
    } else {
        buf.write_str(resolve_unchecked(node.tag));
    }
    buf.write_str(", {");
    write_props_and_events(buf, snapshot, idx, node);
    buf.write_str("}");
    for child_idx in node.children.clone() {
        buf.write_str(", ");
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

/// Shared prop / event / style emission.
///
/// Mirrors the Python emit pipeline:
/// 1. Collect every prop source (rendered_props, event_callbacks, ref,
///    css) with its CAMEL-CASE pre-rename key — the same names
///    `Tag.add_props` would produce.
/// 2. Sort alphabetically by pre-rename key (matches
///    `format_props(sorted(...))`).
/// 3. Apply `_rename_props` to each key as a prefix replace (matches
///    `Component._replace_prop_names`). Position-stable: a renamed
///    entry stays where its original key sorted to.
/// 4. Emit `<key>: <value>` separated by `, `.
///
/// Dedupes: same key from rendered_props and event_callbacks → event
/// wins (it carries the post-Stage-6 useCallback identifier);
/// rendered_props' `css` or `ref` key wins over `node.style` /
/// `node.ref_name` because the explicit prop is what the user wrote.
fn write_props_and_events(
    buf: &mut CodeBuffer,
    snapshot: &Snapshot,
    idx: NodeIdx,
    node: &NodeSnapshot,
) {
    let css_key = intern("css");
    let ref_key = intern("ref");

    // Build the merged entry set with camel-case keys. `rendered_props`
    // keys are already camel (freeze stored them that way); event
    // triggers are stored snake (`on_click`) so the `fix_event_triggers_for_memo`
    // pass can produce snake-named memo identifiers — camelize them
    // here on the fly so they sort + emit as camel JSX keys.
    let event_camel_keys: smallvec::SmallVec<[Symbol; 2]> = node
        .event_callbacks
        .iter()
        .map(|(k, _)| intern(&snake_to_camel(resolve_unchecked(*k))))
        .collect();

    let mut entries: smallvec::SmallVec<[(Symbol, Symbol); 8]> = smallvec::SmallVec::new();
    let mut seen: smallvec::SmallVec<[Symbol; 8]> = smallvec::SmallVec::new();
    for (name, value) in &node.rendered_props {
        if event_camel_keys.contains(name) {
            continue;
        }
        entries.push((*name, *value));
        seen.push(*name);
    }
    for ((trigger, expr), camel_key) in node.event_callbacks.iter().zip(event_camel_keys.iter()) {
        // Memo-body emit precomputes a `useCallback`-hoisted identifier
        // per (node_idx, trigger) into `event_callback_overrides`. When
        // present, emit that identifier instead of the raw chain so the
        // body references the stable name declared in the hooks block.
        // Page-emit leaves the map empty so this falls back to `expr`.
        let final_value = snapshot
            .event_callback_overrides
            .get(&(idx, *trigger))
            .copied()
            .unwrap_or(*expr);
        entries.push((*camel_key, final_value));
        seen.push(*camel_key);
    }
    if node.ref_name != Symbol::EMPTY && !seen.contains(&ref_key) {
        entries.push((ref_key, node.ref_name));
        seen.push(ref_key);
    }
    if node.style != Symbol::EMPTY && !seen.contains(&css_key) {
        entries.push((css_key, node.style));
    }

    entries.sort_by(|a, b| resolve_unchecked(a.0).cmp(resolve_unchecked(b.0)));

    let renames = snapshot.rename_props.get(&idx);

    let mut first = true;
    for (name, value) in &entries {
        if !first {
            buf.write_str(", ");
        }
        first = false;
        let key_str = resolve_unchecked(*name);
        let renamed = renames
            .and_then(|map| apply_rename_prefix(key_str, map))
            .unwrap_or_else(|| key_str.to_owned());
        write_prop_key(buf, &renamed);
        buf.write_str(": ");
        buf.write_str(resolve_unchecked(*value));
    }
}

/// Snake-case to camel-case for event trigger keys at emit time.
/// Mirrors `reflex_base.utils.format.to_camel_case` with
/// `treat_hyphens_as_underscores=False`.
fn snake_to_camel(name: &str) -> String {
    if !name.contains('_') {
        return name.to_owned();
    }
    let mut out = String::with_capacity(name.len());
    let mut iter = name.split('_');
    if let Some(first) = iter.next() {
        out.push_str(first);
    }
    for word in iter {
        let mut chars = word.chars();
        if let Some(c) = chars.next() {
            out.extend(c.to_uppercase());
            out.extend(chars);
        }
    }
    out
}

/// Apply `_rename_props` prefix-replace to a single key. Mirrors
/// `Component._replace_prop_names` (component.py:1495):
/// `prop.startswith(old) → prop.replace(old, new, 1)`. Returns `Some`
/// when at least one rule matched, `None` otherwise — letting callers
/// skip the allocation when no rename applies.
fn apply_rename_prefix(
    camel_key: &str,
    renames: &smallvec::SmallVec<[(Symbol, Symbol); 1]>,
) -> Option<String> {
    for (old_sym, new_sym) in renames {
        let old = resolve_unchecked(*old_sym);
        if camel_key.starts_with(old) {
            let new = resolve_unchecked(*new_sym);
            return Some(format!("{}{}", new, &camel_key[old.len()..]));
        }
    }
    None
}

fn emit_text(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx) {
    let text = snapshot
        .control_flow
        .text_value
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("");
    buf.write_str("\"");
    write_js_string_escaped(buf, text);
    buf.write_str("\"");
}

/// Minimal JS string escape: backslash, double-quote, newline, tab.
fn write_js_string_escaped(buf: &mut CodeBuffer, s: &str) {
    for c in s.chars() {
        match c {
            '\\' => buf.write_str("\\\\"),
            '"' => buf.write_str("\\\""),
            '\n' => buf.write_str("\\n"),
            '\r' => buf.write_str("\\r"),
            '\t' => buf.write_str("\\t"),
            _ => {
                let mut tmp = [0u8; 4];
                buf.write_str(c.encode_utf8(&mut tmp));
            }
        }
    }
}

fn emit_expr(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx) {
    if let Some(expr) = snapshot.control_flow.expr_value.get(&idx) {
        buf.write_str(resolve_unchecked(*expr));
    } else {
        buf.write_str("null");
    }
}

fn emit_fragment(buf: &mut CodeBuffer, snapshot: &Snapshot, node: &NodeSnapshot) {
    buf.write_str("jsx(Fragment, {}");
    for child_idx in node.children.clone() {
        buf.write_str(", ");
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

fn emit_memoize_wrapper(
    buf: &mut CodeBuffer,
    snapshot: &Snapshot,
    _idx: NodeIdx,
    node: &NodeSnapshot,
) {
    let tag = if node.tag == reflex_intern::Symbol::EMPTY {
        "MemoWrapper"
    } else {
        resolve_unchecked(node.tag)
    };
    buf.write_str("jsx(");
    buf.write_str(tag);
    buf.write_str(", {key: \"");
    buf.write_u64(node.subtree_hash);
    buf.write_str("\"}");
    for child_idx in node.children.clone() {
        buf.write_str(", ");
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

/// Keys that are valid JS identifiers emit unquoted; others get quoted.
/// Mirrors `jsx::emit_prop_name` — names with underscores get
/// snake→camel conversion (`class_name` → `className`,
/// `remark_plugins` → `remarkPlugins`); names with non-identifier
/// characters get JS-string quoted.
fn write_prop_key(buf: &mut CodeBuffer, name: &str) {
    if name.contains('_') && is_js_ident(name) {
        write_camel_case(buf, name);
        return;
    }
    if is_js_ident(name) {
        buf.write_str(name);
    } else {
        buf.write_str("\"");
        buf.write_str(name);
        buf.write_str("\"");
    }
}

/// Convert `snake_case` to `camelCase`: lowercase the first segment
/// and Title-case the rest. Mirrors
/// `reflex_codegen::jsx::write_camel_case`.
fn write_camel_case(buf: &mut CodeBuffer, name: &str) {
    let mut after_underscore = false;
    for (i, ch) in name.char_indices() {
        if ch == '_' {
            if i > 0 {
                after_underscore = true;
            }
        } else if after_underscore {
            for u in ch.to_uppercase() {
                let mut tmp = [0u8; 4];
                buf.write_str(u.encode_utf8(&mut tmp));
            }
            after_underscore = false;
        } else {
            let mut tmp = [0u8; 4];
            buf.write_str(ch.encode_utf8(&mut tmp));
        }
    }
}

fn is_js_ident(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !(first.is_ascii_alphabetic() || first == '_' || first == '$') {
        return false;
    }
    chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$')
}

#[cfg(test)]
mod tests {
    use reflex_intern::intern;
    use reflex_ir::{NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::{smallvec, SmallVec};

    use super::*;

    fn buf() -> CodeBuffer {
        CodeBuffer::with_capacity(64)
    }

    fn to_string(buf: CodeBuffer) -> String {
        String::from_utf8(buf.into_bytes()).expect("valid utf8")
    }

    #[test]
    fn empty_snapshot_emits_null() {
        let snap = SnapshotBuilder::new().finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "null");
    }

    #[test]
    fn element_emits_jsx_call() {
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            rendered_props: smallvec![(intern("className"), intern("\"foo\""))],
            ..Default::default()
        });
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "jsx(div, {className: \"foo\"})");
    }

    #[test]
    fn element_with_event_callback() {
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("button"),
            event_callbacks: smallvec![(intern("onClick"), intern("() => null"))],
            ..Default::default()
        });
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "jsx(button, {onClick: () => null})");
    }

    #[test]
    fn element_emits_node_style_as_css_prop() {
        // `read_rendered_props` only iterates dataclass fields, so the
        // `_get_style()` slot has to come from `node.style` and be
        // emitted as the `css:` JSX prop — matching what the Python
        // legacy compile produces for any component whose `style` is
        // non-empty (e.g. `rx.vstack(padding="3em", ...)`).
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            style: intern("({ [\"color\"] : \"red\" })"),
            ..Default::default()
        });
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "jsx(div, {css: ({ [\"color\"] : \"red\" })})");
    }

    #[test]
    fn rendered_css_takes_precedence_over_node_style() {
        // If `rendered_props` already carries `css` (because the
        // Component declared `css` as a typed dataclass field), don't
        // double-emit from `node.style`.
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            rendered_props: smallvec![(intern("css"), intern("({ explicit: true })"))],
            style: intern("({ from_node_style: true })"),
            ..Default::default()
        });
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "jsx(div, {css: ({ explicit: true })})");
    }

    #[test]
    fn redirected_node_emits_wrapper_at_call_site() {
        // Build: parent → child (with subtree_hash=H)
        // Stage 6 redirect: child idx is redirected at a synthetic
        // wrapper at idx=2 with tag="MemoBody_X" and subtree_hash=H.
        // The page emit at child idx should emit the wrapper instead.
        let mut sb = SnapshotBuilder::new();
        let parent = sb.reserve();
        let child = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("p"),
            ..Default::default()
        });
        sb.fill(
            parent,
            NodeSnapshot {
                kind: NodeKind::Element,
                tag: intern("div"),
                children: child..child + 1,
                ..Default::default()
            },
        );
        let wrapper = sb.push(NodeSnapshot {
            kind: NodeKind::MemoizeWrapper,
            tag: intern("MemoBody_X"),
            children: 0..0,
            ..Default::default()
        });
        sb.set_root(parent);
        let mut snap = sb.finish();
        // `finish()` recomputes subtree_hash bottom-up; pin it post-close
        // so the emitter has a stable React key to render.
        snap.nodes[wrapper as usize].subtree_hash = 0xABCD;
        snap.wrap_redirects.insert(child, wrapper);

        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        // Parent emits its tag, then the redirected child renders as the
        // wrapper (with the memo body tag + the React key).
        // 0xABCD = 43981 — `write_u64` formats decimal to match the
        // legacy `emit_memoize` output shape.
        assert_eq!(
            to_string(b),
            "jsx(div, {}, jsx(MemoBody_X, {key: \"43981\"}))"
        );
    }

    #[test]
    fn match_emits_arms_and_default() {
        let mut sb = SnapshotBuilder::new();
        let root = sb.reserve();
        let body_a = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("p"),
            ..Default::default()
        });
        let body_b = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("span"),
            ..Default::default()
        });
        let default = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            ..Default::default()
        });
        sb.fill(
            root,
            NodeSnapshot {
                kind: NodeKind::Match,
                children: body_a..default + 1,
                ..Default::default()
            },
        );
        sb.set_root(root);
        {
            let snap = sb.snapshot_mut();
            snap.control_flow
                .match_value
                .insert(root, intern("state.value"));
            let arms: SmallVec<[(reflex_intern::Symbol, reflex_ir::NodeIdx); 2]> =
                smallvec![(intern("\"a\""), body_a), (intern("\"b\""), body_b)];
            snap.control_flow.match_arms.insert(root, arms);
            snap.control_flow.match_default.insert(root, default);
        }
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(
            to_string(b),
            "match_template((state.value), [[\"a\", jsx(p, {})], [\"b\", jsx(span, {})]], jsx(div, {}))"
        );
    }

    #[test]
    fn fragment_with_children() {
        let mut sb = SnapshotBuilder::new();
        let root = sb.reserve();
        let child = sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("p"),
            ..Default::default()
        });
        sb.fill(
            root,
            NodeSnapshot {
                kind: NodeKind::Fragment,
                children: child..child + 1,
                ..Default::default()
            },
        );
        sb.set_root(root);
        let snap = sb.finish();
        let mut b = buf();
        emit_jsx_from_snapshot(&mut b, &snap);
        assert_eq!(to_string(b), "jsx(Fragment, {}, jsx(p, {}))");
    }
}
