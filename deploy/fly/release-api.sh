#!/bin/sh
set -eu

npm run markets:ensure-state-schema --workspace @alphadb/api
npm run polymarket:discovery-migrate --workspace @alphadb/api
