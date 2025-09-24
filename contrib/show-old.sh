#!/bin/bash

# list dirs with old *.metadata files (older than $1 days)

declare tmp

clean() {
    [[ $tmp && -f $tmp ]] && rm -f "$tmp"
}

main() {
    local days=${1:-5}
    echo "searching old ($days days) projects ..."

    # tmp = today - X days
    tmp=$(mktemp XXXXXX.tmp) || return 1
    tmp=$(readlink -f "$tmp")
    trap 'clean' RETURN
    touch "$tmp" -d "today - $days days" || return 1

    local f1 d1
    local -A skip ok
    while IFS= read -r f1; do # old *.metadata
        d1=${f1%/*}
        [[ ${skip[$d1]} || ${ok[$d1]} ]] && continue
        if [[ $(find "$d1" -maxdepth 1 -type f -name '*.metadata' -newer "$tmp" -print -quit) ]]; then
            # found new *.metadata
            skip[$d1]=1
            continue
        fi
        # report old only once
        echo "$d1"
        ok[$d1]=1
    done < <(find -mindepth 2 -maxdepth 2 -type f -name '*.metadata' ! -newer "$tmp")
}

main "$@"
