#!/bin/bash
# box_helper.sh — shared header box helper with Telegram preformatted block
# Usage: source box_helper.sh
#        box "TITLE" "Field : Value" "Field2 : Value2"

box() {
    local title="$1"; shift
    local w=48
    local sep
    printf -v sep '━%.0s' $(seq 1 $w)
    echo '```'
    echo "$title"
    echo "$sep"
    local line
    for line in "$@"; do
        echo "$line"
    done
    echo "$sep"
    echo '```'
}
