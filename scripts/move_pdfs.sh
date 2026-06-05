#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--dry-run] <source_dir> <target_dir>"
  exit 1
}

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  shift
fi

[[ $# -ne 2 ]] && usage

SRC="${1%/}"
DST="${2%/}"

if [[ ! -d "$SRC" ]]; then
  echo "Source directory not found: $SRC"
  exit 1
fi

declare -A folder_counts
declare -a folder_order
declare -a all_moves  # "src_path|dst_path" pairs

while IFS= read -r pdf; do
  folder=$(dirname "$pdf")
  name=$(basename "$folder")
  dst_folder="$DST/$name"
  all_moves+=("$pdf|$dst_folder/$(basename "$pdf")")
  if [[ -z "${folder_counts[$name]+_}" ]]; then
    folder_order+=("$name")
    folder_counts["$name"]=0
  fi
  folder_counts["$name"]=$(( ${folder_counts["$name"]} + 1 ))
done < <(find "$SRC" -maxdepth 2 -mindepth 2 -name "*.pdf" | sort)

if [[ ${#folder_order[@]} -eq 0 ]]; then
  echo "No PDFs found in 1-depth folders under $SRC"
  exit 0
fi

echo ""
echo "  Source : $SRC"
echo "  Dest   : $DST"
echo ""
printf "  %-50s  %s\n" "Folder" "PDFs"
printf "  %-50s  %s\n" "------" "----"
total=0
for name in "${folder_order[@]}"; do
  count=${folder_counts[$name]}
  printf "  %-50s  %d\n" "$name" "$count"
  (( total += count )) || true
done
echo ""
echo "  Total: $total PDF(s) across ${#folder_order[@]} folder(s)"
echo ""

echo "  Files to move:"
echo ""
for entry in "${all_moves[@]}"; do
  src_file="${entry%%|*}"
  dst_file="${entry##*|}"
  printf "    %s\n      -> %s\n" "$src_file" "$dst_file"
done
echo ""

if $DRY_RUN; then
  echo "  Dry run — no files moved."
  exit 0
fi

conflicts=()
for entry in "${all_moves[@]}"; do
  dst_file="${entry##*|}"
  if [[ -e "$dst_file" ]]; then
    conflicts+=("$dst_file")
  fi
done

if [[ ${#conflicts[@]} -gt 0 ]]; then
  echo "Conflicts — files already exist at destination:"
  for f in "${conflicts[@]}"; do
    echo "  $f"
  done
  echo ""
  echo "Remove or rename these files manually, then re-run."
  exit 1
fi

read -rp "Proceed with move? [y/N] " answer
if [[ "${answer,,}" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""
for entry in "${all_moves[@]}"; do
  src_file="${entry%%|*}"
  dst_file="${entry##*|}"
  dst_folder=$(dirname "$dst_file")
  mkdir -p "$dst_folder"
  mv "$src_file" "$dst_file"
  echo "  Moved: $src_file"
  echo "      -> $dst_file"
done

echo ""
echo "Done."
