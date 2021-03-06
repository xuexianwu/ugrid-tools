import itertools
from collections import deque, OrderedDict

import netCDF4 as nc
import numpy as np
from numpy.ma import MaskedArray
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.geometry.base import BaseMultipartGeometry
from shapely.geometry.polygon import orient

from mpi import MPI_RANK, create_sections, MPI_COMM, MPI_SIZE, dgather
from utools.addict import Dict
from utools.constants import UgridToolsConstants
from utools.logging import log


def convert_multipart_to_singlepart(path_in, path_out, new_uid_name=UgridToolsConstants.LINK_ATTRIBUTE_NAME, start=0):
    """
    Convert a vector GIS file from multipart to singlepart geometries. The function copies all attributes and
    maintains the coordinate system.

    :param str path_in: Path to the input file containing multipart geometries.
    :param str path_out: Path to the output file.
    :param str new_uid_name: Use this name as the default for the new unique identifier.
    :param int start: Start value for the new unique identifier.
    """
    import fiona

    with fiona.open(path_in) as source:
        len_source = len(source)
        source.meta['schema']['properties'][new_uid_name] = 'int'
        with fiona.open(path_out, mode='w', **source.meta) as sink:
            for ctr, record in enumerate(source, start=1):
                geom = shape(record['geometry'])
                if isinstance(geom, BaseMultipartGeometry):
                    for element in geom:
                        record['properties'][new_uid_name] = start
                        record['geometry'] = mapping(element)
                        sink.write(record)
                        start += 1
                else:
                    record['properties'][new_uid_name] = start
                    sink.write(record)
                    start += 1


def get_coordinates_list_and_update_n_coords(record, n_coords):
    geom = record['geom']
    if isinstance(geom, MultiPolygon):
        itr = iter(geom)
    else:
        itr = [geom]
    coordinates_list = []
    for element in itr:
        # Counter-clockwise orientations required by clients such as ESMF Mesh regridding.
        exterior = element.exterior
        if not exterior.is_ccw:
            coords = list(exterior.coords)[::-1]
        else:
            coords = list(exterior.coords)
        current_coordinates = np.array(coords)
        # Assert last coordinate is repeated for each polygon.
        assert current_coordinates[0].tolist() == current_coordinates[-1].tolist()
        # Remove this repeated coordinate.
        current_coordinates = current_coordinates[0:-1, :]
        coordinates_list.append(current_coordinates)
        n_coords += current_coordinates.shape[0]

    return coordinates_list, n_coords


def get_coordinate_dict_variables(cdict, n_coords, polygon_break_value=None, idx_start=0):
    """
    :param dict cdict: Dictionary mapping unique element identifiers to a sequence containing unique element coordinates
     as a sequence. Keys are unique integer element identifiers. Values are lists composed of array-like objects. The
     value lists may contain more than one array, indicating they are multi-polygon geometries.
    :param int n_coords: Total coordinate count across all coordinate sequences.
    :param int polygon_break_value: Negative integer value to use for breaks between multi-geometries.
    :param int idx_start: Start index to use for computing node mappings. Useful in parallel when maintaining global
     mappings.
    :return: A tuple of coordinate dictionary derived variables.

        0 --> Node index mapping to coordinate array.
        1 --> Coordinates array.
        2 --> Edge node index mapping to coordinate array.
    :rtype: tuple (array-like, array-like, array-like)

    >>> cdict = {5: [np.array([[1., 2], [3., 4.]]), np.array([[1., 2], [3., 4.], [5., 6.]])]}
    >>> n_coords = 5
    >>> polygon_break_value = -8

    """
    polygon_break_value = polygon_break_value or UgridToolsConstants.POLYGON_BREAK_VALUE
    dtype_int = np.int32
    face_nodes = np.zeros(len(cdict), dtype=object)

    global_idx_start = idx_start
    for idx_face_nodes, coordinates_list in enumerate(cdict.itervalues()):
        if idx_face_nodes == 0:
            coordinates = np.zeros((n_coords, 2), dtype=coordinates_list[0].dtype)
            edge_nodes = np.zeros_like(coordinates, dtype=dtype_int)

        for ctr, coordinates_element in enumerate(coordinates_list):
            shape_coordinates_row = coordinates_element.shape[0]
            idx_stop = idx_start + shape_coordinates_row
            new_face_nodes = np.arange(idx_start, idx_stop, dtype=dtype_int)
            # log.debug(('new_face_nodes=', new_face_nodes.tolist()))
            edge_nodes[idx_start - global_idx_start: idx_stop - global_idx_start, :] = get_edge_nodes(new_face_nodes)
            if ctr == 0:
                face_nodes_element = new_face_nodes
            else:
                face_nodes_element = np.hstack((face_nodes_element, polygon_break_value))
                face_nodes_element = np.hstack((face_nodes_element, new_face_nodes))
            coordinates[idx_start - global_idx_start:idx_stop - global_idx_start, :] = coordinates_element
            idx_start += shape_coordinates_row
        face_nodes[idx_face_nodes] = face_nodes_element.astype(dtype_int)

    return face_nodes, coordinates, edge_nodes


def get_edge_nodes(face_nodes):
    first = face_nodes.reshape(-1, 1)
    second = first + 1
    edge_nodes = np.hstack((first, second))
    edge_nodes[-1, 1] = edge_nodes[0, 0]
    return edge_nodes


def get_variables(gm, use_ragged_arrays=False, with_connectivity=True):
    """
    :param gm: The geometry manager containing geometries to convert to mesh variables.
    :type gm: :class:`pyugrid.flexible_mesh.helpers.GeometryManager`
    :param pack: If ``True``, de-deduplicate shared coordinates.
    :type pack: bool
    :returns: A tuple of arrays with index locations corresponding to:

    ===== ================ =============================
    Index Name             Type
    ===== ================ =============================
    0     face_nodes       :class:`numpy.ma.MaskedArray`
    1     face_edges       :class:`numpy.ma.MaskedArray`
    2     edge_nodes       :class:`numpy.ndarray`
    3     node_x           :class:`numpy.ndarray`
    4     node_y           :class:`numpy.ndarray`
    5     face_links       :class:`numpy.ndarray`
    6     face_ids         :class:`numpy.ndarray`
    7     face_coordinates :class:`numpy.ndarray`
    ===== ================ =============================

    Information on individual variables may be found here: https://github.com/ugrid-conventions/ugrid-conventions/blob/9b6540405b940f0a9299af9dfb5e7c04b5074bf7/ugrid-conventions.md#2d-flexible-mesh-mixed-triangles-quadrilaterals-etc-topology

    :rtype: tuple (see table for array types)
    :raises: ValueError
    """
    # tdk: update doc
    if len(gm) < MPI_SIZE:
        raise ValueError('The number of geometries must be greater than or equal to the number of processes.')

    pbv = UgridToolsConstants.POLYGON_BREAK_VALUE

    result = get_face_variables(gm, with_connectivity=with_connectivity)
    face_links, nmax_face_nodes, face_ids, face_coordinates, cdict, n_coords, face_areas, section = result

    # Find the start index for each rank.
    all_n_coords = MPI_COMM.gather(n_coords)
    if MPI_RANK == 0:
        all_idx_start = [0] * MPI_SIZE
        for idx in range(len(all_n_coords)):
            if idx == 0:
                continue
            else:
                all_idx_start[idx] = all_n_coords[idx - 1] + all_idx_start[idx - 1]
    else:
        all_idx_start = None
    idx_start = MPI_COMM.scatter(all_idx_start)
    log.debug(('idx_start', idx_start))

    face_nodes, coordinates, edge_nodes = get_coordinate_dict_variables(cdict, n_coords, polygon_break_value=pbv,
                                                                        idx_start=idx_start)
    face_edges = face_nodes
    face_ids = np.array(cdict.keys(), dtype=np.int32)

    if not use_ragged_arrays:
        new_arrays = []
        for a in (face_links, face_nodes, face_edges):
            new_arrays.append(get_rectangular_array_from_object_array(a, (a.shape[0], nmax_face_nodes)))
        face_links, face_nodes, face_edges = new_arrays

    return face_nodes, face_edges, edge_nodes, coordinates, face_links, face_ids, face_coordinates, face_areas, section


def get_rectangular_array_from_object_array(target, shape):
    new_face_links = np.ma.array(np.zeros(shape, dtype=target[0].dtype), mask=True)
    for idx, f in enumerate(target):
        new_face_links[idx, 0:f.shape[0]] = f
    face_links = new_face_links
    assert (face_links.ndim == 2)
    return face_links


def iter_touching(si, gm, shapely_object):
    select_uid = list(si.iter_rtree_intersection(shapely_object))
    select_uid.sort()
    for uid_target, record_target in gm.iter_records(return_uid=True, select_uid=select_uid):
        if shapely_object.touches(record_target['geom']):
            yield uid_target


def get_face_variables(gm, with_connectivity=False):
    if with_connectivity and MPI_SIZE > 1:
        raise ValueError('Connectivity not enabled for parallel conversion.')

    n_face = len(gm)

    if MPI_RANK == 0:
        sections = create_sections(n_face)
    else:
        sections = None

    section = MPI_COMM.scatter(sections, root=0)

    # Create a spatial index to find touching faces.
    if with_connectivity:
        si = gm.get_spatial_index()

    face_ids = np.zeros(section[1] - section[0], dtype=np.int32)
    assert face_ids.shape[0] > 0

    face_links = {}
    max_face_nodes = 0
    face_coordinates = deque()
    face_areas = deque()

    cdict = OrderedDict()
    n_coords = 0

    for ctr, (uid_source, record_source) in enumerate(gm.iter_records(return_uid=True, slc=section)):
        coordinates_list, n_coords = get_coordinates_list_and_update_n_coords(record_source, n_coords)
        cdict[uid_source] = coordinates_list

        face_ids[ctr] = uid_source
        ref_object = record_source['geom']

        # Get representative points for each polygon.
        face_coordinates.append(np.array(ref_object.representative_point()))
        face_areas.append(ref_object.area)

        # For polygon geometries the first coordinate is repeated at the end of the sequence. UGRID clients do not want
        # repeated coordinates (i.e. ESMF).
        try:
            ncoords = len(ref_object.exterior.coords) - 1
        except AttributeError:
            # Likely a multipolygon...
            ncoords = sum([len(e.exterior.coords) - 1 for e in ref_object])
            # A -1 flag will be placed between elements.
            ncoords += (len(ref_object) - 1)
        if ncoords > max_face_nodes:
            max_face_nodes = ncoords

        if with_connectivity:
            touching = deque()
            for uid_target in iter_touching(si, gm, ref_object):
                # If the objects only touch they are neighbors and may share nodes.
                touching.append(uid_target)
            # If nothing touches the faces, indicate this with a flag value.
            if len(touching) == 0:
                touching.append(-1)
            face_links[uid_source] = touching

    # face_ids = MPI_COMM.gather(face_ids, root=0)
    # max_face_nodes = MPI_COMM.gather(max_face_nodes, root=0)
    # face_links = MPI_COMM.gather(face_links, root=0)
    # face_coordinates = MPI_COMM.gather(np.array(face_coordinates), root=0)
    # cdict = MPI_COMM.gather(cdict, root=0)
    # n_coords = MPI_COMM.gather(n_coords, root=0)
    # face_areas = MPI_COMM.gather(np.array(face_areas), root=0)

    # if MPI_RANK == 0:
    #     face_ids = hgather(face_ids)
    #     face_coordinates = vgather(face_coordinates)
    #     cdict = dgather(cdict)
    #     n_coords = sum(n_coords)
    #     face_areas = hgather(face_areas)
    #
    #     max_face_nodes = max(max_face_nodes)

    if with_connectivity:
        face_links = get_mapped_face_links(face_ids, face_links)
    else:
        face_links = None

    face_coordinates = np.array(face_coordinates)
    face_areas = np.array(face_areas)
    return face_links, max_face_nodes, face_ids, face_coordinates, cdict, n_coords, face_areas, section


def get_mapped_face_links(face_ids, face_links):
    """
    :param face_ids: Vector of unique, integer face identifiers.
    :type face_ids: :class:`numpy.ndarray`
    :param face_links: List of dictionaries mapping face unique identifiers to neighbor face unique identifiers.
    :type face_links: list
    :returns: A numpy object array with slots containing numpy integer vectors with values equal to neighbor indices.
    :rtype: :class:`numpy.ndarray`
    """

    face_links = dgather(face_links)
    new_face_links = np.zeros(len(face_links), dtype=object)
    for idx, e in enumerate(face_ids.flat):
        to_fill = np.zeros(len(face_links[e]), dtype=np.int32)
        for idx_f, f in enumerate(face_links[e]):
            # This flag indicates nothing touches the faces. Do not search for this value in the face identifiers.
            if f == -1:
                to_fill_value = f
            # Search for the index location of the face identifier.
            else:
                to_fill_value = np.where(face_ids == f)[0][0]
            to_fill[idx_f] = to_fill_value
        new_face_links[idx] = to_fill
    return new_face_links


def flexible_mesh_to_fiona(out_path, face_nodes, node_x, node_y, crs=None, driver='ESRI Shapefile',
                           indices_to_load=None, face_uid=None):
    import fiona

    if face_uid is None:
        properties = {}
    else:
        properties = {face_uid.name: 'int'}

    schema = {'geometry': 'Polygon', 'properties': properties}
    with fiona.open(out_path, 'w', driver=driver, crs=crs, schema=schema) as f:
        for feature in iter_records(face_nodes, node_x, node_y, indices_to_load=indices_to_load, datasets=[face_uid],
                                    polygon_break_value=UgridToolsConstants.POLYGON_BREAK_VALUE):
            feature['properties'][face_uid.name] = int(feature['properties'][face_uid.name])
            f.write(feature)
    return out_path


def iter_records(face_nodes, node_x, node_y, indices_to_load=None, datasets=None, shapely_only=False,
                 polygon_break_value=None):
    if indices_to_load is None:
        feature_indices = range(face_nodes.shape[0])
    else:
        feature_indices = indices_to_load

    for feature_idx in feature_indices:
        try:
            current_face_node = face_nodes[feature_idx, :]
        except IndexError:
            # Likely an object array.
            assert face_nodes.dtype == object
            current_face_node = face_nodes[feature_idx]

        try:
            nodes = current_face_node.compressed()
        except AttributeError:
            # Likely not a masked array.
            nodes = current_face_node.flatten()

        # Construct the geometry object by collecting node coordinates using indices stored in "nodes".
        if polygon_break_value is not None and polygon_break_value in nodes:
            itr = get_split_array(nodes, polygon_break_value)
            has_multipart = True
        else:
            itr = [nodes]
            has_multipart = False
        polygons = []
        for sub in itr:
            coordinates = [(node_x[ni], node_y[ni]) for ni in sub.flat]
            polygons.append(Polygon(coordinates))
        if has_multipart:
            polygon = MultiPolygon(polygons)
        else:
            polygon = polygons[0]

        # Collect properties if datasets are passed.
        properties = OrderedDict()
        if datasets is not None:
            for ds in datasets:
                properties[ds.name] = ds.data[feature_idx]
        feature = {'id': feature_idx, 'properties': properties}

        # Add coordinates or shapely objects depending on parameters.
        if shapely_only:
            feature['geom'] = polygon
        else:
            feature['geometry'] = mapping(polygon)

        yield feature


def create_rtree_file(gm, path):
    """
    :param gm: Target geometries to index.
    :type gm: :class:`pyugrid.flexible_mesh.helpers.GeometryManager`
    :param path: Output path for the serialized spatial index. See http://toblerity.org/rtree/tutorial.html#serializing-your-index-to-a-file.
    """
    from spatial_index import SpatialIndex

    si = SpatialIndex(path=path)
    for uid, record in gm.iter_records(return_uid=True):
        si.add(uid, record['geom'])


def get_split_array(arr, break_value):
    """
    :param arr: One-dimensional array.
    :type arr: :class:`numpy.ndarray`
    :type break_value: int
    :return_type: sequence of :class:`numpy.ndarray`
    """

    where = np.where(arr == break_value)
    split = np.array_split(arr, where[0])
    ret = [None] * len(split)
    ret[0] = split[0]
    for idx in range(1, len(ret)):
        ret[idx] = split[idx][1:]
    return ret


def get_oriented_and_valid_geometry(geom):
    try:
        assert geom.is_valid
    except AssertionError:
        geom = geom.buffer(0)
        assert geom.is_valid

    if not geom.exterior.is_ccw:
        geom = orient(geom)

    return geom


def convert_collection_to_esmf_format(fmobj, filename, polygon_break_value=None, start_index=0, face_uid_name=None,
                                      dataset_kwargs=None):
    """
    Convert to an ESMF format NetCDF files. Only supports ragged arrays.

    :param fm: Flexible mesh object to convert.
    :type fm: :class:`pyugrid.flexible_mesh.core.FlexibleMesh`
    :param ds: An open netCDF4 dataset object.
    :type ds: :class:`netCDF4.Dataset`
    """

    dataset_kwargs = dataset_kwargs or {}

    # tdk: doc
    # face_areas = fmobj.face_areas
    # face_coordinates = fmobj.face_coordinates
    # if face_uid_name is None:
    #     face_uid_value = None
    # else:
    #     face_uid_value = fmobj.data[face_uid_name].data
    # faces = fmobj.faces
    # nodes = fmobj.nodes

    face_areas = fmobj['face_areas']
    face_coordinates = fmobj['face_coordinates']
    if face_uid_name is not None:
        face_uid_value = fmobj[face_uid_name]
    else:
        face_uid_value = None
    faces = fmobj['face']
    nodes = fmobj['nodes']

    # float_dtype = np.float32
    # int_dtype = np.int32

    # Transform ragged array to one-dimensional array.
    num_element_conn_data = [e.shape[0] for e in faces.flat]
    length_connection_count = sum(num_element_conn_data)
    element_conn_data = np.zeros(length_connection_count, dtype=faces[0].dtype)
    start = 0
    for ii in faces.flat:
        element_conn_data[start: start + ii.shape[0]] = ii
        start += ii.shape[0]

    ####################################################################################################################

    # from ocgis.new_interface.variable import Variable, VariableCollection
    # coll = VariableCollection()
    #
    # coll.add_variable(Variable('nodeCoords', value=nodes, dtype=float_dtype,
    #                            dimensions=['nodeCount', 'coordDim'], units='degrees'))
    #
    # elementConn = Variable('elementConn', value=element_conn_data, dimensions='connectionCount',
    #                        attrs={'long_name': 'Node indices that define the element connectivity.',
    #                               'start_index': start_index})
    # if polygon_break_value is not None:
    #     elementConn.attrs['polygon_break_value'] = polygon_break_value
    # coll.add_variable(elementConn)
    #
    # coll.add_variable(Variable('numElementConn', value=num_element_conn_data, dimensions='elementCount',
    #                            dtype=int_dtype, attrs={'long_name': 'Number of nodes per element.'}))
    #
    # coll.add_variable(Variable('centerCoords', value=face_coordinates, dimensions=['elementCount', 'coordDim'],
    #                            units='degrees', dtype=float_dtype))
    #
    # if face_uid_name is not None:
    #     coll.add_variable(Variable(face_uid_name, value=face_uid_value, dimensions='elementCount',
    #                                attrs={'long_name': 'Element unique identifier.'}))
    #
    # coll.add_variable(Variable('elementArea', value=face_areas, dimensions='elementCount',
    #                            attrs={'units': 'degrees', 'long_name': 'Element area in native units.'},
    #                            dtype=float_dtype))
    #
    # coll.attrs['gridType'] = 'unstructured'
    # coll.attrs['version'] = '0.9'
    # coll.attrs['coordDim'] = 'longitude latitude'
    #
    # coll.write(ds)

    node_counts = MPI_COMM.gather(nodes.shape[0])
    element_counts = MPI_COMM.gather(faces.shape[0])
    length_connection_counts = MPI_COMM.gather(length_connection_count)

    if MPI_RANK == 0:
        ds = nc.Dataset(filename, 'w', **dataset_kwargs)
        try:
            # Dimensions -----------------------------------------------------------------------------------------------

            node_count_size = sum(node_counts)
            element_count_size = sum(element_counts)
            connection_count_size = sum(length_connection_counts)

            node_count = ds.createDimension('nodeCount', node_count_size)
            element_count = ds.createDimension('elementCount', element_count_size)
            coord_dim = ds.createDimension('coordDim', 2)
            # element_conn_vltype = ds.createVLType(fm.faces[0].dtype, 'elementConnVLType')
            connection_count = ds.createDimension('connectionCount', connection_count_size)

            # Variables ------------------------------------------------------------------------------------------------

            node_coords = ds.createVariable('nodeCoords', nodes.dtype, (node_count.name, coord_dim.name))
            node_coords.units = 'degrees'

            element_conn = ds.createVariable('elementConn', element_conn_data.dtype, (connection_count.name,))
            element_conn.long_name = 'Node indices that define the element connectivity.'
            if polygon_break_value is not None:
                element_conn.polygon_break_value = polygon_break_value
            element_conn.start_index = start_index

            num_element_conn = ds.createVariable('numElementConn', np.int32, (element_count.name,))
            num_element_conn.long_name = 'Number of nodes per element.'

            center_coords = ds.createVariable('centerCoords', face_coordinates.dtype, (element_count.name,
                                                                                       coord_dim.name))
            center_coords.units = 'degrees'

            if face_uid_value is not None:
                uid = ds.createVariable(face_uid_name, face_uid_value.dtype, dimensions=(element_count.name,))
                uid.long_name = 'Element unique identifier.'

            element_area = ds.createVariable('elementArea', nodes.dtype, (element_count.name,))
            element_area.units = 'degrees'
            element_area.long_name = 'Element area in native units.'

            # Global Attributes ----------------------------------------------------------------------------------------

            ds.gridType = 'unstructured'
            ds.version = '0.9'
            setattr(ds, coord_dim.name, "longitude latitude")

            # element_mask = ds.createVariable('elementMask', np.int32, (element_count.name,))

        finally:
            ds.close()

    # Fill variable values -----------------------------------------------------------------------------------------

    node_coords_start = 0
    node_coords_stop = None
    element_conn_start = 0
    element_conn_stop = None

    for rank_to_write in range(MPI_SIZE):
        log.debug(('node_coords_start', node_coords_start))
        if MPI_RANK == rank_to_write:
            ds = nc.Dataset(filename, mode='a')
            try:
                node_coords = ds.variables['nodeCoords']
                element_conn = ds.variables['elementConn']
                num_element_conn = ds.variables['numElementConn']
                center_coords = ds.variables['centerCoords']
                element_area = ds.variables['elementArea']
                if face_uid_value is not None:
                    uid = ds.variables[face_uid_name]

                node_coords_stop = node_coords_start + nodes.shape[0]
                element_conn_stop = element_conn_start + element_conn_data.shape[0]
                node_coords[node_coords_start:node_coords_stop] = nodes
                log.debug(('element_conn indices', element_conn_start, element_conn_stop))
                element_conn[element_conn_start:element_conn_stop] = element_conn_data

                start, stop = fmobj['section']
                num_element_conn[start:stop] = num_element_conn_data
                center_coords[start:stop] = face_coordinates
                element_area[start:stop] = face_areas
                if face_uid_value is not None:
                    uid[start:stop] = face_uid_value
            finally:
                ds.close()
        node_coords_start = MPI_COMM.bcast(node_coords_stop, root=rank_to_write)
        element_conn_start = MPI_COMM.bcast(element_conn_stop, root=rank_to_write)
        MPI_COMM.Barrier()


def get_split_polygon_by_node_threshold(geom, node_threshold):
    # tdk: doc
    node_schema = get_node_schema(geom)

    # Collect geometries with node counts higher than the threshold.
    to_split = []
    for k, v in node_schema.items():
        if v['node_count'] > node_threshold:
            to_split.append(k)

    # Identify split parameters for an element exceeding the node threshold.
    for ii in to_split:
        n = node_schema[ii]
        # Approximate number of splits need for each split element to be less than the node threshold.
        n.n_splits = int(np.ceil(n['node_count'] / node_threshold))
        # This is the shape of the polygon grid to use for splitting the target element.
        n.split_shape = np.sqrt(n.n_splits)
        # There should be at least two splits.
        if n.split_shape == 1:
            n.split_shape += 1
        n.split_shape = tuple([int(np.ceil(ns)) for ns in [n.split_shape] * 2])

        # Get polygons to use for splitting.
        n.splitters = get_split_polygons(n['geom'], n.split_shape)

        # Create the individual splits:
        n.splits = []
        for s in n.splitters:
            if n.geom.intersects(s):
                the_intersection = n.geom.intersection(s)
                for ti in get_iter(the_intersection, dtype=Polygon):
                    n.splits.append(ti)

                    # write_fiona(n.splits, '01-splits')

    # Collect the polygons to return as a multipolygon.
    the_multi = []
    for v in node_schema.values():
        if 'splits' in v:
            the_multi += v.splits
        else:
            the_multi.append(v.geom)

    return MultiPolygon(the_multi)


def get_node_schema(geom):
    # tdk: doc
    ret = Dict()
    for ctr, ii in enumerate(get_iter(geom, dtype=Polygon)):
        ret[ctr].node_count = get_node_count(ii)
        ret[ctr].area = ii.area
        ret[ctr].geom = ii
    return ret


def get_node_count(geom):
    node_count = 0
    for ii in get_iter(geom, dtype=Polygon):
        node_count += len(ii.exterior.coords)
    return node_count


def get_bounds_from_1d(centroids):
    """
    :param centroids: Vector representing center coordinates from which to interpolate bounds.
    :type centroids: :class:`numpy.ndarray`
    :returns: A *n*-by-2 array with *n* equal to the shape of ``centroids``.

    >>> import numpy as np
    >>> centroids = np.array([1,2,3])
    >>> get_bounds_from_1d(centroids)
    np.array([[0, 1],[1, 2],[2, 3]])

    :rtype: :class:`numpy.ndarray`
    :raises: NotImplementedError, ValueError
    """

    mids = get_bounds_vector_from_centroids(centroids)

    # loop to fill the bounds array
    bounds = np.zeros((centroids.shape[0], 2), dtype=centroids.dtype)
    for ii in range(mids.shape[0]):
        try:
            bounds[ii, 0] = mids[ii]
            bounds[ii, 1] = mids[ii + 1]
        except IndexError:
            break

    return bounds


def get_split_polygons(geom, split_shape):
    minx, miny, maxx, maxy = geom.bounds
    rows = np.linspace(miny, maxy, split_shape[0])
    cols = np.linspace(minx, maxx, split_shape[1])

    return get_split_polygons_from_meshgrid_vectors(cols, rows)


def get_split_polygons_from_meshgrid_vectors(cols, rows):
    cols, rows = np.meshgrid(cols, rows)

    cols_corners = get_extrapolated_corners_esmf(cols)
    cols_corners = get_ocgis_corners_from_esmf_corners(cols_corners)

    rows_corners = get_extrapolated_corners_esmf(rows)
    rows_corners = get_ocgis_corners_from_esmf_corners(rows_corners)

    corners = np.vstack((rows_corners, cols_corners))
    corners = corners.reshape([2] + list(cols_corners.shape))
    range_row = range(rows.shape[0])
    range_col = range(cols.shape[1])

    fill = np.zeros(cols.shape, dtype=object)

    for row, col in itertools.product(range_row, range_col):
        current_corner = corners[:, row, col]
        coords = np.hstack((current_corner[1, :].reshape(-1, 1),
                            current_corner[0, :].reshape(-1, 1)))
        polygon = Polygon(coords)
        fill[row, col] = polygon

    return fill.flatten().tolist()


def get_ocgis_corners_from_esmf_corners(ecorners):
    """
    :param ecorners: An array of ESMF corners.
    :type ecorners: :class:`numpy.ndarray`
    :returns: A masked array of OCGIS corners.
    :rtype: :class:`~numpy.ma.core.MaskedArray`
    """

    assert ecorners.ndim == 2

    # ESMF corners have an extra row and column.
    base_shape = [xx - 1 for xx in ecorners.shape]
    grid_corners = np.zeros(base_shape + [4], dtype=ecorners.dtype)
    # Uppler left, upper right, lower right, lower left
    slices = [(0, 0), (0, 1), (1, 1), (1, 0)]
    for ii, jj in itertools.product(range(base_shape[0]), range(base_shape[1])):
        row_slice = slice(ii, ii + 2)
        col_slice = slice(jj, jj + 2)
        corners = ecorners[row_slice, col_slice]
        for kk, slc in enumerate(slices):
            grid_corners[ii, jj, kk] = corners[slc]
    grid_corners = np.ma.array(grid_corners, mask=False)
    return grid_corners


def get_extrapolated_corners_esmf(arr):
    """
    :param arr: Array of centroids.
    :type arr: :class:`numpy.ndarray`
    :returns: A two-dimensional array of extrapolated corners with dimension ``(arr.shape[0]+1, arr.shape[1]+1)``.
    :rtype: :class:`numpy.ndarray`
    """

    assert not isinstance(arr, MaskedArray)

    # if this is only a single element, we cannot make corners
    if all([element == 1 for element in arr.shape]):
        msg = 'At least two elements required to extrapolate corners.'
        raise ValueError(msg)

    # if one of the dimensions has only a single element, the fill approach is different
    if any([element == 1 for element in arr.shape]):
        ret = get_extrapolated_corners_esmf_vector(arr.reshape(-1))
        if arr.shape[1] == 1:
            ret = ret.swapaxes(0, 1)
        return ret

    # the corners array has one additional row and column
    corners = np.zeros((arr.shape[0] + 1, arr.shape[1] + 1), dtype=arr.dtype)

    # fill the interior of the array first with a 2x2 moving window. then do edges.
    for ii in range(arr.shape[0] - 1):
        for jj in range(arr.shape[1] - 1):
            window_values = arr[ii:ii + 2, jj:jj + 2]
            corners[ii + 1, jj + 1] = np.mean(window_values)

    # flag to determine if rows are increasing in value
    row_increasing = get_is_increasing(arr[:, 0])
    # flag to determine if columns are increasing in value
    col_increasing = get_is_increasing(arr[0, :])

    # the absolute difference of row and column elements
    row_diff = np.mean(np.abs(np.diff(arr[:, 0])))
    col_diff = np.mean(np.abs(np.diff(arr[0, :])))

    # fill the rows accounting for increasing flag
    for ii in range(1, corners.shape[0] - 1):
        if col_increasing:
            corners[ii, 0] = corners[ii, 1] - col_diff
            corners[ii, -1] = corners[ii, -2] + col_diff
        else:
            corners[ii, 0] = corners[ii, 1] + col_diff
            corners[ii, -1] = corners[ii, -2] - col_diff

    # fill the columns accounting for increasing flag
    for jj in range(1, corners.shape[1] - 1):
        if row_increasing:
            corners[0, jj] = corners[1, jj] - row_diff
            corners[-1, jj] = corners[-2, jj] + row_diff
        else:
            corners[0, jj] = corners[1, jj] + row_diff
            corners[-1, jj] = corners[-2, jj] - row_diff

    # fill the extreme corners accounting for increasing flag
    for row_idx in [0, -1]:
        if col_increasing:
            corners[row_idx, 0] = corners[row_idx, 1] - col_diff
            corners[row_idx, -1] = corners[row_idx, -2] + col_diff
        else:
            corners[row_idx, 0] = corners[row_idx, 1] + col_diff
            corners[row_idx, -1] = corners[row_idx, -2] - col_diff

    return corners


def get_extrapolated_corners_esmf_vector(vec):
    """
    :param vec: A vector.
    :type vec: :class:`numpy.ndarray`
    :returns: A two-dimensional corners array with dimension ``(2, vec.shape[0]+1)``.
    :rtype: :class:`numpy.ndarray`
    :raises: ShapeError
    """

    if len(vec.shape) > 1:
        msg = 'A vector is required.'
        raise ValueError(msg)

    corners = np.zeros((2, vec.shape[0] + 1), dtype=vec.dtype)
    corners[:] = get_bounds_vector_from_centroids(vec)

    return corners


def get_bounds_vector_from_centroids(centroids):
    """
    :param centroids: Vector representing center coordinates from which to interpolate bounds.
    :type centroids: :class:`numpy.ndarray`
    :returns: Vector representing upper and lower bounds for centroids with edges extrapolated.
    :rtype: :class:`numpy.ndarray` with shape ``centroids.shape[0]+1``
    :raises: NotImplementedError, ValueError
    """

    if len(centroids) < 2:
        raise ValueError('Centroid arrays must have length >= 2.')

    # will hold the mean midpoints between coordinate elements
    mids = np.zeros(centroids.shape[0] - 1, dtype=centroids.dtype)
    # this is essentially a two-element span moving average kernel
    for ii in range(mids.shape[0]):
        mids[ii] = np.mean(centroids[ii:ii + 2])
    # account for edge effects by averaging the difference of the midpoints. if there is only a single value, use the
    # different of the original values instead.
    if len(mids) == 1:
        diff = np.diff(centroids)
    else:
        diff = np.mean(np.diff(mids))
    # appends for the edges shifting the nearest coordinate by the mean difference
    mids = np.append([mids[0] - diff], mids)
    mids = np.append(mids, [mids[-1] + diff])

    return mids


def get_is_increasing(vec):
    """
    :param vec: A vector array.
    :type vec: :class:`numpy.ndarray`
    :returns: ``True`` if the array is increasing from index 0 to -1. ``False`` otherwise.
    :rtype: bool
    :raises: SingleElementError, ShapeError
    """

    if vec.shape == (1,):
        raise ValueError('Increasing can only be determined with a minimum of two elements.')
    if len(vec.shape) > 1:
        msg = 'Only vectors allowed.'
        raise ValueError(msg)

    if vec[0] < vec[-1]:
        ret = True
    else:
        ret = False

    return ret


def get_iter(element, dtype=None):
    """
    :param element: The element comprising the base iterator. If the element is a ``basestring`` or :class:`numpy.ndarray`
     then the iterator will return the element and stop iteration.
    :type element: varying
    :param dtype: If not ``None``, use this argument as the argument to ``isinstance``. If ``element`` is an instance of
     ``dtype``, ``element`` will be placed in a list and passed to ``iter``.
    :type dtype: type or tuple
    """

    if dtype is not None:
        if isinstance(element, dtype):
            element = (element,)

    if isinstance(element, (basestring, np.ndarray)):
        it = iter([element])
    else:
        try:
            it = iter(element)
        except TypeError:
            it = iter([element])

    return it


def get_exact_field(lon, lat, to_radians=True, unwrap=True):
    """
    :param lon: Array of longitude coordinates.
    :param lat: Array of latitude coordinates.
    :param to_radians: If ``True``, convert spherical degrees to radians.
    :param unwrap: If ``True``, unwrap spherical data to the 0 to 360 degree domain.
    :return: An array of exact values calculated from radian coordinates.

    >>> lon_rad = np.array([-170., -10., 0., 10., 170.])
    >>> lat_rad = np.array([-40., -10., 0., 10., 40.])
    >>> exact = get_exact_field(lon, lat)
    >>> desired = [3.204474688087701, 3.112123092720088, 4.0, 3.112123092720088, 3.204474688087701]
    >>> assert np.all(np.isclose(exact, desired))
    """

    new_lon_rad = lon.copy()
    new_lat_rad = lat.copy()
    if unwrap:
        new_lon_rad[new_lon_rad < 0.] += 360.
    if to_radians:
        new_lon_rad *= 0.0174533
        new_lat_rad *= 0.0174533
    exact = 2. + np.cos(new_lat_rad) ** 2. + np.cos(2. * new_lon_rad)
    return exact
