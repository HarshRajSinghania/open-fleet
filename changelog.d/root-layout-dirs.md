- **Images and the demo moved out of the repository root.** `assets/` is now
  [`docs/assets/`](../docs/assets/) (diagrams, badges, brand images and the diagram generator),
  and `demo/` is now [`evals/demo/`](../evals/demo/) (the negative-control demo and the target
  app). Run the demo with `sh evals/demo/negative-control/run.sh` and the generator from
  `docs/assets/diagrams/generator/`. The README badges read `docs/assets/badges/`; the
  last-release badge check still reads a pre-move release at `assets/badges/`.
