<script>
  import {
    buildCssArtifacts,
    mergeStyles,
    styleTagHtml,
    styleObjectToString,
  } from "$lib/reflex/components/style.js";

  let {
    tag = "div",
    className = "",
    css = undefined,
    style = undefined,
    ref = undefined,
    children = undefined,
    ...restProps
  } = $props();

  let element = $state(null);

  const cssArtifacts = $derived(buildCssArtifacts(css, className));
  const resolvedClass = $derived(cssArtifacts.className || undefined);
  const resolvedStyle = $derived(
    mergeStyles(
      typeof style === "string" ? style : styleObjectToString(style),
    ) || undefined,
  );

  $effect(() => {
    if (ref && typeof ref === "object") {
      ref.current = element ?? null;
    }
  });
</script>

<svelte:head>
  {#if cssArtifacts.cssText}
    {@html styleTagHtml(cssArtifacts.cssText)}
  {/if}
</svelte:head>

<svelte:element
  this={tag}
  bind:this={element}
  class={resolvedClass}
  style={resolvedStyle}
  {...restProps}
>
  {@render children?.()}
</svelte:element>
