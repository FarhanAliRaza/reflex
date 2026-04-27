"""Tailwind class strings for every visually-styled Radix component.

Each component's ``create()`` resolves its variant/size props through
the matching ``*_classes`` helper here and emits the result as
``class_name`` on a plain HTML element. Class strings reference Radix's
``--accent-*`` / ``--gray-*`` CSS variables (already on the page via
``[data-accent-color]`` / ``[data-gray-color]``) so a user's
``rx.theme(...)`` automatically tints everything — no extra Tailwind
config required.

This is the entire styling layer that replaces
``@radix-ui/themes/styles.css`` (~800 KB) for the converted
components. Total size of this module's compiled Tailwind utilities
is on the order of 10-20 KB depending on how many variants the app
actually uses (Tailwind v4 tree-shakes per-class).
"""

from __future__ import annotations

from ._variants import variants

button_classes = variants(
    base=(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap "
        "rounded-(--radius-3) font-medium transition-colors "
        "focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:pointer-events-none disabled:opacity-50 cursor-pointer"
    ),
    defaults={"variant": "solid", "size": "2"},
    variant={
        "solid": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] "
            "hover:bg-[var(--accent-10)] shadow-sm"
        ),
        "soft": (
            "bg-[var(--accent-3)] text-[var(--accent-11)] "
            "hover:bg-[var(--accent-4)]"
        ),
        "surface": (
            "border border-[var(--accent-a7)] bg-[var(--accent-surface)] "
            "text-[var(--accent-11)] hover:bg-[var(--accent-a3)] "
            "shadow-sm"
        ),
        "outline": (
            "border border-[var(--accent-a8)] bg-transparent "
            "text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "ghost": (
            "bg-transparent text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "classic": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] "
            "hover:bg-[var(--accent-10)] shadow-md"
        ),
    },
    size={
        "1": "h-6 px-2 text-xs",
        "2": "h-8 px-3 text-sm",
        "3": "h-10 px-5 text-base",
        "4": "h-12 px-6 text-base",
    },
)


badge_classes = variants(
    base=(
        "inline-flex items-center gap-1 whitespace-nowrap "
        "rounded-(--radius-2) font-medium"
    ),
    defaults={"variant": "soft", "size": "1"},
    variant={
        "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
        "soft": "bg-[var(--accent-3)] text-[var(--accent-11)]",
        "surface": (
            "border border-[var(--accent-a6)] bg-[var(--accent-surface)] "
            "text-[var(--accent-11)]"
        ),
        "outline": (
            "border border-[var(--accent-a7)] bg-transparent text-[var(--accent-11)]"
        ),
    },
    size={
        "1": "h-5 px-1.5 text-xs",
        "2": "h-6 px-2 text-sm",
        "3": "h-7 px-2.5 text-base",
    },
)


callout_classes = variants(
    base=(
        "flex gap-2 rounded-(--radius-3) "
        "[&_svg]:shrink-0 [&_svg]:mt-0.5"
    ),
    defaults={"variant": "soft", "size": "2"},
    variant={
        "soft": "bg-[var(--accent-3)] text-[var(--accent-11)]",
        "surface": (
            "border border-[var(--accent-a6)] bg-[var(--accent-surface)] "
            "text-[var(--accent-11)]"
        ),
        "outline": (
            "border border-[var(--accent-a7)] bg-transparent text-[var(--accent-11)]"
        ),
    },
    size={
        "1": "p-2 text-sm gap-1.5",
        "2": "p-3 text-sm",
        "3": "p-4 text-base",
    },
)


card_classes = variants(
    base="rounded-(--radius-4) overflow-hidden",
    defaults={"variant": "surface", "size": "2"},
    variant={
        "surface": (
            "border border-[var(--gray-a4)] bg-[var(--color-panel)] "
            "shadow-[0_0_0_1px_var(--gray-a3),_0_1px_2px_var(--gray-a3)]"
        ),
        "classic": (
            "bg-[var(--color-panel-solid)] "
            "shadow-[0_0_0_1px_var(--gray-a4),_0_2px_4px_-1px_var(--gray-a4)]"
        ),
        "ghost": "bg-transparent",
    },
    size={
        "1": "p-2",
        "2": "p-3",
        "3": "p-4",
        "4": "p-5",
        "5": "p-6",
    },
)


heading_classes = variants(
    base="font-bold tracking-tight text-[var(--gray-12)]",
    defaults={"size": "6"},
    size={
        "1": "text-xs leading-tight",
        "2": "text-sm leading-tight",
        "3": "text-base leading-snug",
        "4": "text-lg leading-snug",
        "5": "text-xl leading-snug",
        "6": "text-2xl leading-snug",
        "7": "text-3xl leading-tight tracking-tight",
        "8": "text-4xl leading-tight tracking-tight",
        "9": "text-6xl leading-none tracking-tighter",
    },
    weight={
        "light": "font-light",
        "regular": "font-normal",
        "medium": "font-medium",
        "bold": "font-bold",
    },
    align={
        "left": "text-left",
        "center": "text-center",
        "right": "text-right",
    },
)


text_classes = variants(
    base="text-[var(--gray-12)]",
    defaults={"size": "2"},
    size={
        "1": "text-xs leading-snug tracking-wide",
        "2": "text-sm leading-snug",
        "3": "text-base leading-normal",
        "4": "text-lg leading-relaxed",
        "5": "text-xl leading-relaxed tracking-tight",
        "6": "text-2xl leading-relaxed tracking-tight",
        "7": "text-3xl leading-snug tracking-tight",
        "8": "text-4xl leading-tight tracking-tight",
        "9": "text-6xl leading-none tracking-tighter",
    },
    weight={
        "light": "font-light",
        "regular": "font-normal",
        "medium": "font-medium",
        "bold": "font-bold",
    },
    align={
        "left": "text-left",
        "center": "text-center",
        "right": "text-right",
    },
)


link_classes = variants(
    base="cursor-pointer transition-colors",
    defaults={"underline": "auto"},
    underline={
        "auto": "text-[var(--accent-11)] hover:underline underline-offset-2",
        "always": "text-[var(--accent-11)] underline underline-offset-2",
        "hover": "text-[var(--accent-11)] hover:underline underline-offset-2",
        "none": "text-[var(--accent-11)] no-underline",
    },
)


code_classes = variants(
    base=(
        "font-mono rounded-(--radius-2) "
        "[font-family:var(--code-font-family,_ui-monospace,_SFMono-Regular,_Menlo,_Consolas,_monospace)]"
    ),
    defaults={"variant": "soft", "size": "2"},
    variant={
        "solid": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] px-1 py-0.5"
        ),
        "soft": (
            "bg-[var(--accent-a3)] text-[var(--accent-12)] px-1 py-0.5"
        ),
        "outline": (
            "border border-[var(--accent-a7)] text-[var(--accent-11)] px-1 py-0.5"
        ),
        "ghost": "text-[var(--accent-11)]",
    },
    size={
        "1": "text-xs",
        "2": "text-sm",
        "3": "text-base",
        "4": "text-lg",
        "5": "text-xl",
        "6": "text-2xl",
        "7": "text-3xl",
        "8": "text-4xl",
        "9": "text-6xl",
    },
)


kbd_classes = variants(
    base=(
        "inline-flex items-center justify-center "
        "border border-[var(--gray-a6)] bg-[var(--gray-1)] text-[var(--gray-12)] "
        "shadow-sm font-mono rounded-(--radius-2)"
    ),
    defaults={"size": "2"},
    size={
        "1": "h-4 min-w-[1rem] px-1 text-xs",
        "2": "h-5 min-w-[1.25rem] px-1 text-xs",
        "3": "h-6 min-w-[1.5rem] px-1.5 text-sm",
        "4": "h-7 min-w-[1.75rem] px-1.5 text-sm",
        "5": "h-8 min-w-[2rem] px-2 text-base",
    },
)


separator_classes = variants(
    base="bg-[var(--gray-a6)]",
    defaults={"orientation": "horizontal", "size": "1"},
    orientation={
        "horizontal": "w-full h-px",
        "vertical": "h-full w-px inline-block",
    },
    size={
        "1": "",
        "2": "",
        "3": "",
        "4": "",
    },
)


blockquote_classes = variants(
    base=(
        "border-l-2 border-[var(--accent-a7)] pl-4 "
        "italic text-[var(--gray-12)]"
    ),
    defaults={"size": "3"},
    size={
        "1": "text-xs",
        "2": "text-sm",
        "3": "text-base",
        "4": "text-lg",
        "5": "text-xl",
        "6": "text-2xl",
        "7": "text-3xl",
        "8": "text-4xl",
        "9": "text-6xl",
    },
)


spinner_classes = variants(
    base=(
        "inline-block animate-spin rounded-full "
        "border-2 border-[var(--accent-a4)] border-t-[var(--accent-9)]"
    ),
    defaults={"size": "2"},
    size={
        "1": "size-3",
        "2": "size-4",
        "3": "size-5",
    },
)


skeleton_classes = variants(
    base=(
        "animate-pulse bg-[var(--gray-a3)] rounded-(--radius-2) "
        "[&_*]:invisible"
    ),
)


avatar_classes = variants(
    base=(
        "inline-flex items-center justify-center align-middle overflow-hidden "
        "select-none shrink-0 rounded-(--radius-3) "
        "font-medium uppercase"
    ),
    defaults={"variant": "soft", "size": "3"},
    variant={
        "solid": "bg-[var(--accent-9)] text-[var(--accent-contrast)]",
        "soft": "bg-[var(--accent-3)] text-[var(--accent-11)]",
    },
    size={
        "1": "size-6 text-xs",
        "2": "size-8 text-sm",
        "3": "size-10 text-base",
        "4": "size-12 text-lg",
        "5": "size-16 text-xl",
        "6": "size-20 text-2xl",
        "7": "size-24 text-3xl",
        "8": "size-32 text-4xl",
        "9": "size-40 text-5xl",
    },
)


icon_button_classes = variants(
    base=(
        "inline-flex items-center justify-center shrink-0 "
        "rounded-(--radius-3) transition-colors cursor-pointer "
        "focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:pointer-events-none disabled:opacity-50"
    ),
    defaults={"variant": "solid", "size": "2"},
    variant={
        "solid": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] "
            "hover:bg-[var(--accent-10)] shadow-sm"
        ),
        "soft": (
            "bg-[var(--accent-3)] text-[var(--accent-11)] "
            "hover:bg-[var(--accent-4)]"
        ),
        "surface": (
            "border border-[var(--accent-a7)] bg-[var(--accent-surface)] "
            "text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "outline": (
            "border border-[var(--accent-a8)] bg-transparent "
            "text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "ghost": (
            "bg-transparent text-[var(--accent-11)] hover:bg-[var(--accent-a3)]"
        ),
        "classic": (
            "bg-[var(--accent-9)] text-[var(--accent-contrast)] "
            "hover:bg-[var(--accent-10)] shadow-md"
        ),
    },
    size={
        "1": "size-6 text-xs",
        "2": "size-8 text-sm",
        "3": "size-10 text-base",
        "4": "size-12 text-base",
    },
)


text_field_classes = variants(
    base=(
        "flex w-full transition-colors "
        "rounded-(--radius-2) text-[var(--gray-12)] "
        "placeholder:text-[var(--gray-a10)] "
        "focus-within:outline-none "
        "focus-within:ring-2 focus-within:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50"
    ),
    defaults={"variant": "surface", "size": "2"},
    variant={
        "classic": (
            "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
            "shadow-[inset_0_1px_2px_var(--gray-a3)]"
        ),
        "surface": (
            "border border-[var(--gray-a7)] bg-[var(--color-surface)]"
        ),
        "soft": "bg-[var(--accent-a3)] border border-transparent",
    },
    size={
        "1": "h-6 text-xs px-2",
        "2": "h-8 text-sm px-3",
        "3": "h-10 text-base px-3",
    },
)


text_area_classes = variants(
    base=(
        "flex w-full rounded-(--radius-2) transition-colors "
        "text-[var(--gray-12)] placeholder:text-[var(--gray-a10)] "
        "focus:outline-none focus:ring-2 focus:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50"
    ),
    defaults={"variant": "surface", "size": "2"},
    variant={
        "classic": (
            "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
            "shadow-[inset_0_1px_2px_var(--gray-a3)]"
        ),
        "surface": "border border-[var(--gray-a7)] bg-[var(--color-surface)]",
        "soft": "bg-[var(--accent-a3)] border border-transparent",
    },
    size={
        "1": "text-xs px-2 py-1 min-h-16",
        "2": "text-sm px-3 py-2 min-h-20",
        "3": "text-base px-3 py-2 min-h-24",
    },
)


checkbox_classes = variants(
    base=(
        "peer shrink-0 appearance-none cursor-pointer transition-colors "
        "rounded-(--radius-2) align-middle "
        "focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50 "
        "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
        "checked:border-[var(--accent-9)] "
        "checked:bg-[var(--accent-9)] "
        "checked:bg-no-repeat checked:bg-center "
        "checked:bg-[length:80%_80%] "
        "checked:bg-[image:url(\"data:image/svg+xml;utf8,"
        "%3Csvg%20viewBox%3D%270%200%2016%2016%27%20fill%3D%27none%27%20"
        "xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%3E"
        "%3Cpath%20d%3D%27M3%208.5L7%2012L13%204%27%20stroke%3D%27white%27%20"
        "stroke-width%3D%272%27%20stroke-linecap%3D%27round%27%20"
        "stroke-linejoin%3D%27round%27%2F%3E%3C%2Fsvg%3E\")]"
    ),
    defaults={"size": "2"},
    size={
        "1": "size-3.5",
        "2": "size-4",
        "3": "size-5",
    },
)


switch_classes = variants(
    base=(
        "inline-flex items-center shrink-0 cursor-pointer rounded-full "
        "transition-colors focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50 "
        "bg-[var(--gray-a5)] data-[state=checked]:bg-[var(--accent-9)]"
    ),
    defaults={"variant": "surface", "size": "2"},
    variant={
        "classic": "shadow-sm",
        "surface": "",
        "soft": "",
    },
    size={
        "1": "h-4 w-7 p-0.5 [&_[data-thumb]]:size-3",
        "2": "h-5 w-9 p-0.5 [&_[data-thumb]]:size-4",
        "3": "h-6 w-11 p-0.5 [&_[data-thumb]]:size-5",
    },
)


radio_classes = variants(
    base=(
        "shrink-0 appearance-none rounded-full align-middle "
        "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
        "cursor-pointer transition-colors "
        "focus-visible:outline-none focus-visible:ring-2 "
        "focus-visible:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50 "
        "checked:border-[var(--accent-9)] "
        "checked:bg-no-repeat checked:bg-center "
        "checked:bg-[radial-gradient(circle,var(--accent-9)_45%,var(--color-surface)_50%)]"
    ),
    defaults={"size": "2"},
    size={
        "1": "size-3.5",
        "2": "size-4",
        "3": "size-5",
    },
)


slider_classes = variants(
    base="relative flex w-full touch-none select-none items-center",
    defaults={"variant": "surface", "size": "2"},
    variant={
        "classic": "",
        "surface": "",
        "soft": "",
    },
    size={
        "1": "[&_[data-track]]:h-1 [&_[data-thumb]]:size-3",
        "2": "[&_[data-track]]:h-1.5 [&_[data-thumb]]:size-4",
        "3": "[&_[data-track]]:h-2 [&_[data-thumb]]:size-5",
    },
)


progress_classes = variants(
    base=(
        "w-full overflow-hidden rounded-full bg-[var(--gray-a3)] "
        "[&>[data-indicator]]:h-full "
        "[&>[data-indicator]]:bg-[var(--accent-9)] "
        "[&>[data-indicator]]:transition-all"
    ),
    defaults={"size": "2"},
    size={
        "1": "h-1",
        "2": "h-1.5",
        "3": "h-2",
    },
)


select_classes = variants(
    base=(
        "inline-flex items-center justify-between gap-2 "
        "rounded-(--radius-2) cursor-pointer transition-colors "
        "focus:outline-none focus:ring-2 focus:ring-[var(--accent-8)] "
        "disabled:cursor-not-allowed disabled:opacity-50"
    ),
    defaults={"variant": "surface", "size": "2"},
    variant={
        "classic": (
            "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
            "text-[var(--gray-12)] shadow-sm"
        ),
        "surface": (
            "border border-[var(--gray-a7)] bg-[var(--color-surface)] "
            "text-[var(--gray-12)]"
        ),
        "soft": (
            "bg-[var(--accent-a3)] text-[var(--accent-11)] "
            "border border-transparent"
        ),
        "ghost": (
            "bg-transparent text-[var(--gray-12)] "
            "hover:bg-[var(--gray-a3)]"
        ),
    },
    size={
        "1": "h-6 px-2 text-xs",
        "2": "h-8 px-3 text-sm",
        "3": "h-10 px-4 text-base",
    },
)


tabs_list_classes = variants(
    base=(
        "inline-flex items-center gap-1 border-b border-[var(--gray-a6)]"
    ),
    defaults={"size": "2"},
    size={
        "1": "text-xs",
        "2": "text-sm",
    },
)


tabs_trigger_classes = variants(
    base=(
        "inline-flex items-center justify-center px-3 py-2 "
        "text-[var(--gray-11)] cursor-pointer transition-colors "
        "border-b-2 border-transparent -mb-px "
        "hover:text-[var(--gray-12)] "
        "data-[state=active]:text-[var(--accent-12)] "
        "data-[state=active]:border-[var(--accent-9)]"
    ),
)


tooltip_classes = variants(
    base=(
        "z-50 overflow-hidden rounded-(--radius-2) "
        "bg-[var(--gray-12)] px-2 py-1 text-xs "
        "text-[var(--gray-1)] shadow-md "
        "data-[state=delayed-open]:animate-in "
        "data-[state=closed]:animate-out fade-in-0 fade-out-0"
    ),
)


popover_content_classes = variants(
    base=(
        "z-50 overflow-hidden rounded-(--radius-3) "
        "border border-[var(--gray-a4)] "
        "bg-[var(--color-panel-solid)] p-4 shadow-lg "
        "data-[state=open]:animate-in data-[state=closed]:animate-out"
    ),
)


dialog_overlay_classes = variants(
    base=(
        "fixed inset-0 z-50 bg-[var(--color-overlay)] "
        "data-[state=open]:animate-in data-[state=closed]:animate-out "
        "fade-in-0 fade-out-0"
    ),
)


dialog_content_classes = variants(
    base=(
        "fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 "
        "rounded-(--radius-4) border border-[var(--gray-a4)] "
        "bg-[var(--color-panel-solid)] p-6 shadow-xl "
        "max-w-md w-[calc(100%-2rem)] "
        "data-[state=open]:animate-in data-[state=closed]:animate-out"
    ),
)


scroll_area_classes = variants(
    base="relative overflow-hidden",
)


segmented_control_classes = variants(
    base=(
        "inline-flex items-center bg-[var(--gray-a3)] "
        "rounded-(--radius-2) p-0.5 gap-0.5"
    ),
    defaults={"size": "2"},
    size={
        "1": "h-6 text-xs",
        "2": "h-8 text-sm",
        "3": "h-10 text-base",
    },
)
