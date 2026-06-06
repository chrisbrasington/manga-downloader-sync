#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--dry-run] <dir>"
  echo ""
  echo "  Converts .zip → .cbz (rename)"
  echo "  Converts .rar → .cbz (extract + rezip)"
  echo "  Converts .7z  → .cbz (extract + rezip)"
  echo ""
  echo "  Searches recursively under <dir>."
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

# Check tools
need_rar=false
need_7z=false
while IFS= read -r f; do
  [[ "$f" == *.rar ]] && need_rar=true
  [[ "$f" == *.7z  ]] && need_7z=true
done < <(find "$DIR" -type f \( -iname "*.rar" -o -iname "*.7z" \) | sort)

if $need_7z && ! command -v 7z &>/dev/null; then
  echo "7z files found but '7z' is not installed."
  exit 1
fi

if $need_rar && ! command -v unrar &>/dev/null && ! command -v 7z &>/dev/null; then
  echo "RAR files found but neither 'unrar' nor '7z' is installed."
  exit 1
fi

EXTRACTOR=""
if command -v unrar &>/dev/null; then
  EXTRACTOR="unrar"
elif command -v 7z &>/dev/null; then
  EXTRACTOR="7z"
fi

mapfile -t FILES < <(find "$DIR" -type f \( -iname "*.zip" -o -iname "*.rar" -o -iname "*.7z" \) | sort)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No .zip, .rar, or .7z files found under $DIR"
  exit 0
fi

zip_count=0
rar_count=0
sevenz_count=0
for f in "${FILES[@]}"; do
  ext="${f##*.}"
  case "${ext,,}" in
    zip) (( zip_count++ )) || true ;;
    rar) (( rar_count++ )) || true ;;
    7z)  (( sevenz_count++ )) || true ;;
  esac
done

echo ""
echo "  Directory : $DIR"
echo "  .zip files: $zip_count  (rename only)"
echo "  .rar files: $rar_count  (extract + rezip)"
echo "  .7z files : $sevenz_count  (extract + rezip)"
echo "  Total     : ${#FILES[@]}"
$DRY_RUN && echo "  Mode      : DRY RUN"
echo ""

convert_zip() {
  local src="$1"
  local dst="${src%.*}.cbz"

  if [[ "$src" == "$dst" ]]; then
    echo "  [zip] SKIP (already .cbz?): $src"
    return
  fi

  echo "  [zip] $src"
  echo "          -> $(basename "$dst")"

  if $DRY_RUN; then
    echo "         (dry run)"
    return
  fi

  if [[ -e "$dst" ]]; then
    echo "         WARNING: destination exists, skipping"
    return
  fi

  mv "$src" "$dst"
  echo "         done."
}

rar_converted=()
sevenz_converted=()

convert_rar() {
  local src="$1"
  local dst="${src%.*}.cbz"
  local tmp
  tmp=$(mktemp -d)

  echo "  [rar] $src"
  echo "         -> $(basename "$dst")"

  if $DRY_RUN; then
    echo "         (dry run)"
    rm -rf "$tmp"
    return
  fi

  if [[ -e "$dst" ]]; then
    echo "         WARNING: destination exists, skipping"
    rm -rf "$tmp"
    return
  fi

  echo "         extracting..."
  if [[ "$EXTRACTOR" == "unrar" ]]; then
    unrar x -inul "$src" "$tmp/"
  else
    7z x -bd -bso0 "$src" -o"$tmp"
  fi

  echo "         repacking as cbz..."
  # zip from inside tmp so paths inside the archive are relative
  (cd "$tmp" && zip -r -q "$dst" .)

  rm -rf "$tmp"
  rar_converted+=("$src")
  echo "         done."
}

convert_7z() {
  local src="$1"
  local dst="${src%.*}.cbz"
  local tmp
  tmp=$(mktemp -d)

  echo "  [7z]  $src"
  echo "         -> $(basename "$dst")"

  if $DRY_RUN; then
    echo "         (dry run)"
    rm -rf "$tmp"
    return
  fi

  if [[ -e "$dst" ]]; then
    echo "         WARNING: destination exists, skipping"
    rm -rf "$tmp"
    return
  fi

  echo "         extracting..."
  7z x -bd -bso0 "$src" -o"$tmp"

  echo "         repacking as cbz..."
  (cd "$tmp" && zip -r -q "$dst" .)

  rm -rf "$tmp"
  sevenz_converted+=("$src")
  echo "         done."
}

errors=0
for f in "${FILES[@]}"; do
  ext="${f##*.}"
  case "${ext,,}" in
    zip) convert_zip "$f" || (( errors++ )) || true ;;
    rar) convert_rar "$f" || (( errors++ )) || true ;;
    7z)  convert_7z  "$f" || (( errors++ )) || true ;;
  esac
done

echo ""
if [[ $errors -gt 0 ]]; then
  echo "Done with $errors error(s) — original RAR/7z files kept."
  exit 1
fi

if [[ ${#rar_converted[@]} -gt 0 ]]; then
  echo "  Removing original RAR files..."
  for src in "${rar_converted[@]}"; do
    rm -f "$src"
    echo "    deleted: $src"
  done
  echo ""
fi

if [[ ${#sevenz_converted[@]} -gt 0 ]]; then
  echo "  Removing original 7z files..."
  for src in "${sevenz_converted[@]}"; do
    rm -f "$src"
    echo "    deleted: $src"
  done
  echo ""
fi

echo "Done."
