<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    buildCssArtifacts,
    mergeClasses,
    mergeStyles,
    styleTagHtml,
    textLetterSpacing,
    textLineHeight,
    textSize,
  } from "$lib/reflex/components/style.js";

  let {
    asChild = false,
    href = "#",
    size = "3",
    underline = "auto",
    highContrast = false,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const linkCss = $derived({
    color: "inherit",
    fontSize: textSize(size),
    lineHeight: textLineHeight(size),
    letterSpacing: textLetterSpacing(size),
    fontWeight: "500",
    textDecorationLine: underline === "always" ? "underline" : "none",
    textDecorationStyle: "solid",
    textDecorationThickness: "min(2px, max(1px, 0.05em))",
    textUnderlineOffset: "calc(0.025em + 2px)",
    textDecorationColor: highContrast ? "var(--accent-a6)" : "var(--accent-a5)",
    ...((css && typeof css === "object") ? css : {}),
  });
  const childArtifacts = $derived(
    asChild ? buildCssArtifacts(linkCss, className, " > *") : null,
  );
  const classes = $derived(
    asChild
      ? mergeClasses(
          "rxs-link-slot",
          `rxs-link-slot--underline-${underline}`,
          childArtifacts?.className,
        )
      : mergeClasses("rxs-link", `rxs-link--underline-${underline}`, className),
  );
</script>

<svelte:head>
  {#if childArtifacts?.cssText}
    {@html styleTagHtml(childArtifacts.cssText)}
  {/if}
</svelte:head>

{#if asChild}
  <span class={classes} style="display: contents;">
    {@render children?.()}
  </span>
{:else}
  <Primitive
    tag="a"
    className={classes}
    css={linkCss}
    style={typeof style === "string" ? mergeStyles(style) : style}
    href={href}
    children={children}
    {...restProps}
  />
{/if}

<style>
  :global(.rxs-link),
  :global(.rxs-link-slot > *) {
    cursor: var(--cursor-link, pointer);
    text-decoration-line: none;
  }

  @media (hover: hover) {
    :global(.rxs-link--underline-auto:hover),
    :global(.rxs-link--underline-hover:hover),
    :global(.rxs-link-slot--underline-auto > *:hover),
    :global(.rxs-link-slot--underline-hover > *:hover) {
      text-decoration-line: underline;
    }
  }

  :global(.rxs-link--underline-always),
  :global(.rxs-link-slot--underline-always > *) {
    text-decoration-line: underline;
  }

  :global(.rxs-link:focus-visible),
  :global(.rxs-link-slot > *:focus-visible) {
    border-radius: calc(0.07em * var(--radius-factor, 1));
    outline: 2px solid var(--focus-8);
    outline-offset: 2px;
    text-decoration-line: none;
  }
</style>
