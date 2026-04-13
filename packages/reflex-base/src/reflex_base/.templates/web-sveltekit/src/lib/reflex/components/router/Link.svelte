<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses } from "$lib/reflex/components/style.js";

  let {
    to = "#",
    className = "",
    css = undefined,
    target = undefined,
    rel = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(mergeClasses(className));
  const resolvedRel = $derived(
    rel ?? (target === "_blank" ? "noreferrer noopener" : undefined),
  );
</script>

<Primitive
  tag="a"
  className={classes}
  css={css}
  href={to}
  target={target || undefined}
  rel={resolvedRel}
  children={children}
  {...restProps}
/>
