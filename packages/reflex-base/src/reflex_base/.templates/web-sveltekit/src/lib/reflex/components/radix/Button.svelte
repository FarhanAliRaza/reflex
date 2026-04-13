<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    mergeClasses,
    mergeStyles,
    radiusValue,
    textLetterSpacing,
    textLineHeight,
    textSize,
  } from "$lib/reflex/components/style.js";

  const SIZE_STYLE = {
    "1": {
      fontSize: textSize("1"),
      lineHeight: textLineHeight("1"),
      letterSpacing: textLetterSpacing("1"),
      gap: "var(--space-1)",
      height: "var(--space-5)",
      paddingInline: "var(--space-2)",
      ghostGap: "var(--space-1)",
      ghostPadding: "var(--space-1) var(--space-2)",
      radius: "max(var(--radius-1), var(--radius-full))",
    },
    "2": {
      fontSize: textSize("2"),
      lineHeight: textLineHeight("2"),
      letterSpacing: textLetterSpacing("2"),
      gap: "var(--space-2)",
      height: "var(--space-6)",
      paddingInline: "var(--space-3)",
      ghostGap: "var(--space-1)",
      ghostPadding: "var(--space-1) var(--space-2)",
      radius: "max(var(--radius-2), var(--radius-full))",
    },
    "3": {
      fontSize: textSize("3"),
      lineHeight: textLineHeight("3"),
      letterSpacing: textLetterSpacing("3"),
      gap: "var(--space-3)",
      height: "var(--space-7)",
      paddingInline: "var(--space-4)",
      ghostGap: "var(--space-2)",
      ghostPadding: "calc(var(--space-1) * 1.5) var(--space-3)",
      radius: "max(var(--radius-3), var(--radius-full))",
    },
    "4": {
      fontSize: textSize("4"),
      lineHeight: textLineHeight("4"),
      letterSpacing: textLetterSpacing("4"),
      gap: "var(--space-3)",
      height: "var(--space-8)",
      paddingInline: "var(--space-5)",
      ghostGap: "var(--space-2)",
      ghostPadding: "var(--space-2) var(--space-4)",
      radius: "max(var(--radius-4), var(--radius-full))",
    },
  };

  let {
    variant = "solid",
    size = "2",
    radius = "full",
    highContrast = false,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(
    mergeClasses(
      "rxs-button",
      `rxs-button--${variant}`,
      highContrast ? "rxs-button--contrast" : "",
      className,
    ),
  );
  const sizeStyle = $derived(SIZE_STYLE[String(size)] ?? SIZE_STYLE["3"]);
  const resolvedRadius = $derived(
    radius === undefined || radius === null || radius === ""
      ? sizeStyle.radius
      : radiusValue(radius, sizeStyle.radius),
  );
  const buttonStyle = $derived(
    mergeStyles(
      `gap: ${variant === "ghost" ? sizeStyle.ghostGap : sizeStyle.gap}`,
      `font-size: ${sizeStyle.fontSize}`,
      `line-height: ${sizeStyle.lineHeight}`,
      `letter-spacing: ${sizeStyle.letterSpacing}`,
      variant === "ghost" ? `padding: ${sizeStyle.ghostPadding}` : "",
      variant === "ghost" ? "" : `height: ${sizeStyle.height}`,
      variant === "ghost" ? "" : `padding-inline: ${sizeStyle.paddingInline}`,
      variant === "ghost" ? "" : "padding-block: 0",
      `border-radius: ${resolvedRadius}`,
      style,
    ),
  );
</script>

<Primitive
  tag="button"
  className={classes}
  css={css}
  style={buttonStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-button) {
    appearance: none;
    align-items: center;
    background-color: transparent;
    border: none;
    box-sizing: border-box;
    color: var(--gray-12);
    cursor: pointer;
    display: inline-flex;
    flex-shrink: 0;
    font-family: var(--default-font-family, inherit);
    font-style: normal;
    font-weight: 500;
    justify-content: center;
    text-decoration: none;
    user-select: none;
    white-space: nowrap;
    transition:
      background-color 120ms ease,
      box-shadow 120ms ease,
      color 120ms ease,
      filter 120ms ease,
      opacity 120ms ease;
  }

  :global(.rxs-button:focus-visible) {
    outline: 2px solid var(--focus-8);
    outline-offset: 2px;
  }

  :global(.rxs-button--solid) {
    background-color: var(--accent-9);
    color: var(--accent-contrast);
  }

  @media (hover: hover) {
    :global(.rxs-button--solid:hover) {
      background-color: var(--accent-10);
    }
  }

  :global(.rxs-button--solid:active) {
    background-color: var(--accent-10);
  }

  :global(.rxs-button--solid.rxs-button--contrast) {
    background-color: var(--accent-12);
    color: var(--gray-1);
  }

  @media (hover: hover) {
    :global(.rxs-button--solid.rxs-button--contrast:hover) {
      background-color: var(--accent-12);
      filter: var(--base-button-solid-high-contrast-hover-filter, none);
    }
  }

  :global(.rxs-button--solid.rxs-button--contrast:active) {
    background-color: var(--accent-12);
    filter: var(--base-button-solid-high-contrast-active-filter, none);
  }

  :global(.rxs-button--soft),
  :global(.rxs-button--ghost) {
    color: var(--accent-a11);
  }

  :global(.rxs-button--soft.rxs-button--contrast),
  :global(.rxs-button--ghost.rxs-button--contrast) {
    color: var(--accent-12);
  }

  :global(.rxs-button--soft) {
    background-color: var(--accent-a3);
  }

  :global(.rxs-button--soft:focus-visible),
  :global(.rxs-button--ghost:focus-visible),
  :global(.rxs-button--outline:focus-visible),
  :global(.rxs-button--surface:focus-visible) {
    outline-offset: -1px;
  }

  @media (hover: hover) {
    :global(.rxs-button--soft:hover) {
      background-color: var(--accent-a4);
    }
  }

  :global(.rxs-button--soft:active) {
    background-color: var(--accent-a5);
  }

  @media (hover: hover) {
    :global(.rxs-button--ghost:hover) {
      background-color: var(--accent-a3);
    }
  }

  :global(.rxs-button--ghost:active) {
    background-color: var(--accent-a4);
  }

  :global(.rxs-button--outline) {
    box-shadow: inset 0 0 0 1px var(--accent-a8);
    color: var(--accent-a11);
  }

  @media (hover: hover) {
    :global(.rxs-button--outline:hover) {
      background-color: var(--accent-a2);
    }
  }

  :global(.rxs-button--outline:active) {
    background-color: var(--accent-a3);
  }

  :global(.rxs-button--outline.rxs-button--contrast) {
    box-shadow:
      inset 0 0 0 1px var(--accent-a7),
      inset 0 0 0 1px var(--gray-a11);
    color: var(--accent-12);
  }

  :global(.rxs-button--surface) {
    background-color: var(--accent-surface);
    box-shadow: inset 0 0 0 1px var(--accent-a7);
    color: var(--accent-a11);
  }

  @media (hover: hover) {
    :global(.rxs-button--surface:hover) {
      box-shadow: inset 0 0 0 1px var(--accent-a8);
    }
  }

  :global(.rxs-button--surface:active) {
    background-color: var(--accent-a3);
    box-shadow: inset 0 0 0 1px var(--accent-a8);
  }

  :global(.rxs-button--surface.rxs-button--contrast) {
    color: var(--accent-12);
  }

  :global(.rxs-button[data-disabled]),
  :global(.rxs-button:disabled) {
    cursor: var(--cursor-disabled, not-allowed);
    filter: none;
  }

  :global(.rxs-button--solid[data-disabled]),
  :global(.rxs-button--solid:disabled) {
    background-color: var(--gray-a3);
    color: var(--gray-a8);
  }

  :global(.rxs-button--soft[data-disabled]),
  :global(.rxs-button--soft:disabled) {
    background-color: var(--gray-a3);
    color: var(--gray-a8);
  }

  :global(.rxs-button--ghost[data-disabled]),
  :global(.rxs-button--ghost:disabled) {
    background-color: transparent;
    color: var(--gray-a8);
  }

  :global(.rxs-button--outline[data-disabled]),
  :global(.rxs-button--outline:disabled) {
    background-color: transparent;
    box-shadow: inset 0 0 0 1px var(--gray-a7);
    color: var(--gray-a8);
  }

  :global(.rxs-button--surface[data-disabled]),
  :global(.rxs-button--surface:disabled) {
    background-color: var(--gray-a2);
    box-shadow: inset 0 0 0 1px var(--gray-a6);
    color: var(--gray-a8);
  }
</style>
