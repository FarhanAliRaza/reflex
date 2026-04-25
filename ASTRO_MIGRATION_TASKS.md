# Astro Migration Master Tasks

## Context

Client islands are the second lever on top of per-page entries. Once each page has its own entry, `render_mode="static"` removes page-wide React hydration from SEO/content pages, `render_mode="app"` keeps today's whole-page React behavior for interactive app routes, and `render_mode="islands"` carves individual hydrated components out of an otherwise static page.

Chosen direction:

- Add Astro as a second generated frontend target while retaining the current React Router target's public API and user-visible behavior until Astro reaches parity.
- Static output only: use Astro client islands, but no Astro SSR adapters, no on-demand rendering, no server islands, and no runtime server-side rendering.
- Astro has three page modes: `static`, `app` (default), and `islands`.
  - `static` — no Reflex runtime, 0 KiB first-party JS. For blog posts, docs pages, plain content.
  - `app` — whole page compiles to one page-root island (one hydrated React root). Zero user annotation or component metadata required. Zero-migration default for existing Reflex apps. For dashboards and mostly-interactive routes.
  - `islands` — most of the page ships as HTML; only component-marked or signal-detected subtrees hydrate as separate islands. For marketing homepages and landing pages with targeted interactive widgets (theme switcher, subscribe form).
- Cross-page navigation uses document navigation, with hover prefetch where appropriate.
- Extract a target-agnostic event loop runtime that both targets share.
  - React Router target: `useEventLoop` is a React hook adapter that instantiates and manages the shared `EventLoop` lifecycle.
  - Astro target: a page/global runtime singleton uses the same `EventLoop` directly.
- Use Zustand as the generated state/runtime store for both frontend targets. React Router output should be converted to the same store surface, and Astro islands benefit because Zustand can be shared across separate React roots.

## Glossary

- `react_router` target: the current generated frontend target. Its public API and user-visible behavior must remain compatible while its internal state/event runtime can be refactored.
- `astro` target: the new generated static-output frontend target.
- `static` page: corresponds to `render_mode="static"`. An Astro page with no Reflex runtime JS, no React root, no websocket, and no `client:*` directive. State/event usage is a compile error.
- `app` page (default): corresponds to `render_mode="app"`. An Astro page that compiles the whole route to one hydrated React root (one page-root island). No user annotation or component metadata consulted; behaves like today's Reflex page.
- `islands` page: corresponds to `render_mode="islands"`. An Astro page where most of the route ships as HTML and only component-marked or signal-detected subtrees hydrate as separate islands. Compiler reads `requires_hydration` component metadata (Path B) plus state/event signals from the render tree (Path A) to place island boundaries.
- page-root island: the single hydrated React root emitted by an `app` page. Also the shape used to represent any subtree that hydrates as one React root inside an `islands` page.
- explicit island: a user-authored `rx.island(...)` call. Valid only in `render_mode="islands"` pages; used to override hydration strategy, widen a boundary, or force `client_only`.
- runtime bootstrap: the code path that initializes the Reflex runtime (Zustand store, `EventLoop`, socket). Runs inside whichever island hydrates first — the page-root island in `app` mode, the first stateful island in `islands` mode. Not emitted as a separate Astro component.

## Phase A: Zustand Runtime On React Router

- [ ] Refactor generated React Router output to use the shared Zustand store/runtime before starting the Astro prototype.
  - Preserve the current React Router target's public API, commands, routing behavior, and app output shape.
  - Replace generated `StateContexts`, `DispatchContext`, `EventLoopContext`, `UploadFilesContext`, and `ColorModeContext` state/runtime wiring with Zustand selectors/actions.
  - Keep `StateProvider`, `EventLoopProvider`, and `AppWrap` only as compatibility shells that delegate to the shared store/event-loop runtime.
  - Record the planned deprecation and removal versions for those compatibility shells before shipping the refactor broadly.
- [ ] Prove React Router + Zustand parity before using it as the Astro baseline.
  - Run the full existing unit, integration, and Playwright suites unchanged against the React Router target.
  - Run representative docs/app and example app smoke tests.
  - Record a React Router + Zustand performance baseline for selected `docs/app` routes.
  - Do not start Phase B until this phase passes.

## Phase B: Astro MVP on `docs/app`

- [ ] Ship an Astro-target MVP on `docs/app`: one `.astro` file per Reflex route generated under `.web/src/pages/`, `render_mode="app"` on every route, page-root island as `client:load`. React Router target remains in parallel. Record the resulting per-route bundle shape and mobile Lighthouse deltas vs. the Phase A baseline directly in this file, then proceed to Phase C.

## Phase C: Full Astro Target And Migration

## Master Task 1: Generated Frontend Targets

- [x] Add a frontend target abstraction:
  - `react_router`: current generated target, kept compatible.
  - `astro`: new static-output target.
  - target selection is explicit in config/CLI during migration.
- [x] Generate target-specific `package.json` commands and dependencies:
  - React Router target keeps current `react-router dev --host` and `react-router build` commands.
  - Astro target uses `astro dev --host` and `astro build`.
  - React Router dependencies remain scoped to the React Router target.
  - Shared generated runtime adds `zustand` for both targets after Phase A.
  - Astro target adds `astro` and `@astrojs/react`.
- [x] Generate `astro.config.mjs` for the Astro target while preserving `react-router.config.js` for the React Router target.
  - Set Astro output to static.
  - Do not install or configure SSR adapters.
  - Preserve `frontend_path`/base path behavior.
  - Preserve dev server host/port/HMR settings.
  - Keep existing Vite aliases for `$` and `@`.
  - Remove the Safari cache-bust plugin for the Astro target and rely on Astro/Vite content-hashed assets.
  - If Phase B finds a Safari-specific cache regression, treat it as a separate targeted bug instead of keeping the old plugin by default.
  - Configure env exposure for both preferred Astro `PUBLIC_*` variables and legacy `VITE_*` variables during the migration window.
- [ ] Restructure `.web` output:
  - Keep the current React Router layout for the `react_router` target.
  - Generate Astro pages under `src/pages` for the `astro` target.
  - Generate shared layouts under `src/layouts` for the `astro` target.
  - Generate React app/island modules under `src/components` or `src/reflex` for the `astro` target.
  - Generate one Astro entry per route so unrelated routes do not share first-load JS by default.
  - Preserve `public/`, assets copying, `env.json`, and `reflex.json`.
- [ ] Update `reflex run`, `reflex export`, deploy, and frontend build helpers to branch by frontend target.
  - AppHarness scope is narrow: the `<js_runtime> run dev` spawn at [reflex/testing.py:376-382](reflex/testing.py#L376-L382) is already target-agnostic. Only the startup regex at [packages/reflex-base/src/reflex_base/constants/base.py:170-178](packages/reflex-base/src/reflex_base/constants/base.py#L170-L178) needs to match Astro's dev-server output (`➜  Local    http://...`) in addition to the React Router form.
  - Document dev-vs-prod differences in Astro island hydration and HMR boundaries.
- [ ] Enumerate the four React-Router-hardcoded surfaces that must become target-aware. No other location in `reflex/` or `packages/reflex-base/` should reference React Router directly.
  - [packages/reflex-base/src/reflex_base/.templates/web/utils/state.js:9-13](packages/reflex-base/src/reflex_base/.templates/web/utils/state.js#L9-L13): `useLocation`, `useNavigate`, `useParams`, `useSearchParams` imported from `"react-router"`. Replace with a router adapter interface (see Master Task 5).
  - [packages/reflex-base/src/reflex_base/compiler/templates.py:206](packages/reflex-base/src/reflex_base/compiler/templates.py#L206): root template imports `Outlet` from `'react-router'`. Astro target emits a different root template with no `Outlet`.
  - [packages/reflex-base/src/reflex_base/constants/installer.py:107-108](packages/reflex-base/src/reflex_base/constants/installer.py#L107-L108): `PackageJson.Commands.DEV = "react-router dev --host"` and `EXPORT = "react-router build"`. These become target-aware (Astro uses `astro dev --host` / `astro build`).
  - [packages/reflex-base/src/reflex_base/constants/installer.py:126](packages/reflex-base/src/reflex_base/constants/installer.py#L126): `PackageJson.DEPENDENCIES` hardcodes `react-router`. Astro target replaces it with `astro` + `@astrojs/react`.
- [ ] Add a CI grep check that fails if any non-target-specific module references `react-router` or `@react-router/*` after the refactor.

## Master Task 2: Astro Page Modes

- [x] Add `render_mode: Literal["static", "app", "islands"] = "app"` to the `rx.page` decorator in [reflex/page.py](reflex/page.py). Thread it through to the compilation context used by `compile_page` ([packages/reflex-base/src/reflex_base/plugins/compiler.py:276](packages/reflex-base/src/reflex_base/plugins/compiler.py#L276)).
- [ ] Per-mode output shape (Astro target):
  - `static`: emit `.web/src/pages/<route>.astro` with raw HTML for the rendered tree + `<script>` for the inline head theme setter. No React module import. No runtime.
  - `app` (default): emit `.web/src/pages/<route>.astro` containing one React component import rendered with `client:load`. That component is the page-root island and holds the full rendered tree, the Zustand runtime bootstrap, and `initialEvents` with `HYDRATE` + `onLoadInternalEvent()`.
  - `islands`: emit `.web/src/pages/<route>.astro` with inline Astro HTML for static subtrees and one `<ComponentName client:*/>` element per compiler-detected island. Each island is a separate generated module under `.web/src/reflex/islands/`. `initialEvents` omits `onLoadInternalEvent()`.
- [ ] Island-boundary placement rule (`islands` mode only). Deterministic; runs inside the existing component-walk plugin in `memoize.py`.
  - Path A — tree signals (already computed by `MemoizeStatefulPlugin._should_memoize`): any node with var_data, event_triggers, or structural Cond/Foreach/Match with state-dependent condition → promote the smallest enclosing subtree to an island.
  - Path B — class metadata from Master Task 7: `requires_hydration = True` → island root at this node. `provides_hydrated_context = True` → island boundary covers the entire subtree. `client_only = True` → `client:only="react"` directive.
  - Suppression: if any ancestor is already an island root in the same walk, skip.
  - Emission: each island root gets its own generated React module imported by the `.astro` file with the chosen `client:*` directive.
- [ ] `rx.island(...)` compile-time validation (one location, per-mode):
  - `static`: raise `CompileError` with message pointing at the offending call site.
  - `app`: raise `CompileError` or warn-and-strip the wrapper (pick one; current plan leaves the choice open).
  - `islands`: allowed; merges with compiler-auto-placed islands. Options: `hydrate` ∈ `{"load", "idle", "visible"}` or `{"media": str}`; `client_only: bool`.
- [ ] `static`-mode rejection in the compiler walk: on a `render_mode="static"` page, any node whose tree signals match Path A is a `CompileError`. Error includes file, line, component class, and the offending var/trigger name. Implement as a plugin that runs before `MemoizeStatefulPlugin` on `static` pages.
- [x] React Router target behavior: `render_mode` is accepted but only `"app"` is honored. `"static"` and `"islands"` emit a `console.deprecate`-style warning ("Astro-only; compiling as 'app'") and fall through to the existing codegen path.
- [ ] Navigation model (applies to `app` and `islands`):
  - Cross-route `rx.link(...)` compiles to `<a href=...>` (document navigation). No `<Link>` component from a framework router.
  - `rx.redirect(...)` events call `window.location.href = url` for internal routes.
  - Back/forward/history defer to browser default behavior.
- [ ] Route-file generation cases the compiler must cover (one `.astro` file per case):
  - index (`/`) → `.web/src/pages/index.astro`
  - nested static (`/docs/guide`) → `.web/src/pages/docs/guide.astro`
  - dynamic with known paths (`/blog/[slug]`) → `getStaticPaths()` in the `.astro` file returning the compile-time list
  - catchall (`/docs/[...path]`) → `getStaticPaths()` returning all prebuilt paths; unknown paths rely on host rewrite (Master Task 10)
  - 404 → `.web/src/pages/404.astro`
  - `frontend_path` (e.g. `/docs`) → Astro `base` config + route prefix in file paths

## Master Task 3: Routing, Navigation, And Prefetch

- [ ] Rewrite the page-emission path to produce one file per route for the Astro target.
  - Current state: `compile_page` in [packages/reflex-base/src/reflex_base/plugins/compiler.py:276](packages/reflex-base/src/reflex_base/plugins/compiler.py#L276) contributes to a single `.web/src/app/routes.js` manifest + shared `entry.client.js` (both in the compiler's `keep_files` list). The page-compile loop lives in [reflex/compiler/compiler.py](reflex/compiler/compiler.py).
  - New `AstroPageEmitter` plugin (or target-specific branch in `compile_page`): writes `.web/src/pages/<route>.astro` per page, imports the generated island module(s), and does not contribute to any manifest.
  - Split point — artifacts that stay shared on the Astro target: the generated runtime module (`.web/src/reflex/runtime.ts`), the Zustand store module, component modules, styles. Artifacts that become per-page: the `.astro` file, the page-root island module (`app` mode), and island modules (`islands` mode).
  - Delete `routes.js` and `entry.client.js` from the Astro-target keep-list; keep them on the React Router target.
- [ ] Route-path → file-path translation in the emitter:
  - `/` → `pages/index.astro`
  - `/foo/bar` → `pages/foo/bar.astro`
  - `/blog/[slug]` → `pages/blog/[slug].astro` with `export async function getStaticPaths()` returning the compile-time list
  - `/docs/[...path]` → `pages/docs/[...path].astro`
  - `frontend_path="/docs"` sets Astro's `base: "/docs"` in `astro.config.mjs` and files still sit at `pages/*`; Astro handles the base-path prefixing.
- [ ] Internal link compilation:
  - `rx.link(href=...)` on the Astro target compiles to `<a href={href}>` with no framework router involvement.
  - Optional `prefetch` prop: maps to Astro's `<a data-astro-prefetch>` attribute (`"hover"`, `"tap"`, `"viewport"`, `"load"`, or `false`). Default `"hover"`; document others as opt-in.
- [ ] Route data passed from Astro into hydrated React modules. Astro exposes `Astro.url`, `Astro.params`, `Astro.request.url` at build time for prerender. Compile these into the generated island's props at page-compile time:
  - `pathname` from `Astro.url.pathname`
  - `search_params` — read in-browser from `window.location.search` inside the island (build-time URL has no live search params)
  - `params` from `Astro.params` (dynamic segments)
  - `frontend_path` from config
- [ ] Runtime `rx.State.router` slot: populate from the same sources when the Zustand runtime boots in the island. Same shape the backend sees today; no new fields.

## Master Task 4: Zustand Runtime State

- [ ] Rewrite `context_template()` in [packages/reflex-base/src/reflex_base/compiler/templates.py:344-422](packages/reflex-base/src/reflex_base/compiler/templates.py#L344-L422) to emit a Zustand store module instead of five React Contexts. Keep the function name and emitted file path (`$/utils/context.js` or renamed to `.ts`) so downstream imports resolve; swap the body.
- [ ] Store shape. One module-singleton Zustand store with named slices:
  - `state: { [stateName: string]: any }` — replaces `StateContexts` (`templates.py:359`). Initial value from `initialState` literal (already generated).
  - `dispatch: { [stateName: string]: (delta) => void }` — replaces `DispatchContext` (`templates.py:358`). Actions set slices of `state` from backend deltas.
  - `eventLoop: { addEvents, connectErrors, isHydrated }` — replaces `EventLoopContext` (`templates.py:360`). Populated by the `EventLoop` runtime module (Master Task 5) at boot.
  - `uploads: { [componentId: string]: File[] }` — replaces `UploadFilesContext` (`templates.py:357`).
  - `colorMode: { colorMode, resolvedColorMode, toggleColorMode, setColorMode }` — replaces `ColorModeContext` (`templates.py:351-356`).
- [ ] Emit helper hooks in the same generated module so call sites change minimally:
  - `useReflexState(stateName)` → `useStore(s => s.state[stateName])`
  - `useReflexDispatch(stateName)` → `useStore(s => s.dispatch[stateName])`
  - `useReflexEventLoop()` → `useStore(s => s.eventLoop)`
  - `useReflexUploads(componentId)` → `useStore(s => s.uploads[componentId])`
  - `useReflexColorMode()` → `useStore(s => s.colorMode)`
- [ ] Atomic delta application. Backend deltas that touch multiple slices must `set((s) => ({...}))` once, not once per slice, so subscribers see one commit. Implement inside the `EventLoop`'s `applyDelta` path ([state.js:applyDelta](packages/reflex-base/src/reflex_base/.templates/web/utils/state.js)).
- [ ] Call-site migration in templates. Update emitted hook bodies across [templates.py](packages/reflex-base/src/reflex_base/compiler/templates.py):
  - `useContext(StateContexts.foo)` → `useReflexState("foo")`
  - `useContext(EventLoopContext)` → `useReflexEventLoop()`
  - `useContext(UploadFilesContext)` → `useReflexUploads(id)`
  - `useContext(ColorModeContext)` → `useReflexColorMode()`
- [ ] Delete on both targets after the migration window: `StateProvider`, `EventLoopProvider`, `UploadFilesProvider`, `AppWrap` function, and `_get_app_wrap_components` aggregation (see Master Task 7). Providers that require React Context (Radix Roots, etc.) live inside their own island tree via `provides_hydrated_context` metadata, not at the app root.
- [ ] Test invariant: every generated file in `.web/src/` is grep-clean of `createContext` and `useContext(State`/`useContext(EventLoop`/`useContext(Upload`/`useContext(ColorMode` after the refactor. Keep one CI check that asserts this.
- [ ] Preserve runtime behavior; each item below must land in the Zustand port with a test:
  - initial state hydration from the generated `initialState` literal
  - backend delta application
  - `hydrateClientStorage` (`state.js`) reads cookies/local/session on boot and writes on change
  - websocket connect/reconnect re-fires `initialEvents` against the new socket
  - frontend exception events route to the same endpoint
  - `HYDRATE` and (in `app` mode) `onLoadInternalEvent()` events fire on connect

## Master Task 5: Events, Backend Sync, And Browser Actions

- [ ] Extract the event loop out of `state.js` into a target-agnostic module.
  - Prefer TypeScript for the new runtime module, for example `event_loop.ts`.
  - The module owns socket lifecycle, event queueing, backend URL resolution, router data, reconnect behavior, and frontend event application.
  - The module must not import React, React Router, Astro, or Zustand.
  - Keep small adapter modules for framework-specific integration.
- [ ] Define a router adapter interface that each target implements. Required today at [state.js:863-867](packages/reflex-base/src/reflex_base/.templates/web/utils/state.js#L863-L867): `useEventLoop` calls `useLocation()`, `useNavigate()`, `useParams()`, `useSearchParams()` as top-level hooks from `react-router` directly. Extraction is blocked until these are replaced with an adapter.
  - Adapter surface: `getLocation()`, `navigate(url)`, `getParams()`, `getSearchParams()`, plus a subscription mechanism for location changes.
  - React Router adapter: implements the surface using React Router hooks (`useLocation`, `useNavigate`, etc.). Lives in target-specific glue, not in the shared module.
  - Astro adapter: implements the surface using `window.location`, `history.pushState`, and `URLSearchParams` directly (document navigation only — see Master Task 3).
  - `EventLoop` calls the adapter methods instead of importing router hooks.
- [ ] Refactor `useEventLoop` into a React hook wrapper over the shared `EventLoop`.
  - React Router target keeps `AppWrap`/provider wiring during the compatibility window.
  - `useEventLoop` creates or acquires the page-level `EventLoop`, starts it on mount, reacts to route/location changes via the router adapter, and disposes it on unmount.
  - Existing React components continue receiving `addEvents` and `connectErrors` through the current mechanism until the target is migrated.
- [ ] Add an Astro runtime adapter over the same `EventLoop`.
  - Do not reuse the current React Router `AppWrap` as a global Astro layout wrapper. A layout-level React wrapper would force the Reflex runtime script to preload on every page, including static pages that do not need it, which drops Lighthouse performance for no corresponding benefit.
  - Astro layouts must stay non-React unless the page render mode explicitly needs hydration.
  - Astro page-root island pages create one page-level runtime singleton for that page's root island.
  - Astro page-root island pages use the same island wrapper shape as smaller islands, for example `AstroIslandRoot`, mounted around the whole page with the chosen `client:*` directive.
  - Astro island pages create one page-level runtime singleton shared by every island on that document.
  - Astro island pages use a tiny island wrapper, for example `AstroIslandRoot`, only around the hydrated island.
  - Components and islands never create their own websocket; they call generated runtime actions that delegate to the page-level `EventLoop`.
  - A document navigation tears down the old page runtime and the next page creates a new one if needed.
- [ ] Preserve all current frontend event behaviors:
  - redirect
  - download
  - set focus / blur focus
  - set value
  - call script / call function
  - upload files
  - temporal event actions
  - debounce/throttle helpers
  - websocket queueing
- [ ] Remove deprecated unload usage if possible.
  - Prefer `pagehide`/visibility-safe cleanup to improve best-practices score.
- [ ] Keep backend endpoint assumptions intact:
  - event websocket
  - upload endpoint
  - ping/health
  - `_all_routes`
  - backend path prefixing
- [ ] Measure the initial-load cost of the socket runtime.
  - `socket.io-client` is a meaningful payload on every `app` page and every `islands` page where a stateful island hydrates.
  - Track the cost separately in Phase A and Phase B bundle reports with a concrete ceiling (e.g. the per-page runtime bundle must be ≤ N KB gzip; pick N from the Phase A baseline).
  - If it breaks the `islands`-mode budget, investigate replacing socket.io with native WebSocket plus a thin reconnect/heartbeat protocol as a separate design decision.

## Master Task 6: Compiler And Plugin Output

- [ ] Update compiler templates:
  - page template emits an Astro page plus optional page-local React island imports.
  - document/root template becomes Astro layout.
  - context template becomes Zustand runtime module.
  - Vite config template becomes Astro config template.
  - Astro layout must not import `AstroIslandRoot`, Zustand, socket.io, or the event loop unless the page mode requires it.
  - `static` pages must not include `client:*` directives or React runtime imports.
  - `app` pages include one `client:load` directive on the page-root island; the runtime boots inside that island.
  - `islands` pages include `client:*` directives only on the compiler-placed islands (Path A / Path B from Master Task 2) and user-authored `rx.island(...)` overrides. The runtime boots inside the first stateful island to hydrate; no separate bootstrap component is emitted.
- [ ] Preserve plugin hooks defined at [packages/reflex-base/src/reflex_base/plugins/base.py](packages/reflex-base/src/reflex_base/plugins/base.py):
  - `get_frontend_dependencies` (line 89) and `get_frontend_development_dependencies` (line 76)
  - `get_static_assets` (line 102)
  - `get_stylesheet_paths` (line 115)
  - `pre_compile` (line 126) and `post_compile` (line 133)
  - `eval_page` (line 140)
  - `compile_page` (line 157) — runs once per page after component walking; Astro per-page entry emission plugs in here
  - `enter_component` (line 166) and `leave_component` (line 188)
  - app-wrap aggregation (to be deleted with the Zustand refactor; see Master Task 4)
  - memoized component wrappers ([reflex/compiler/plugins/memoize.py](reflex/compiler/plugins/memoize.py))
- [ ] Harden tree-shaking invariants:
  - Avoid global imports of heavy component packages unless needed by the page/island.
  - Fail CI if a static page bundle includes runtime JS or component packages flagged as hydrated/app-only.
  - Fail CI if a shared layout import pulls known heavy barrels such as Radix, Recharts, Plotly, or dashboard-only component bundles into static pages.
- [ ] Keep custom components and experimental memo output working with Astro-generated React modules.

## Master Task 7: Component Compatibility

- [ ] Audit every component package for Astro/runtime assumptions:
  - core components
  - Radix
  - Lucide
  - Recharts
  - Plotly
  - DataEditor
  - Markdown/Shiki/code
  - Moment
  - React Player
  - GridJS
  - Sonner/toast
  - internal/base components
- [ ] Classify components:
  - static-generation safe
  - hydrated interactive
  - browser-only `client:only="react"`
  - page-root-island only
- [ ] Design compiler metadata so components can declare hydration/runtime requirements.
  - Add `ClassVar` attributes on the `Component` base class, alongside the existing class-level metadata fields `tag`, `library`, and `lib_dependencies` in [packages/reflex-base/src/reflex_base/components/component.py](packages/reflex-base/src/reflex_base/components/component.py). Note: `tag` and `library` are dataclass-style fields today, not `ClassVar` declarations — the new hydration metadata is the first case of class-level `ClassVar` state on `Component` beyond the existing `_is_tag_in_global_scope`.
  - Minimum fields: `requires_hydration: ClassVar[bool]`, `provides_hydrated_context: ClassVar[bool]`, `client_only: ClassVar[bool]`, and a `heavy_bundle_group: ClassVar[str | None]` for CSS/JS chunking.
  - Framework-audited first-party components (core, Radix, Lucide, Recharts, Plotly, DataEditor, Markdown/Shiki, Moment, ReactPlayer, GridJS, Sonner, internal/base) declare these values explicitly on each class as part of the audit above.
  - Keep end users writing Reflex apps out of this — a user composing existing components should never need to set these flags.
  - Provide a `HydratedComponent(Component)` convenience base class for wrapper authors, parallel to the existing `NoSSRComponent` pattern in [packages/reflex-base/src/reflex_base/components/component.py:2373](packages/reflex-base/src/reflex_base/components/component.py#L2373). A custom component wrapping a third-party React library that needs the runtime subclasses `HydratedComponent` (or sets `requires_hydration = True` directly). This is the same "wrapper authors opt in" ergonomics Reflex already uses for SSR safety.
- [ ] Surface new ClassVar metadata in docgen and `.pyi` stubs.
  - Verify how `scripts/make_pyi.py` handles `ClassVar` attributes — `tag`/`library` are dataclass fields today, so there is no direct precedent for `ClassVar` defaults appearing in stubs.
  - Expected outcome: each component class's `.pyi` stub includes the declared `requires_hydration` / `provides_hydrated_context` / `client_only` / `heavy_bundle_group` values as class-level defaults.
  - Add a unit test in `tests/units/` that takes a representative component from each first-party package and asserts its stub contains the expected metadata.
  - Update `pyi_hashes.json` if the generated stubs change shape.
- [ ] Define metadata defaults and failure modes for third-party custom components:
  - The base `Component` default must be chosen by audit: either safe-default (`requires_hydration = True`, audited static primitives opt out) or fast-default (`requires_hydration = False`, audited interactive primitives opt in). Pick one and document the trade-off before shipping.
  - Unknown components in `render_mode="static"` are rejected unless the class declares it is static-generation safe.
  - Wrapper authors who forget to set `requires_hydration` on a third-party wrapper hit the same class of bug users hit today when they forget `NoSSRComponent` on a browser-only library; provide the same escape hatch (wrap the call site in `rx.island(...)`) and the same discoverable docs pointer.
- [ ] Ensure browser-only components do not break static rendering.

## Master Task 7A: Stateful Component Handling

- [ ] Preserve the current auto-memoization model.
  - Today `MemoizeStatefulPlugin` wraps components/subtrees that directly use state vars, special forms, or event triggers.
  - The compiler generates experimental memo component modules under `$/utils/components/{WrapperTag}`.
  - Each page imports the generated wrapper at the call site.
  - The old shared `$/utils/stateful_components` file is not emitted and should not come back.
  - App wrap/provider metadata discovered inside memoized subtrees must still bubble to the page/root runtime.
- [ ] Convert memo wrappers to the shared Zustand/runtime surface.
  - React Router target memo wrappers should also read state through generated Zustand selectors after the store refactor.
  - `StateProvider`, `EventLoopProvider`, and `AppWrap` can remain as compatibility shells during migration, but they should delegate to the shared store/event-loop runtime.
  - Stateful/eventful memo wrappers should continue receiving `addEvents`, state values, upload state, and color mode through target adapters backed by the shared runtime.
- [ ] Generate Astro target memo wrappers against the same shared runtime.
  - In `render_mode="app"` pages, memoized stateful subtrees live inside the page-root island automatically. No explicit wrapping or component metadata required.
  - In `render_mode="islands"` pages, the Path A classifier promotes each memoized stateful subtree to an island automatically; Path B component metadata covers the React-stateful-but-no-Reflex-state case (Radix roots, Plotly, etc.). `rx.island(...)` remains available as a per-call override.
  - Astro-generated memo wrappers read state through the same generated Zustand selectors as React Router output.
  - Event triggers inside Astro memo wrappers call generated runtime actions that delegate to the page-level `EventLoop`.
- [ ] Enforce mode-specific rules with actionable compile errors.
  - `render_mode="static"` rejects stateful components, event triggers, uploads, and state-dependent special forms. The error names the offending component, file, line, and specific var/trigger, and suggests either moving the behavior off the page or switching the page to `app` or `islands`.
  - `render_mode="app"` accepts stateful components anywhere — they land inside the page-root island. Component metadata (`requires_hydration`, etc.) is not consulted in this mode; everything hydrates as one React root.
  - `render_mode="islands"` auto-places islands using Path A (tree signals) and Path B (component metadata) from Master Task 2. User action is not required for correctness; `rx.island(...)` is only needed to override strategy or widen a boundary.
- [ ] Define the stateful-component classifier conservatively and test it.
  - Stateful means direct `rx.State` var reads in props/style/children, event trigger presence, uploads, state-dependent `rx.foreach`, state-dependent `rx.cond`, state-dependent `rx.match`, or hooks/imports that require the Reflex runtime.
  - Non-stateful means static render data only, no Reflex event triggers, no client storage sync, and no runtime hooks.
  - The classifier drives compile-time validation in `static` mode, memo wrapper generation in all modes, and island-boundary placement in `islands` mode.
- [ ] Keep late hydration safe.
  - A stateful subtree hydrating inside a deferred island reads the current Zustand snapshot on mount.
  - If backend deltas arrived before the subtree mounted, the store already contains them.
  - Multiple islands on one document share one page runtime and one websocket, not one websocket per memo wrapper or component.
- [ ] Preserve stateful page/backend semantics separately from stateful components.
  - Routes that create dynamic `rx.State` subclasses during compilation still need the backend stateful-pages marker behavior.
  - This marker is independent of the memoized stateful component wrapper mechanism.

## Master Task 8: Client Island API And Runtime Wiring

- [ ] Position `rx.island(...)` as an `islands`-mode override, not a correctness requirement.
  - `render_mode="static"` pages reject `rx.island(...)` at compile time (cannot hydrate in no-JS mode).
  - `render_mode="app"` pages (the zero-migration default) do not need `rx.island(...)`; the whole page is already one React root. `rx.island(...)` here is a compile error or warn-and-ignore — pick one and document.
  - `render_mode="islands"` pages auto-place islands via Path A (tree signals) and Path B (component metadata, Master Task 7). `rx.island(...)` is used only to change hydration strategy (`"idle"`/`"visible"`/media), widen a boundary to include sibling static content, or force `client_only` on a subtree the compiler would otherwise prerender.
- [ ] Add the explicit client island wrapper API:
  - `rx.island(component, hydrate="load")`
  - `hydrate="idle"`
  - `hydrate="visible"`
  - `hydrate={"media": "(max-width: 768px)"}`
  - `client_only=True | False` for browser-only components that cannot be rendered during the static build.
  - Default `hydrate` is `"load"` for correctness; users opt into `"idle"`, `"visible"`, or media-based hydration.
  - Default `client_only` is `False`; component metadata can force `client_only=True` for browser-only components (mirroring the existing `NoSSRComponent` pattern).
- [ ] Map Reflex island options to Astro `client:*` directives in static builds.
- [ ] Map browser-only islands to Astro `client:only="react"` instead of any SSR behavior.
- [ ] Define runtime boot policy per mode:
  - `render_mode="static"`: no runtime, no websocket.
  - `render_mode="app"`: page-root island is tagged `client:load`. Runtime boots on hydration (Zustand store, `EventLoop`, socket).
  - `render_mode="islands"`: no eager bootstrap. Runtime boots lazily when the first stateful/event island hydrates; its `useEffect` calls `getOrCreateRuntime().start()`. Pages without any stateful island never open a websocket.
  - Astro target does not support page `on_load` handlers outside `render_mode="app"`. Pages with `on_load` must use `app` mode (or drop the handler). Compile error otherwise. Rationale: `on_load` would require a separate `client:load` bootstrap island on every `islands` page, re-adding the cost `islands` mode exists to avoid.
  - Client storage reads that affect first paint (theme/color mode) are handled by an inline head script in Master Task 9, not by the runtime.
  - Multiple hydrated islands on one page share the same `EventLoop` and websocket (module-singleton runtime).
- [ ] Make late-hydrating islands race-safe:
  - Shared Zustand runtime initializes once per page.
  - Backend hydration deltas are applied to the store even before a given island mounts.
  - Islands hydrating later read the latest store snapshot on mount.
  - Event handlers queue until the runtime/socket path they need is ready.
- [ ] Define the island boundary serialization model.
  - Event handlers are not serialized through Astro props; the compiler bakes event chains into the generated island module/body.
  - Serializable props are JSON-compatible literals plus compiler-supported encoded Vars that can be resolved inside the generated island module.
  - Children passed to `rx.island(...)` are compiled as part of the island body, not serialized as arbitrary React nodes.
  - Event chains reachable from an island root must be statically resolvable by the compiler; dynamic event composition that cannot be reduced at compile time is a compile error.
  - Reject function props, arbitrary class instances, and unsupported Python objects at compile time with actionable errors.
- [ ] Define nested island behavior (`islands` mode only).
  - Reject nested `rx.island(...)` at compile time for v1.
  - An inner stateful subtree inside the page-root island (`app` mode) or inside an outer `rx.island(...)` (`islands` mode) is already part of that island's React tree; it does not need its own `rx.island(...)` wrapper.
- [ ] Support nested static content around islands in `islands` mode without pulling full-page React into an island's bundle. Tie this to the tree-shaking invariants in Master Task 6 and the per-page bundle budgets in Master Task 11: fail CI if a static portion of an `islands` page shows up in any island's bundle.
- [ ] Make `initialEvents` emission mode-aware in the generated runtime module.
  - Today [packages/reflex-base/src/reflex_base/compiler/templates.py:311-315](packages/reflex-base/src/reflex_base/compiler/templates.py#L311-L315) unconditionally emits `initialEvents = () => [ReflexEvent(HYDRATE), ...onLoadInternalEvent()]`, which runs on every websocket (re)connect.
  - `render_mode="app"`: emit `HYDRATE` + `onLoadInternalEvent()` as today; behavior unchanged.
  - `render_mode="islands"`: omit `onLoadInternalEvent()` entirely. `on_load` is already rejected on non-`app` pages (Master Task 2 / Master Task 12), so there is nothing to fire, and the `HYDRATE` event is all the runtime needs on connect.
  - `render_mode="static"`: `initialEvents` is not generated at all because the runtime module itself is not emitted on static pages.

## Master Task 9: Head, Styling, Assets, And Performance

- [ ] Preserve Reflex head/meta behavior through Astro layouts:
  - page title
  - `rx.meta`
  - Open Graph and Twitter tags
  - canonical URLs
  - favicon/manifest links
  - robots directives
  - sitemap output
- [ ] Prevent flash-of-wrong-theme on static/island pages. This is **new infrastructure**, not a port — the React Router target handles theme today via the React `ThemeProvider` at mount time, which does not run on `static` pages and runs too late on `islands` pages.
  - Build an inline head-script emitter that runs before first paint, reads persisted theme from the chosen storage source (cookie, localStorage, or a configured override), and sets the theme class/data attribute on `<html>`.
  - Define the fallback order explicitly (e.g. cookie → localStorage → system preference → `defaultColorMode`) and keep it consistent with whatever the runtime Zustand `colorMode` slice resolves to on hydration so islands do not re-flash after mount.
  - Make the script injection part of the Astro layout for `static` and `islands` pages, and part of the `app` page-root island's head for `app` pages.
  - Test that JS-disabled `static` pages still render with the correct theme from the cookie.
  - Apply the same pattern to other first-paint client preferences if needed (e.g. locale class on `<html>`).
- [ ] Split CSS by page/island where possible.
  - Static pages should not load dashboard/component-library CSS.
  - Component CSS should follow the component/page that needs it.
- [ ] Preserve Reflex style system behavior:
  - reset style
  - global styles
  - theme styles
  - plugin stylesheets
  - responsive/style props
- [ ] Fix landing-page performance issues separately from Astro:
  - cache headers for hashed assets
  - oversized images/responsive images
  - CORS issue for `numbers-pattern.avif`
  - render-blocking CSS
  - CLS from nav/hero sections
  - analytics loading strategy
- [ ] Add bundle reporting and enforced budgets for static pages, page-root island pages, and smaller-island pages.

## Master Task 10: Export, Hosting, And 404 Behavior

- [ ] Update export to package Astro static output.
- [ ] Separate behavior for ASGI-mounted frontend and CDN/static hosting:
  - ASGI mount can rewrite unknown paths to the generated 404/catchall document.
  - CDN/static hosts only serve generated files unless a host-specific rewrite config exists.
- [ ] Emit host-specific rewrite artifacts where possible:
  - Netlify `_redirects`
  - Vercel `vercel.json`
  - Cloudflare Pages `_redirects`
  - nginx snippet
  - S3/CloudFront custom error document notes
  - GitHub Pages `404.html` fallback notes, including the 404 status limitation
- [ ] Define dynamic/catchall route support under static output:
  - Known paths are prebuilt.
  - Unknown dynamic paths require ASGI or host rewrite support.
  - Hosts without rewrite support only support prebuilt paths plus `404.html` fallback behavior.
- [ ] Ensure static hosting works:
  - generated `dist`
  - `404.html`
  - frontend path subdirectory moves
  - asset paths
- [ ] Preserve ASGI frontend mounting in dev/prod where Reflex serves the frontend.
- [ ] Ensure no server-rendering entrypoint or adapter artifact is required for deploy.
- [ ] Verify deploy paths used by Reflex Cloud still receive the same backend/frontend artifacts.
- [ ] Keep `_all_routes` accurate for route patterns, prebuilt routes, and fallback behavior.

## Master Task 11: Tests, Visual Regression, And Budgets

- [ ] Unit tests:
  - package generation
  - Astro config generation
  - Astro `PUBLIC_*` and legacy `VITE_*` env exposure during the migration window
  - route conversion
  - render-mode validation
  - Zustand hook generation
  - Zustand transaction/slice consistency under multi-field backend deltas
  - head/meta generation
  - no generated React Context usage
  - Astro target emits no React Router dependencies/imports
- [ ] Integration tests:
  - full existing React Router integration suite passes unchanged after the Zustand refactor
  - React Router target on Zustand preserves behavior against the current Context baseline
  - `static` page works with JS disabled
  - `islands` page hydrates only the compiler-placed islands (Path A/Path B) and any user-authored `rx.island(...)` overrides
  - delayed `client:visible` island receives latest state snapshot
  - multiple stateful islands on one page share one websocket/event loop
  - `app` page dashboard-like route supports state/events/document navigation
  - uploads still work
  - client storage sync still works
  - color mode does not flash the wrong theme
  - websocket reconnect still works
- [ ] Playwright tests:
  - page navigation across `static`, `app`, and `islands` routes
  - dynamic params/search params
  - 404 and host fallback behavior
  - frontend path/base path
  - JS-disabled run against a `static`-mode route
- [ ] Visual regression tests:
  - compare key `docs/app` landing/content/library/API pages before and after migration
  - include light and dark color modes
  - include desktop and mobile viewports
- [ ] Performance tests and CI budgets:
  - `static` pages load 0 KiB first-party Reflex runtime JS by default
  - `app` pages load only their page-root island chunk (runtime boots inside it), with no React Router manifest/router chunk
  - `islands` pages load only their island chunks (runtime boots inside the first stateful island), with zero JS on the static portions of the page and zero JS on pages whose islands never hydrate
  - route JS/CSS budgets fail CI on regressions above the configured threshold
  - Lighthouse baselines are tracked for selected `docs/app` routes and example landing pages

## Master Task 12: Migration, Docs, And Breaking Change Work

- [ ] Target selection: add `frontend_target: Literal["react_router", "astro"] = "react_router"` to `rx.Config`. Wire it through `reflex run` / `reflex export` / `reflex init` / `AppHarness` so the same Reflex app can be compiled against either target based on config.
- [ ] Compile-time defaults for Astro target (no user code changes required to migrate an existing app):
  - `render_mode` on every existing page defaults to `"app"`.
  - ✅ `on_load` + `render_mode` combo: if user picks `static`/`islands` with an `on_load` present, raise `CompileError` at the page-registration site in [reflex/page.py](reflex/page.py) with message `"on_load is only supported in render_mode='app' on the Astro target. Remove the handler or switch the page to app mode."`
  - Custom components with no `requires_hydration` ClassVar used on an `islands` page: emit a single `console.deprecate`-style warning with the class name and suggest `HydratedComponent(Component)` subclassing.
  - `static` pages using state/events: `CompileError` naming offending node (handled by Master Task 7A classifier).
- [ ] Compatibility shim policy (one table, one version per row):
  - `StateProvider`, `EventLoopProvider`, `UploadFilesProvider`, `AppWrap` function: shim until the Zustand refactor ships; emit as thin delegations to the generated Zustand hooks. Deprecate in the next dot version after Phase A lands. Remove in 1.0.
  - `_get_app_wrap_components` method on `Component`: emit `console.deprecate` from any override site at import time. No-op on Astro target from day one. Remove in 1.0.
  - Legacy `VITE_*` env vars: exposed alongside `PUBLIC_*` for the full migration window. Remove when React Router target is removed.
  - `rx.page(on_load=...)` on `static`/`islands` pages: fails fast with a `CompileError`; no shim.
- [ ] Gates for making Astro the default target (flip `frontend_target` default to `astro`):
  - Full `tests/units` pass on both targets with the same app inputs.
  - Full `tests/integration/tests_playwright` pass against `frontend_target="astro"`.
  - `docs/app` builds and serves on Astro with no visual regressions and meets its recorded Phase B budget.
  - ASGI-mounted frontend path works on Astro target (Master Task 10).
  - Reflex Cloud export path produces deployable artifacts on Astro target.
  - A PR exists that sets a concrete `deprecation_version` / `removal_version` for the React Router target via `console.deprecate()` and updates `pyi_hashes.json`.
- [ ] Write the user-facing migration guide with a one-per-step format: (1) set `frontend_target="astro"` in config; (2) re-run `reflex init`; (3) verify pages with `on_load` still work (they compile as `app`); (4) optionally switch content pages to `render_mode="static"` and measure; (5) optionally switch landing pages to `render_mode="islands"` and measure. No step requires component code changes for existing apps.
- [ ] Document mode limitations as a single reference table:
  - `static`: no state, no events, no uploads, no `on_load`, no client storage writes.
  - `app`: no effective difference from today's Reflex.
  - `islands`: `rx.island(...)` boundary props must be JSON-serializable or compiler-resolvable Vars; nested `rx.island(...)` is a compile error; unknown dynamic paths require ASGI or host rewrite support; browser-only components require `client_only=True`.
- [ ] Update release notes, `CHANGELOG`, and troubleshooting docs. Add a top-level section to [CLAUDE.md](CLAUDE.md) pointing at the three-mode model for coding-agent context.

## Acceptance Criteria

- Phase A proves Zustand-on-React-Router before Astro measurement:
  - full existing unit, integration, and Playwright suites pass unchanged on the React Router target after the Zustand refactor.
  - representative `docs/app` and example app smoke tests pass with React Router + Zustand.
  - React Router + Zustand becomes the baseline for Phase B performance comparison.
- Phase B proves the per-page Astro entry approach before full migration:
  - selected `docs/app` routes no longer load a React Router manifest or unrelated cross-page route chunks in the Astro target.
  - mobile Lighthouse performance improves by at least 25 points on the selected worst `docs/app` route, or the `islands`-mode fail path below becomes the next milestone.
  - if the selected route matches the current report shape, mobile Lighthouse performance improves from about 47 to at least 75 in the `app`-mode prototype.
  - FCP and LCP both improve by at least 30% from each selected route's React Router baseline, or the `islands`-mode fail path below becomes the next milestone.
  - if the prototype misses the improvement gate, the next milestone switches one representative route from `app` to `islands` mode and re-measures before broad implementation continues.
- Final render-mode targets:
  - `render_mode="static"` pages ship 0 KiB first-party Reflex runtime JS by default and pass Playwright with JavaScript disabled.
  - `render_mode="app"` pages (default) hydrate the whole page as one React root and keep current Reflex state/event behavior without a React Router manifest/router chunk. Zero-migration default for existing Reflex apps.
  - `render_mode="islands"` pages hydrate only component-marked or signal-detected subtrees and do not open a websocket unless lifecycle/state/event behavior requires it. The rest of the page ships as HTML.
  - After moving mostly-static routes (marketing homepage, docs landing, etc.) from `app` to `islands`, representative `docs/app` content/library routes reach at least 90 mobile Lighthouse performance unless documented route-specific constraints explain the miss.
- Regression guards:
  - `examples/landing_page` mobile Lighthouse performance stays at 94+.
  - per-page JS/CSS bundle budgets are enforced in CI for `static`, `app`, and `islands` pages.
  - visual regression checks pass for selected `docs/app` routes in light and dark mode.
- Platform behavior:
  - Astro output is static-only, with first-class client islands and no SSR adapter, no on-demand pages, and no server islands.
  - Export/deploy workflows produce usable frontend/backend artifacts for ASGI, Reflex Cloud, and documented static hosts.
  - Existing component packages are either compatible, explicitly classified, or rejected with actionable compiler errors.

## References

- Astro Islands: https://docs.astro.build/en/concepts/islands/
- Astro client directives: https://docs.astro.build/en/reference/directives-reference/
- Astro React integration: https://docs.astro.build/en/guides/integrations-guide/react/
- Astro routing: https://docs.astro.build/en/guides/routing/
