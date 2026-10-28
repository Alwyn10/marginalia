const KEY = "marginalia_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let payload;
  if (form) payload = form;
  else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`/api${path}`, { method, headers, body: payload });

  if (res.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("signout"));
  }
  if (!res.ok) {
    let message = "Something went wrong. Try again.";
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg || message;
    } catch {
      /* keep default message */
    }
    throw new Error(message);
  }
  return res.status === 204 ? null : res.json();
}
