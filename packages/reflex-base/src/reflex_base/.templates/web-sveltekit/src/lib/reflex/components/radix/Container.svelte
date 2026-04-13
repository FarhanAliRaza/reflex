<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    containerWidth,
    mergeClasses,
    mergeStyles,
  } from "$lib/reflex/components/style.js";

  let {
    size = "3",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-container", className));
  const containerStyle = $derived(
    mergeStyles(
      `width: min(100%, ${containerWidth(size)})`,
      "margin-inline: auto",
      "padding-inline: 1rem",
      style,
    ),
  );
</script>

<Primitive
  tag="div"
  className={classes}
  css={css}
  style={containerStyle}
  children={children}
  {...restProps}
/>
