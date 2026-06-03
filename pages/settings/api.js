export function createApi(bridge) {
  const apiGet = bridge?.apiGet?.bind(bridge);
  const apiPost = bridge?.apiPost?.bind(bridge);

  if (!apiGet || !apiPost) {
    throw new Error("Bridge API is unavailable");
  }

  function unwrap(response) {
    if (
      response &&
      typeof response === "object" &&
      Object.prototype.hasOwnProperty.call(response, "ok")
    ) {
      if (!response.ok) {
        throw new Error(response.error || response.message || "Request failed");
      }
      return Object.prototype.hasOwnProperty.call(response, "data")
        ? response.data
        : response;
    }
    return response;
  }

  async function safeGet(endpoint, params) {
    return unwrap(await apiGet(endpoint, params));
  }

  async function safePost(endpoint, body) {
    return unwrap(await apiPost(endpoint, body));
  }

  return { safeGet, safePost };
}
