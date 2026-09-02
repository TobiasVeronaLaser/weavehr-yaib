# Dataset workflows

There is exactly one Python notebook per OpenICU dataset. Every notebook creates the all-hours/all-concepts OpenICU YAIB-wide output. Optional validation workflows are available for datasets with a matching RICU source and can compare the first 168 hours against RICU. `mimic-iv-demo` and `nwicu` have no RICU validation wrapper.

The notebook output layout is `WORKSPACE/yaib/<dataset>/...`. If an OpenICU project root is supplied, `workspace/yaib` is selected automatically. If an arbitrary output directory is supplied, `yaib` is created below that directory and `concept/` is expected alongside it unless `concept_root` is supplied explicitly.

For AUMC, the workflow automatically derives stay windows from the OpenICU `VISIT_START` and `VISIT_END` extraction outputs when no explicit stay table is supplied.
