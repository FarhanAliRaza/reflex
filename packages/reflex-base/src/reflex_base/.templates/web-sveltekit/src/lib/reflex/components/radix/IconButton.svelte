<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles } from "$lib/reflex/components/style.js";

  let {
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();
  const classes = $derived(mergeClasses("rxs-icon-button", className));
  const iconStyle = $derived(
    mergeStyles(
      "min-width: 2.75rem",
      "min-height: 2.75rem",
      "padding: 0.65rem",
      "border-radius: 999px",
      style,
    ),
  );
</script>

<Primitive
  tag="button"
  className={classes}
  css={css}
  style={iconStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-icon-button) {
    appearance: none;
    border: none;
    background: rgba(255, 255, 255, 0.72);
    color: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 12px 35px -24px rgba(15, 23, 42, 0.65);
    backdrop-filter: blur(12px);
  }
  </style>
