const SPACE_SCALE = {
  "1": "var(--space-1)",
  "2": "var(--space-2)",
  "3": "var(--space-3)",
  "4": "var(--space-4)",
  "5": "var(--space-5)",
  "6": "var(--space-6)",
  "7": "var(--space-7)",
  "8": "var(--space-8)",
  "9": "var(--space-9)",
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
  "1": "calc(var(--font-size-1) * var(--heading-font-size-adjust))",
  "2": "calc(var(--font-size-2) * var(--heading-font-size-adjust))",
  "3": "calc(var(--font-size-3) * var(--heading-font-size-adjust))",
  "4": "calc(var(--font-size-4) * var(--heading-font-size-adjust))",
  "5": "calc(var(--font-size-5) * var(--heading-font-size-adjust))",
  "6": "calc(var(--font-size-6) * var(--heading-font-size-adjust))",
  "7": "calc(var(--font-size-7) * var(--heading-font-size-adjust))",
  "8": "calc(var(--font-size-8) * var(--heading-font-size-adjust))",
  "9": "calc(var(--font-size-9) * var(--heading-font-size-adjust))",
};

const TEXT_SCALE = {
  "1": "var(--font-size-1)",
  "2": "var(--font-size-2)",
  "3": "var(--font-size-3)",
  "4": "var(--font-size-4)",
  "5": "var(--font-size-5)",
  "6": "var(--font-size-6)",
  "7": "var(--font-size-7)",
  "8": "var(--font-size-8)",
  "9": "var(--font-size-9)",
};

const TEXT_LINE_HEIGHT_SCALE = {
  "1": "var(--line-height-1)",
  "2": "var(--line-height-2)",
  "3": "var(--line-height-3)",
  "4": "var(--line-height-4)",
  "5": "var(--line-height-5)",
  "6": "var(--line-height-6)",
  "7": "var(--line-height-7)",
  "8": "var(--line-height-8)",
  "9": "var(--line-height-9)",
};

const TEXT_LETTER_SPACING_SCALE = {
  "1": "var(--letter-spacing-1)",
  "2": "var(--letter-spacing-2)",
  "3": "var(--letter-spacing-3)",
  "4": "var(--letter-spacing-4)",
  "5": "var(--letter-spacing-5)",
  "6": "var(--letter-spacing-6)",
  "7": "var(--letter-spacing-7)",
  "8": "var(--letter-spacing-8)",
  "9": "var(--letter-spacing-9)",
};

const HEADING_LINE_HEIGHT_SCALE = {
  "1": "var(--heading-line-height-1)",
  "2": "var(--heading-line-height-2)",
  "3": "var(--heading-line-height-3)",
  "4": "var(--heading-line-height-4)",
  "5": "var(--heading-line-height-5)",
  "6": "var(--heading-line-height-6)",
  "7": "var(--heading-line-height-7)",
  "8": "var(--heading-line-height-8)",
  "9": "var(--heading-line-height-9)",
};

const HEADING_LETTER_SPACING_SCALE = {
  "1": "calc(var(--letter-spacing-1) + var(--heading-letter-spacing))",
  "2": "calc(var(--letter-spacing-2) + var(--heading-letter-spacing))",
  "3": "calc(var(--letter-spacing-3) + var(--heading-letter-spacing))",
  "4": "calc(var(--letter-spacing-4) + var(--heading-letter-spacing))",
  "5": "calc(var(--letter-spacing-5) + var(--heading-letter-spacing))",
  "6": "calc(var(--letter-spacing-6) + var(--heading-letter-spacing))",
  "7": "calc(var(--letter-spacing-7) + var(--heading-letter-spacing))",
  "8": "calc(var(--letter-spacing-8) + var(--heading-letter-spacing))",
  "9": "calc(var(--letter-spacing-9) + var(--heading-letter-spacing))",
};

const CONTAINER_WIDTH = {
  "1": "var(--container-1)",
  "2": "var(--container-2)",
  "3": "var(--container-3)",
  "4": "var(--container-4)",
};

const BREAKPOINTS = {
  xs: "30em",
  sm: "48em",
  md: "62em",
  lg: "80em",
  xl: "96em",
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
  if (value === undefined || value === null || value === "") {
    return HEADING_SCALE["6"];
  }
  return HEADING_SCALE[String(value)] ?? String(value);
}

export function headingLineHeight(value) {
  if (value === undefined || value === null || value === "") {
    return HEADING_LINE_HEIGHT_SCALE["6"];
  }
  return HEADING_LINE_HEIGHT_SCALE[String(value)] ?? String(value);
}

export function headingLetterSpacing(value) {
  if (value === undefined || value === null || value === "") {
    return HEADING_LETTER_SPACING_SCALE["6"];
  }
  return HEADING_LETTER_SPACING_SCALE[String(value)] ?? String(value);
}

export function textSize(value) {
  if (value === undefined || value === null || value === "") {
    return TEXT_SCALE["4"];
  }
  return TEXT_SCALE[String(value)] ?? String(value);
}

export function textLineHeight(value) {
  if (value === undefined || value === null || value === "") {
    return "var(--default-line-height)";
  }
  return TEXT_LINE_HEIGHT_SCALE[String(value)] ?? String(value);
}

export function textLetterSpacing(value) {
  if (value === undefined || value === null || value === "") {
    return "inherit";
  }
  return TEXT_LETTER_SPACING_SCALE[String(value)] ?? String(value);
}

export function containerWidth(value) {
  if (value === undefined || value === null || value === "") {
    return CONTAINER_WIDTH["3"];
  }
  return CONTAINER_WIDTH[String(value)] ?? String(value);
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
    xs: [],
    sm: [],
    md: [],
    lg: [],
    xl: [],
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
