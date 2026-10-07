#!/usr/bin/env Rscript

# Export RICU stay windows for Python comparison.
#
# Defaults:
#   RICU_SRC        = miiv
#   RICU_OUT_DIR    = ~/output/weavehr_yaib
#   RICU_WINDOW_OUT = ${RICU_OUT_DIR}/ricu_stay_windows_${RICU_SRC}.parquet
#
# Example:
#   RICU_OUT_DIR="$HOME/output/weavehr_yaib" Rscript scripts/export_ricu_stay_windows.R

suppressPackageStartupMessages({
  library(ricu)
  library(data.table)
  library(lubridate)
})

src <- Sys.getenv("RICU_SRC", unset = "miiv")
out_dir <- Sys.getenv(
  "RICU_OUT_DIR",
  unset = file.path(Sys.getenv("HOME"), "output", "weavehr_yaib")
)
out <- Sys.getenv(
  "RICU_WINDOW_OUT",
  unset = file.path(out_dir, sprintf("ricu_stay_windows_%s.parquet", src))
)

dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)

interval <- as.difftime(1, units = "hours")
patients <- stay_windows(src, interval = interval)
dt <- as.data.table(patients)

# Keep original column names. Typical columns include stay_id, start, and end.
print(names(dt))
print(head(dt))
print(meta_vars(patients))

if (requireNamespace("arrow", quietly = TRUE)) {
  arrow::write_parquet(dt, out)
  message("Wrote parquet: ", out)
} else {
  csv_out <- sub("\\.parquet$", ".csv", out)
  data.table::fwrite(dt, csv_out)
  message("Package 'arrow' not available. Wrote CSV: ", csv_out)
}
