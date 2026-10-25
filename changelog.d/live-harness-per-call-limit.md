- **The live harness can hand a registration's per-call limit to every model call** (#604).
  `live_container.py run --per-call-usd 1.60` writes a read-only settings file into the arm's
  container. The in-container `claude` then appends `--max-budget-usd 1.60` to each call that does
  not pass its own, as #604's registration says the owner's isolation wrapper does on the host.
  The receipt records the limit. Settings that cannot be read make `claude` refuse.
