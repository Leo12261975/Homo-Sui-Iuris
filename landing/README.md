# Homo Sui Iuris — landing page

Marketing site for the Free Cognitive Protocol (FCP) and its reference
implementation, W0Guard. Built with [Astro](https://astro.build) as a static
site (no client framework), self-hosted fonts, and a single hero asset.

## Develop

```bash
pnpm install
pnpm dev        # http://localhost:4321
```

## Build

```bash
pnpm build      # -> dist/  (static, deploy anywhere)
pnpm preview    # serve the production build locally
```

## Structure

- `src/pages/index.astro` — page composition + scroll-reveal script
- `src/layouts/Base.astro` — HTML shell, meta/OG, font imports
- `src/components/` — `SiteNav`, `Hero`, `About`, `Work`, `Involve`, `SiteFooter`
- `src/styles/global.css` — OKLCH design tokens, base styles, buttons, reveal
- `src/assets/cognition-figure.png` — hero figure (cropped from the approved art)

## Design notes

- **Type:** Libre Caslon Text (display, constitutional gravitas), Hanken Grotesk
  (body), JetBrains Mono (metadata labels only). All self-hosted via Fontsource.
- **Color:** committed strategy — near-black + one gold, threaded through a warm
  off-white reading surface. Dark hero and Involve bookend a light middle.
- **Motion:** one orchestrated hero load reveal + IntersectionObserver scroll
  reveals. Content is visible by default; motion only enhances. Full
  `prefers-reduced-motion` path.
- **Contrast:** all body/meta text verified ≥ 4.5:1 (WCAG AA).

## Deploying to GitHub Pages

Automated via [`.github/workflows/deploy-landing.yml`](../.github/workflows/deploy-landing.yml)
(at the repo root). On every push to `main` that touches `landing/**`, it builds
this folder and publishes to Pages.

- **One-time setup:** in the repo's **Settings → Pages**, set *Source* to
  **GitHub Actions**.
- The workflow derives `site`/`base` from the repo it runs in
  (`https://<owner>.github.io/<repo>/`), so it needs no editing — it only builds
  for `Leo12261975/Homo-Sui-Iuris`, never for forks.
- **Custom domain instead?** Add a `CNAME`, then set `SITE=https://your-domain`
  and `BASE_PATH=/` (env) or hard-code them in `astro.config.mjs`.

Locally, `pnpm dev` / `pnpm build` run at root (`base: /`); the subpath is applied
only in CI.

## Open items (see `../lading_docs/`)

- **"Get in touch"** currently renders as a marked placeholder (`soon`). Wire it
  to a real email/form target in `src/components/Involve.astro`.
- The **"Get a token"** self-serve CTA is intentionally omitted for now;
  "Run a node" points to the repo setup guide instead.
