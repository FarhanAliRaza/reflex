import { browser } from "$app/environment";
import Cookies from "universal-cookie";
import JSON5 from "json5";
import io from "socket.io-client";

import env from "$lib/reflex/generated/env.js";
import reflexEnvironment from "$lib/reflex/generated/reflex.js";
import debounce from "$lib/reflex/utils/helpers/debounce";
import throttle from "$lib/reflex/utils/helpers/throttle";
import { uploadFiles } from "$lib/reflex/utils/helpers/upload";

const SAME_DOMAIN_HOSTNAMES = ["localhost", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"];
const TOKEN_KEY = "token";
const cookies = new Cookies();

export const REFLEX_RUNTIME = Symbol("reflex-runtime");

export function ReflexEvent(
  name,
  payload = {},
  event_actions = {},
  handler = null,
) {
  const event = { name };
  if (payload && Object.keys(payload).length > 0) {
    event.payload = payload;
  }
  if (event_actions && Object.keys(event_actions).length > 0) {
    event.event_actions = event_actions;
  }
  if (handler !== null) {
    event.handler = handler;
  }
  return event;
}

export function applyEventActions(
  target,
  event_actions = {},
  args = [],
  action_key = null,
  temporal_handler = null,
) {
  if (!(args instanceof Array)) {
    args = [args];
  }

  const event = args.find((item) => item?.preventDefault !== undefined);

  if (event_actions?.preventDefault && event?.preventDefault) {
    event.preventDefault();
  }
  if (event_actions?.stopPropagation && event?.stopPropagation) {
    event.stopPropagation();
  }
  if (event_actions?.temporal && temporal_handler && !temporal_handler()) {
    return;
  }

  const invokeTarget = () => target(...args);
  const resolvedActionKey = action_key ?? target.toString();

  if (event_actions?.throttle) {
    if (!throttle(resolvedActionKey, event_actions.throttle)) {
      return;
    }
  }
  if (event_actions?.debounce) {
    debounce(resolvedActionKey, invokeTarget, event_actions.debounce);
    return;
  }
  return invokeTarget();
}

export class ReflexRuntime {
  state = $state({});
  connectErrors = $state([]);
  colorMode = $state("system");
  resolvedColorMode = $state("light");
  filesById = $state({});
  refs = {};

  constructor({
    initialState = {},
    clientStorage = {},
    stateName = undefined,
    exceptionStateName = undefined,
    defaultColorMode = "system",
  } = {}) {
    this.state = structuredClone(initialState);
    this.clientStorage = clientStorage;
    this.stateName = stateName;
    this.exceptionStateName = exceptionStateName;
    this.defaultColorMode = defaultColorMode;
    this.colorMode = defaultColorMode;
    this.resolvedColorMode = this._resolveColorMode(defaultColorMode);
    this.stateAliases = Object.fromEntries(
      Object.keys(this.state).map((fullName) => [
        fullName.replaceAll(".", "__"),
        fullName,
      ]),
    );
    this.eventQueue = [];
    this.socket = null;
    this.token = null;
    this.mounted = false;
  }

  createRef(name) {
    if (!(name in this.refs)) {
      this.refs[name] = { current: null };
    }
    return this.refs[name];
  }

  resolveRef(refOrName) {
    if (typeof refOrName === "string") {
      return this.refs[refOrName] ?? refOrName;
    }
    return refOrName;
  }

  getState(fullName) {
    if (!(fullName in this.state)) {
      this.state[fullName] = {};
    }
    return this.state[fullName];
  }

  getStateByAlias(alias) {
    return this.getState(this.stateAliases[alias] ?? alias);
  }

  setFilesById(update) {
    this.filesById =
      typeof update === "function" ? update(this.filesById) : update;
  }

  _resolveColorMode(mode) {
    if (!browser) {
      return mode === "dark" ? "dark" : "light";
    }
    if (mode === "system") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }
    return mode;
  }

  _applyColorMode(mode) {
    this.colorMode = mode;
    this.resolvedColorMode = this._resolveColorMode(mode);
    if (!browser) {
      return;
    }
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(this.resolvedColorMode);
    root.style.colorScheme = this.resolvedColorMode;
    root.dataset.colorMode = this.colorMode;
    root.dataset.resolvedColorMode = this.resolvedColorMode;
  }

  setColorMode(mode) {
    this._applyColorMode(mode);
  }

  toggleColorMode() {
    this.setColorMode(this.resolvedColorMode === "dark" ? "light" : "dark");
  }

  _generateUUID() {
    let d = new Date().getTime();
    let d2 = (performance && performance.now && performance.now() * 1000) || 0;
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
      let value = Math.random() * 16;
      if (d > 0) {
        value = ((d + value) % 16) | 0;
        d = Math.floor(d / 16);
      } else {
        value = ((d2 + value) % 16) | 0;
        d2 = Math.floor(d2 / 16);
      }
      return (char === "x" ? value : (value & 0x7) | 0x8).toString(16);
    });
  }

  _getToken() {
    if (this.token) {
      return this.token;
    }
    if (browser) {
      if (!window.sessionStorage.getItem(TOKEN_KEY)) {
        window.sessionStorage.setItem(TOKEN_KEY, this._generateUUID());
      }
      this.token = window.sessionStorage.getItem(TOKEN_KEY);
    }
    return this.token;
  }

  _getBackendURL(urlString = env.PING) {
    const endpoint = new URL(urlString);
    if (browser && SAME_DOMAIN_HOSTNAMES.includes(endpoint.hostname)) {
      endpoint.hostname = window.location.hostname;
      if (window.location.protocol === "https:") {
        if (endpoint.protocol === "ws:") {
          endpoint.protocol = "wss:";
        } else if (endpoint.protocol === "http:") {
          endpoint.protocol = "https:";
        }
        endpoint.port = "";
      }
    }
    return endpoint;
  }

  _hydrateClientStorage() {
    const clientStorageValues = {};
    if (this.clientStorage.cookies) {
      for (const stateKey in this.clientStorage.cookies) {
        const cookieOptions = this.clientStorage.cookies[stateKey];
        const cookieName = cookieOptions.name || stateKey;
        const cookieValue = cookies.get(cookieName, { doNotParse: true });
        if (cookieValue !== undefined) {
          clientStorageValues[stateKey] = cookieValue;
        }
      }
    }
    if (this.clientStorage.local_storage && browser) {
      for (const stateKey in this.clientStorage.local_storage) {
        const options = this.clientStorage.local_storage[stateKey];
        const localStorageValue = localStorage.getItem(options.name || stateKey);
        if (localStorageValue !== null) {
          clientStorageValues[stateKey] = localStorageValue;
        }
      }
    }
    if (this.clientStorage.session_storage && browser) {
      for (const stateKey in this.clientStorage.session_storage) {
        const options = this.clientStorage.session_storage[stateKey];
        const sessionValue = sessionStorage.getItem(options.name || stateKey);
        if (sessionValue !== null) {
          clientStorageValues[stateKey] = sessionValue;
        }
      }
    }
    return clientStorageValues;
  }

  _applyClientStorageDelta(delta) {
    for (const substate in delta) {
      for (const key in delta[substate]) {
        const stateKey = `${substate}.${key}`;
        if (this.clientStorage.cookies && stateKey in this.clientStorage.cookies) {
          const cookieOptions = { ...this.clientStorage.cookies[stateKey] };
          const cookieName = cookieOptions.name || stateKey;
          delete cookieOptions.name;
          cookies.set(cookieName, delta[substate][key], cookieOptions);
          continue;
        }
        if (this.clientStorage.local_storage && stateKey in this.clientStorage.local_storage && browser) {
          const options = this.clientStorage.local_storage[stateKey];
          localStorage.setItem(options.name || stateKey, delta[substate][key]);
          continue;
        }
        if (this.clientStorage.session_storage && stateKey in this.clientStorage.session_storage && browser) {
          const options = this.clientStorage.session_storage[stateKey];
          sessionStorage.setItem(options.name || stateKey, delta[substate][key]);
        }
      }
    }
  }

  _initialEvents() {
    if (!this.stateName) {
      return [];
    }

    const internalEvents = [];
    const clientStorageVars = this._hydrateClientStorage();
    if (clientStorageVars && Object.keys(clientStorageVars).length !== 0) {
      internalEvents.push(
        ReflexEvent(`${this.stateName}.reflex___state____update_vars_internal_state.update_vars_internal`, {
          vars: clientStorageVars,
        }),
      );
    }
    internalEvents.push(
      ReflexEvent(
        `${this.stateName}.reflex___state____on_load_internal_state.on_load_internal`,
      ),
    );
    return [ReflexEvent(`${this.stateName}.hydrate`), ...internalEvents];
  }

  _isBackendDisabled() {
    if (!browser) {
      return false;
    }
    const cookie = document.cookie
      .split("; ")
      .find((row) => row.startsWith("backend-enabled="));
    return cookie !== undefined && cookie.split("=")[1] === "false";
  }

  _isStatefulEvent(event) {
    return event?.name?.startsWith("reflex___state");
  }

  _mergeDelta(delta) {
    for (const substate in delta) {
      if (!(substate in this.state)) {
        this.state[substate] = {};
      }
      Object.assign(this.state[substate], delta[substate]);
    }
    this._applyClientStorageDelta(delta);
  }

  async _applyRestEvent(event) {
    if (event.handler === "uploadFiles") {
      await uploadFiles(
        event.name,
        event.payload.files,
        event.payload.upload_id,
        event.payload.on_upload_progress,
        event.payload.extra_headers,
        this.socket,
        {},
        (url) => this._getBackendURL(url),
        () => this._getToken(),
      );
    }
  }

  async _applyFrontendEvent(event) {
    if (!browser) {
      return;
    }

    if (event.name === "_redirect" && event.payload?.path) {
      if (event.payload.external) {
        window.open(
          event.payload.path,
          "_blank",
          "noopener" + (event.payload.popup ? ",popup" : ""),
        );
        return;
      }
      if (event.payload.replace) {
        window.location.replace(event.payload.path);
      } else {
        window.location.assign(event.payload.path);
      }
      return;
    }

    if (event.name === "_remove_cookie") {
      cookies.remove(event.payload.key, { ...event.payload.options });
      this.queueEvents(this._initialEvents(), true);
      return;
    }

    if (event.name === "_clear_local_storage") {
      localStorage.clear();
      this.queueEvents(this._initialEvents(), true);
      return;
    }

    if (event.name === "_remove_local_storage") {
      localStorage.removeItem(event.payload.key);
      this.queueEvents(this._initialEvents(), true);
      return;
    }

    if (event.name === "_clear_session_storage") {
      sessionStorage.clear();
      this.queueEvents(this._initialEvents(), true);
      return;
    }

    if (event.name === "_remove_session_storage") {
      sessionStorage.removeItem(event.payload.key);
      this.queueEvents(this._initialEvents(), true);
      return;
    }

    if (event.name === "_set_focus") {
      const ref = this.resolveRef(event.payload.ref);
      ref?.current?.focus?.();
      return;
    }

    if (event.name === "_blur_focus") {
      const ref = this.resolveRef(event.payload.ref);
      ref?.current?.blur?.();
      return;
    }

    if (event.name === "_set_value") {
      const ref = this.resolveRef(event.payload.ref);
      if (ref?.current) {
        ref.current.value = event.payload.value;
      }
      return;
    }

    if (event.name === "_call_script") {
      // eslint-disable-next-line no-eval
      eval(event.payload.javascript_code);
      return;
    }

    if (event.name === "_call_function") {
      if (typeof event.payload.function === "function") {
        await event.payload.function();
        return;
      }
      // eslint-disable-next-line no-eval
      await eval(event.payload.function)();
      return;
    }

    if (!event.router_data) {
      event.router_data = {
        pathname: window.location.pathname,
        asPath:
          window.location.pathname +
          window.location.search +
          window.location.hash,
        query: Object.fromEntries(new URLSearchParams(window.location.search)),
      };
    }

    if (this.socket?.connected) {
      this.socket.emit("event", event);
    }
  }

  async processEvent() {
    if (this.processing || this.eventQueue.length === 0) {
      return;
    }
    this.processing = true;
    try {
      while (this.eventQueue.length > 0) {
        const event = this.eventQueue.shift();
        if (this._isStatefulEvent(event) && !this.socket?.connected) {
          this.processing = false;
          await this.ensureSocketConnected();
          this.processing = true;
          if (!this.socket?.connected) {
            break;
          }
        }
        if (event.handler) {
          await this._applyRestEvent(event);
        } else {
          await this._applyFrontendEvent(event);
        }
      }
    } finally {
      this.processing = false;
    }
  }

  queueEvents(events, prepend = false) {
    const validEvents = (events || []).filter((event) => event !== undefined && event !== null);
    if (prepend) {
      this.eventQueue = [...validEvents, ...this.eventQueue];
    } else {
      this.eventQueue.push(...validEvents);
    }
    return this.processEvent();
  }

  addEvents(events, args = [], eventActions = {}) {
    const filteredEvents = (events || []).filter((event) => event !== undefined && event !== null);
    const mergedEventActions = filteredEvents.reduce(
      (accumulator, event) => ({ ...accumulator, ...event.event_actions }),
      eventActions ?? {},
    );

    return applyEventActions(
      () => this.queueEvents(filteredEvents, false),
      mergedEventActions,
      args,
      filteredEvents.map((event) => event.name).join("+++"),
      () => !!this.socket?.connected,
    );
  }

  async ensureSocketConnected() {
    if (!browser || this._isBackendDisabled()) {
      return;
    }
    if (this.socket?.connected) {
      return;
    }
    if (Object.keys(this.state).length <= 1 && !this.stateName) {
      return;
    }

    const endpoint = this._getBackendURL(env.EVENT);
    this.socket = io(endpoint.href, {
      path: endpoint.pathname,
      transports: [env.TRANSPORT],
      protocols: [reflexEnvironment.version],
      autoUnref: false,
      query: { token: this._getToken() },
      reconnection: true,
    });
    this.socket.io.encoder.replacer = (key, value) =>
      value === undefined ? null : value;
    this.socket.io.decoder.tryParse = (value) => {
      try {
        return JSON5.parse(value);
      } catch {
        return false;
      }
    };

    this.socket.on("connect", async () => {
      this.connectErrors = [];
      this.queueEvents(this._initialEvents(), true);
    });

    this.socket.on("connect_error", (error) => {
      this.connectErrors = [...this.connectErrors.slice(-9), error];
    });

    this.socket.on("event", (update) => {
      if (update.delta && Object.keys(update.delta).length > 0) {
        this._mergeDelta(update.delta);
      }
      if (update.events && update.events.length > 0) {
        this.queueEvents(update.events, false);
      }
    });

    this.socket.on("new_token", (newToken) => {
      this.token = newToken;
      if (browser) {
        window.sessionStorage.setItem(TOKEN_KEY, newToken);
      }
    });
  }

  mount() {
    if (this.mounted) {
      return;
    }
    this.mounted = true;
    this._applyColorMode(this.defaultColorMode);
    this.queueEvents(this._initialEvents(), true);
    void this.ensureSocketConnected();
  }
}
