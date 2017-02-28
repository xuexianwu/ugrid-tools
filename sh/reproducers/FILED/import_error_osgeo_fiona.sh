#!/usr/bin/env bash


#BSUB -W 00:01
#BSUB -n 8
#BSUB -J import_fault_osgeo_fiona
#BSUB -o ifof.test.%J.out
#BSUB -e ifof.test.%J.err
#BSUB -q geyser

module reset

module swap intel gnu

module load python/2.7.7
module load gdal/2.0.3
module load shapely/1.5.16
module load numpy/1.11.0
module load netcdf4python/1.2.4
module load cython/0.23.4
module load mpi4py/2.0.0
module load fiona/1.7.0.p2
module load logbook


mpirun.lsf python /glade/u/home/benkoz/src/ugrid-tools/sh/reproducers/import_error_osgeo_fiona.py

