<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, textSize } from "$lib/reflex/components/style.js";

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
      as === "span" ? "line-height: inherit" : "line-height: 1.65",
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
    margin: 0;
  }
</style>
