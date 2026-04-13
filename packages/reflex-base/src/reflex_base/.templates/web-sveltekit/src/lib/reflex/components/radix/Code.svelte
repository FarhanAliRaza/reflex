<script>
  import Primitive from "$lib/reflex/components/Primitive.svelte";
  import { mergeClasses } from "$lib/reflex/components/style.js";

  let { className = "", css = undefined, children = undefined, ...restProps } = $props();
  const classes = $derived(mergeClasses("rxs-code", className));
</script>

<Primitive
  tag="code"
  className={classes}
  css={css}
  children={children}
  {...restProps}
/>

<style>
  :global(.rxs-code) {
    font-family:
      "SFMono-Regular",
      "SF Mono",
      "IBM Plex Mono",
      "Menlo",
      monospace;
    font-size: 0.95em;
    background: rgba(148, 163, 184, 0.16);
    border-radius: 0.5rem;
    padding: 0.2rem 0.45rem;
  }
  </style>
