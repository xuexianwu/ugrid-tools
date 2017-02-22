#!/usr/bin/env bash

[ -z "${UTOOLS_DIR}" ] && ( >&2 echo "Need to set UTOOLS_DIR (the base ugrid-tools directory)" ) && exit 1

module reset

# GDAL loads its own internal NetCDF.
module unload netcdf

module load python/2.7.7
module load gdal/2.0.3
module load shapely/1.5.16
module load numpy/1.11.0
module load netcdf4python/1.2.4
module load cython/0.23.4
module load mpi4py/2.0.0
module load logbook
module load fiona/1.7.0.p2

export PYTHONPATH=${UTOOLS_DIR}/build/lib:${PYTHONPATH}
export PATH=${UTOOLS_DIR}/build/scripts-2.7:${PATH}
