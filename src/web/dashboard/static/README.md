# Dashboard static application

The deployed owner dashboard is served directly from this directory by `src.plugins.dashboard`. It uses native HTML, CSS and JavaScript without a bundler or third-party UI runtime.

- `index.html` is the public application shell and contains no private data.
- `assets/dashboard.js` loads same-origin ES modules from `assets/js/`. The `api.js` module calls the protected summary API with a Bearer token.
- `assets/dashboard.css` imports the six `assets/css/` files in the original cascade order.

Do not create a second dashboard source tree. If a bundler is introduced later, its build must reproduce this directory in CI and the generated files must not be edited independently.
