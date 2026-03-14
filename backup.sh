#!/bin/sh
#
# backup sqlite files every N seconds
#
while :; do
  cp -av db.sqlit* bak/
  sleep 900
done
