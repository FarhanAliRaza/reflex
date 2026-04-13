"""SvelteKit-specific compiler helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reflex_base import constants
from reflex_base.event import EventChain
from reflex_base.utils import format as format_utils
from reflex_base.utils.exceptions import UnsupportedFrontendTargetError
from reflex_base.utils.imports import ParsedImportDict, collapse_imports
from reflex_base.vars.base import LiteralVar, Var

from reflex.utils.prerequisites import get_web_dir

if TYPE_CHECKING:
    from reflex.compiler.utils import _ImportDict
    from reflex_base.vars import VarData


_HEAD_TAGS = {"title", "meta", "link", "style", "script", "base"}
_SELF_CLOSING_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_ATTR_RENAMES = {
    "className": "class",
    "htmlFor": "for",
    "tabIndex": "tabindex",
    "readOnly": "readonly",
}
_DROPPED_IMPORTS = {
    "react",
    "@emotion/react",
    "$/utils/context",
    "$/utils/state",
}
_IMPORT_REWRITES = {
    "@radix-ui/themes": "$lib/reflex/components/radix-themes.js",
    "react-router": "$lib/reflex/components/router.js",
    "lucide-react": "$lib/reflex/components/lucide.js",
}
_STATE_CONTEXT_RE = re.compile(
    r"^const\s+(?P<name>[A-Za-z0-9_$]+)\s*=\s*useContext\(StateContexts\.(?P<alias>[A-Za-z0-9_$]+)\)\s*;?$"
)
_EVENT_LOOP_RE = re.compile(
    r"^const\s*\[\s*(?P<add>[A-Za-z0-9_$]+)\s*,\s*(?P<errors>[A-Za-z0-9_$]+)\s*\]\s*=\s*useContext\(EventLoopContext\)\s*;?$"
)
_UPLOAD_RE = re.compile(
    r"^const\s*\[\s*(?P<files>[A-Za-z0-9_$]+)\s*,\s*(?P<setter>[A-Za-z0-9_$]+)\s*\]\s*=\s*useContext\(UploadFilesContext\)\s*;?$"
)
_COLOR_MODE_RE = re.compile(
    r"^const\s*\{\s*(?P<vars>[A-Za-z0-9_$\s,]+)\s*\}\s*=\s*useContext\(ColorModeContext\)\s*;?$"
)
_REF_RE = re.compile(
    r'^const\s+(?P<name>[A-Za-z0-9_$]+)\s*=\s*useRef\(null\);\s*refs\["(?P<ref>[A-Za-z0-9_$]+)"\]\s*=\s*(?P=name);$'
)


def get_page_path(route: str) -> str:
    """Get the SvelteKit route output path for a Reflex route."""

    route_parts: list[str]
    if route == constants.Page404.SLUG:
        route_parts = ["[...404]"]
    elif route == constants.PageNames.INDEX_ROUTE:
        route_parts = []
    else:
        route_parts = [part for part in route.split("/") if part]

    return str(
        get_web_dir() / "src" / "routes" / Path(*route_parts) / "+page.svelte",
    )


def get_context_path() -> str:
    """Get the generated Svelte context module path."""

    return str(get_web_dir() / "src" / "lib" / "reflex" / "generated" / "context.js")


def normalize_imports(imports: ParsedImportDict) -> ParsedImportDict:
    """Rewrite page imports for the Svelte target."""

    rewritten: ParsedImportDict = {}
    unsupported: list[str] = []

    for lib, fields in collapse_imports(imports).items():
        formatted_lib = format_utils.format_library_name(lib) if lib else lib
        if formatted_lib in _DROPPED_IMPORTS:
            continue

        if formatted_lib in _IMPORT_REWRITES:
            rewritten.setdefault(_IMPORT_REWRITES[formatted_lib], []).extend(fields)
            continue

        if not formatted_lib:
            rewritten.setdefault(formatted_lib, []).extend(fields)
            continue

        if formatted_lib.startswith(("./", "../", "$/")):
            unsupported.append(formatted_lib)
            continue

        unsupported.append(formatted_lib)

    if unsupported:
        unsupported_rendered = ", ".join(sorted(dict.fromkeys(unsupported)))
        msg = (
            "The SvelteKit frontend target does not yet support these frontend "
            f"imports: {unsupported_rendered}"
        )
        raise UnsupportedFrontendTargetError(msg)

    return collapse_imports(rewritten)


def context_template(
    *,
    is_dev_mode: bool,
    default_color_mode: str,
    initial_state: dict[str, Any] | None = None,
    state_name: str | None = None,
    client_storage: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    """Render the Svelte runtime context module."""

    del is_dev_mode
    return (
        f"export const initialState = {format_utils.json_dumps(initial_state or {})};\n"
        f"export const clientStorage = {json.dumps(client_storage or {}, sort_keys=True)};\n"
        f"export const stateName = {json.dumps(state_name)};\n"
        f"export const exceptionStateName = {json.dumps(constants.CompileVars.FRONTEND_EXCEPTION_STATE_FULL if state_name else None)};\n"
        f"export const defaultColorMode = {default_color_mode};\n"
    )


def page_template(
    *,
    imports: Iterable[_ImportDict],
    dynamic_imports: Iterable[str],
    custom_codes: Iterable[str],
    hooks: dict[str, VarData | None],
    render: dict[str, Any],
) -> str:
    """Render a Svelte page component."""

    dynamic_imports = list(dynamic_imports)
    custom_codes = list(custom_codes)
    if dynamic_imports:
        msg = "Dynamic frontend imports are not yet supported on the SvelteKit target."
        raise UnsupportedFrontendTargetError(msg)
    if custom_codes:
        msg = "Custom frontend code snippets are not yet supported on the SvelteKit target."
        raise UnsupportedFrontendTargetError(msg)

    renderer = _SvelteRenderer()
    head_nodes, body_nodes = _split_head_nodes(render)
    rendered_head = [renderer.render(node) for node in head_nodes]
    head_markup = "\n".join(markup for markup in rendered_head if markup.strip())
    rendered_body = [renderer.render(node) for node in body_nodes]
    body_markup = "\n".join(markup for markup in rendered_body if markup.strip())
    translated_hooks = _translate_hooks(hooks)

    imports_str = "\n".join(_render_import(module) for module in imports)

    joined_code = "\n".join([imports_str, head_markup, body_markup, *translated_hooks])
    uses_runtime = "runtime." in joined_code or "addEvents(" in joined_code
    uses_add_events = "addEvents(" in joined_code

    script_lines: list[str] = []
    if uses_runtime:
        script_lines.append('import { getReflexRuntime } from "$lib/reflex/context.js";')

    runtime_imports: list[str] = []
    if "ReflexEvent(" in joined_code:
        runtime_imports.append("ReflexEvent")
    if "applyEventActions(" in joined_code:
        runtime_imports.append("applyEventActions")
    if runtime_imports:
        script_lines.append(
            "import { "
            + ", ".join(runtime_imports)
            + ' } from "$lib/reflex/runtime.svelte.js";'
        )
    if renderer.uses_style_object_to_string:
        script_lines.append(
            'import { styleObjectToString } from "$lib/reflex/components/style.js";'
        )

    if imports_str:
        script_lines.append(imports_str)

    if uses_runtime:
        script_lines.append("const runtime = getReflexRuntime();")
    if uses_add_events:
        script_lines.append("const addEvents = (...args) => runtime.addEvents(...args);")
    script_lines.extend(translated_hooks)

    sections = [
        "<script>",
        "\n".join(script_lines),
        "</script>",
    ]
    if head_markup:
        sections.extend((
            "",
            "<svelte:head>",
            head_markup,
            "</svelte:head>",
        ))
    if body_markup:
        sections.extend(("", body_markup))

    return (
        "\n".join(section for section in sections if section is not None).strip() + "\n"
    )


def _render_import(module: _ImportDict) -> str:
    default_import = module["default"]
    rest_imports = module["rest"]

    if default_import and rest_imports:
        rest_imports_str = ", ".join(sorted(rest_imports))
        return (
            f'import {default_import}, {{ {rest_imports_str} }} from "{module["lib"]}";'
        )
    if default_import:
        return f'import {default_import} from "{module["lib"]}";'
    if rest_imports:
        rest_imports_str = ", ".join(sorted(rest_imports))
        return f'import {{ {rest_imports_str} }} from "{module["lib"]}";'
    return f'import "{module["lib"]}";'


def _split_head_nodes(
    render: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if render.get("name") == "Fragment":
        head_nodes = []
        body_nodes = []
        for child in render.get("children", []):
            if _is_head_node(child):
                head_nodes.append(child)
            else:
                body_nodes.append(child)
        return head_nodes, body_nodes
    if _is_head_node(render):
        return [render], []
    return [], [render]


def _is_head_node(node: Any) -> bool:
    if not isinstance(node, Mapping):
        return False
    if any(key in node for key in ("cond_state", "iterable", "match_cases")):
        return False
    name = _strip_quotes(node.get("name", ""))
    return name in _HEAD_TAGS


def _translate_hooks(hooks: dict[str, VarData | None]) -> list[str]:
    translated: list[str] = []
    seen: set[str] = set()

    for hook in hooks:
        hook = hook.strip()
        if not hook:
            continue

        replacement = _translate_hook(hook)
        if replacement is None:
            continue

        lines = [replacement] if isinstance(replacement, str) else replacement
        for line in lines:
            if line not in seen:
                seen.add(line)
                translated.append(line)

    return translated


def _translate_hook(hook: str) -> str | list[str] | None:
    if match := _STATE_CONTEXT_RE.fullmatch(hook):
        alias = match.group("alias")
        name = match.group("name")
        return f'const {name} = runtime.getStateByAlias("{alias}");'

    if match := _EVENT_LOOP_RE.fullmatch(hook):
        connect_errors = match.group("errors")
        return [
            f"const {connect_errors} = $derived(runtime.connectErrors);",
        ]

    if match := _UPLOAD_RE.fullmatch(hook):
        files = match.group("files")
        setter = match.group("setter")
        return [
            f"const {files} = $derived(runtime.filesById);",
            f"const {setter} = (...args) => runtime.setFilesById(...args);",
        ]

    if match := _COLOR_MODE_RE.fullmatch(hook):
        lines: list[str] = []
        for variable_name in [part.strip() for part in match.group("vars").split(",")]:
            if variable_name == "rawColorMode":
                lines.append("const rawColorMode = $derived(runtime.colorMode);")
            elif variable_name == "resolvedColorMode":
                lines.append(
                    "const resolvedColorMode = $derived(runtime.resolvedColorMode);"
                )
            elif variable_name == "toggleColorMode":
                lines.append(
                    "const toggleColorMode = (...args) => runtime.toggleColorMode(...args);"
                )
            elif variable_name == "setColorMode":
                lines.append(
                    "const setColorMode = (...args) => runtime.setColorMode(...args);"
                )
            else:
                msg = (
                    "The SvelteKit frontend target does not support the "
                    f"ColorModeContext binding `{hook}`."
                )
                raise UnsupportedFrontendTargetError(msg)
        return lines

    if match := _REF_RE.fullmatch(hook):
        return (
            f'const {match.group("name")} = runtime.createRef("{match.group("ref")}");'
        )

    if hook == "const [addEvents, connectErrors] = useContext(EventLoopContext);":
        return None

    msg = f"The SvelteKit frontend target cannot translate the hook `{hook}` yet."
    raise UnsupportedFrontendTargetError(msg)


class _SvelteRenderer:
    def __init__(self) -> None:
        self._counter = 0
        self.uses_style_object_to_string = False

    def render(self, node: Any) -> str:
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if "contents" in node:
            return self._render_contents(node["contents"])
        if "iterable" in node:
            return self._render_each(node)
        if "match_cases" in node:
            return self._render_match(node)
        if "cond_state" in node:
            return self._render_condition(node)
        return self._render_tag(node)

    def _render_contents(self, contents: str) -> str:
        return f"{{{contents}}}"

    def _render_condition(self, node: Mapping[str, Any]) -> str:
        true_value = self.render(node["true_value"])
        false_value = (
            self.render(node["false_value"]) if node.get("false_value") else ""
        )
        sections = [
            f"{{#if {node['cond_state']}}}",
            true_value,
        ]
        if false_value:
            sections.extend(("{:else}", false_value))
        sections.append("{/if}")
        return "\n".join(section for section in sections if section)

    def _render_each(self, node: Mapping[str, Any]) -> str:
        iterable_value = node.get("iterable")
        if iterable_value is None:
            iterable_value = node.get("iterable_state")
        iterable = str(iterable_value if iterable_value is not None else "[]")
        arg_name = node.get("arg_var_name") or node.get("arg_name") or "item"
        index_name = node.get("index_var_name") or node.get("arg_index") or "index"
        children = [_strip_key_attribute(child) for child in node.get("children", [])]
        key_expr = _extract_each_key(node.get("children", []))
        rendered_children = [self.render(child) for child in children]
        body = "\n".join(markup for markup in rendered_children if markup.strip())
        opening = f"{{#each ({iterable} ?? []) as {arg_name}, {index_name}"
        if key_expr:
            opening += f" ({key_expr})"
        opening += "}"
        return "\n".join((opening, body, "{/each}"))

    def _render_match(self, node: Mapping[str, Any]) -> str:
        self._counter += 1
        match_name = f"__reflexMatch{self._counter}"
        lines = [f"{{@const {match_name} = {node['cond']}}}"]
        for index, (conditions, result) in enumerate(node["match_cases"]):
            condition_expr = " || ".join(
                f"JSON.stringify({match_name}) === JSON.stringify({condition})"
                for condition in conditions
            )
            lines.append(
                f"{{#if {condition_expr}}}"
                if index == 0
                else f"{{:else if {condition_expr}}}"
            )
            lines.append(self.render(result))
        lines.extend(("{:else}", self.render(node["default"]), "{/if}"))
        return "\n".join(lines)

    def _render_tag(self, node: Mapping[str, Any]) -> str:
        name = node.get("name") or ""
        if name in ("", "Fragment"):
            return "\n".join(
                rendered
                for child in node.get("children", [])
                if (rendered := self.render(child)).strip()
            )

        stripped_name = _strip_quotes(name)
        attributes = dict(node.get("attributes") or {})
        dangerous_html = attributes.pop("dangerouslySetInnerHTML", None)

        rendered_attrs: list[str] = []
        for attr_name, value in attributes.items():
            if attr_name == "key":
                continue
            rendered_attr = self._render_attribute(stripped_name, attr_name, value)
            if rendered_attr:
                rendered_attrs.append(rendered_attr)

        rendered_attrs.extend(
            f"{{...{_expression(spread)}}}" for spread in node.get("spreads", [])
        )
        attrs = (" " + " ".join(rendered_attrs)) if rendered_attrs else ""

        if dangerous_html is not None:
            children_markup = f'{{@html ({_expression(dangerous_html)}).__html ?? ""}}'
        else:
            children_markup = "\n".join(
                rendered
                for child in node.get("children", [])
                if (rendered := self.render(child)).strip()
            )

        if not children_markup and stripped_name in _SELF_CLOSING_TAGS:
            return f"<{stripped_name}{attrs} />"

        if children_markup:
            return f"<{stripped_name}{attrs}>\n{children_markup}\n</{stripped_name}>"
        return f"<{stripped_name}{attrs}></{stripped_name}>"

    def _render_attribute(self, tag_name: str, name: str, value: Any) -> str:
        normalized_name = _ATTR_RENAMES.get(name, name)
        if normalized_name.startswith("on") and len(normalized_name) > 2:
            normalized_name = "on" + normalized_name[2:].lower()

        if (
            tag_name
            and (not tag_name[:1].isupper() or tag_name.startswith("Lucide"))
            and normalized_name in {"css", "style"}
        ):
            self.uses_style_object_to_string = True
            expression = _expression(value)
            return (
                "style={"
                f'(typeof ({expression}) === "string" ? ({expression}) : styleObjectToString({expression}))'
                "}"
            )

        return f"{normalized_name}={{{_expression(value)}}}"


def _strip_quotes(name: str) -> str:
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {'"', "'"}:
        return json.loads(name)
    return name


def _expression(value: Any) -> str:
    if isinstance(value, EventChain):
        return format_utils.format_prop(value)
    if isinstance(value, Var):
        return str(value)
    return str(LiteralVar.create(value))


def _extract_each_key(children: Sequence[Any]) -> str | None:
    for child in children:
        if not isinstance(child, Mapping):
            continue
        if (attributes := child.get("attributes")) and "key" in attributes:
            return _expression(attributes["key"])
    return None


def _strip_key_attribute(node: Any) -> Any:
    if not isinstance(node, Mapping):
        return node
    updated = dict(node)
    if "attributes" in updated and updated["attributes"]:
        attributes = dict(updated["attributes"])
        attributes.pop("key", None)
        updated["attributes"] = attributes
    return updated
