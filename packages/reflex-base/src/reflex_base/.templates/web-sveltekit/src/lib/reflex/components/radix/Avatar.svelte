<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, radiusValue, textSize } from "$lib/reflex/components/style.js";

  const SIZE_MAP = {
    "1": "1.5rem",
    "2": "2rem",
    "3": "2.5rem",
    "4": "3rem",
    "5": "3.5rem",
  };

  let {
    fallback = "",
    size = "2",
    radius = "full",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const avatarSize = $derived(SIZE_MAP[String(size)] ?? SIZE_MAP["2"]);
  const classes = $derived(mergeClasses("rxs-avatar", className));
  const avatarStyle = $derived(
    mergeStyles(
      `width: ${avatarSize}`,
      `height: ${avatarSize}`,
      `border-radius: ${radiusValue(radius, "999px")}`,
      `font-size: ${textSize(size === "1" ? "1" : "2")}`,
      style,
    ),
  );
</script>

<Primitive
  tag="span"
  className={classes}
  css={css}
  style={avatarStyle}
  {...restProps}
>
  {#if children}
    {@render children()}
  {:else}
    {fallback}
  {/if}
</Primitive>

<style>
  :global(.rxs-avatar) {
    align-items: center;
    background: var(--gray-3);
    border: 1px solid var(--gray-a5);
    color: var(--gray-12);
    display: inline-flex;
    font-weight: 700;
    justify-content: center;
    overflow: hidden;
    user-select: none;
  }
</style>
