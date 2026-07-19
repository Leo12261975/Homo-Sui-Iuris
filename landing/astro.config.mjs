// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// `site` (origin) and `base` (repo subpath) drive canonical URLs, Open Graph
// URLs, the sitemap, robots.txt, and every hashed asset path.
//
// On GitHub Pages the deploy workflow injects these from the repo context:
//   SITE=https://<owner>.github.io   BASE_PATH=/<repo>
// Locally they fall back to root (`/`) so `pnpm dev` stays at localhost:4321/.
// For a custom domain, set SITE=https://your-domain and BASE_PATH=/.
const SITE = process.env.SITE ?? 'https://leo12261975.github.io';
const BASE = process.env.BASE_PATH ?? '/';

export default defineConfig({
  site: SITE,
  base: BASE,
  trailingSlash: 'ignore',
  integrations: [sitemap()],
  build: {
    inlineStylesheets: 'auto',
  },
});
