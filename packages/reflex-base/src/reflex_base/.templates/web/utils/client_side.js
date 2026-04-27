/**
 * SSR-safe lazy loader for components that should only render on the
 * client (e.g. `react-fast-marquee`, sonner's `Toaster`). Lives in its
 * own module so islands that only need this helper don't transitively
 * pull ``state.js`` (socket.io transport) through ``context.js``'s
 * ``StateProvider`` / ``EventLoopProvider`` exports.
 */

import { useState, useEffect } from "react";
import { jsx } from "@emotion/react";

export function ClientSide(component) {
  return ({ children, ...props }) => {
    const [Component, setComponent] = useState(null);
    useEffect(() => {
      async function load() {
        const comp = await component();
        setComponent(() => comp);
      }
      load();
    }, []);
    return Component ? jsx(Component, props, children) : null;
  };
}
