<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    headingLetterSpacing,
    headingLineHeight,
    headingSize,
    mergeClasses,
    mergeStyles,
  } from "$lib/reflex/components/style.js";

  let {
    as = "h1",
    size = "6",
    weight = undefined,
    align = undefined,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-heading", className));
  const headingStyle = $derived(
    mergeStyles(
      `font-size: ${headingSize(size)}`,
      `line-height: ${headingLineHeight(size)}`,
      `letter-spacing: ${headingLetterSpacing(size)}`,
      weight ? `font-weight: ${weight === "bold" ? "700" : weight}` : "",
      align ? `text-align: ${align}` : "",
      style,
    ),
  );
</script>

<Primitive
  tag={as}
  className={classes}
  css={css}
  style={headingStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-heading) {
    color: var(--gray-12);
    font-family: var(--heading-font-family, inherit);
    font-style: var(--heading-font-style, normal);
    font-weight: 700;
    margin: 0;
    text-wrap: balance;
  }
</style>
