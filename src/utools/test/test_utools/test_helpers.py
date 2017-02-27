import fiona
from shapely.geometry import Polygon
from shapely.geometry import box
from shapely.geometry import mapping
from shapely.geometry.multipolygon import MultiPolygon

from utools.exc import NoInteriorsError
from utools.helpers import GeometrySplitter
from utools.test.base import AbstractUToolsTest


class TestGeometrySplitter(AbstractUToolsTest):
    def test_init(self):
        ge = GeometrySplitter(self.polygon_with_hole)
        self.assertIsInstance(ge.geometry, Polygon)

        # Test a geometry with no holes.
        with self.assertRaises(NoInteriorsError):
            GeometrySplitter(box(1, 2, 3, 4))

    def test_create_split_vector_dict(self):
        ge = GeometrySplitter(self.polygon_with_hole)
        desired = [{'rows': (9.999999, 13.0, 20.000001), 'cols': (1.999999, 3.0, 4.000001)}]
        actual = list([ge.create_split_vector_dict(i) for i in ge.iter_interiors()])
        self.assertEqual(actual, desired)

    def test_create_split_polygons(self):
        ge = GeometrySplitter(self.polygon_with_hole)
        spolygons = ge.create_split_polygons(list(ge.iter_interiors())[0])
        self.assertEqual(len(spolygons), 4)

        actual = [sp.bounds for sp in spolygons]
        desired = [(1.999999, 9.999999, 3.0, 13.0), (3.0, 9.999999, 4.000001, 13.0),
                   (3.0, 13.0, 4.000001, 20.000001), (1.999999, 13.0, 3.0, 20.000001)]
        self.assertEqual(actual, desired)

    def test_split(self):
        to_test = [self.polygon_with_hole, MultiPolygon([self.polygon_with_hole, box(200, 100, 300, 400)])]
        desired_counts = {0: 4, 1: 5}

        for ctr, t in enumerate(to_test):
            ge = GeometrySplitter(t)
            split = ge.split()

            self.assertEqual(len(split), desired_counts[ctr])
            self.assertEqual(split.area, t.area)

            actual_bounds = [g.bounds for g in split]
            actual_areas = [g.area for g in split]

            desired_bounds = [(2.0, 10.0, 3.0, 13.0), (3.0, 10.0, 4.0, 13.0),
                              (3.0, 13.0, 4.0, 20.0), (2.0, 13.0, 3.0, 20.0)]
            desired_areas = [1.75, 1.75, 5.75, 5.75]

            if ctr == 1:
                desired_bounds.append((200.0, 100.0, 300.0, 400.0))
                desired_areas.append(30000.0)

            self.assertEqual(actual_bounds, desired_bounds)
            self.assertEqual(actual_areas, desired_areas)

            # path = self.get_temporary_file_path('splits.shp')
            # with fiona.open(path,
            #                 schema={'geometry': 'Polygon', 'properties': {}},
            #                 driver='ESRI Shapefile',
            #                 mode='w') as sink:
            #     for p in spolygons:
            #         sink.write({'geometry': mapping(p), 'properties': {}})
            #
            #     path = self.get_temporary_file_path('polygon.shp')
            #     with fiona.open(path,
            #                     schema={'geometry': 'Polygon', 'properties': {}},
            #                     driver='ESRI Shapefile',
            #                     mode='w') as sink:
            #         sink.write({'geometry': mapping(self.polygon_with_hole), 'properties': {}})
            #
            #     path = self.get_temporary_file_path('split.shp')
            #     with fiona.open(path,
            #                     schema={'geometry': 'Polygon', 'properties': {}},
            #                     driver='ESRI Shapefile',
            #                     mode='w') as sink:
            #         sink.write({'geometry': mapping(split), 'properties': {}})
            # import pdb;pdb.set_trace()

    def test_iter_interiors(self):
        ge = GeometrySplitter(self.polygon_with_hole)
        actual = list([g.bounds for g in ge.iter_interiors()])
        self.assertEqual(actual, [(2.5, 10.5, 3.5, 15.5)])
