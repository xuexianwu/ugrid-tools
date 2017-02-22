import os
from utools_cli import convert

source_uid = 'GRIDCODE'
testbin = os.environ['UTOOLS_TEST_BIN']
testtmpdir = os.environ['TESTTMPDIR']

source = os.path.join(testbin, 'nhd_catchments_texas', 'nhd_catchments_texas.shp')
esmf_format = os.path.join(testtmpdir, 'test_esmf_format.nc')
convert(source_uid, source, esmf_format, None, None, None, 5000, False)
