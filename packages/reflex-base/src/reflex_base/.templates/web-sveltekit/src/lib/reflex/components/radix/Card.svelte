<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, radiusValue } from "$lib/reflex/components/style.js";

  const SIZE_PADDING = {
    "1": "0.85rem",
    "2": "1.1rem",
    "3": "1.35rem",
    "4": "1.7rem",
    "5": "2rem",
  };

  let {
    size = "3",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses("rxs-card", className));
  const cardStyle = $derived(
    mergeStyles(
      `padding: ${SIZE_PADDING[String(size)] ?? SIZE_PADDING["3"]}`,
      `border-radius: ${radiusValue("large", "1rem")}`,
      style,
    ),
  );
</script>

<Primitive
  tag="div"
  className={classes}
  css={css}
  style={cardStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-card) {
    background: var(--color-panel-solid);
    border: 1px solid var(--gray-a5);
    box-shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
  }
</style>
