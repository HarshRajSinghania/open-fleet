- **#604's WIP-curve experiment is re-registered as version 2** (#604). Version 1's first two live
  runs showed two runner defects. A run the API refused every call of for an expired credential
  still read `complete`, so its one allowed re-run was refused. Inside the container live harness,
  every launch named a different machine, so no two runs could be pooled. In version 2 a refused
  credential halts the run, which ends `failed` (`credential-rejected`) and may be re-run once.
  The launcher's attestation also records the host (`host_sha256`), and the runner names the
  machine by it. Nothing else in the design changes. Version 2's runs are `wip2-*`, in a new
  results directory, and the
  [pre-registration](../docs/experiments/wip-curve-prereg.md#version-2) records why.
