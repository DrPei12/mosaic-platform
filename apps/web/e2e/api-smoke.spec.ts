import { expect, test, type Page } from "@playwright/test";

async function fetchJson(page: Page, path: string) {
  return page.evaluate(async (requestPath) => {
    const response = await fetch(requestPath);
    return {
      status: response.status,
      body: (await response.json()) as unknown,
    };
  }, path);
}

test("browser reaches FastAPI live and unavailable-ready through the Next rewrite", async ({
  page,
}) => {
  await page.goto("/");

  const live = await fetchJson(page, "/api/v1/health/live");
  expect(live.status).toBe(200);
  expect(live.body).toEqual({
    service: "mosaic-api",
    status: "ok",
    version: "0.1.0",
  });

  const ready = await fetchJson(page, "/api/v1/health/ready");
  expect(ready.status).toBe(503);
  expect(ready.body).toMatchObject({
    error: { code: "SERVICE_DEPENDENCY_NOT_READY" },
  });
});
