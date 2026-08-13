#!/bin/sh
# Verify that every delivered source-index entry names the exact blob at a commit.
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 REPOSITORY COMMIT SOURCE_INDEX" >&2
    exit 2
fi

repository=$1
commit=$2
source_index=$3
normalized_index=$(mktemp)
mismatch_log=$(mktemp)
trap 'rm -f "$normalized_index" "$mismatch_log"' EXIT HUP INT TERM

sed 's/\r$//' "$source_index" >"$normalized_index"

entries=$(wc -l <"$normalized_index" | tr -d ' ')
duplicate_paths=$(cut -f2- "$normalized_index" | sort | uniq -d)
if [ -n "$duplicate_paths" ]; then
    printf '%s\n' "$duplicate_paths" | sed 's/^/duplicate=/'
    duplicates=$(printf '%s\n' "$duplicate_paths" | wc -l | tr -d ' ')
else
    duplicates=0
fi

while IFS="$(printf '\t')" read -r descriptor path; do
    descriptor_tail=${descriptor#* }
    object_type=${descriptor_tail%% *}
    expected_object=${descriptor_tail#* }
    actual_object=$(git -C "$repository" rev-parse "$commit:$path")
    if [ "$object_type" != blob ] || [ "$actual_object" != "$expected_object" ]; then
        printf 'mismatch=%s expected=%s actual=%s\n' \
            "$path" "$expected_object" "$actual_object" >>"$mismatch_log"
    fi
done <"$normalized_index"

mismatches=$(wc -l <"$mismatch_log" | tr -d ' ')
cat "$mismatch_log"
printf 'source_commit=%s\n' "$commit"
printf 'entries=%s\n' "$entries"
printf 'duplicates=%s\n' "$duplicates"
printf 'mismatches=%s\n' "$mismatches"

if [ "$entries" -eq 0 ] || [ "$duplicates" -ne 0 ] || [ "$mismatches" -ne 0 ]; then
    exit 1
fi

echo SOURCE_OBJECT_INDEX_OK
