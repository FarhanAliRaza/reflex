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
      padding: "calc(var(--space-1) * 0.5) calc(var(--space-1) * 1.5)",
      gap: "calc(var(--space-1) * 1.5)",
      radius: "max(var(--radius-1), var(--radius-full))",
    },
    "2": {
      fontSize: textSize("1"),
      lineHeight: textLineHeight("1"),
      letterSpacing: textLetterSpacing("1"),
      padding: "var(--space-1) var(--space-2)",
      gap: "calc(var(--space-1) * 1.5)",
      radius: "max(var(--radius-2), var(--radius-full))",
    },
    "3": {
      fontSize: textSize("2"),
      lineHeight: textLineHeight("2"),
      letterSpacing: textLetterSpacing("2"),
      padding: "var(--space-1) calc(var(--space-2) * 1.25)",
      gap: "var(--space-2)",
      radius: "max(var(--radius-2), var(--radius-full))",
    },
  };

  let {
    size = "1",
    variant = "soft",
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
      "rxs-badge",
      `rxs-badge--${variant}`,
      highContrast ? "rxs-badge--contrast" : "",
      className,
    ),
  );
  const sizeStyle = $derived(SIZE_STYLE[String(size)] ?? SIZE_STYLE["1"]);
  const resolvedRadius = $derived(
    radius === undefined || radius === null || radius === ""
      ? sizeStyle.radius
      : radiusValue(radius, sizeStyle.radius),
  );
  const badgeStyle = $derived(
    mergeStyles(
      `font-size: ${sizeStyle.fontSize}`,
      `line-height: ${sizeStyle.lineHeight}`,
      `letter-spacing: ${sizeStyle.letterSpacing}`,
      `padding: ${sizeStyle.padding}`,
      `gap: ${sizeStyle.gap}`,
      `border-radius: ${resolvedRadius}`,
      style,
    ),
  );
</script>

<Primitive
  tag="span"
  className={classes}
  css={css}
  style={badgeStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-badge) {
    align-items: center;
    display: inline-flex;
    flex-shrink: 0;
    font-family: var(--default-font-family, inherit);
    font-style: normal;
    font-weight: 500;
    height: fit-content;
    line-height: 1;
    white-space: nowrap;
  }

  :global(.rxs-badge--surface) {
    background-color: var(--accent-surface);
    box-shadow: inset 0 0 0 1px var(--accent-a6);
    color: var(--accent-a11);
  }

  :global(.rxs-badge--surface.rxs-badge--contrast) {
    color: var(--accent-12);
  }

  :global(.rxs-badge--soft) {
    background-color: var(--accent-a3);
    color: var(--accent-a11);
  }

  :global(.rxs-badge--soft.rxs-badge--contrast) {
    color: var(--accent-12);
  }

  :global(.rxs-badge--solid) {
    background-color: var(--accent-9);
    color: var(--accent-contrast);
  }

  :global(.rxs-badge--solid.rxs-badge--contrast) {
    background-color: var(--accent-12);
    color: var(--accent-1);
  }

  :global(.rxs-badge--outline) {
    box-shadow: inset 0 0 0 1px var(--accent-a8);
    color: var(--accent-a11);
  }

  :global(.rxs-badge--outline.rxs-badge--contrast) {
    box-shadow:
      inset 0 0 0 1px var(--accent-a7),
      inset 0 0 0 1px var(--gray-a11);
    color: var(--accent-12);
  }
</style>
