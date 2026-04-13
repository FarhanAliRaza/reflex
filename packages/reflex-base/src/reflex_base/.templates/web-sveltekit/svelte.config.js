import adapter from "@sveltejs/adapter-static";

const frontendPath = (process.env.REFLEX_FRONTEND_PATH || "").replace(
  /^\/+|\/+$/g,
  "",
);

export default {
  kit: {
    adapter: adapter({
      pages: "build/client",
      assets: "build/client",
      fallback: "200.html",
      strict: false,
    }),
    alias: {
      $: ".",
      "@": "./public",
    },
    paths: {
      base: frontendPath ? `/${frontendPath}` : "",
    },
    prerender: {
      handleUnseenRoutes: "ignore",
    },
  },
};
