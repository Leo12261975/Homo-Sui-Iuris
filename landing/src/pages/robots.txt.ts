import type { APIRoute } from "astro";

// Dynamic so the Sitemap URL always reflects the deploy origin + base
// (localhost, a GitHub Pages project subpath, or a custom domain).
export const GET: APIRoute = ({ site }) => {
  const path = `${import.meta.env.BASE_URL.replace(/\/$/, "")}/sitemap-index.xml`;
  const sitemap = new URL(path, site);
  const body = ["User-agent: *", "Allow: /", "", `Sitemap: ${sitemap}`, ""].join(
    "\n",
  );
  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
