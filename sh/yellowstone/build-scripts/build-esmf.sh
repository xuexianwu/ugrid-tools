#!/bin/bash

export OUTDIR=/glade/u/home/benkoz/logs/esmf-build
#export SRCDIR_NAME=esmf
#export BUILDDIR=`mktemp -d`
export CPU_COUNT=1
export SHOULD_GIT_CLONE="false"
export SHOULD_GIT_PULL="false"

export PREFIX=/glade/u/home/benkoz/sandbox/esmf-debug
#export PREFIX=/glade/u/home/benkoz/sandbox/esmf
#export ESMF_DIR=${BUILDDIR}/${SRCDIR_NAME}
export ESMF_DIR=~/src/esmf
#export SRCDIR=~/src/${SRCDIR_NAME}
export ESMF_COMPILER=intel
export ESMF_F90COMPILEOPTS="-g"
export ESMF_CXXCOMPILEOPTS="-g"

#-----------------------------------------------------------------------------------------------------------------------

if [ ${SHOULD_GIT_CLONE} == "true" ]; then
    cd ~/src && \
     git clone git://git.code.sf.net/p/esmf/esmf
fi

if [ ${SHOULD_GIT_PULL} == "true" ]; then
    ( cd ~/src/esmf && git pull )
fi

#cp -r ${SRCDIR} ${BUILDDIR}
cd ${ESMF_DIR}

rm -rf ${PREFIX}

module reset
#module swap intel gnu

export ESMF_INSTALL_PREFIX=${PREFIX}
export ESMF_INSTALL_BINDIR=${PREFIX}/bin
export ESMF_INSTALL_DOCDIR=${PREFIX}/doc
export ESMF_INSTALL_HEADERDIR=${PREFIX}/include
export ESMF_INSTALL_LIBDIR=${PREFIX}/lib
export ESMF_INSTALL_MODDIR=${PREFIX}/mod
export ESMF_NETCDF="split"
export ESMF_COMM=mpich2
#export ESMF_NETCDF_INCLUDE=${PREFIX}/include
#export ESMF_NETCDF_LIBPATH=${PREFIX}/lib

#make clean && \
make distclean 2>&1 | tee "${OUTDIR}/esmf.make.distclean.`date`.out" && \
 make info 2>&1 | tee "${OUTDIR}/esmf.make.info.`date`.out" && \
 make -j ${CPU_COUNT} 2>&1 | tee "${OUTDIR}/esmf.make.`date`.out" && \
# make check
# make all_tests | tee ~/esmf_all_tests.out
 make install 2>&1 | tee "${OUTDIR}/esmf.make.install.`date`.out"

#rm -rf ${BUILDDIR}

#module swap intel gnu
#module load python numpy mpi4py
#cd ${ESMF_DIR}
#export WD=`pwd -LP`
#export ESMFMKFILE=`find ${WD} -name '*esmf.mk'`
#cd ${ESMF_DIR}/src/addon/ESMPy
#python setup.py build --ESMFMKFILE=${ESMFMKFILE}
#python setup.py install
