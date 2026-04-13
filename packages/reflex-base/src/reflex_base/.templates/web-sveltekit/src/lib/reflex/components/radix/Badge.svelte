<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, radiusValue, textSize } from "$lib/reflex/components/style.js";

  const SIZE_PADDING = {
    "1": "0.18rem 0.45rem",
    "2": "0.28rem 0.6rem",
    "3": "0.38rem 0.75rem",
  };

  let {
    size = "2",
    variant = "soft",
    radius = "full",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-badge", `rxs-badge--${variant}`, className));
  const badgeStyle = $derived(
    mergeStyles(
      `font-size: ${textSize(size === "1" ? "1" : "2")}`,
      `padding: ${SIZE_PADDING[String(size)] ?? SIZE_PADDING["2"]}`,
      `border-radius: ${radiusValue(radius, "999px")}`,
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
    font-weight: 700;
    gap: 0.35rem;
    letter-spacing: 0.02em;
    line-height: 1;
  }

  :global(.rxs-badge--soft),
  :global(.rxs-badge--surface) {
    background: var(--accent-3);
    border: 1px solid var(--accent-5);
    color: var(--accent-10);
  }

  :global(.rxs-badge--outline) {
    background: transparent;
    border: 1px solid var(--gray-a6);
    color: var(--gray-12);
  }
</style>
