<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles } from "$lib/reflex/components/style.js";

  const SIZE_PADDING = {
    "1": "1.5rem",
    "2": "2.25rem",
    "3": "3rem",
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
