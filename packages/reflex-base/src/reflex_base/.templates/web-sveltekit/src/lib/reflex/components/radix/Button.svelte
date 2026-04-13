<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses, mergeStyles, radiusValue, textSize } from "$lib/reflex/components/style.js";

  const SIZE_STYLE = {
    "1": { fontSize: textSize("1"), minHeight: "2rem", padding: "0.45rem 0.8rem" },
    "2": { fontSize: textSize("2"), minHeight: "2.25rem", padding: "0.55rem 0.95rem" },
    "3": { fontSize: textSize("3"), minHeight: "2.65rem", padding: "0.72rem 1.15rem" },
    "4": { fontSize: textSize("4"), minHeight: "3rem", padding: "0.88rem 1.35rem" },
  };

  let {
    variant = "solid",
    size = "3",
    radius = "full",
    highContrast = false,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const classes = $derived(
    mergeClasses(
      "rxs-button",
      `rxs-button--${variant}`,
      highContrast ? "rxs-button--contrast" : "",
      className,
    ),
  );
  const sizeStyle = $derived(SIZE_STYLE[String(size)] ?? SIZE_STYLE["3"]);
  const buttonStyle = $derived(
    mergeStyles(
      `font-size: ${sizeStyle.fontSize}`,
      `min-height: ${sizeStyle.minHeight}`,
      `padding: ${sizeStyle.padding}`,
      `border-radius: ${radiusValue(radius, "999px")}`,
      style,
    ),
  );
</script>

<Primitive
  tag="button"
  className={classes}
  css={css}
  style={buttonStyle}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-button) {
    appearance: none;
    align-items: center;
    background: var(--accent-9);
    border: 1px solid transparent;
    box-shadow: 0 18px 40px -28px rgba(17, 24, 39, 0.35);
    color: white;
    cursor: pointer;
    display: inline-flex;
    font: inherit;
    font-weight: 700;
    gap: 0.5rem;
    justify-content: center;
    line-height: 1;
    text-decoration: none;
    transition:
      transform 140ms ease,
      box-shadow 140ms ease,
      opacity 140ms ease,
      background-color 140ms ease,
      border-color 140ms ease;
  }

  :global(.rxs-button:hover) {
    opacity: 0.98;
    transform: translateY(-1px);
  }

  :global(.rxs-button--outline) {
    background: transparent;
    border-color: var(--gray-a6);
    color: var(--gray-12);
    box-shadow: none;
  }

  :global(.rxs-button--soft) {
    background: var(--accent-3);
    color: var(--accent-10);
    box-shadow: none;
  }

  :global(.rxs-button--contrast) {
    background: var(--gray-12);
    color: var(--gray-1);
  }

  :global(.rxs-button--outline.rxs-button--contrast) {
    background: transparent;
    border-color: var(--gray-12);
    color: var(--gray-12);
  }
</style>
