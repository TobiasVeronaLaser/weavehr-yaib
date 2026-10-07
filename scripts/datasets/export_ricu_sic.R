#!/usr/bin/env Rscript

# RICU 7-day validation export for WeavEHR dataset sic.
Sys.setenv(RICU_SRC = "sic")

script_dir <- file.path(getwd(), "scripts")
source(file.path(script_dir, "export_ricu_dynamic_vars.R"), chdir = TRUE)
source(file.path(script_dir, "export_ricu_stay_windows.R"), chdir = TRUE)
