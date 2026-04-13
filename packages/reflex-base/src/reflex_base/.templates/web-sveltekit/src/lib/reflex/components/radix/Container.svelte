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
  const containerStyle = $derived(mergeStyles(style));
  const innerStyle = $derived(
    mergeStyles("width: 100%", `max-width: ${containerWidth(size)}`),
  );
</script>

<Primitive
  tag="div"
  className={classes}
  css={css}
  style={containerStyle}
  {...restProps}
>
  <div class="rxs-container__inner" style={innerStyle}>
    {@render children?.()}
  </div>
</Primitive>

<style>
  :global(.rxs-container) {
    align-items: center;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    flex-grow: 1;
    flex-shrink: 0;
  }

  :global(.rxs-container__inner) {
    width: 100%;
  }
</style>
