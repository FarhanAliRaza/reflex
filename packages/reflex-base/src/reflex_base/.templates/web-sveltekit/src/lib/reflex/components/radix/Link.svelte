<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    buildCssArtifacts,
    mergeClasses,
    mergeStyles,
    styleTagHtml,
    textSize,
  } from "$lib/reflex/components/style.js";

  let {
    asChild = false,
    href = "#",
    size = "3",
    underline = "auto",
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const linkCss = $derived({
    color: "inherit",
    fontSize: textSize(size),
    fontWeight: "500",
    textDecoration: underline === "none" ? "none" : "underline",
    ...((css && typeof css === "object") ? css : {}),
  });
  const childArtifacts = $derived(
    asChild ? buildCssArtifacts(linkCss, className, " > *") : null,
  );
  const classes = $derived(
    asChild
      ? mergeClasses("rxs-link-slot", childArtifacts?.className)
      : mergeClasses("rxs-link", className),
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
  :global(.rxs-link:hover),
  :global(.rxs-link-slot > *:hover) {
    color: var(--accent-9);
  }
</style>
