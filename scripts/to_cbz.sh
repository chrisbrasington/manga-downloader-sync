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

if ! $DRY_RUN && ! command -v trash &>/dev/null; then
  echo "'trash' is not installed — needed to safely remove source files after conversion."
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

# Verify extracted content: at least one file, no empty files.
check_extraction() {
  local tmp="$1" src="$2"

  local file_count
  file_count=$(find "$tmp" -type f | wc -l)
  if [[ $file_count -eq 0 ]]; then
    echo "         ERROR: extraction produced no files — archive may be empty or corrupt: $src"
    return 1
  fi

  local zero_files=()
  while IFS= read -r f; do
    zero_files+=("$f")
  done < <(find "$tmp" -type f -empty)
  if [[ ${#zero_files[@]} -gt 0 ]]; then
    echo "         ERROR: extraction produced ${#zero_files[@]} empty file(s) — archive may be corrupt or use an unsupported method: $src"
    for zf in "${zero_files[@]}"; do
      echo "           $(basename "$zf")"
    done
    [[ "$EXTRACTOR" == "7z" ]] && echo "         Tip: install 'unrar' for full RAR compression support."
    return 1
  fi

  echo "         $file_count file(s) extracted OK"
}

repack_as_cbz() {
  local tmp="$1" abs_dst="$2"
  local ec=0
  (cd "$tmp" && zip -r -q "$abs_dst" .) || ec=$?
  if [[ $ec -ne 0 ]]; then
    echo "         ERROR: zip failed (exit $ec)"
    # Remove partial output — it's a file we just created, not a source.
    [[ -f "$abs_dst" ]] && rm -f "$abs_dst"
    return 1
  fi
}

convert_zip() {
  local src="$1"
  local dst="${src%.*}.cbz"

  if [[ "$src" == "$dst" ]]; then
    echo "  [zip] SKIP (already .cbz?): $src"
    return
  fi

  echo "  [zip] $src"
  echo "         -> $(basename "$dst")"

  if $DRY_RUN; then
    echo "         (dry run)"
    return
  fi

  if [[ -e "$dst" ]]; then
    echo "         SKIP: destination already exists: $dst"
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
    echo "         SKIP: destination already exists: $dst"
    rm -rf "$tmp"
    return
  fi

  echo "         extracting..."
  local ec=0
  if [[ "$EXTRACTOR" == "unrar" ]]; then
    unrar x -inul "$src" "$tmp/" || ec=$?
  else
    7z x -bd -bso0 "$src" -o"$tmp" || ec=$?
  fi
  if [[ $ec -ne 0 ]]; then
    echo "         ERROR: $EXTRACTOR exited with $ec"
    [[ "$EXTRACTOR" == "7z" ]] && echo "         Tip: install 'unrar' for full RAR compression support."
    rm -rf "$tmp"
    return 1
  fi

  if ! check_extraction "$tmp" "$src"; then
    rm -rf "$tmp"
    return 1
  fi

  echo "         repacking as cbz..."
  local abs_dst
  abs_dst="$(cd "$(dirname "$src")" && pwd)/$(basename "$dst")"
  if ! repack_as_cbz "$tmp" "$abs_dst"; then
    rm -rf "$tmp"
    return 1
  fi

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
    echo "         SKIP: destination already exists: $dst"
    rm -rf "$tmp"
    return
  fi

  echo "         extracting..."
  local ec=0
  7z x -bd -bso0 "$src" -o"$tmp" || ec=$?
  if [[ $ec -ne 0 ]]; then
    echo "         ERROR: 7z exited with $ec"
    rm -rf "$tmp"
    return 1
  fi

  if ! check_extraction "$tmp" "$src"; then
    rm -rf "$tmp"
    return 1
  fi

  echo "         repacking as cbz..."
  local abs_dst
  abs_dst="$(cd "$(dirname "$src")" && pwd)/$(basename "$dst")"
  if ! repack_as_cbz "$tmp" "$abs_dst"; then
    rm -rf "$tmp"
    return 1
  fi

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
  echo "Done with $errors error(s) — no source files removed."
  exit 1
fi

if [[ ${#rar_converted[@]} -gt 0 ]]; then
  echo "  Trashing original RAR files..."
  for src in "${rar_converted[@]}"; do
    trash "$src"
    echo "    trashed: $src"
  done
  echo ""
fi

if [[ ${#sevenz_converted[@]} -gt 0 ]]; then
  echo "  Trashing original 7z files..."
  for src in "${sevenz_converted[@]}"; do
    trash "$src"
    echo "    trashed: $src"
  done
  echo ""
fi

echo "Done."
