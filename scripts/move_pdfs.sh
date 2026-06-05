#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <source_dir> <target_dir>"
  exit 1
fi

SRC="${1%/}"
DST="${2%/}"

if [[ ! -d "$SRC" ]]; then
  echo "Source directory not found: $SRC"
  exit 1
fi

declare -A folder_counts
declare -a folder_order

while IFS= read -r pdf; do
  folder=$(dirname "$pdf")
  name=$(basename "$folder")
  if [[ -z "${folder_counts[$name]+_}" ]]; then
    folder_order+=("$name")
    folder_counts[$name]=0
  fi
  (( ++folder_counts[$name] ))
done < <(find "$SRC" -maxdepth 2 -mindepth 2 -name "*.pdf" | sort)

if [[ ${#folder_order[@]} -eq 0 ]]; then
  echo "No PDFs found in 1-depth folders under $SRC"
  exit 0
fi

echo ""
echo "Dry run — PDFs to move from: $SRC"
echo "                          to: $DST"
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

conflicts=()
for name in "${folder_order[@]}"; do
  src_folder="$SRC/$name"
  dst_folder="$DST/$name"
  while IFS= read -r pdf; do
    dst_file="$dst_folder/$(basename "$pdf")"
    if [[ -e "$dst_file" ]]; then
      conflicts+=("$dst_file")
    fi
  done < <(find "$src_folder" -maxdepth 1 -name "*.pdf" | sort)
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
for name in "${folder_order[@]}"; do
  src_folder="$SRC/$name"
  dst_folder="$DST/$name"
  mkdir -p "$dst_folder"
  while IFS= read -r pdf; do
    mv "$pdf" "$dst_folder/"
    echo "  Moved: $name/$(basename "$pdf")"
  done < <(find "$src_folder" -maxdepth 1 -name "*.pdf" | sort)
done

echo ""
echo "Done."
