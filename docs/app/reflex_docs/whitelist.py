"""A list of whitelist paths that should be built.
If the list is empty, all pages will be built.

Tips:
- Ensure that the path starts with a forward slash '/'.
- Do not include a trailing slash '/' at the end of the path.

Examples:
- Correct: WHITELISTED_PAGES = ["/getting-started/introduction"]
- Incorrect: WHITELISTED_PAGES = ["/getting-started/introduction/"]
"""

WHITELISTED_PAGES = [
    # TEMP (local Lighthouse measurement only, do not commit): build everything
    # except /wrapping-react/local-packages, whose live demo pulls
    # @masenf/hello-react from GitHub, which is blocked in this sandbox.
    "/advanced_onboarding",
    "/ai-builder",
    "/ai_builder",
    "/api-reference",
    "/api-routes",
    "/authentication",
    "/client_storage",
    "/components",
    "/custom-components",
    "/database",
    "/enterprise",
    "/events",
    "/getting-started",
    "/getting_started",
    "/hosting",
    "/library",
    "/pages",
    "/recipes",
    "/state",
    "/state_structure",
    "/styling",
    "/ui",
    "/utility_methods",
    "/vars",
    "/wrapping-react/custom-code-and-hooks",
    "/wrapping-react/example",
    "/wrapping-react/imports-and-styles",
    "/wrapping-react/library-and-tags",
    "/wrapping-react/more-wrapping-examples",
    "/wrapping-react/overview",
    "/wrapping-react/props",
    "/wrapping-react/serializers",
    "/wrapping-react/step-by-step",
]


def _check_whitelisted_path(path: str):
    if len(WHITELISTED_PAGES) == 0:
        return True

    # If the path is the root, always build it.
    if path == "/":
        return True

    if len(WHITELISTED_PAGES) == 1 and WHITELISTED_PAGES[0] == "/":
        return False

    for whitelisted_path in WHITELISTED_PAGES:
        if path.startswith(whitelisted_path):
            return True

    return False
