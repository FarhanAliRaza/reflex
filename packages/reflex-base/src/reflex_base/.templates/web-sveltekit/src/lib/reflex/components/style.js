const SPACE_SCALE = {
  "1": "0.25rem",
  "2": "0.5rem",
  "3": "0.75rem",
  "4": "1rem",
  "5": "1.5rem",
  "6": "2rem",
  "7": "2.5rem",
  "8": "3rem",
  "9": "4rem",
};

const ALIGN_MAP = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  baseline: "baseline",
  stretch: "stretch",
};

const JUSTIFY_MAP = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  between: "space-between",
  around: "space-around",
  evenly: "space-evenly",
};

const HEADING_SCALE = {
  "1": "1rem",
  "2": "1.125rem",
  "3": "1.25rem",
  "4": "1.5rem",
  "5": "1.75rem",
  "6": "2.125rem",
  "7": "2.5rem",
  "8": "3rem",
  "9": "3.75rem",
};

const TEXT_SCALE = {
  "1": "0.75rem",
  "2": "0.875rem",
  "3": "0.95rem",
  "4": "1rem",
  "5": "1.125rem",
  "6": "1.25rem",
  "7": "1.5rem",
  "8": "1.75rem",
  "9": "2rem",
};

const CONTAINER_WIDTH = {
  "1": "42rem",
  "2": "56rem",
  "3": "72rem",
  "4": "84rem",
};

const BREAKPOINTS = {
  sm: "40rem",
  md: "48rem",
  lg: "64rem",
  xl: "80rem",
  "2xl": "96rem",
};

const RADIUS_SCALE = {
  none: "0px",
  small: "0.375rem",
  medium: "0.75rem",
  large: "1rem",
  full: "9999px",
};

const UNIT_LESS_PROPS = new Set([
  "fontWeight",
  "lineHeight",
  "opacity",
  "zIndex",
  "order",
  "flex",
  "flexGrow",
  "flexShrink",
  "gridColumn",
  "gridRow",
]);

const SPACING_PROPS = new Set([
  "gap",
  "rowGap",
  "columnGap",
  "padding",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "margin",
  "marginTop",
  "marginRight",
  "marginBottom",
  "marginLeft",
  "top",
  "right",
  "bottom",
  "left",
  "inset",
  "insetBlock",
  "insetBlockStart",
  "insetBlockEnd",
  "insetInline",
  "insetInlineStart",
  "insetInlineEnd",
]);

const SHORTHAND_MAP = {
  p: ["padding"],
  px: ["paddingLeft", "paddingRight"],
  py: ["paddingTop", "paddingBottom"],
  pt: ["paddingTop"],
  pr: ["paddingRight"],
  pb: ["paddingBottom"],
  pl: ["paddingLeft"],
  m: ["margin"],
  mx: ["marginLeft", "marginRight"],
  my: ["marginTop", "marginBottom"],
  mt: ["marginTop"],
  mr: ["marginRight"],
  mb: ["marginBottom"],
  ml: ["marginLeft"],
};

export function mergeClasses(...values) {
  return values.flat().filter(Boolean).join(" ");
}

export function mergeStyles(...values) {
  return values
    .flatMap((value) => {
      if (!value) {
        return [];
      }
      if (isPlainObject(value)) {
        const resolved = styleObjectToString(value);
        return resolved ? [resolved] : [];
      }
      return [String(value)];
    })
    .join("; ");
}

export function resolveSpacing(value) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }
  if (typeof value === "number") {
    return `${value}px`;
  }
  return SPACE_SCALE[String(value)] ?? String(value);
}

export function alignValue(value) {
  return ALIGN_MAP[value] ?? value;
}

export function justifyValue(value) {
  return JUSTIFY_MAP[value] ?? value;
}

export function headingSize(value) {
  return HEADING_SCALE[String(value)] ?? String(value ?? HEADING_SCALE["6"]);
}

export function textSize(value) {
  return TEXT_SCALE[String(value)] ?? String(value ?? TEXT_SCALE["4"]);
}

export function containerWidth(value) {
  return CONTAINER_WIDTH[String(value)] ?? "72rem";
}

export function radiusValue(value, fallback = "0.75rem") {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  return RADIUS_SCALE[String(value)] ?? String(value);
}

export function camelToKebab(value) {
  return value.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`);
}

function isPlainObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeScalarValue(prop, value) {
  if (value === undefined || value === null || value === false) {
    return undefined;
  }
  if (typeof value === "number") {
    if (UNIT_LESS_PROPS.has(prop)) {
      return String(value);
    }
    return `${value}px`;
  }
  if (typeof value === "string") {
    if (value === "") {
      return undefined;
    }
    if (
      (prop in SHORTHAND_MAP || SPACING_PROPS.has(prop)) &&
      /^-?\d+(\.\d+)?$/.test(value)
    ) {
      return resolveSpacing(value);
    }
    if (prop.toLowerCase().includes("radius")) {
      return radiusValue(value, value);
    }
    return value;
  }
  return String(value);
}

function expandProperty(prop, value) {
  const normalizedProps = SHORTHAND_MAP[prop] ?? [prop];
  return normalizedProps
    .map((key) => [key, normalizeScalarValue(key, value)])
    .filter(([, normalizedValue]) => normalizedValue !== undefined);
}

function appendDeclaration(target, prop, value) {
  for (const [expandedProp, expandedValue] of expandProperty(prop, value)) {
    target.push(`${camelToKebab(expandedProp)}: ${expandedValue};`);
  }
}

function createResponsiveBuckets() {
  return {
    base: [],
    sm: [],
    md: [],
    lg: [],
    xl: [],
    "2xl": [],
  };
}

function serializeCssObject(selector, css) {
  if (!isPlainObject(css)) {
    return "";
  }

  const declarations = createResponsiveBuckets();
  const nestedRules = [];

  for (const [prop, value] of Object.entries(css)) {
    if (value === undefined || value === null || value === false) {
      continue;
    }

    if (prop.startsWith("&") && isPlainObject(value)) {
      nestedRules.push(serializeCssObject(prop.replaceAll("&", selector), value));
      continue;
    }

    if (isPlainObject(value)) {
      let handledResponsiveValue = false;
      for (const [breakpoint, responsiveValue] of Object.entries(value)) {
        if (breakpoint === "base" || breakpoint in BREAKPOINTS) {
          appendDeclaration(
            declarations[breakpoint === "base" ? "base" : breakpoint],
            prop,
            responsiveValue,
          );
          handledResponsiveValue = true;
        }
      }
      if (handledResponsiveValue) {
        continue;
      }
    }

    appendDeclaration(declarations.base, prop, value);
  }

  const rules = [];
  if (declarations.base.length > 0) {
    rules.push(`${selector} { ${declarations.base.join(" ")} }`);
  }
  for (const [breakpoint, declarationList] of Object.entries(declarations)) {
    if (breakpoint === "base" || declarationList.length === 0) {
      continue;
    }
    rules.push(
      `@media (min-width: ${BREAKPOINTS[breakpoint]}) { ${selector} { ${declarationList.join(" ")} } }`,
    );
  }

  return [...rules, ...nestedRules.filter(Boolean)].join("\n");
}

function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (!isPlainObject(value)) {
    return JSON.stringify(value);
  }

  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(",")}}`;
}

function hashString(value) {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }
  return Math.abs(hash).toString(36);
}

export function buildCssArtifacts(
  css,
  className = "",
  selectorSuffix = "",
) {
  if (!isPlainObject(css)) {
    return {
      className: mergeClasses(className),
      cssText: "",
    };
  }

  const cacheKey = stableStringify(css);
  const generatedClass = `rxs-${hashString(`${selectorSuffix}|${cacheKey}`)}`;
  const selector = `.${generatedClass}${selectorSuffix}`;

  return {
    className: mergeClasses(className, generatedClass),
    cssText: serializeCssObject(selector, css),
  };
}

export function styleTagHtml(cssText) {
  if (!cssText) {
    return "";
  }

  return `<style>${cssText.replaceAll("</style>", "<\\/style>")}</style>`;
}

export function styleObjectToString(style) {
  if (!isPlainObject(style)) {
    return typeof style === "string" ? style : "";
  }

  return Object.entries(style)
    .filter(([, value]) => !isPlainObject(value))
    .flatMap(([key, value]) =>
      expandProperty(key, value).map(
        ([expandedProp, expandedValue]) =>
          `${camelToKebab(expandedProp)}: ${expandedValue}`,
      ),
    )
    .join("; ");
}
