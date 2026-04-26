"""shadcn-style code helpers.

``code(...)`` compiles to inline ``<code>`` with the shadcn inline-code
style; ``code_block(...)`` compiles to ``<pre><code>`` with block styling.
No syntax highlighting in v1 — this is the lightweight content-page
flavor. For full syntax highlighting, use ``rx.code_block`` (Shiki) on
the React Router target or in islands mode where you own the JS budget.
"""

from __future__ import annotations

from reflex_base.components.component import Component
from reflex_components_core.el.elements.inline import Code as ElCode
from reflex_components_core.el.elements.typography import Pre as ElPre

from ._variants import cn

_INLINE_CODE = (
    "relative rounded bg-muted px-[0.3rem] py-[0.2rem] font-mono text-sm font-semibold"
)
_CODE_BLOCK = (
    "block w-full overflow-x-auto rounded-md bg-zinc-950 text-zinc-50 "
    "p-4 font-mono text-sm leading-6"
)


class ShadcnInlineCode(ElCode):
    """Inline ``<code>`` with shadcn typography defaults."""

    @classmethod
    def create(cls, *children, **props) -> Component:
        """Render shadcn inline code.

        Args:
            *children: Code text content.
            **props: Pass-through to ``<code>``.

        Returns:
            The code element.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_INLINE_CODE, existing)
        return super().create(*children, **props)


class ShadcnCodeBlock(ElPre):
    """Block ``<pre><code>`` with shadcn dark code-block styling."""

    @classmethod
    def create(cls, *children, **props) -> Component:
        """Render a shadcn code block (no syntax highlighting in v1).

        Args:
            *children: Code source string (or already-tokenized children).
            **props: Pass-through to ``<pre>``.

        Returns:
            The pre/code element.
        """
        existing = props.pop("class_name", "")
        props["class_name"] = cn(_CODE_BLOCK, existing)
        # Wrap raw strings in a child <code> element so semantic tooling
        # treats it as code; passes through complex children unchanged.
        return super().create(ElCode.create(*children), **props)


code = ShadcnInlineCode.create
code_block = ShadcnCodeBlock.create
