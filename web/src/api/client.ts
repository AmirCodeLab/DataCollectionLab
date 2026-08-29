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
    throw new ApiError(response.status, await describeFailure(response));
  }
  return (await response.json()) as T;
}

/** FastAPI puts the useful part under `detail`; fall back to the status text. */
async function describeFailure(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Not JSON — the status line is all we have.
  }
  return `${response.status} ${response.statusText}`;
}

/** POST JSON. The only write the console makes today is registering a key. */
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
    throw new ApiError(response.status, await describeFailure(response));
  }
  return (await response.json()) as T;
}
