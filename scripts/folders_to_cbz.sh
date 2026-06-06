#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--dry-run] <dir>"
  echo ""
  echo "  Zips each subdirectory of <dir> into a .cbz, then trashes the folder."
  exit 1
}

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  shift
fi

[[ $# -ne 1 ]] && usage

DIR="${1%/}"

if [[ ! -d "$DIR" ]]; then
  echo "Directory not found: $DIR"
  exit 1
fi

mapfile -t FOLDERS < <(find "$DIR" -mindepth 1 -maxdepth 1 -type d | sort)

if [[ ${#FOLDERS[@]} -eq 0 ]]; then
  echo "No subdirectories found under $DIR"
  exit 0
fi

echo ""
echo "  Directory : $DIR"
echo "  Folders   : ${#FOLDERS[@]}"
$DRY_RUN && echo "  Mode      : DRY RUN"
echo ""

errors=0
for d in "${FOLDERS[@]}"; do
  cbz="${d}.cbz"
  echo "  $d"
  echo "    -> $(basename "$cbz")"

  if $DRY_RUN; then
    echo "       (dry run)"
    continue
  fi

  if [[ -e "$cbz" ]]; then
    echo "       WARNING: $cbz already exists, skipping"
    continue
  fi

  if zip -r -q "$cbz" "$d"; then
    trash "$d"
    echo "       done."
  else
    echo "       ERROR: zip failed, folder kept"
    (( errors++ )) || true
  fi
done

echo ""
[[ $errors -gt 0 ]] && echo "Done with $errors error(s)." || echo "Done."
[[ $errors -gt 0 ]] && exit 1 || exit 0
