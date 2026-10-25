- **The plugin bundle now carries what Anthropic's plugin directory requires** (#235). The
  developer portal blocked the `dist` bundle because its plugin folder had no README. It also
  takes `.claude-plugin/icon.png` as the listing icon, once, at the first save.
  `scripts/bundle.py` now ships `.claude-plugin/bundle-README.md` as the bundle's `README.md`,
  disclosing everything the plugin runs and sends and where. It also ships a square
  `.claude-plugin/icon.png`. Both are required build inputs.
  [docs/distribution.md](../docs/distribution.md) records the portal's validation report and
  says to submit branch `dist`.
