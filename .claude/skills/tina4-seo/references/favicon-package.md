# Phase 8 - Favicon package

> Reference for the `tina4-seo` skill: Phase 8 (favicon package). Moved out of `SKILL.md` unchanged.

## Phase 8 — Favicon package

### Read the Favicon Brief from DESIGN.md

If DESIGN.md has a `## Favicon Brief` section (written by tina4-design), read it for:
- Icon mark description
- Light and dark background/icon colours
- App name
- RFG package status (`pending` or `complete`)

If DESIGN.md is absent or has no Favicon Brief, ask for:
- The logo mark file (SVG preferred)
- Light and dark brand colours
- App short name (used for PWA home-screen label)

### SVG favicon (primary — generate first)

Create `favicon.svg` at the webroot. An SVG favicon with an embedded media query is
theme-aware from a single file with no JavaScript:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <style>
    /* Light mode */
    .bg { fill: [light-background-hex]; }
    .mark { fill: [light-icon-hex]; }

    /* Dark mode */
    @media (prefers-color-scheme: dark) {
      .bg { fill: [dark-background-hex]; }
      .mark { fill: [dark-icon-hex]; }
    }
  </style>

  <!-- Background square (optional — omit if mark works on any background) -->
  <rect class="bg" width="32" height="32" rx="[radius]"/>

  <!-- Icon mark paths from the logo file — describe what the mark looks like -->
  <!-- IMPORTANT: never invent or guess SVG paths. If the logo file cannot be read,
       ask the developer to paste the path data from the icon element. -->
  <path class="mark" d="[path data from logo icon element]"/>
</svg>
```

**Never invent SVG path data.** Read the actual logo file to extract it. If the logo is a
PNG with no SVG source, note it and skip the SVG favicon — fall back to the RFG package.

### RFG package (full favicon set)

Real Favicon Generator provides the complete multi-platform favicon package. Call the
non-interactive API if the logo file is available:

```
POST https://realfavicongenerator.net/api/favicon
Content-Type: application/json

{
  "favicon_generation": {
    "api_key": "no_key_required_for_free_tier",
    "master_picture": {
      "type": "url",
      "url": "https://[domain]/[logo-file-path]"
    },
    "settings": {
      "compression": "2",
      "scaling_algorithm": "Mitchell",
      "error_on_image_too_small": false
    },
    "favicon_design": {
      "desktop_browser": {},
      "ios": {
        "picture_aspect": "background_and_margin",
        "margin": "18%",
        "background_color": "[light-background-hex]"
      },
      "android_chrome": {
        "picture_aspect": "background_and_margin",
        "margin": "18%",
        "background_color": "[light-background-hex]",
        "manifest": {
          "name": "[App name from Favicon Brief]",
          "short_name": "[Short name — max 12 chars]",
          "display": "standalone",
          "orientation": "not_set",
          "theme_color": "[accent hex]",
          "background_color": "[bg hex]"
        }
      },
      "safari_pinned_tab": {
        "picture_aspect": "silhouette",
        "theme_color": "[accent hex]"
      }
    },
    "settings": {
      "target_path": "/favicons"
    }
  }
}
```

The API returns a ZIP package. Extract it to `[public]/favicons/` and paste the HTML
snippet it provides into the base template `<head>`, replacing any existing favicon links.

If the logo cannot be sent to an external service (ask the developer to confirm), provide
the instructions for manual generation at https://realfavicongenerator.net and skip the
API call.

### Minimum `<head>` favicon snippet

Whether from RFG or hand-built:

```html
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicons/favicon-32x32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/favicons/apple-touch-icon.png">
<link rel="manifest" href="/favicons/site.webmanifest">
```

Update `DESIGN.md` Favicon Brief to set `RFG package: complete`.
