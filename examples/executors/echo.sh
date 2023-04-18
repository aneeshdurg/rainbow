#!/bin/bash
while read line; do
  if [ "$line" == "--" ]; then
    echo "null"
  else
    echo "ECHO:" "$line" >&2
  fi
done
