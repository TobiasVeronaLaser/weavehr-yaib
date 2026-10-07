#!/usr/bin/env Rscript

# Export RICU dynamic variables for Python comparison.
#
# Defaults:
#   RICU_SRC     = miiv
#   RICU_OUT_DIR = ~/output/weavehr_yaib
#   RICU_DYN_OUT = ${RICU_OUT_DIR}/ricu_dynamic_vars_${RICU_SRC}.parquet
#
# Provenance:
#   Writes ${RICU_DYN_OUT%.parquet}.provenance.json recording the RICU source,
#   the ricu package version and the source dataset version. RICU's config only
#   knows the version it would download (its source URL); set
#   RICU_SOURCE_VERSION to declare the version of the data actually loaded from
#   RICU_DATA_PATH. Only a declared version counts as verified provenance.
#
# Example:
#   RICU_OUT_DIR="$HOME/output/weavehr_yaib" Rscript scripts/export_ricu_dynamic_vars.R

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

# Provenance sidecar read by weavehr_yaib.versions.resolve_reference_version().
src_url <- tryCatch({
  cfg <- jsonlite::read_json(
    system.file("extdata", "config", "data-sources.json", package = "ricu")
  )
  hit <- Filter(function(x) identical(x$name, src), cfg)
  if (length(hit) == 1 && !is.null(hit[[1]]$url)) hit[[1]]$url else NA_character_
}, error = function(e) NA_character_)

declared_version <- Sys.getenv("RICU_SOURCE_VERSION", unset = "")

provenance <- list(
  reference = "ricu",
  ricu_source = src,
  ricu_package_version = as.character(utils::packageVersion("ricu")),
  source_url = if (is.na(src_url)) NULL else src_url,
  source_version_from_url = if (is.na(src_url)) NULL else basename(src_url),
  source_version_declared = if (nzchar(declared_version)) declared_version else NULL,
  dynamic_vars = dynamic_vars,
  interval_hours = 1,
  exported_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
)

provenance_out <- sub("\\.(parquet|csv)$", ".provenance.json", out)
jsonlite::write_json(
  provenance, provenance_out, auto_unbox = TRUE, pretty = TRUE, null = "null"
)
message("Wrote provenance: ", provenance_out)
