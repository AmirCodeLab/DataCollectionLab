/** The one place the console talks to the API.
 *
 * Vite proxies /api and /health to the backend in development (vite.config.ts);
 * in a self-hosted deployment the SPA is served from the same origin, so the
 * relative paths hold either way.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** FastAPI's `detail` as sent — a string, or for `POST /forms/compile` and
     *  `POST /forms/versions` a list of violations. `message` flattens it;
     *  this keeps the shape for a view that renders one line per violation. */
    readonly detail: unknown = message,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type QueryValue = string | number | boolean | undefined | null;

export async function apiGet<T>(
  path: string,
  params: Record<string, QueryValue> = {},
): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // Absent means "no filter"; an empty string would filter for empty.
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const queryString = query.toString();
  const suffix = queryString === "" ? "" : `?${queryString}`;

  let response: Response;
  try {
    response = await fetch(`${path}${suffix}`, {
      headers: { Accept: "application/json" },
    });
  } catch (cause) {
    // fetch only rejects when the request never completed — the API is down,
    // or the dev proxy has nothing to talk to.
    throw new ApiError(0, `API unreachable (${String(cause)})`);
  }

  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as T;
}

/** Fired on any 401. The layout listens and drops the cached session, so the
 *  page returns to the sign-in form instead of showing a screen of failures.
 *  The sign-in POST is excluded: a wrong password is not a lost session. */
export const SIGNED_OUT_EVENT = "dcp:signed-out";

/** FastAPI puts the useful part under `detail`; fall back to the status text. */
async function failure(response: Response): Promise<ApiError> {
  if (response.status === 401 && !response.url.endsWith("/auth/login")) {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  let detail: unknown = `${response.status} ${response.statusText}`;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      detail = body.detail;
    }
  } catch {
    // Not JSON — the status line is all we have.
  }
  const message = typeof detail === "string" ? detail : JSON.stringify(detail);
  return new ApiError(response.status, message, detail);
}

/** POST JSON. */
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, `API unreachable (${String(cause)})`);
  }

  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as T;
}

/** PUT JSON. The builder's draft is the one thing the console replaces whole. */
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, `API unreachable (${String(cause)})`);
  }

  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as T;
}
