#!/bin/zsh
# shellcheck disable=SC1071
# Resolve Installomator labels under faked arch + macOS version on a single Apple Silicon Mac.
#
# Architecture: Intel branch via Rosetta (arch -x86_64), arm64 via native run.
# OS version: a sw_vers shim on PATH (see ./shim/sw_vers) feeds each label a faked version.
# GitHub: a curl shim (see ./shim/curl) authenticates api.github.com to dodge the rate limit.
#
# It drives the real Installomator.sh in DEBUG mode and scrapes the downloadURL/appNewVersion
# it prints before downloading. Labels that download-and-inspect a binary won't be faked out
# by this — only URL-templating / API-query labels are.
#
# Axes are auto-selected per label from its source: a label is swept across arm64/x86_64 only
# if it reads arch, and across macOS versions only if it reads sw_vers. Labels that read
# neither resolve once. No flags needed.
#
# Usage: ./sweep.sh <label> [<label> ...]

set -u

HERE=${0:A:h}
REPO=${INSTALLOMATOR_DIR:-${HERE:h}}  # Installomator checkout (resolver sets INSTALLOMATOR_DIR)
INSTALLO="$REPO/Installomator.sh"
SHIMDIR="$HERE/shim"
TIMEOUT=90

LABELDIR="$REPO/fragments/labels"

# What makes a label worth a given axis. Kept in sync with candidates/ generation.
ARCH_RE='\$\(/?(usr/bin/)?arch\)|`/?(usr/bin/)?arch`|uname -m|sysctl -n hw\.|cpu_type\(\)'
OS_RE='sw_vers|OSVERSION'

# Axis values. name:productVersion:buildVersion / name:archflag.
os_axis=( "macOS 14:14.6.1:23G93" "macOS 15:15.5:24F74" )
os_none=( "host::" )                          # empty product → shim defers to real sw_vers
arch_axis=( "arm64:-arm64" "x86_64:-x86_64" )
arch_none=( "any:-arm64" )                     # arch irrelevant → one host pass

if [[ $# -eq 0 ]]; then
    print -u2 "usage: $0 <label> [<label> ...]"
    exit 2
fi

if ! /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
    print -u2 "warning: Rosetta not available — x86_64 rows will be empty."
fi

# Installomator hard-resets PATH (header.sh:21), wiping the shim. Run a temp copy whose
# PATH line is rewritten to prepend the shim dir, so bare sw_vers hits the mock.
PATCHED=$(mktemp -t installomator-sweep)
trap 'rm -f "$PATCHED"' EXIT
sed "s|^export PATH=/usr/bin:/bin:/usr/sbin:/sbin\$|export PATH=$SHIMDIR:/usr/bin:/bin:/usr/sbin:/sbin|" \
    "$INSTALLO" > "$PATCHED"
if ! grep -q "^export PATH=$SHIMDIR:" "$PATCHED"; then
    print -u2 "error: could not patch PATH line in Installomator.sh — did header.sh:21 change?"
    exit 1
fi
chmod +x "$PATCHED"

kill_tree() { local p=$1 c; for c in $(pgrep -P $p); do kill_tree $c; done; kill $p 2>/dev/null; }

# Run one label under a given arch + faked OS. Stops as soon as the metadata is printed,
# before the download starts.
resolve() {
    local archflag=$1 product=$2 build=$3 label=$4
    local tmp=$(mktemp)
    /usr/bin/arch "$archflag" /bin/zsh -c "
        export FAKE_OS_PRODUCT='$product' FAKE_OS_BUILD='$build'
        exec '$PATCHED' '$label' DEBUG=1 NOTIFY=silent BLOCKING_PROCESS_ACTION=ignore
    " >"$tmp" 2>/dev/null &
    local pid=$! i=0
    while kill -0 $pid 2>/dev/null; do
        grep -q 'appNewVersion=' "$tmp" && break
        (( i++ >= TIMEOUT * 10 )) && break
        sleep 0.1
    done
    kill_tree $pid
    cat "$tmp"
    rm -f "$tmp"
}

field() {  # extract value after "<key>=" from captured output
    sed -n "s/.*$1=//p" | tail -1
}

# Source for a label: its fragment if present, else the block carved out of the monolith.
label_source() {
    local label=$1
    if [[ -f "$LABELDIR/$label.sh" ]]; then
        cat "$LABELDIR/$label.sh"
    else
        awk -v l="$label" '$0 ~ "^"l"\\)" {f=1} f {print} f && /^[[:space:]]*;;[[:space:]]*$/ {exit}' "$INSTALLO"
    fi
}

# One JSON object per resolution, collected here, grouped by label at the end.
rows=$(mktemp)
trap 'rm -f "$PATCHED" "$rows"' EXIT

for label in "$@"; do
    src=$(label_source "$label")
    if print -r -- "$src" | grep -qE "$ARCH_RE"; then arches=($arch_axis); else arches=($arch_none); fi
    if print -r -- "$src" | grep -qE "$OS_RE";   then oses=($os_axis);    else oses=($os_none);    fi
    print -u2 -r -- "$label: arch×os = ${#arches}×${#oses}"

    for os_entry in $oses; do
        os_name=${os_entry%%:*}
        rest=${os_entry#*:}
        product=${rest%%:*}
        build=${rest##*:}
        for arch_entry in $arches; do
            arch_name=${arch_entry%%:*}
            archflag=${arch_entry##*:}
            print -u2 -r -- "  resolving $label [$os_name / $arch_name] ..."
            out=$(resolve "$archflag" "$product" "$build" "$label")
            du=$(print -r -- "$out" | field downloadURL)
            nv=$(print -r -- "$out" | field appNewVersion)
            jq -nc --arg label "$label" --arg os "$os_name" --arg arch "$arch_name" \
                --arg url "$du" --arg ver "$nv" \
                '{label:$label, os:$os, arch:$arch,
                  downloadURL:   ($url | if . == "" then null else . end),
                  appNewVersion: ($ver | if . == "" then null else . end)}' >> "$rows"
        done
    done
done

jq -s 'group_by(.label)
       | map({label: .[0].label, results: map(del(.label))})' "$rows"
