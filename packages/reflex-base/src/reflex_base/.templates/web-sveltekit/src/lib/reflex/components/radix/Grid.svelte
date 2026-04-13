<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import {
    buildCssArtifacts,
    mergeClasses,
    mergeStyles,
    resolveSpacing,
    styleTagHtml,
    styleObjectToString,
  } from "$lib/reflex/components/style.js";

  function normalizeColumns(value) {
    if (value === undefined || value === null || value === "") {
      return "repeat(1, minmax(0, 1fr))";
    }
    return /^\d+$/.test(String(value))
      ? `repeat(${value}, minmax(0, 1fr))`
      : String(value);
  }

  function buildGridCss(columns, gap, css) {
    return {
      display: "grid",
      gap: gap === undefined ? undefined : resolveSpacing(gap),
      gridTemplateColumns: columns,
      ...((css && typeof css === "object") ? css : {}),
    };
  }

  let {
    columns = "1",
    gap = undefined,
    className = "",
    css = undefined,
    style = undefined,
    children = undefined,
    ...restProps
  } = $props();

  const responsiveColumns = $derived(
    typeof columns === "object"
      ? Object.fromEntries(
          Object.entries(columns).map(([breakpoint, value]) => [
            breakpoint,
            normalizeColumns(value),
          ]),
        )
      : normalizeColumns(columns),
  );
  const gridCss = $derived(buildGridCss(responsiveColumns, gap, css));
  const gridArtifacts = $derived(buildCssArtifacts(gridCss, className));
  const gridStyle = $derived(
    mergeStyles(
      typeof style === "string" ? style : styleObjectToString(style),
    ),
  );
</script>

<svelte:head>
  {#if gridArtifacts.cssText}
    {@html styleTagHtml(gridArtifacts.cssText)}
  {/if}
</svelte:head>

<Primitive
  tag="div"
  className={mergeClasses("rxs-grid", gridArtifacts.className)}
  style={gridStyle}
  children={children}
  {...restProps}
/>
