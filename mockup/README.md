# Caralee Medical Group — Website Preview

Interactive preview site for [caraleemg.com.au](https://caraleemg.com.au).

## Live preview

### Option A — GitHub Pages (recommended, permanent)

1. In the repo go to **Settings → Pages → Build and deployment**
2. Set **Source** to **GitHub Actions**
3. Re-run the **Deploy preview site to GitHub Pages** workflow

Site URL: **https://minidigital.github.io/caralee/**

### Option B — Run locally

```bash
cd mockup && python3 -m http.server 8080
```

Open http://localhost:8080

## Features

- Original Caralee logo preserved (`logo.jpg`)
- 2026 refresh influenced by Medtronic's brand: bold headlines, expressive
  blue gradients, layered/glass surfaces, and a geometric sans typeface
- Deep indigo (`#170f5f`) + electric blue (`#2b2bff`) gradient system, with the
  Caralee red (`#e32129`) preserved as an accent
- Sora (display) + Inter (body) typography
- Mobile-responsive navigation
- Google Maps embed with directions link
- Real practice content: services, fees, contact, policies
- Healthengine online booking link
