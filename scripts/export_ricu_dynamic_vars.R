#!/usr/bin/env Rscript

# Export RICU dynamic variables for Python comparison.
#
# Defaults:
#   RICU_SRC     = miiv
#   RICU_OUT_DIR = ~/output/openicu_yaib
#   RICU_DYN_OUT = ${RICU_OUT_DIR}/ricu_dynamic_vars_${RICU_SRC}.parquet
#
# Example:
#   RICU_OUT_DIR="$HOME/output/openicu_yaib" Rscript scripts/export_ricu_dynamic_vars.R

suppressPackageStartupMessages({
  library(ricu)
  library(data.table)
  library(lubridate)
})

src <- Sys.getenv("RICU_SRC", unset = "miiv")
out_dir <- Sys.getenv(
  "RICU_OUT_DIR",
  unset = file.path(Sys.getenv("HOME"), "output", "openicu_yaib")
)
out <- Sys.getenv(
  "RICU_DYN_OUT",
  unset = file.path(out_dir, sprintf("ricu_dynamic_vars_%s.parquet", src))
)

dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)

dynamic_vars_env <- Sys.getenv("RICU_DYNAMIC_VARS", unset = "")

dynamic_vars <- if (nzchar(dynamic_vars_env)) {
  trimws(strsplit(dynamic_vars_env, ",", fixed = TRUE)[[1]])
} else {
  c("alb", "alp", "alt", "ast", "be", "bicar", "bili", "bili_dir",
    "bnd", "bun", "ca", "cai", "ck", "ckmb", "cl", "crea", "crp",
    "dbp", "fgn", "fio2", "glu", "hgb", "hr", "inr_pt", "k", "lact",
    "lymph", "map", "mch", "mchc", "mcv", "methb", "mg", "na", "neut",
    "o2sat", "pco2", "ph", "phos", "plt", "po2", "ptt", "resp", "sbp",
    "temp", "tnt", "urine", "wbc")
}

interval <- as.difftime(1, units = "hours")
df <- load_concepts(dynamic_vars, src = src, interval = interval)
dt <- as.data.table(df)

print(names(dt))
message("Rows: ", nrow(dt))
print(meta_vars(df))

# Normalize charttime to integer hours if present as difftime.
if ("charttime" %in% names(dt)) {
  dt[, time := as.integer(as.numeric(charttime, units = "hours"))]
}

if (requireNamespace("arrow", quietly = TRUE)) {
  arrow::write_parquet(dt, out)
  message("Wrote parquet: ", out)
} else {
  csv_out <- sub("\\.parquet$", ".csv", out)
  data.table::fwrite(dt, csv_out)
  message("Package 'arrow' not available. Wrote CSV: ", csv_out)
}
