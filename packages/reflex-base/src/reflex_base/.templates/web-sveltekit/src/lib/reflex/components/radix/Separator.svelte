<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, resolveSpacing } from "$lib/reflex/components/style.js";

  let {
    size = "3",
    orientation = "horizontal",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-separator", className));
  const isVertical = $derived(orientation === "vertical");
  const separatorStyle = $derived(
    mergeStyles(
      isVertical ? "width: 1px" : "height: 1px",
      isVertical ? "align-self: stretch" : "width: 100%",
      !isVertical ? `margin-block: ${resolveSpacing(size) ?? "1rem"}` : "",
      style,
    ),
  );
</script>

<Primitive
  tag="div"
  aria-orientation={orientation}
  className={classes}
  css={css}
  style={separatorStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-separator) {
    background: var(--gray-a6);
    flex-shrink: 0;
  }
</style>
