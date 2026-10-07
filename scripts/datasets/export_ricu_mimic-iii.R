#!/usr/bin/env Rscript

# RICU 7-day validation export for WeavEHR dataset mimic-iii.
# Current WeavEHR bundles no mimic-iii dataset configs; the WeavEHR side of this
# comparison requires custom WeavEHR dataset configs.
Sys.setenv(RICU_SRC = "mimic")

script_dir <- file.path(getwd(), "scripts")
source(file.path(script_dir, "export_ricu_dynamic_vars.R"), chdir = TRUE)
source(file.path(script_dir, "export_ricu_stay_windows.R"), chdir = TRUE)
