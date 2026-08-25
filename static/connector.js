(() => {
  "use strict";

  const CONNECTOR_ORIGIN = "http://127.0.0.1:57231";
  const TOKEN_KEY = "viralx.connector.session.v1";
  const PAIRING_FRAGMENT = "viralx-connector";

  function sessionToken() {
    return window.sessionStorage.getItem(TOKEN_KEY) || "";
  }

  function clearSession() {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }

  function clearPairingFragment(params) {
    params.delete(PAIRING_FRAGMENT);
    const nextHash = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash ? `#${nextHash}` : ""}`,
    );
  }

  async function loopbackFetch(path, options = {}, timeout = 0) {
    const target = new URL(path, CONNECTOR_ORIGIN);
    if (target.origin !== CONNECTOR_ORIGIN) throw new Error("Connector 地址不受信任");

    const headers = new Headers(options.headers || {});
    const token = sessionToken();
    if (token) headers.set("X-ViralX-Connector-Token", token);

    const controller = timeout > 0 && !options.signal ? new AbortController() : null;
    const timer = controller ? window.setTimeout(() => controller.abort(), timeout) : 0;
    try {
      const request = new Request(target.href, {
        ...options,
        headers,
        mode: "cors",
        credentials: "omit",
        cache: options.cache || "no-store",
        signal: options.signal || controller?.signal,
        targetAddressSpace: "loopback",
      });
      return await window.fetch(request);
    } finally {
      if (timer) window.clearTimeout(timer);
    }
  }

  async function consumePairingFragment() {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const pairingSecret = params.get(PAIRING_FRAGMENT) || "";
    if (!pairingSecret) return { attempted: false };

    clearPairingFragment(params);
    clearSession();
    try {
      const response = await loopbackFetch("/connector/v1/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pairing_secret: pairingSecret }),
      }, 6000);
      const data = await response.json();
      if (!response.ok || !data.session_token) {
        throw new Error(data.message || `HTTP ${response.status}`);
      }
      window.sessionStorage.setItem(TOKEN_KEY, data.session_token);
      return { attempted: true, paired: true };
    } catch (error) {
      return { attempted: true, paired: false, error: error.message };
    }
  }

  const pairing = consumePairingFragment();

  async function ready() {
    return pairing;
  }

  async function probe({ force = false } = {}) {
    await pairing;
    const response = await loopbackFetch(
      `/connector/v1/status${force ? "?refresh=1" : ""}`,
      { method: "GET" },
      2500,
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
    if (!data.paired) clearSession();
    return data;
  }

  async function request(path, options = {}) {
    await pairing;
    if (!sessionToken()) throw new Error("本机 Connector 尚未完成安全配对");
    const response = await loopbackFetch(path, options);
    if (response.status === 401) clearSession();
    return response;
  }

  async function permissionState() {
    if (!navigator.permissions?.query) return "unknown";
    for (const name of ["loopback-network", "local-network-access"]) {
      try {
        const result = await navigator.permissions.query({ name });
        return result.state || "unknown";
      } catch (_) {
        // Try the compatibility permission name, then degrade to unknown.
      }
    }
    return "unknown";
  }

  window.ViralXConnector = {
    origin: CONNECTOR_ORIGIN,
    ready,
    probe,
    request,
    permissionState,
    clearSession,
    isPaired: () => Boolean(sessionToken()),
  };
})();
