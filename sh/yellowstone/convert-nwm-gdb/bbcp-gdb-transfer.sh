#!/usr/bin/env bash


BBCP_EXE=/home/benkoziol/sandbox/bbcp/bbcp
USERNAME=benkoz
TARGET=/glade/u/home/benkoz/storage
FILENAME="/home/benkoziol/l/data/nfie/NHDPlusV21_NationalData_National_Seamless_Geodatabase_02.7z"

${BBCP_EXE} -w 4m -s 16 -V -D ${FILENAME} ${USERNAME}@data-access1.ucar.edu:${TARGET}
