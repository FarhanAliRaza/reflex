<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    mergeClasses,
    mergeStyles,
    radiusValue,
    textLetterSpacing,
    textSize,
  } from "$lib/reflex/components/style.js";

  const SIZE_MAP = {
    "1": {
      size: "var(--space-5)",
      fontSize: textSize("2"),
      secondaryFontSize: textSize("1"),
      letterSpacing: textLetterSpacing("1"),
      radius: "max(var(--radius-2), var(--radius-full))",
    },
    "2": {
      size: "var(--space-6)",
      fontSize: textSize("3"),
      secondaryFontSize: textSize("2"),
      letterSpacing: textLetterSpacing("2"),
      radius: "max(var(--radius-2), var(--radius-full))",
    },
    "3": {
      size: "var(--space-7)",
      fontSize: textSize("4"),
      secondaryFontSize: textSize("3"),
      letterSpacing: textLetterSpacing("3"),
      radius: "max(var(--radius-3), var(--radius-full))",
    },
    "4": {
      size: "var(--space-8)",
      fontSize: textSize("5"),
      secondaryFontSize: textSize("4"),
      letterSpacing: textLetterSpacing("4"),
      radius: "max(var(--radius-3), var(--radius-full))",
    },
    "5": {
      size: "var(--space-9)",
      fontSize: textSize("6"),
      secondaryFontSize: textSize("6"),
      letterSpacing: textLetterSpacing("6"),
      radius: "max(var(--radius-4), var(--radius-full))",
    },
  };

  let {
    fallback = "",
    size = "3",
    variant = "soft",
    radius = "full",
    highContrast = false,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const sizeStyle = $derived(SIZE_MAP[String(size)] ?? SIZE_MAP["3"]);
  const fallbackText = $derived(String(fallback ?? ""));
  const classes = $derived(
    mergeClasses(
      "rxs-avatar",
      `rxs-avatar--${variant}`,
      highContrast ? "rxs-avatar--contrast" : "",
      className,
    ),
  );
  const resolvedRadius = $derived(
    radius === undefined || radius === null || radius === ""
      ? sizeStyle.radius
      : radiusValue(radius, sizeStyle.radius),
  );
  const avatarStyle = $derived(
    mergeStyles(
      `width: ${sizeStyle.size}`,
      `height: ${sizeStyle.size}`,
      `border-radius: ${resolvedRadius}`,
      `--avatar-fallback-one-letter-font-size: ${sizeStyle.fontSize}`,
      `--avatar-fallback-two-letters-font-size: ${sizeStyle.secondaryFontSize}`,
      `letter-spacing: ${sizeStyle.letterSpacing}`,
      style,
    ),
  );
  const fallbackClasses = $derived(
    mergeClasses(
      "rxs-avatar__fallback",
      fallbackText.length === 1 ? "rxs-avatar__fallback--one-letter" : "",
      fallbackText.length === 2 ? "rxs-avatar__fallback--two-letters" : "",
    ),
  );
</script>

<Primitive
  tag="span"
  className={classes}
  css={css}
  style={avatarStyle}
  {...restProps}
>
  {#if children}
    {@render children()}
  {:else}
    <span class={fallbackClasses}>
      {fallback}
    </span>
  {/if}
</Primitive>

<style>
  :global(.rxs-avatar) {
    align-items: center;
    display: inline-flex;
    flex-shrink: 0;
    font-family: var(--default-font-family, inherit);
    font-style: normal;
    justify-content: center;
    overflow: hidden;
    user-select: none;
    vertical-align: middle;
  }

  :global(.rxs-avatar img) {
    border-radius: inherit;
    height: 100%;
    object-fit: cover;
    width: 100%;
  }

  :global(.rxs-avatar__fallback) {
    align-items: center;
    border-radius: inherit;
    display: flex;
    font-family: var(--default-font-family, inherit);
    font-style: normal;
    font-weight: 500;
    height: 100%;
    justify-content: center;
    line-height: 1;
    text-transform: uppercase;
    width: 100%;
    z-index: 0;
  }

  :global(.rxs-avatar__fallback--one-letter) {
    font-size: var(--avatar-fallback-one-letter-font-size);
  }

  :global(.rxs-avatar__fallback--two-letters) {
    font-size: var(
      --avatar-fallback-two-letters-font-size,
      var(--avatar-fallback-one-letter-font-size)
    );
  }

  :global(.rxs-avatar--solid .rxs-avatar__fallback) {
    background-color: var(--accent-9);
    color: var(--accent-contrast);
  }

  :global(.rxs-avatar--solid.rxs-avatar--contrast .rxs-avatar__fallback) {
    background-color: var(--accent-12);
    color: var(--accent-1);
  }

  :global(.rxs-avatar--soft .rxs-avatar__fallback) {
    background-color: var(--accent-a3);
    color: var(--accent-a11);
  }

  :global(.rxs-avatar--soft.rxs-avatar--contrast .rxs-avatar__fallback) {
    color: var(--accent-12);
  }
</style>
