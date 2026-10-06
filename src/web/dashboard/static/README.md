# Dashboard static application

This directory is the single source of truth for the deployed owner dashboard.
It is intentionally dependency-free and is served by `src.plugins.dashboard`.

- `index.html` is the public application shell and contains no private data.
- `assets/dashboard.js` assembles same-origin ES modules from `assets/js/`; `api.js` calls the protected summary API with a Bearer token.
- `assets/dashboard.css` imports the six `assets/css/` files in the original cascade order.

Do not create a second dashboard source tree. If a bundler is introduced later,
its build must reproduce this directory in CI and the generated files must not
be edited independently.
