const apiOrigin = process.env.\u004dOSAIC_API_ORIGIN ?? "http://127.0.0.1:8000";

export async function requestLocalSession(): Promise<Response> {
  return fetch(`${apiOrigin}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      account: process.env.\u004dOSAIC_DEMO_EMAIL,
      password: process.env.\u004dOSAIC_DEMO_PASSWORD,
      ...(process.env.\u004dOSAIC_DEMO_TENANT_SLUG
        ? { tenant_slug: process.env.\u004dOSAIC_DEMO_TENANT_SLUG }
        : {}),
    }),
    cache: "no-store",
  });
}
