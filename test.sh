#!/usr/bin/env bash


export UTOOLS_LOGGING_LEVEL=error
export UTOOLS_TEST_ESMF_EXE=`which ESMF_RegridWeightGen`
export UTOOLS_TEST_MPIRUN_EXE=`which mpirun`


echo '+++ Serial tests +++'
nosetests -q -a '!mpi_only,!dev' src && \
echo '' && \

echo '+++ MPI tests ++++++' && \
mpirun -n 8 nosetests -q -a 'mpi' src && \

echo '+++ CLI tests ++++++' && \
TESTBIN=src/utools/test/bin
TESTTMPDIR=`mktemp -d`
SOURCE_FIELD=${TESTBIN}/precipitation_synthetic-20160310-1909.nc
SOURCE_SHP=${TESTBIN}/nhd_catchments_texas/nhd_catchments_texas.shp
SOURCE_SHP_UID=GRIDCODE
ESMF_FORMAT_FILE=${TESTTMPDIR}/test_esmf_format.nc
WEIGHTS=${TESTTMPDIR}/test_weights.nc
OUTPUT=${TESTTMPDIR}/test_weighted_output.nc
CLI='python src/utools_cli.py'

mpirun -n 8 ${CLI} convert -u ${SOURCE_SHP_UID} -s ${SOURCE_SHP} -e ${ESMF_FORMAT_FILE} && \
mpirun -n 8 ESMF_RegridWeightGen -s ${SOURCE_FIELD} -d ${ESMF_FORMAT_FILE} -w ${WEIGHTS} -m conserve \
    --src_type GRIDSPEC --dst_type ESMF --src_regional && \
mpirun -n 8 ${CLI} apply -s ${SOURCE_FIELD} -n pr -w ${WEIGHTS} -e ${ESMF_FORMAT_FILE} -o ${OUTPUT} && \

echo 'CLI tests complete. No errors.' && \
exit 0
