const DJANGO_API_URL = process.env.DJANGO_API_URL || "http://127.0.0.1:8000"

export async function djangoFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const url = `${DJANGO_API_URL}${path}`
  return fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  })
}

export async function djangoAuthFetch(
  path: string,
  accessToken: string,
  init: RequestInit = {}
): Promise<Response> {
  const url = `${DJANGO_API_URL}${path}`
  return fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...init.headers,
    },
  })
}

export { DJANGO_API_URL }
