//! Compact-format JSX emitter for the `Snapshot` arena.
//!
//! Mirrors the legacy `_RenderUtils.render` output exactly — no spaces
//! between `,` and the next token, no space after `:` in prop entries.
//! This is the format the legacy `app_root_template` and
//! `document_root_template` splice into their respective JSX modules.
//!
//! The pretty (spaced) version in
//! [`crate::page_from_snapshot::emit_jsx_from_snapshot`] is used by the
//! page emit pipeline; this compact version is used by the app-root /
//! document-root arena emitters that must produce byte-identical output
//! to the previous Python `_RenderUtils.render(component.render())`
//! shuttle so the existing match-against-legacy harness keeps passing.
//!
//! Coverage is the same subset as the spaced emitter: `Element`,
//! `Text`, `Fragment`, `Expr`, `MemoizeWrapper`, `Foreach`, `Cond`,
//! `Match`, `Memoize`. Prop / event / ref / css merging mirrors
//! `write_props_and_events` line-for-line; only the separator strings
//! differ.

use reflex_intern::{intern, resolve_unchecked, Symbol};
use reflex_ir::{NodeIdx, NodeKind, NodeSnapshot, Snapshot};

use crate::buffer::CodeBuffer;

/// Compact-format walk rooted at `snapshot.root`. Empty snapshots emit
/// `null`, matching the legacy `_RenderUtils.render` fallback.
pub fn emit_jsx_compact_from_snapshot(buf: &mut CodeBuffer, snapshot: &Snapshot) {
    if snapshot.is_empty() {
        buf.write_str("null");
        return;
    }
    emit_node(buf, snapshot, snapshot.root);
}

fn emit_node(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx) {
    let emit_idx = snapshot.wrap_redirects.get(&idx).copied().unwrap_or(idx);
    let node = snapshot.node(emit_idx);
    match node.kind {
        NodeKind::Element => emit_element(buf, snapshot, emit_idx, node),
        NodeKind::Text => emit_text(buf, snapshot, emit_idx),
        NodeKind::Expr => emit_expr(buf, snapshot, emit_idx),
        NodeKind::Fragment => emit_fragment(buf, snapshot, node),
        NodeKind::MemoizeWrapper => emit_memoize_wrapper(buf, snapshot, node),
        NodeKind::Foreach => emit_foreach(buf, snapshot, emit_idx, node),
        NodeKind::Cond => emit_cond(buf, snapshot, emit_idx, node),
        NodeKind::Match => emit_match(buf, snapshot, emit_idx, node),
        NodeKind::Memoize => emit_memoize(buf, snapshot, emit_idx, node),
    }
}

fn emit_element(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    buf.write_str("jsx(");
    if node.tag == Symbol::EMPTY {
        buf.write_str("Fragment");
    } else {
        buf.write_str(resolve_unchecked(node.tag));
    }
    buf.write_str(",{");
    write_props_and_events(buf, snapshot, idx, node);
    // Legacy `_RenderUtils.render_tag` always emits one `,` after the
    // props dict and joins children with `,` afterwards, so the
    // output is `jsx(name,{props},)` for childless elements,
    // `jsx(name,{props},c1)` for one child, and `jsx(name,{props},c1,c2)`
    // for two — preserve that exact comma layout.
    buf.write_str("},");
    let mut first = true;
    for child_idx in node.children.clone() {
        if !first {
            buf.write_str(",");
        }
        first = false;
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

fn emit_fragment(buf: &mut CodeBuffer, snapshot: &Snapshot, node: &NodeSnapshot) {
    buf.write_str("jsx(Fragment,{},");
    let mut first = true;
    for child_idx in node.children.clone() {
        if !first {
            buf.write_str(",");
        }
        first = false;
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
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

fn emit_expr(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx) {
    if let Some(expr) = snapshot.control_flow.expr_value.get(&idx) {
        buf.write_str(resolve_unchecked(*expr));
    } else {
        buf.write_str("null");
    }
}

fn emit_memoize_wrapper(buf: &mut CodeBuffer, snapshot: &Snapshot, node: &NodeSnapshot) {
    let tag = if node.tag == Symbol::EMPTY {
        "MemoWrapper"
    } else {
        resolve_unchecked(node.tag)
    };
    buf.write_str("jsx(");
    buf.write_str(tag);
    buf.write_str(",{key:\"");
    buf.write_u64(node.subtree_hash);
    buf.write_str("\"},");
    let mut first = true;
    for child_idx in node.children.clone() {
        if !first {
            buf.write_str(",");
        }
        first = false;
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

fn emit_foreach(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let iter_expr = snapshot
        .control_flow
        .foreach_iter
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("[]");
    let (arg, index) = foreach_arg_names(snapshot, idx);
    buf.write_str("Array.prototype.map.call(");
    buf.write_str(iter_expr);
    buf.write_str(" ?? [],((");
    buf.write_str(arg);
    buf.write_str(",");
    buf.write_str(index);
    buf.write_str(")=>(");
    if let Some(body) = node.children.clone().next() {
        emit_node(buf, snapshot, body);
    } else {
        buf.write_str("null");
    }
    buf.write_str(")))");
}

/// The foreach callback's `(arg, index)` parameter names recorded by the
/// freeze (the frozen body references them); placeholders only for
/// snapshots predating the table.
pub(crate) fn foreach_arg_names(snapshot: &Snapshot, idx: NodeIdx) -> (&str, &str) {
    snapshot
        .control_flow
        .foreach_args
        .get(&idx)
        .map(|(a, i)| (resolve_unchecked(*a), resolve_unchecked(*i)))
        .unwrap_or(("item", "index"))
}

fn emit_cond(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let test = snapshot
        .control_flow
        .cond_test
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("false");
    buf.write_str("(");
    buf.write_str(test);
    buf.write_str("?(");
    let mut iter = node.children.clone();
    if let Some(then_idx) = iter.next() {
        emit_node(buf, snapshot, then_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str("):(");
    if let Some(else_idx) = iter.next() {
        emit_node(buf, snapshot, else_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str("))");
}

/// Render a Match node as the legacy switch-IIFE
/// (`templates._RenderUtils.render_match_tag`): one `case
/// JSON.stringify(...)` label per condition, consecutive arms sharing a
/// body collapse into one `return`, and the `default` arm closes the
/// switch. (The previous `match_template(...)` form referenced a runtime
/// helper that doesn't exist.)
fn emit_match(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, _node: &NodeSnapshot) {
    let value = snapshot
        .control_flow
        .match_value
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .unwrap_or("null");
    buf.write_str("(() => {\n  switch (JSON.stringify(");
    buf.write_str(value);
    buf.write_str(")) {\n");
    if let Some(arms) = snapshot.control_flow.match_arms.get(&idx) {
        let mut i = 0;
        while i < arms.len() {
            let body = arms[i].1;
            while i < arms.len() && arms[i].1 == body {
                buf.write_str("    case JSON.stringify(");
                buf.write_str(resolve_unchecked(arms[i].0));
                buf.write_str("):\n");
                i += 1;
            }
            buf.write_str("      return ");
            emit_node(buf, snapshot, body);
            buf.write_str(";\n      break;\n");
        }
    }
    buf.write_str("    default:\n      return ");
    if let Some(default_idx) = snapshot.control_flow.match_default.get(&idx) {
        emit_node(buf, snapshot, *default_idx);
    } else {
        buf.write_str("null");
    }
    buf.write_str(";\n      break;\n  }\n})()");
}

fn emit_memoize(buf: &mut CodeBuffer, snapshot: &Snapshot, idx: NodeIdx, node: &NodeSnapshot) {
    let key = snapshot
        .control_flow
        .memo_key
        .get(&idx)
        .map(|s| resolve_unchecked(*s))
        .map(|s| s.to_owned())
        .unwrap_or_else(|| format!("\"{:016x}\"", node.subtree_hash));
    buf.write_str("jsx(MemoWrapper,{key:");
    buf.write_str(&key);
    buf.write_str("}");
    for child_idx in node.children.clone() {
        buf.write_str(",");
        emit_node(buf, snapshot, child_idx);
    }
    buf.write_str(")");
}

fn write_props_and_events(
    buf: &mut CodeBuffer,
    snapshot: &Snapshot,
    idx: NodeIdx,
    node: &NodeSnapshot,
) {
    let css_key = intern("css");
    let ref_key = intern("ref");

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
            buf.write_str(",");
        }
        first = false;
        let key_str = resolve_unchecked(*name);
        let renamed = renames
            .and_then(|map| apply_rename_prefix(key_str, map))
            .unwrap_or_else(|| key_str.to_owned());
        write_prop_key(buf, &renamed);
        buf.write_str(":");
        buf.write_str(resolve_unchecked(*value));
    }
    // Spread props render after the keyed props (legacy `format_props`
    // appends `...{expr}` entries last).
    if let Some(spreads) = snapshot.control_flow.special_props.get(&idx) {
        for spread in spreads {
            if !first {
                buf.write_str(",");
            }
            first = false;
            buf.write_str("...");
            buf.write_str(resolve_unchecked(*spread));
        }
    }
}

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

#[cfg(test)]
mod tests {
    use reflex_ir::{NodeKind, NodeSnapshot, SnapshotBuilder};
    use smallvec::smallvec;

    use super::*;

    #[test]
    fn empty_emits_null() {
        let snap = SnapshotBuilder::new().finish();
        let mut buf = CodeBuffer::with_capacity(32);
        emit_jsx_compact_from_snapshot(&mut buf, &snap);
        assert_eq!(String::from_utf8(buf.into_bytes()).unwrap(), "null");
    }

    #[test]
    fn element_no_spaces() {
        let mut sb = SnapshotBuilder::new();
        sb.push(NodeSnapshot {
            kind: NodeKind::Element,
            tag: intern("div"),
            rendered_props: smallvec![
                (intern("className"), intern("\"foo\"")),
                (intern("size"), intern("\"6\"")),
            ],
            ..Default::default()
        });
        let snap = sb.finish();
        let mut buf = CodeBuffer::with_capacity(64);
        emit_jsx_compact_from_snapshot(&mut buf, &snap);
        assert_eq!(
            String::from_utf8(buf.into_bytes()).unwrap(),
            "jsx(div,{className:\"foo\",size:\"6\"},)"
        );
    }

    #[test]
    fn fragment_with_children_no_spaces() {
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
        let mut buf = CodeBuffer::with_capacity(64);
        emit_jsx_compact_from_snapshot(&mut buf, &snap);
        assert_eq!(
            String::from_utf8(buf.into_bytes()).unwrap(),
            "jsx(Fragment,{},jsx(p,{},))"
        );
    }
}
