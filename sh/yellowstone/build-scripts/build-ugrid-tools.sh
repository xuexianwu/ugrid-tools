#!/usr/bin/env bash

[ -z "${UTOOLS_DIR}" ] && echo "Need to set UTOOLS_DIR (the base ugrid-tools directory)" && exit 1

# ----------------------------------------------------------------------------------------------------------------------

UTOOLS_ENV_SCRIPT=${UTOOLS_DIR}/sh/yellowstone/utools-env.sh

# ----------------------------------------------------------------------------------------------------------------------

source ${UTOOLS_ENV_SCRIPT}

cd ${UTOOLS_DIR}
rm -rf build
python setup.py build
