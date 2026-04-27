/**
 * Side-effect-free utilities used by every generated component module.
 *
 * Importing the heavier ``state.js`` runtime drags ``socket.io-client``
 * along (top-level packet-type initialization), so a static styled
 * component that only needs ``isTrue`` would otherwise pull the entire
 * Reflex backend transport into the page bundle. Keeping these pure
 * helpers in their own module preserves Vite's tree-shaking — modules
 * that import only from here have no transitive socket.io dependency.
 */

// Dictionary holding component references. Mutable shared state, but no
// import-time side effects beyond the empty-object literal.
export const refs = {};

/**
 * Generate a UUID (used for session tokens).
 * Taken from https://stackoverflow.com/questions/105034/how-do-i-create-a-guid-uuid.
 * @returns A UUID.
 */
export const generateUUID = () => {
  let d = new Date().getTime(),
    d2 = (performance && performance.now && performance.now() * 1000) || 0;
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    let r = Math.random() * 16;
    if (d > 0) {
      r = ((d + r) % 16) | 0;
      d = Math.floor(d / 16);
    } else {
      r = ((d2 + r) % 16) | 0;
      d2 = Math.floor(d2 / 16);
    }
    return (c == "x" ? r : (r & 0x7) | 0x8).toString(16);
  });
};

/**
 * Check if a value is "truthy" by Reflex semantics (non-empty arrays /
 * objects also count as true).
 * @param val The value to check.
 * @returns True if the value is truthy, false otherwise.
 */
export const isTrue = (val) => {
  if (Array.isArray(val)) return val.length > 0;
  if (val === Object(val)) return Object.keys(val).length > 0;
  return Boolean(val);
};

/**
 * Check if a value is not null or undefined.
 * @param val The value to check.
 * @returns True if the value is not null or undefined, false otherwise.
 */
export const isNotNullOrUndefined = (val) => {
  return (val ?? undefined) !== undefined;
};

/**
 * Get the value from a ref.
 * @param ref The ref to get the value from.
 * @returns The value.
 */
export const getRefValue = (ref) => {
  if (!ref || !ref.current) {
    return;
  }
  if (ref.current.type == "checkbox") {
    return ref.current.checked; // chakra
  } else if (
    ref.current.className?.includes("rt-CheckboxRoot") ||
    ref.current.className?.includes("rt-SwitchRoot")
  ) {
    return ref.current.ariaChecked == "true"; // radix
  } else if (ref.current.className?.includes("rt-SliderRoot")) {
    // find the actual slider
    return ref.current.querySelector(".rt-SliderThumb")?.ariaValueNow;
  } else {
    //querySelector(":checked") is needed to get value from radio_group
    return (
      ref.current.value ||
      (ref.current.querySelector &&
        ref.current.querySelector(":checked") &&
        ref.current.querySelector(":checked")?.value)
    );
  }
};

/**
 * Get the values from a ref array.
 * @param refs The refs to get the values from.
 * @returns The values array.
 */
export const getRefValues = (refs) => {
  if (!refs) {
    return;
  }
  // getAttribute is used by RangeSlider because it doesn't assign value
  return refs.map((ref) =>
    ref.current
      ? ref.current.value || ref.current.getAttribute("aria-valuenow")
      : null,
  );
};

/**
 * Spread two arrays or two objects.
 * @param first The first array or object.
 * @param second The second array or object.
 * @returns The final merged array or object.
 */
export const spreadArraysOrObjects = (first, second) => {
  if (Array.isArray(first) && Array.isArray(second)) {
    return [...first, ...second];
  } else if (typeof first === "object" && typeof second === "object") {
    return { ...first, ...second };
  } else {
    throw new Error("Both parameters must be either arrays or objects.");
  }
};
