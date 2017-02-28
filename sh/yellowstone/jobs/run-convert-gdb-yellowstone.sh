#!/usr/bin/env bash


#BSUB -B
#BSUB -n 64
#BSUB -W 00:30
#BSUB -q "regular"
#BSUB -R "span[ptile=16]"
#BSUB -J convert-seamless-split-interiors
#BSUB -o "utools.%J.out"
#BSUB -e "utools.%J.out"
#BSUB -P P35071400

[ -z "${UTOOLS_DIR}" ] && ( >&2 echo "Need to set UTOOLS_DIR (the base ugrid-tools directory)" ) && exit 1
source ${UTOOLS_DIR}/sh/yellowstone/utools-env.sh

STORAGE=/glade/u/home/benkoz/storage
UTOOLS_CFG_PATH=${STORAGE}/utools.cfg
UTOOLS_DEBUG='--no-debug'
UTOOLS_FEATURE_CLASS=Catchment
UTOOLS_GDB_PATH=${STORAGE}/NHDPlusNationalData/NHDPlusV21_National_Seamless.gdb
UTOOLS_DEST_CRS_INDEX="National_Water_Model,crs_wkt"
export UTOOLS_LOGGING_ENABLED="true"
export UTOOLS_LOGGING_MODE="w"
export UTOOLS_LOGGING_TOFILE="true"
UTOOLS_OUTPUT_FILE=${STORAGE}/esmf_unstructured/ESMF_Unstructured_Cartesian_NHDPlusV21_National_Seamless_20160228_0857.nc
UTOOLS_SRC_UID="GRIDCODE"
UTOOLS_CLI=utools_cli

#export UTOOLS_LOGGING_DIR=~/htmp
#export UTOOLS_LOGGING_LEVEL=DEBUG
#export UTOOLS_LOGGING_STDOUT="true"

#-----------------------------------------------------------------------------------------------------------------------

mpirun.lsf python ${UTOOLS_CLI} convert -u ${UTOOLS_SRC_UID} -s ${UTOOLS_GDB_PATH} \
    -e ${UTOOLS_OUTPUT_FILE} --feature-class ${UTOOLS_FEATURE_CLASS} --config-path ${UTOOLS_CFG_PATH} \
    --dest_crs_index=${UTOOLS_DEST_CRS_INDEX} ${UTOOLS_DEBUG}
