<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles } from "$lib/reflex/components/style.js";

  const SIZE_PADDING = {
    "1": "var(--space-5)",
    "2": "var(--space-7)",
    "3": "var(--space-9)",
    "4": "calc(80px * var(--scaling))",
  };

  let {
    size = "2",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-section", className));
  const sectionStyle = $derived(
    mergeStyles(
      `padding-block: ${SIZE_PADDING[String(size)] ?? SIZE_PADDING["2"]}`,
      style,
    ),
  );
</script>

<Primitive
  tag="section"
  className={classes}
  css={css}
  style={sectionStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-section) {
    box-sizing: border-box;
    flex-shrink: 0;
  }
</style>
