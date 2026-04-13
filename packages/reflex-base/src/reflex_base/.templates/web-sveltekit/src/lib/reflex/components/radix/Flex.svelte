<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    alignValue,
    justifyValue,
    mergeClasses,
    mergeStyles,
    resolveSpacing,
  } from "$lib/reflex/components/style.js";

  let {
    direction = "row",
    align = undefined,
    justify = undefined,
    gap = undefined,
    wrap = undefined,
    minHeight = undefined,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-flex", className));
  const flexStyle = $derived(
    mergeStyles(
      "display: flex",
      direction ? `flex-direction: ${direction}` : "",
      align ? `align-items: ${alignValue(align)}` : "",
      justify ? `justify-content: ${justifyValue(justify)}` : "",
      gap ? `gap: ${resolveSpacing(gap)}` : "",
      wrap ? `flex-wrap: ${wrap}` : "",
      minHeight ? `min-height: ${minHeight}` : "",
      style,
    ),
  );
</script>

<Primitive
  tag="div"
  className={classes}
  css={css}
  style={flexStyle}
  children={children}
  {...restProps}
/>
