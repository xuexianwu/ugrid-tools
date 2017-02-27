import os
from unittest import SkipTest

import numpy as np
from shapely import wkt
from shapely.geometry import shape

from utools.helpers import write_fiona
from utools.io.geom_manager import GeometryManager
from utools.io.helpers import get_split_polygon_by_node_threshold
from utools.io.mpi import MPI_RANK, MPI_COMM
from utools.prep.prep_shapefiles import convert_to_esmf_format
from utools.test import long_lines
from utools.test.base import AbstractUToolsTest, attr


class Test(AbstractUToolsTest):
    @property
    def path_in_shp(self):
        return os.path.join(self.path_bin, 'nhd_catchments_texas', 'nhd_catchments_texas.shp')

    @attr('mpi')
    def test_convert_to_esmf_format(self):
        # mpirun -n 2 nosetests -vs utools.test.test_utools.test_prep.test_prep_shapefiles:Test.test_convert_to_esmf_format

        name_uid = 'GRIDCODE'
        if MPI_RANK == 0:
            path_out_nc = self.get_temporary_file_path('out.nc')
        else:
            path_out_nc = None
        path_out_nc = MPI_COMM.bcast(path_out_nc)

        convert_to_esmf_format(path_out_nc, self.path_in_shp, name_uid)

        if MPI_RANK == 0:
            with self.nc_scope(path_out_nc) as ds:
                self.assertEqual(len(ds.variables), 6)
                self.assertEqual(len(ds.variables[name_uid]), len(GeometryManager(name_uid, path=self.path_in_shp)))
                # shutil.copy2(path_out_nc, '/tmp/my.nc')

    @attr('mpi')
    def test_convert_to_esmf_format_node_threshold(self):
        """Test conversion with a node threshold for the elements."""

        name_uid = 'GRIDCODE'
        if MPI_RANK == 0:
            path_out_nc = self.get_temporary_file_path('out.nc')
        else:
            path_out_nc = None
        path_out_nc = MPI_COMM.bcast(path_out_nc)

        convert_to_esmf_format(path_out_nc, self.path_in_shp, name_uid, node_threshold=80)

        if MPI_RANK == 0:
            with self.nc_scope(path_out_nc) as ds:
                self.assertGreater(ds.dimensions['nodeCount'], 16867)
                self.assertEqual(len(ds.variables), 6)
                # self.assertNcEqual(path_out_nc, '/home/benkoziol/htmp/template_esmf_format.nc')

        MPI_COMM.Barrier()

    def test_get_split_polygon_by_node_threshold(self):
        mp = long_lines.mp
        geom = wkt.loads(mp)
        desired_areas = [8.625085418953529e-08, 1.079968352698555e-06, 4.1784871773306116e-05, 2.5076269922661793e-05,
                         3.3855701685935655e-09, 2.8657206177145753e-06, 1.0972327342376188e-06, 8.786092310138479e-05,
                         0.00010110750647968422, 9.000945595248119e-05, 8.294314903503167e-05, 3.771759628159003e-05,
                         7.109809049616299e-05, 0.00010110750647961063, 0.0001011075064794719, 0.0001011075064794719,
                         0.00010068346095469527, 4.5613938714394565e-05, 2.58521435096663e-05, 0.00010055844609512709,
                         0.00010110750647961063, 0.0001011075064794719, 0.0001011075064794719, 0.00010110750647974937,
                         0.00010102553077737228, 3.5445725182157024e-05, 2.3017920373339736e-06, 6.356456832123063e-05,
                         0.00010110750647968422, 0.00010110750647954548, 0.00010110750647954548, 0.00010110750647982296,
                         0.00010110750647940675, 0.00010077363977375008, 1.3861408815707898e-05, 5.540594942042427e-06,
                         2.9946101143502452e-05, 8.322365017149943e-05, 0.0001011075064794719, 0.00010110750647974937,
                         0.00010110750647933316, 0.00010110750647961063, 9.141939119146819e-05, 1.8935129580488383e-05,
                         1.2868802415556094e-05, 6.997506385223853e-05, 0.00010110750647974937, 0.00010110750647933316,
                         0.00010110750647961063, 8.961198923834417e-05, 2.210381570757395e-05, 5.629701317779406e-05,
                         0.00010110750647982296, 0.00010110750647940675, 8.200102962203643e-05, 6.525027997827258e-06,
                         2.3998405756057673e-05, 9.951035052363768e-05, 5.635100120283968e-05, 2.6333871794810716e-05,
                         2.1377064578012194e-05]

        # write_fiona(geom, '01-original_geom')
        actual = get_split_polygon_by_node_threshold(geom, 10)
        # write_fiona(actual, '01-assembled')
        self.assertAlmostEqual(geom.area, actual.area)

        actual_areas = [g.area for g in actual]
        for idx in range(len(desired_areas)):
            self.assertAlmostEqual(actual_areas[idx], desired_areas[idx])

    def test_dev_get_split_polygon_by_node_threshold_many_nodes(self):
        raise SkipTest('development only')
        self.set_debug()

        shp_path = '/home/benkoziol/l/data/nfie/linked_catchment_shapefiles/linked_13-RioGrande.shp'

        with fiona.open(shp_path) as source:
            for record in source:
                if record['properties']['GRIDCODE'] == 2674572:
                    geom = shape(record['geometry'])

        # write_fiona(geom, '01-original_geom')
        actual = get_split_polygon_by_node_threshold(geom, 10000)
        # write_fiona(actual, '01-assembled')
        self.assertAlmostEqual(geom.area, actual.area)

        for p in actual:
            print len(p.exterior.coords)

        write_fiona(actual, 'assembled')

    def test_dev_get_split_shapefile(self):
        raise SkipTest('development only')
        self.set_debug()

        shp_path = '/home/benkoziol/l/data/nfie/linked_catchment_shapefiles/linked_13-RioGrande.shp'
        rd = RequestDataset(uri=shp_path)
        field = rd.get()
        self.log.debug('loading from file')
        field.geom.value
        node_count = map(get_node_count, field.geom.value)
        select = np.array(node_count) > 10000
        to_split = field['GRIDCODE'][select]
        for gc in to_split.value.flat:
            self.log.debug('target gridcode: {}'.format(gc))
            idx = np.where(field['GRIDCODE'].value == gc)[0][0]
            target_geom = field.geom.value[idx]
            split_geom = get_split_polygon_by_node_threshold(target_geom, 10000)
            # write_fiona(split_geom, gc)
            self.assertAlmostEqual(split_geom.area, target_geom.area)
            field.geom.value[idx] = split_geom
            self.assertAlmostEqual(field.geom.value[idx].area, target_geom.area)
        self.log.debug(field.geom.geom_type)
        # field.geom[select].parent.write('/tmp/rio-grande-assembled.shp', driver=DriverVector)

        # write_fiona(field.geom.value, 'rio-grande-assembled')
        self.log.debug('writing shapefile')
        field.write('/tmp/rio-grande-assembled.shp', driver=DriverVector)
