"""Behavior test of the generated store.js runtime."""
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from reflex_base.compiler.zustand_template import zustand_store_template


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_store_in_node(actions: list[str]) -> dict:
    """Execute store.js in a node sandbox with mocked DOM/storage and return final state.

    ``actions`` is a list of JS expressions to execute *after* the store is
    created. Each is awaited (so async handlers settle). The final mocked
    DOM/cookie/storage state plus the slice values are emitted as JSON on
    stdout.
    """
    store_src = zustand_store_template()
    # Inline a minimal zustand-compatible `create` so node doesn't need the real package.
    minimal_zustand = textwrap.dedent("""
    function create(setupOrFactory) {
      const setup = setupOrFactory;
      let state;
      const listeners = new Set();
      const setState = (partialOrFn) => {
        const partial = typeof partialOrFn === "function" ? partialOrFn(state) : partialOrFn;
        const next = (typeof partial !== "object" || partial === null) ? partial : Object.assign({}, state, partial);
        if (!Object.is(next, state)) {
          const prev = state;
          state = next;
          listeners.forEach(l => l(state, prev));
        }
      };
      const getState = () => state;
      const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
      const api = { setState, getState, subscribe };
      state = setup(setState, getState, api);
      const useStore = (selector) => selector ? selector(state) : state;
      Object.assign(useStore, api);
      return useStore;
    }
    """)
    # Replace the import line with our minimal create
    src = store_src.replace('import { create } from "zustand";', minimal_zustand)
    src = src.replace("export const ", "globalThis.")
    src = src.replace("export { applyReflexDelta, useReflexStore };", "")
    src = src.replace("export ", "")  # any remaining

    actions_js = "\n".join(actions)
    harness = textwrap.dedent(f"""
    let _classList = [];
    let _cookieJar = '';
    let _storage = {{}};
    let _dataAttrs = {{}};
    globalThis.window = {{
      matchMedia: () => ({{ matches: false, addEventListener: () => {{}} }}),
      localStorage: {{
        getItem: (k) => _storage[k] ?? null,
        setItem: (k, v) => {{ _storage[k] = String(v); }},
      }},
    }};
    globalThis.document = {{
      documentElement: {{
        classList: {{
          remove: (...a) => {{ a.forEach(c => {{ _classList = _classList.filter(x => x !== c); }}); }},
          add: (...a) => {{ a.forEach(c => {{ if (!_classList.includes(c)) _classList.push(c); }}); }},
        }},
        setAttribute: (k, v) => {{ _dataAttrs[k] = v; }},
        style: {{}},
      }},
    }};
    Object.defineProperty(globalThis.document, 'cookie', {{
      get() {{ return _cookieJar; }},
      set(v) {{ _cookieJar = v; }},
    }});
    {src}
    (async () => {{
      {actions_js}
      // Allow async handlers to settle.
      await new Promise(r => setTimeout(r, 50));
      const slice = useReflexStore.getState().colorMode;
      console.log(JSON.stringify({{
        rawColorMode: slice.rawColorMode,
        colorMode: slice.colorMode,
        resolvedColorMode: slice.resolvedColorMode,
        htmlClasses: _classList,
        cookie: _cookieJar,
        storage: _storage,
        dataAttrs: _dataAttrs,
      }}));
    }})();
    """)
    result = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node failed: {result.stderr}\n--- stdout ---\n{result.stdout}")
    # The node script may print other things — find the JSON line.
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"no JSON output: {result.stdout}")


@pytest.mark.skipif(not _node_available(), reason="node not on PATH")
def test_set_color_mode_dark_updates_dom_and_persistence():
    state = _run_store_in_node([
        'useReflexStore.getState().colorMode.setColorMode("dark");',
    ])
    assert state["rawColorMode"] == "dark"
    assert state["resolvedColorMode"] == "dark"
    assert state["htmlClasses"] == ["dark"]
    assert "reflex-color-mode=dark" in state["cookie"]
    assert state["storage"]["color_mode"] == "dark"


@pytest.mark.skipif(not _node_available(), reason="node not on PATH")
def test_toggle_color_mode_flips_resolved():
    """Starting from system mode (resolved=light here, since matchMedia=false), toggle should flip to dark, then to light."""
    state = _run_store_in_node([
        'useReflexStore.getState().colorMode.toggleColorMode();',
    ])
    assert state["resolvedColorMode"] == "dark"
    assert state["htmlClasses"] == ["dark"]


@pytest.mark.skipif(not _node_available(), reason="node not on PATH")
def test_event_loop_runs_call_function_locally():
    """addEvents([_call_function event]) executes the function without a backend adapter."""
    state = _run_store_in_node([
        'const cm = useReflexStore.getState().colorMode;',
        'useReflexStore.getState().eventLoop.addEvents([',
        '  { name: "_call_function", payload: { function: () => cm.setColorMode("dark"), callback: null } }',
        '], [{}], {});',
    ])
    assert state["rawColorMode"] == "dark"
    assert state["htmlClasses"] == ["dark"]
    assert "reflex-color-mode=dark" in state["cookie"]


@pytest.mark.skipif(not _node_available(), reason="node not on PATH")
def test_event_loop_runs_call_script_locally():
    state = _run_store_in_node([
        'useReflexStore.getState().eventLoop.addEvents([',
        '  { name: "_call_script", payload: { javascript_code: "useReflexStore.getState().colorMode.setColorMode(\\"light\\")", callback: null } }',
        '], [{}], {});',
    ])
    assert state["rawColorMode"] == "light"
    assert state["htmlClasses"] == ["light"]


@pytest.mark.skipif(not _node_available(), reason="node not on PATH")
def test_set_color_mode_persistence_round_trip():
    """Once setColorMode runs, cookie + localStorage persist; a 'reload' (re-eval module) reads them back."""
    # First, set dark, capture state.
    state1 = _run_store_in_node([
        'useReflexStore.getState().colorMode.setColorMode("dark");',
    ])
    assert state1["storage"]["color_mode"] == "dark"
    # Simulate a fresh module load with the cookie pre-set: we re-run the harness with a pre-seeded cookie.
    # This is an internal probe — verify the read path actually picks up the persisted value.
    # Done by setting _cookieJar before module init.
    seeded = subprocess.run(
        ["node", "--input-type=module", "-e", _seeded_harness("dark")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert seeded.returncode == 0, seeded.stderr
    out = json.loads(seeded.stdout.strip().splitlines()[-1])
    assert out["rawColorMode"] == "dark"
    assert out["resolvedColorMode"] == "dark"


def _seeded_harness(persisted_mode: str) -> str:
    """Run the store with a pre-set cookie to verify the read path."""
    store_src = zustand_store_template()
    # Same minimal zustand
    minimal_zustand = textwrap.dedent("""
    function create(setupOrFactory) {
      const setup = setupOrFactory;
      let state;
      const listeners = new Set();
      const setState = (partialOrFn) => {
        const partial = typeof partialOrFn === "function" ? partialOrFn(state) : partialOrFn;
        const next = (typeof partial !== "object" || partial === null) ? partial : Object.assign({}, state, partial);
        if (!Object.is(next, state)) { state = next; listeners.forEach(l => l(state)); }
      };
      const getState = () => state;
      const subscribe = (l) => { listeners.add(l); return () => listeners.delete(l); };
      const api = { setState, getState, subscribe };
      state = setup(setState, getState, api);
      const useStore = (selector) => selector ? selector(state) : state;
      Object.assign(useStore, api);
      return useStore;
    }
    """)
    src = store_src.replace('import { create } from "zustand";', minimal_zustand)
    src = src.replace("export const ", "globalThis.")
    src = src.replace("export { applyReflexDelta, useReflexStore };", "")
    src = src.replace("export ", "")
    return textwrap.dedent(f"""
    let _classList = [];
    let _cookieJar = 'reflex-color-mode={persisted_mode}';
    let _storage = {{ color_mode: '{persisted_mode}' }};
    globalThis.window = {{
      matchMedia: () => ({{ matches: false, addEventListener: () => {{}} }}),
      localStorage: {{
        getItem: (k) => _storage[k] ?? null,
        setItem: (k, v) => {{ _storage[k] = String(v); }},
      }},
    }};
    globalThis.document = {{
      documentElement: {{
        classList: {{ remove: () => {{}}, add: () => {{}} }},
        setAttribute: () => {{}},
        style: {{}},
      }},
    }};
    Object.defineProperty(globalThis.document, 'cookie', {{
      get() {{ return _cookieJar; }},
      set(v) {{ _cookieJar = v; }},
    }});
    {src}
    const slice = useReflexStore.getState().colorMode;
    console.log(JSON.stringify({{ rawColorMode: slice.rawColorMode, resolvedColorMode: slice.resolvedColorMode }}));
    """)
