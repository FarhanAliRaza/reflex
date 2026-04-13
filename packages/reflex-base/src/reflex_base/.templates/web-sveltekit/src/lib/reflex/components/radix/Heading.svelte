<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { headingSize, mergeClasses, mergeStyles } from "$lib/reflex/components/style.js";

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
      "line-height: 1.05",
      weight ? `font-weight: ${weight === "bold" ? "800" : weight}` : "",
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
    font-weight: 800;
    letter-spacing: -0.04em;
    margin: 0;
    text-wrap: balance;
  }
</style>
