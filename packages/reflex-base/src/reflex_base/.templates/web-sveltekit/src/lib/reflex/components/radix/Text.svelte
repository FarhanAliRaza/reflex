<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    mergeClasses,
    mergeStyles,
    textLetterSpacing,
    textLineHeight,
    textSize,
  } from "$lib/reflex/components/style.js";

  let {
    as = "p",
    size = undefined,
    weight = undefined,
    align = undefined,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-text", className));
  const resolvedSize = $derived(size ?? (as === "span" ? undefined : "4"));
  const textStyle = $derived(
    mergeStyles(
      resolvedSize ? `font-size: ${textSize(resolvedSize)}` : "",
      resolvedSize
        ? `line-height: ${textLineHeight(resolvedSize)}`
        : as === "span"
          ? "line-height: inherit"
          : "line-height: var(--default-line-height)",
      resolvedSize ? `letter-spacing: ${textLetterSpacing(resolvedSize)}` : "",
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
  style={textStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-text) {
    color: var(--gray-12);
    font-family: var(--default-font-family, inherit);
    font-style: normal;
    margin: 0;
  }
</style>
