# debounce_native_input

Example app that verifies the fix in reflex-dev/reflex#6637:
`rx.debounce_input` wrapping **native DOM elements** (`rx.el.input`,
`rx.el.textarea`).

## The bug

Before the fix, wrapping a native element produced an unquoted JS identifier
in the generated `element` prop:

```jsx
jsx(DebounceInput,{element:input, ...})   // ReferenceError: input is not defined
```

because `DebounceInput.create()` used `_js_expr=str(child.alias or child.tag)`,
emitting the bare token `input` instead of the string `"input"`.

## The fix

`Component._get_tag_name()` quotes global-scope elements (those with
`_is_tag_in_global_scope=True` and no `library`), so the generated output is:

```jsx
jsx(DebounceInput,{element:"input", ...})      // native input  ✓
jsx(DebounceInput,{element:"textarea", ...})   // native textarea  ✓
jsx(DebounceInput,{element:RadixThemesTextField.Root, ...})  // library input (unchanged)  ✓
```

## How to verify

```bash
uv run reflex export --frontend-only --no-zip
grep -r "element:" .web/utils/components/Debounceinput_*.jsx
```

Native elements must render as quoted string literals; library components must
remain unquoted identifiers.
