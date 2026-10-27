- **Reading a worker's checkout for episodic hints no longer runs a command the checkout names.**
  `runtime/scripts/hint_provenance.py` diffed the live working tree under the hardened git
  environment but without `gitexec.driver_blanks`, so a clean filter the worker declared in its
  own `.git/config` and selected from `.git/info/attributes` ran on the coordinator whenever a
  hint's currency was checked (the #629 channel). Every `diff` and `log` it runs now blanks the
  repo's declared filter, diff and merge drivers, every git call closes stdin, and a config it
  cannot read is a `ProvenanceError` rather than a diff with nothing blanked.
  `tests/test_gitexec_config_commands.py` pins it with a planted filter and a mutation control.
